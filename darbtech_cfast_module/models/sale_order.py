from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    cfast_quotation_id = fields.Integer(string="CFAST Quotation ID", index=True, copy=False)
    cfast_reference = fields.Char(string="CFAST Reference", copy=False)

    _sql_constraints = [
        (
            "sale_order_company_cfast_quotation_unique",
            "unique(company_id, cfast_quotation_id)",
            "Une commande existe déjà pour cet ID de Devis CFAST dans cette société.",
        ),
    ]

