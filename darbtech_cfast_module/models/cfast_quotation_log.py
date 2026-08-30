
import json
import logging
from datetime import timedelta

from markupsafe import Markup, escape

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _first_defined(mapping: dict, *keys):
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _parse_cfast_quotation_id(item: dict) -> int | None:
    raw = _first_defined(item, "id", "quotationId", "quotation_id")
    if raw is None or raw is False:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _to_float(val):
    if val is None or val is False:
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _to_bool(val):
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes", "y", "oui")
    return False


def _to_optional_positive_int(val):
    if val is None or val is False:
        return False
    try:
        return int(val)
    except (TypeError, ValueError):
        return False


class CfastQuotationLog(models.Model):
    _name = "cfast.quotation.log"
    _description = "CFAST Quotations Log"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    _sql_constraints = [
        (
            "partner_cfast_quotation_unique",
            "unique(partner_id, cfast_quotation_id)",
            "Une Quotation avec cet identifiant CFAST existe déjà pour ce contact.",
        ),
    ]

    partner_id = fields.Many2one(
        "res.partner",
        string="Contact",
        required=True,
        index=True,
        ondelete="cascade",
    )

    company_id = fields.Many2one(
        "res.company",
        string="Société",
        related="partner_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )

    currency_id = fields.Many2one(
        "res.currency",
        string="Devise",
        related="company_id.currency_id",
        store=True,
        readonly=True,
    )

    sale_order_id = fields.Many2one(
        "sale.order",
        string="Commande Odoo",
        readonly=True,
    )

    project_id = fields.Many2one(
        "project.project",
        string="Projet",
        compute="_compute_project_id",
        store=False,
        readonly=True,
    )

    cfast_quotation_id = fields.Integer(
        string="ID cot CFAST",
        required=True,
        index=True,
    )

    reference = fields.Char(string="Référence")
    name = fields.Char(string="Nom")

    quotation_type_name = fields.Char(
        string="Type de devis CFAST",
        readonly=True,
        index=True,
    )

    customer_id = fields.Char(string="Client CFAST (ref)")
    salesperson_id = fields.Char(string="Commercial CFAST")

    quotation_date = fields.Date(string="Date devis")
    send_datetime = fields.Datetime(string="Envoi")

    status = fields.Char(string="Statut CFAST")
    is_closed = fields.Boolean(string="Clôturé")

    total_activation_price = fields.Float(string="Montant activation")
    total_periodic_price = fields.Float(string="Montant périodique")

    validity_duration = fields.Integer(string="Durée validité (jours)")

    raw_json = fields.Text(string="JSON brut")

    sync_state = fields.Selection(
        selection=[
            ("draft", "Reçu"),
            ("order_created", "Commande créée"),
            ("order_confirmed", "Commande confirmée"),
            ("project_generated", "Projet généré"),
            ("error", "Erreur"),
        ],
        string="État synchro",
        default="draft",
        required=True,
        tracking=True,
    )

    error_message = fields.Text(string="Message d'erreur")
    confirmation_error = fields.Text(string="Erreur confirmation")
    last_sync_date = fields.Datetime(string="Dernière synchro", readonly=True)

    @api.depends("sale_order_id.order_line")
    def _compute_project_id(self):
        Project = self.env["project.project"]
        for rec in self:
            project = Project
            if rec.sale_order_id:
                project = Project.search(
                    [("sale_line_id", "in", rec.sale_order_id.order_line.ids)],
                    limit=1,
                )
            rec.project_id = project[:1].id if project else False

    def _get_product_from_quotation_type_name(self):
        self.ensure_one()

        quotation_type_name = (self.quotation_type_name or "").strip()

        if not quotation_type_name:
            raise UserError(
                _(
                    "Le champ quotationTypeName est absent pour devis "
                    "CFAST %(quotation_id)s."
                )
                % {
                    "quotation_id": self.cfast_quotation_id,
                }
            )

        ProductTemplate = self.env["product.template"]

        templates = ProductTemplate.search(
            [
                ("name", "=ilike", quotation_type_name),
                ("sale_ok", "=", True),
                ("active", "=", True),
            ],
            limit=2,
        )

        if not templates:
            raise UserError(
                _(
                    "Aucun produit Odoo actif et vendable ne porte exactement "
                    "le nom « %(product_name)s »."
                )
                % {
                    "product_name": quotation_type_name,
                }
            )

        if len(templates) > 1:
            raise UserError(
                _(
                    "Plusieurs produits Odoo portent exactement le nom "
                    "« %(product_name)s ». Le mapping est ambigu."
                )
                % {
                    "product_name": quotation_type_name,
                }
            )

        product = templates.product_variant_id

        if not product or not product.active:
            raise UserError(
                _(
                    "Le produit Odoo « %(product_name)s » ne possède pas "
                    "de variante active."
                )
                % {
                    "product_name": quotation_type_name,
                }
            )

        return product

    def _get_order_line_commands_from_payload(self):
        """
        Génère une seule ligne de commande à partir de quotationTypeName.
        """
        self.ensure_one()

        product = self._get_product_from_quotation_type_name()

        amount = (
            self.total_activation_price
            or self.total_periodic_price
            or 0.0
        )

        description_parts = [
            product.display_name,
            _("Prestation issue de CFAST"),
        ]

        if self.reference:
            description_parts.append(
                _("Référence CFAST : %s") % self.reference
            )

        if self.cfast_quotation_id:
            description_parts.append(
                _("ID CFAST : %s") % self.cfast_quotation_id
            )

        return [
            Command.create(
                {
                    "product_id": product.id,
                    "name": "\n".join(description_parts),
                    "product_uom_qty": 1.0,
                    "price_unit": amount,
                }
            )
        ]

    @api.model
    def _prepare_vals_from_api_item(self, partner, item: dict) -> dict | None:
        cid = _parse_cfast_quotation_id(item)
        if cid is None:
            _logger.warning("CFAST quotation without numeric id skipped: %s", item)
            return None

        qdate_raw = _first_defined(
            item,
            "quotationDate",
            "quotation_date",
            "date",
            "quoteDate",
        )

        quotation_date = False
        if qdate_raw:
            quotation_date = fields.Date.to_date(qdate_raw)

        send_raw = _first_defined(
            item,
            "sendDatetime",
            "send_datetime",
            "sentAt",
            "sent_at",
        )

        send_datetime = False
        if send_raw:
            send_datetime = fields.Datetime.to_datetime(send_raw)

     

        return {
            "partner_id": partner.id,
            "cfast_quotation_id": cid,
            "reference": _first_defined(item, "reference", "Reference") or False,
            "name": _first_defined(item, "name", "title", "label") or False,
            "quotation_type_name": (
                str(
                    _first_defined(
                        item,
                        "quotationTypeName",
                        "quotation_type_name",
                    )
                    or ""
                ).strip()
                or False
            ),
            "customer_id": _first_defined(item, "customerId", "customer_id") or False,
            "salesperson_id": _first_defined(
                item,
                "salespersonId",
                "salesperson_id",
                "sellerId",
            )
            or False,
            "quotation_date": quotation_date,
            "send_datetime": send_datetime,
            "status": _first_defined(item, "status", "state") or False,
            "is_closed": _to_bool(_first_defined(item, "isClosed", "is_closed")),
            "total_activation_price": _to_float(
                _first_defined(
                    item,
                    "totalActivationPrice",
                    "total_activation_price",
                    "activationTotal",
                )
            ),
            "total_periodic_price": _to_float(
                _first_defined(
                    item,
                    "totalPeriodicPrice",
                    "total_periodic_price",
                    "periodicTotal",
                )
            ),
            "validity_duration": _to_optional_positive_int(
                _first_defined(item, "validityDuration", "validity_duration")
            ),
            "raw_json": json.dumps(item, ensure_ascii=False, indent=2),
            "last_sync_date": fields.Datetime.now(),
        }

    def _resolve_salesperson_user(self):
        self.ensure_one()

        if not self.salesperson_id:
            return False

        salesperson_ref = str(self.salesperson_id).strip()

        if salesperson_ref.isdigit():
            user = self.env["res.users"].browse(int(salesperson_ref))
            return user if user.exists() else self.env["res.users"]

        return self.env["res.users"].search([("login", "=", salesperson_ref)], limit=1)

    def action_create_sale_order(self):
        self.ensure_one()

        if self.sale_order_id and self.sale_order_id.state in ("sale", "done"):
            return self.action_open_sale_order()

        if not self.partner_id:
            raise UserError(_("Contact manquant sur la ligne de log."))

        partner = self.partner_id.commercial_partner_id
        company = self.company_id or partner.company_id or self.env.company

        note_body = False
        if self.name:
            note_body = Markup("<p>%s</p>") % escape(self.name)

        date_order = False
        if self.quotation_date:
            date_order = fields.Datetime.to_datetime(self.quotation_date)

        validity_date = False
        if self.quotation_date and self.validity_duration:
            validity_date = self.quotation_date + timedelta(
                days=int(self.validity_duration)
            )

        salesperson = self._resolve_salesperson_user()

        order_vals = {
            "partner_id": partner.id,
            "company_id": company.id,
            "client_order_ref": self.reference or False,
            "note": note_body,
            "date_order": date_order or fields.Datetime.now(),
            "validity_date": validity_date or False,
            "cfast_quotation_id": self.cfast_quotation_id,
            "cfast_reference": self.reference or False,
        }

        if salesperson:
            order_vals["user_id"] = salesperson.id

        # Vérifier le mapping produit avant de créer la commande.
        try:
            line_commands = [
                Command.clear(),
                *self._get_order_line_commands_from_payload(),
            ]
        except UserError as exc:
            self.write(
                {
                    "sync_state": "error",
                    "error_message": str(exc),
                    "confirmation_error": False,
                    "last_sync_date": fields.Datetime.now(),
                }
            )

            _logger.error(
                "CFAST product mapping failed: quotation_id=%s, "
                "quotation_type_name=%r, error=%s",
                self.cfast_quotation_id,
                self.quotation_type_name,
                exc,
            )
            raise

        SaleOrder = self.env["sale.order"].with_company(company)

        sale_order = self.sale_order_id

        if not sale_order:
            sale_order = SaleOrder.search(
                [
                    ("company_id", "=", company.id),
                    ("cfast_quotation_id", "=", self.cfast_quotation_id),
                ],
                limit=1,
            )

        try:
            if sale_order:
                if sale_order.state in ("draft", "sent"):
                    sale_order.write(order_vals)
            else:
                sale_order = SaleOrder.create(order_vals)
                self.write(
                    {
                        "sale_order_id": sale_order.id,
                        "sync_state": "order_created",
                        "error_message": False,
                        "confirmation_error": False,
                    }
                )

        except Exception as exc:
            _logger.exception(
                "Impossible de créer/mettre à jour la commande depuis CFAST log id=%s",
                self.id,
            )
            self.write(
                {
                    "sync_state": "error",
                    "error_message": str(exc),
                    "last_sync_date": fields.Datetime.now(),
                }
            )
            raise UserError(
                _("Échec de la création de la commande Odoo : %s") % str(exc)
            ) from exc

        try:
            if sale_order.state in ("draft", "sent"):
                sale_order.write({"order_line": line_commands})

        except Exception as exc:
            _logger.exception(
                "Impossible de créer les lignes de commande CFAST pour sale.order %s",
                sale_order.id,
            )
            self.write(
                {
                    "sale_order_id": sale_order.id,
                    "sync_state": "error",
                    "error_message": str(exc),
                    "last_sync_date": fields.Datetime.now(),
                }
            )
            raise UserError(
                _("Échec de la création des lignes de commande : %s") % str(exc)
            ) from exc

        if sale_order.state in ("draft", "sent"):
            try:
                sale_order.action_confirm()

            except Exception as exc:
                _logger.exception(
                    "Confirmation impossible pour sale.order %s (CFAST %s)",
                    sale_order.id,
                    self.cfast_quotation_id,
                )
                self.write(
                    {
                        "sale_order_id": sale_order.id,
                        "sync_state": "order_created",
                        "confirmation_error": str(exc),
                        "error_message": _("Commande créée mais confirmation impossible."),
                        "last_sync_date": fields.Datetime.now(),
                    }
                )
                raise UserError(
                    _("Commande créée mais confirmation impossible : %s") % str(exc)
                ) from exc

        new_state = "order_confirmed"

        self.invalidate_recordset(["project_id"])
        if self.project_id:
            new_state = "project_generated"

        self.write(
            {
                "sale_order_id": sale_order.id,
                "sync_state": new_state,
                "error_message": False,
                "confirmation_error": False,
                "last_sync_date": fields.Datetime.now(),
            }
        )

        self.message_post(body=_("Commande confirmée : %s") % sale_order.display_name)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Commande créée"),
                "message": sale_order.display_name,
                "type": "success",
                "sticky": False,
                "next": {
                    "type": "ir.actions.act_window",
                    "name": _("Commande"),
                    "res_model": "sale.order",
                    "res_id": sale_order.id,
                    "view_mode": "form",
                    "views": [(False, "form")],
                    "target": "current",
                },
            },
        }

    def action_open_sale_order(self):
        self.ensure_one()

        if not self.sale_order_id:
            raise UserError(_("Aucune commande Odoo liée."))

        return {
            "type": "ir.actions.act_window",
            "name": _("Commande Odoo"),
            "res_model": "sale.order",
            "res_id": self.sale_order_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_project(self):
        self.ensure_one()

        if not self.project_id:
            raise UserError(_("Aucun projet lié n'a été détecté pour cette commande."))

        return {
            "type": "ir.actions.act_window",
            "name": _("Projet"),
            "res_model": "project.project",
            "res_id": self.project_id.id,
            "view_mode": "form",
            "target": "current",
        }