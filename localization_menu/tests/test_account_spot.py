from odoo.tests import common

@common.tagged('post_install', '-at_install')
class TestLocalizationMenu(common.TransactionCase):

    def setUp(self):
        super(TestLocalizationMenu, self).setUp()
        self.AccountSpotRetention = self.env['account.spot.retention']
        self.AccountSpotDetraction = self.env['account.spot.detraction']
        self.CodeAduana = self.env['code.aduana']

    def test_account_spot_retention_creation(self):
        retention = self.AccountSpotRetention.create({
            'name': 'Test Retention'
        })
        self.assertEqual(retention.name, 'Test Retention')

    def test_account_spot_detraction_creation(self):
        detraction = self.AccountSpotDetraction.create({
            'name': 'Test Detraction'
        })
        self.assertEqual(detraction.name, 'Test Detraction')

    def test_code_aduana_creation(self):
        aduana = self.CodeAduana.create({
            'name': 'Test Aduana',
            'code': 'TA001'
        })
        self.assertEqual(aduana.name, 'Test Aduana')
        self.assertEqual(aduana.code, 'TA001')

    def test_menu_creation(self):
        self.assertTrue(self.env.ref('localization_menu.menu_localization',raise_if_not_found=False))
        self.assertTrue(self.env.ref('localization_menu.menu_hr_sub_localization',raise_if_not_found=False))
        self.assertTrue(self.env.ref('localization_menu.menu_localization_spot',raise_if_not_found=False))
        self.assertTrue(self.env.ref('localization_menu.menu_localization_ple',raise_if_not_found=False))
        self.assertTrue(self.env.ref('localization_menu.menu_localization_invoicing',raise_if_not_found=False))
        self.assertTrue(self.env.ref('localization_menu.menu_hr_localization_datos_nomina',raise_if_not_found=False))

        self.assertTrue(self.env.ref('localization_menu.menu_hr_information_plame',raise_if_not_found=False))
        self.assertTrue(self.env.ref('localization_menu.menu_hr_information_mintra',raise_if_not_found=False))
        self.assertTrue(self.env.ref('localization_menu.menu_anexo_3',raise_if_not_found=False))
        self.assertTrue(self.env.ref('localization_menu.menu_localization_spot_retention',raise_if_not_found=False))
        self.assertTrue(self.env.ref('localization_menu.menu_localization_spot_detraction',raise_if_not_found=False))
        self.assertTrue(self.env.ref('localization_menu.menu_code_aduana_anexo',raise_if_not_found=False))

    def test_menu_hierarchy(self):
        localization_menu = self.env.ref('localization_menu.menu_localization',raise_if_not_found=False)
        spot_menu = self.env.ref('localization_menu.menu_localization_spot',raise_if_not_found=False)
        ple_menu = self.env.ref('localization_menu.menu_localization_ple',raise_if_not_found=False)

        self.assertEqual(spot_menu.parent_id, localization_menu)
        self.assertEqual(ple_menu.parent_id, localization_menu)

        anexo_3_menu = self.env.ref('localization_menu.menu_anexo_3',raise_if_not_found=False)
        self.assertEqual(anexo_3_menu.parent_id, ple_menu)

    def test_action_window_creation(self):
        self.assertTrue(self.env.ref('localization_menu.account_spot_retention_action',raise_if_not_found=False))
        self.assertTrue(self.env.ref('localization_menu.account_spot_detraction_action',raise_if_not_found=False))
        self.assertTrue(self.env.ref('localization_menu.code_aduana_action',raise_if_not_found=False))
        