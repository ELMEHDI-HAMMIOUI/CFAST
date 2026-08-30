# Part of darbtech_cfast_module. See LICENSE file for full copyright and licensing details.

import json

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCfastOrderSync(TransactionCase):
    def test_create_and_confirm_order_from_log(self):
        partner = self.env["res.partner"].create({"name": "Client CFAST", "ref": "CUST-001"})
        product = self.env["product.product"].create(
            {
                "name": "Service CFAST A",
                "type": "service",
                "cfast_external_id": "SVC-EXT-1",
                # sale_project expects service tracking to create project/tasks (depends on configuration)
                "service_tracking": "no",
            }
        )
        payload = {
            "id": 123,
            "reference": "Q-123",
            "name": "Cotation test",
            "lines": [
                {
                    "productExternalId": "SVC-EXT-1",
                    "description": "Prestation A",
                    "quantity": 2,
                    "unitPrice": 100.0,
                }
            ],
        }
        log = self.env["cfast.quotation.log"].create(
            {
                "partner_id": partner.id,
                "cfast_quotation_id": 123,
                "reference": "Q-123",
                "name": "Cotation test",
                "raw_json": json.dumps(payload),
            }
        )

        log.action_create_sale_order()

        self.assertTrue(log.sale_order_id, "A sale.order must be linked to the log.")
        self.assertIn(log.sale_order_id.state, ("sale", "done"), "Order must be confirmed.")
        self.assertEqual(log.sale_order_id.cfast_quotation_id, 123)
        self.assertEqual(len(log.sale_order_id.order_line), 1)
        self.assertEqual(log.sale_order_id.order_line.product_id.id, product.id)

    def test_no_duplication_on_resync(self):
        partner = self.env["res.partner"].create({"name": "Client CFAST", "ref": "CUST-002"})
        product = self.env["product.product"].create(
            {
                "name": "Service CFAST B",
                "type": "service",
                "cfast_external_id": "SVC-EXT-2",
                "service_tracking": "no",
            }
        )
        payload = {
            "id": 456,
            "reference": "Q-456",
            "name": "Cotation test 2",
            "lines": [
                {
                    "productExternalId": "SVC-EXT-2",
                    "description": "Prestation B",
                    "quantity": 1,
                    "unitPrice": 50.0,
                }
            ],
        }
        log = self.env["cfast.quotation.log"].create(
            {
                "partner_id": partner.id,
                "cfast_quotation_id": 456,
                "reference": "Q-456",
                "name": "Cotation test 2",
                "raw_json": json.dumps(payload),
            }
        )
        log.action_create_sale_order()
        order1 = log.sale_order_id

        # Resync / re-run conversion should not create a new order
        log2 = self.env["cfast.quotation.log"].search(
            [("partner_id", "=", partner.id), ("cfast_quotation_id", "=", 456)], limit=1
        )
        log2.action_create_sale_order()
        self.assertEqual(log2.sale_order_id.id, order1.id)

