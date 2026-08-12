{
    'name': 'Cambiar Cuenta Corriente Facturas',
    'version': '18.0.1.0.2',
    'author': 'Ganemo',
    'website': 'https://www.ganemo.co',
    'category': 'Accounting/Accounting',
    'summary': 'International financial management invoices.',
    'description': 'The account receivable and payable of the invoices, changes according to the currency and the type of proof of payment',
    'depends': ['account'],
    'data': [
        'security/ir.model.access.csv',
        'security/account_security.xml',
        'views/account_change_by_type_views.xml',
        'views/account_move_views.xml',
        'views/account_menus.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'Other proprietary',
    'currency': 'USD',
    'price': 119.00,
    'module_type': 'official'
}
