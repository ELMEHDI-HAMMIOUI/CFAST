import logging
from datetime import datetime, time, timezone

from dateutil import parser

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.darbtech_cfast_module.services import cfast_quotation_client

_logger = logging.getLogger(__name__)


_UPDATABLE_WHEN_ORDER_EXISTS = frozenset(
    (
        "reference",
        "name",
        "quotation_type_name",
        "customer_id",
        "salesperson_id",
        "quotation_date",
        "send_datetime",
        "status",
        "is_closed",
        "total_activation_price",
        "total_periodic_price",
        "validity_duration",
        "raw_json",
    )
)


class ResPartner(models.Model):
    _inherit = "res.partner"

    cfast_quotation_log_ids = fields.One2many(
        "cfast.quotation.log",
        "partner_id",
        string="Quotations CFAST",
    )

    cfast_last_sync_datetime = fields.Datetime(
        string="Dernière synchronisation CFAST",
        readonly=True,
        copy=False,
    )

    def _cfast_item_datetime(self, item):
        raw = (
            item.get("creationDatetime")
            or item.get("creationDateTime")
            or item.get("creation_datetime")
            or item.get("createdAt")
            or item.get("created_at")
            or item.get("quotationDate")
            or item.get("quotation_date")
        )

        if not raw:
            return False

        try:
            item_datetime = parser.parse(str(raw))
        except Exception:
            return False

        if item_datetime.tzinfo:
            item_datetime = (
                item_datetime.astimezone(timezone.utc)
                .replace(tzinfo=None)
            )

        if not isinstance(item_datetime, datetime):
            item_datetime = datetime.combine(
                item_datetime,
                time.min,
            )

        return item_datetime

    def _sync_cfast_quotations_core(self, incremental=False):
        self.ensure_one()

        customer_ref = (self.ref or "").strip()

        if not customer_ref:
            raise UserError(
                _(
                    "Le champ Référence interne (ref) du contact est vide ; "
                    "impossible d'appeler CFAST."
                )
            )

        icp = self.env["ir.config_parameter"].sudo()

        token = (
            icp.get_param(
                "darbtech_cfast_module.cfast_access_token"
            )
            or ""
        ).strip()

        base_url = (
            icp.get_param(
                "darbtech_cfast_module.cfast_base_url"
            )
            or ""
        ).strip()

        if not token:
            raise UserError(
                _(
                    "Le token CFAST n'est pas configuré "
                    "(paramètres système)."
                )
            )

        if not base_url:
            raise UserError(
                _("L'URL de base CFAST n'est pas configurée.")
            )

        payload, status_code, error = (
            cfast_quotation_client.fetch_quotations(
                base_url,
                token,
                customer_ref,
                timeout=cfast_quotation_client.DEFAULT_TIMEOUT,
            )
        )

        if error and payload is None:
            message = _(
                "Échec de la synchronisation CFAST : %s"
            ) % error

            self.message_post(
                body=message,
                subject=_("CFAST — erreur"),
            )

            _logger.error(
                "CFAST sync partner=%s error=%s",
                self.id,
                error,
            )

            raise UserError(message)

        if status_code and status_code >= 400:
            message_body = (
                error
                or _("Erreur HTTP %s") % status_code
            )

            message = _(
                "Échec de la synchronisation CFAST : %s"
            ) % message_body
            
            if created or created_orders or errors:
                self.message_post(
                    body=message,
                    subject=_("CFAST — erreur"),
                )

            _logger.error(
                "CFAST sync partner=%s http=%s detail=%s",
                self.id,
                status_code,
                message_body,
            )

            raise UserError(message)

        items = (
            cfast_quotation_client.extract_quotation_payloads(
                payload
            )
        )

        if incremental and self.cfast_last_sync_datetime:
            last_sync = self.cfast_last_sync_datetime

            items = [
                item
                for item in items
                if self._cfast_item_datetime(item)
                and self._cfast_item_datetime(item) > last_sync
            ]

        created = 0
        created_orders = 0
        confirmed_orders = 0
        errors = 0

        Log = self.env["cfast.quotation.log"]

        for item in items:
            values = Log._prepare_vals_from_api_item(
                self,
                item,
            )

            if not values:
                continue

            values["customer_id"] = (
                values.get("customer_id")
                or customer_ref
            )

            existing = Log.search(
                [
                    ("partner_id", "=", self.id),
                    (
                        "cfast_quotation_id",
                        "=",
                        values["cfast_quotation_id"],
                    ),
                ],
                limit=1,
            )

            if existing:
                if existing.sale_order_id:
                    patch = {
                        key: values[key]
                        for key in _UPDATABLE_WHEN_ORDER_EXISTS
                        if key in values
                    }

                    if patch:
                        existing.write(patch)

                else:
                    write_values = dict(values)
                    write_values.pop("partner_id", None)

                    write_values["sync_state"] = "draft"
                    write_values["error_message"] = False
                    write_values["confirmation_error"] = False

                    existing.write(write_values)

                log_record = existing

            else:
                values.setdefault("sync_state", "draft")
                values.setdefault("error_message", False)
                values.setdefault("confirmation_error", False)
                values["last_sync_date"] = fields.Datetime.now()

                log_record = Log.create(values)
                created += 1

            order_before = log_record.sale_order_id

            try:
                log_record.action_create_sale_order()

                if (
                    log_record.sale_order_id
                    and not order_before
                ):
                    created_orders += 1

                if (
                    log_record.sale_order_id
                    and log_record.sale_order_id.state
                    in ("sale", "done")
                ):
                    confirmed_orders += 1

            except Exception as exception:
                errors += 1

                _logger.exception(
                    "Auto-conversion CFAST -> commande failed "
                    "for log %s: %s",
                    log_record.id,
                    exception,
                )

        self.write(
            {
                "cfast_last_sync_datetime": fields.Datetime.now(),
            }
        )

        summary = _(
            "Synchronisation CFAST terminée : "
            "%(created)s devis(s) créée(s), "
            "%(orders)s commande(s) créée(s), "
            "%(errors)s erreur(s)."
        ) % {
            "created": created,
            "orders": created_orders,

            "errors": errors,
        }
        if created >0 or created_orders > 0 or errors > 0:
            self.message_post(
                body=summary,
                subject=_("CFAST"),
            )

        return {
            "created": created,
            "orders": created_orders,
            "confirmed": confirmed_orders,
            "errors": errors,
            "items": len(items),
            "summary": summary,
        }

    def action_sync_cfast_quotations(self):
        result = self._sync_cfast_quotations_core(
            incremental=False
        )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Synchronisation CFAST"),
                "message": result["summary"],
                "type": (
                    "warning"
                    if result["errors"]
                    else "success"
                ),
                "sticky": bool(result["errors"]),
            },
        }

    @api.model
    def cron_sync_cfast_quotations(self):
        partners = self.search(
            [
                ("ref", "!=", False),
                ("active", "=", True),
            ]
        )

        total_created = 0
        total_orders = 0
        total_errors = 0

        for partner in partners:
            try:
                result = (
                    partner._sync_cfast_quotations_core(
                        incremental=True
                    )
                )

                total_created += result["created"]
                total_orders += result["orders"]
                total_errors += result["errors"]

            except Exception as exception:
                total_errors += 1

                _logger.exception(
                    "Cron CFAST échoué pour partner %s : %s",
                    partner.id,
                    exception,
                )

        if total_created >0 or total_orders > 0 or total_errors > 0:
            _logger.info(
                "Cron CFAST terminé : %s quotation(s) créée(s), "
                "%s commande(s) créée(s), %s erreur(s)",
                total_created,
                total_orders,
                total_errors,
            )