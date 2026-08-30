# from odoo import http


# class DarbtechCfastModule(http.Controller):
#     @http.route('/darbtech_cfast_module/darbtech_cfast_module', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/darbtech_cfast_module/darbtech_cfast_module/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('darbtech_cfast_module.listing', {
#             'root': '/darbtech_cfast_module/darbtech_cfast_module',
#             'objects': http.request.env['darbtech_cfast_module.darbtech_cfast_module'].search([]),
#         })

#     @http.route('/darbtech_cfast_module/darbtech_cfast_module/objects/<model("darbtech_cfast_module.darbtech_cfast_module"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('darbtech_cfast_module.object', {
#             'object': obj
#         })

