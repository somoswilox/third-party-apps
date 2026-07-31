{
    "name": "MercadoLibre Accounting / Mercado Libre Publisher Extension",
    'version': '18.0.26.44',
    'author': 'Moldeo Interactive',
    'website': 'https://www.moldeointeractive.com',
    'category': 'Sale',
    'sequence': 14,
    'summary': 'MercadoLibre Accounting / Mercado Libre Publisher Extension',
    'depends': [
        'base',
        'account',
        'sale',
        'meli_oerp'
    ],
    'data': [
        'data/account_data.xml',
        'data/pipeline_diagnostic_cron.xml',
        'security/ir.model.access.csv',
        'views/meli_view.xml',
        'views/company_view.xml',
        'views/tax_view.xml',
        'wizard/afip_sequence_sync.xml',
        #'wizard/mercadolibre_public_invoice.xml'
    ],
    'demo': [
    ],
    'price': '100.00',
    'currency': 'EUR',
    'images': [ 'static/description/main_screenshot.png',
                'static/description/meli_oerp_accounting_configuration.png',
                'static/description/moldeo_interactive_logo.png'],
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'GPL-3',
}
