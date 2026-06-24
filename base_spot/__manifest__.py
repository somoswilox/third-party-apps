{
    'name': 'Base Spot',
    'version': '18.0.1.0.0',
    'author': 'Ganemo',
    'website': 'https://www.ganemo.co',
    'category': 'All',
    'summary': 'Add fields for legal deductions',
    'Description': """
Create additional fields on purchase invoices that allow you to identify if an invoice is affected by legal deductions, the type of deduction, the payment date of the deduction and the payment operation code of the deduction.
""",
    'depends': [
        'localization_menu'
    ],
    'data': [
        'data/account_spot_detraction_data.xml',
        'views/account_move_views.xml',
        'views/account_spot_detraction_views.xml'
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
    'license': 'Other proprietary',
    'currency': 'USD',
    'price': 10.00,
    'module_type': 'official'
}
