# Part of darbtech_cfast_module. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    cfast_external_id = fields.Char(
        string="CFAST External ID",
        index=True,
        help="Identifiant externe produit CFAST utilisé pour mapper les lignes CFAST vers les produits Odoo.",
    )

