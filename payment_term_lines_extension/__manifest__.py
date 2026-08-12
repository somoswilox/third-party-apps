{
    'name': 'Payment Term Lines Extension',
    'version': '18.0.1.0.6',
    'author': 'Ganemo',
    'website': 'https://www.ganemo.co',
    'category':'Accounting',
    'summary': 'Module to round payment terms and modify specific accounting accounts',
    'description': """ 
Extend the module so that it rounds the lines of the payment terms and can change the accounting account of some line in the payment terms.
""",
    'depends': [
        'payment_term_lines',
        'automatic_account_change',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/account_payment_term_line_views.xml',
        'views/account_payment_term_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'payment_term_lines_extension/static/src/css/main.css',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'Other proprietary',
    'currency': 'USD',
    'price': 8.00,
    'module_type': 'official',
}

