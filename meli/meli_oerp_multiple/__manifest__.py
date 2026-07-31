# -*- coding: utf-8 -*-
##############################################################################
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

{
    'name': 'MercadoLibre Multiple Accounts / Mercado Libre Publisher Extension',
    'version': '18.0.26.88',
    'author': 'Moldeo Interactive',
    'website': 'https://www.moldeointeractive.com',
    "category": "Sales",
    "depends": ['base', 'product','sale_management','website_sale','stock','mrp','odoo_connector_api','meli_oerp','meli_oerp_stock','meli_oerp_accounting'],
    'data': [
        'security/odoo_connector_api_security.xml',
        'security/ir.model.access.csv',
        'views/meli_stock_location_view.xml',
        'views/wizards_view.xml',
        'views/company_view.xml',
        'views/connection_account_view.xml',
        'views/connection_view.xml',
        'views/cron_execution_view.xml',
        'views/notification_view.xml',
        'views/product_category_views.xml',
        'views/product_view.xml',
        'views/sale_view.xml',
        'data/data.xml',
        'data/cron_jobs.xml',
        'data/cron_jobs_update.xml',
        'views/warning_view.xml',
        'views/questions_view.xml',
        'views/stock_view.xml',
        'views/mrp_bom_view.xml',
        'wizard/wizard_sales.xml',
        'wizard/wizard_orders_actions.xml',
        'views/ocapi_menu.xml',
        #'views/connection_account_kpis_view.xml',
        #'views/connection_account_dashboard.xml'
    ],
    'price': '350.00',
    'currency': 'EUR',
    'images': [ 'static/description/main_screenshot.png',
                'static/description/meli_oerp_screenshot.png',
                'static/description/meli_oerp_configuration_1.png',
                'static/description/meli_oerp_configuration_2.png',
                'static/description/meli_oerp_configuration_3.png',
                'static/description/meli_oerp_configuration_4.png',
                'static/description/moldeo_interactive_logo.png',
                'static/description/meli_oerp_multiple_configuration_1.png',
                'static/description/meli_oerp_multiple_configuration_2.png',
                'static/description/meli_oerp_multiple_configuration_3.png',
                'static/description/odoo_to_meli.png'],
    'assets': {
        'web.assets_backend': [
            '/meli_oerp_multiple/static/src/css/meli_oerp_multiple.css',
        ]
    },
    'demo_xml': [],
    'active': False,
    'installable': True,
    'application': True,
    'license': 'GPL-3',
    'post_init_hook': 'post_init_hook',
}
