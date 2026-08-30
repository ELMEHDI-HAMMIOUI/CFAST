{
    'name': "darbtech_cfast_module",

    'summary': "Intégration CFAST — synchronisation des cotations vers les contacts Odoo",

    'description': """
        Connexion API CFAST (token OAuth), journal des cotations par contact (ref = customerId),
        création automatique de commandes confirmées Odoo (workflow standard) avec traçabilité complète
        (JSON brut, chatter) et déclenchement standard des projets/tâches via sale_project.
    """,

    'author': "DarbTech",
    'website': "https://www.darbtech.com",

    'category': 'Sales',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',

    'depends': [
        'base',
        'mail',
        'sale',
        'sales_team',
        'sale_project',
    ],

    'data': [
        'security/ir.model.access.csv',
        'security/cfast_quotation_log_rules.xml',
        'views/cfast_quotation_log_views.xml',
        'views/res_partner_views.xml',
        'views/res_config_settings_views.xml',
        "data/ir_cron.xml",
    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],

    'installable': True,
    
    'application': True,
}

