import configparser
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from portefeuille_viewer.config.settings_manager import SettingsManager
from portefeuille_viewer.config.profile_storage import ProfileStorage


class ThemeTests(unittest.TestCase):
    def settings(self):
        value=SettingsManager.__new__(SettingsManager)
        value.config=configparser.ConfigParser();value.save=Mock()
        return value

    def test_default_and_profile_theme_roundtrip(self):
        settings=self.settings()
        self.assertEqual(settings.get_asset_dashboard_theme(),"dark")
        settings.set_asset_dashboard_theme("sand")
        settings.save.assert_called_once()
        self.assertEqual(settings.get_asset_dashboard_theme(),"sand")
        settings.set_asset_dashboard_theme("dark")
        self.assertEqual(settings.get_asset_dashboard_theme(),"dark")

    def test_unknown_theme_does_not_save(self):
        settings=self.settings()
        with self.assertRaises(ValueError):settings.set_asset_dashboard_theme("unknown")
        settings.save.assert_not_called()
        settings.config.read_dict({"ui":{"asset_dashboard_theme":"unknown"}})
        self.assertEqual(settings.get_asset_dashboard_theme(),"dark")

    def test_theme_is_profile_preference(self):
        with TemporaryDirectory() as root:
            storage=ProfileStorage("onno","unused-shared","unused-local",root=root,machine_id="test")
            self.assertEqual(storage.target("ui","asset_dashboard_theme"),storage.preferences)


if __name__=="__main__":unittest.main()
