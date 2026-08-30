from odoo import fields, models, api
from odoo.exceptions import UserError
import requests
from requests.auth import HTTPBasicAuth
import logging

_logger = logging.getLogger(__name__)

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    cfast_access_token = fields.Char(
        string="Access Token",
        config_parameter="darbtech_cfast_module.cfast_access_token",
        readonly=True,
    )

    cfast_token_url = fields.Char(
        string="URL Token",
        config_parameter="darbtech_cfast_module.cfast_token_url",
    )
    cfast_base_url = fields.Char(
        string="Base URL",
        config_parameter="darbtech_cfast_module.cfast_base_url",
    )
    cfast_auth_type = fields.Selection(
        selection=[
            ('basic', 'Basic Auth'),
            ('password', 'Password Grant'),
            ('client_credentials', 'Client Credentials'),
        ],
        string="Type d'authentification",
        default='password',
        config_parameter="darbtech_cfast_module.cfast_auth_type",
    )
    cfast_client_id = fields.Char(
        string="Client ID",
        config_parameter="darbtech_cfast_module.cfast_client_id",
    )
    cfast_client_secret = fields.Char(
        string="Client Secret",
        config_parameter="darbtech_cfast_module.cfast_client_secret",
    )
    cfast_username = fields.Char(
        string="Username",
        config_parameter="darbtech_cfast_module.cfast_username",
    )
    cfast_password = fields.Char(
        string="Password",
        config_parameter="darbtech_cfast_module.cfast_password",
    )
    cfast_scope = fields.Char(
        string="Scope",
        config_parameter="darbtech_cfast_module.cfast_scope",
    )

    def set_values(self):
        super().set_values()
        ICP = self.env['ir.config_parameter'].sudo()

        ICP.set_param('darbtech_cfast_module.cfast_access_token', self.cfast_access_token or '')
        ICP.set_param('darbtech_cfast_module.cfast_token_url', self.cfast_token_url or '')
        ICP.set_param('darbtech_cfast_module.cfast_base_url', self.cfast_base_url or '')
        ICP.set_param('darbtech_cfast_module.cfast_auth_type', self.cfast_auth_type or '')
        ICP.set_param('darbtech_cfast_module.cfast_client_id', self.cfast_client_id or '')
        ICP.set_param('darbtech_cfast_module.cfast_client_secret', self.cfast_client_secret or '')
        ICP.set_param('darbtech_cfast_module.cfast_username', self.cfast_username or '')
        ICP.set_param('darbtech_cfast_module.cfast_password', self.cfast_password or '')
        ICP.set_param('darbtech_cfast_module.cfast_scope', self.cfast_scope or '')

    @api.model
    def get_values(self): 
        res = super().get_values()
        ICP = self.env['ir.config_parameter'].sudo()

        res.update(
            cfast_access_token=ICP.get_param('darbtech_cfast_module.cfast_access_token'),
            cfast_token_url=ICP.get_param('darbtech_cfast_module.cfast_token_url'),
            cfast_base_url=ICP.get_param('darbtech_cfast_module.cfast_base_url'),
            cfast_auth_type=ICP.get_param('darbtech_cfast_module.cfast_auth_type'),
            cfast_client_id=ICP.get_param('darbtech_cfast_module.cfast_client_id'),
            cfast_client_secret=ICP.get_param('darbtech_cfast_module.cfast_client_secret'),
            cfast_username=ICP.get_param('darbtech_cfast_module.cfast_username'),
            cfast_password=ICP.get_param('darbtech_cfast_module.cfast_password'),
            cfast_scope=ICP.get_param('darbtech_cfast_module.cfast_scope'),
        )

        return res
    

    def _refresh_cfast_token(self):
        ICP = self.env['ir.config_parameter'].sudo()

        token_url = (ICP.get_param('darbtech_cfast_module.cfast_token_url') or '').strip()
        client_id = ICP.get_param('darbtech_cfast_module.cfast_client_id')
        client_secret = ICP.get_param('darbtech_cfast_module.cfast_client_secret')
        username = ICP.get_param('darbtech_cfast_module.cfast_username')
        password = ICP.get_param('darbtech_cfast_module.cfast_password')
        scope = ICP.get_param('darbtech_cfast_module.cfast_scope')
        auth_type = ICP.get_param('darbtech_cfast_module.cfast_auth_type') or 'password'

        missing_fields = []
        if not token_url:
            missing_fields.append("URL Token")
        if not client_id:
            missing_fields.append("Client ID")
        if not client_secret:
            missing_fields.append("Client Secret")

        if auth_type == 'password':
            if not username:
                missing_fields.append("Username")
            if not password:
                missing_fields.append("Password")

        if missing_fields:
            raise UserError(
                "Les champs suivants sont obligatoires pour rafraîchir le token : %s"
                % ", ".join(missing_fields)
            )

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }

        data = {
            "grant_type": auth_type if auth_type in ('password', 'client_credentials') else 'password',
            "scope": scope or '',
        }

        if data["grant_type"] == 'password':
            data.update({
                "username": username,
                "password": password,
            })

        try:
            response = requests.post(
                token_url,
                data=data,
                headers=headers,
                auth=HTTPBasicAuth(client_id, client_secret),
                timeout=15,
            )
        except requests.RequestException as e:
            raise UserError("Erreur lors de l'appel à l'API CFAST : %s" % str(e))

        if response.status_code != 200:
            raise UserError(
                "Échec de l'authentification CFAST.\nCode HTTP : %s\nRéponse : %s"
                % (response.status_code, response.text)
            )

        try:
            result = response.json()
        except ValueError:
            raise UserError("La réponse du serveur n'est pas un JSON valide.")

        access_token = result.get("access_token")

        if not access_token:
            raise UserError("Le token n'a pas été retourné par l'API.")

        ICP.set_param('darbtech_cfast_module.cfast_access_token', access_token)

        return access_token

    def action_test_connection(self):
        self.ensure_one()

        access_token = self._refresh_cfast_token()
        self.cfast_access_token = access_token

        token_preview = access_token[:20] + "..." if len(access_token) > 20 else access_token

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Connexion API réussie',
                'message': "Token reçu : %s" % token_preview,
                'type': 'success',
                'sticky': False,
            }
        }
    

    @api.model
    def cron_refresh_token(self):
        _logger.info("CFAST - Début du refresh automatique du token.")

        try:
            self.sudo()._refresh_cfast_token()
            _logger.info("CFAST - Token rafraîchi avec succès.")

        except Exception:
            _logger.exception("CFAST - Erreur lors du refresh automatique du token.")