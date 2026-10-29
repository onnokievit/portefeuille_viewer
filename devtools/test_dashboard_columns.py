import configparser
import unittest
from unittest.mock import Mock
from tempfile import TemporaryDirectory
from portefeuille_viewer.config.settings_manager import SettingsManager
from portefeuille_viewer.config.profile_storage import ProfileStorage
from portefeuille_viewer.services.asset_dashboard_columns import validate_columns

class ColumnTests(unittest.TestCase):
    def settings(self):
        settings=SettingsManager.__new__(SettingsManager)
        settings.config=configparser.ConfigParser();settings.save=Mock();return settings

    def test_roundtrip_and_screen_isolation(self):
        settings=self.settings();value=dict(version=1,tables={'options':[1/16]*16,'stocks':[.2]*5,'sprinters':[1/9]*9})
        settings.set_asset_dashboard_position_columns('desktop',value)
        self.assertEqual(settings.get_asset_dashboard_position_columns('desktop'),value)
        self.assertIsNone(settings.get_asset_dashboard_position_columns('laptop'))
        result=validate_columns(value);result['tables']['options'][0]=.1
        self.assertEqual(value['tables']['options'][0],1/16)

    def test_invalid_widths_are_not_saved(self):
        settings=self.settings()
        for value in [None,dict(version=1,name_width=112,weights=[1/17]*17),dict(version=1,tables={'options':[1/16]*16,'stocks':[.2]*5,'sprinters':[float('nan')]*9}),dict(version=1,tables={'options':[1.]*16,'stocks':[.2]*5,'sprinters':[1/9]*9})]:
            with self.assertRaises(ValueError):settings.set_asset_dashboard_position_columns('desktop',value)
        settings.save.assert_not_called()

    def test_profile_routing(self):
        with TemporaryDirectory() as root:
            storage=ProfileStorage('onno','unused','unused',root=root,machine_id='test')
            for mode in ('desktop','laptop'):
                self.assertEqual(storage.target('ui','asset_dashboard_position_columns_'+mode),storage.preferences)

if __name__=='__main__':unittest.main()
