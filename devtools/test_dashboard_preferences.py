import configparser
from copy import deepcopy
import json
import unittest
from unittest.mock import Mock
from portefeuille_viewer.config.settings_manager import SettingsManager
from portefeuille_viewer.services.asset_dashboard_preferences import export_preferences,import_preferences
from devtools.test_dashboard_layout import fixture

class PreferenceTests(unittest.TestCase):
    def settings(self):
        settings=SettingsManager.__new__(SettingsManager);settings.config=configparser.ConfigParser();settings.save=Mock()
        settings.config.read_dict({'interactive_brokers':{'secret':'keep-secret'},'databases':{'mine':'private-path'}})
        return settings

    def test_cross_profile_roundtrip_contains_presentation_only(self):
        source=self.settings();source.set_asset_dashboard_theme('sand');source.set_asset_dashboard_layout('desktop',fixture())
        source.set_asset_dashboard_position_columns('laptop',dict(version=1,tables={'options':[1/16]*16,'stocks':[.2]*5,'sprinters':[1/9]*9}))
        data=export_preferences(source)
        self.assertNotIn('keep-secret',json.dumps(data));self.assertNotIn('private-path',json.dumps(data))
        target=self.settings();target.config.set('interactive_brokers','secret','target-secret')
        import_preferences(target,data)
        self.assertEqual(export_preferences(target),data)
        self.assertEqual(target.config.get('interactive_brokers','secret'),'target-secret')
        target.save.assert_called_once()

    def test_validation_completes_before_changes_and_save_failure_rolls_back(self):
        settings=self.settings();original=settings.config;data=export_preferences(settings)
        bad=deepcopy(data);bad['modes']['laptop']['layout']={'version':999}
        with self.assertRaises(ValueError):import_preferences(settings,bad)
        self.assertIs(settings.config,original);settings.save.assert_not_called()
        settings.save.side_effect=OSError('cannot save')
        with self.assertRaises(OSError):import_preferences(settings,data)
        self.assertIs(settings.config,original)

    def test_missing_layout_means_default_and_unknown_file_is_rejected(self):
        settings=self.settings();data=export_preferences(settings)
        settings.set_asset_dashboard_layout('desktop',fixture())
        import_preferences(settings,data)
        self.assertIsNone(settings.get_asset_dashboard_layout('desktop'))
        with self.assertRaises(ValueError):import_preferences(settings,{'format':'other','version':1})

if __name__=='__main__':unittest.main()
