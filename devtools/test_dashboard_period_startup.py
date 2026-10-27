import configparser
from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from portefeuille_viewer.config.settings_manager import SettingsManager
from portefeuille_viewer.services.history_indicator_runner import HistoryIndicatorRunner


class PeriodAndStartupTests(unittest.TestCase):
    def settings(self):
        settings = SettingsManager.__new__(SettingsManager)
        settings.config = configparser.ConfigParser()
        settings.save = Mock()
        return settings

    def test_period_roundtrip_and_legacy_start_fallback(self):
        settings = self.settings()
        settings.config.read_dict({"app":{"single_asset_analyse_start_date":"2021-10-08"}})
        self.assertEqual(settings.get_asset_dashboard_period(),
                         {"start":"2021-10-08","end":date.today().isoformat()})
        settings.set_asset_dashboard_period("2020-01-02","2026-10-27")
        settings.save.assert_called_once()
        self.assertEqual(settings.get_asset_dashboard_period(),
                         {"start":"2020-01-02","end":"2026-10-27"})
        self.assertEqual(settings.config.get("app","single_asset_analyse_start_date"),"2021-10-08")

    def test_invalid_period_does_not_save(self):
        settings=self.settings()
        with self.assertRaises(ValueError):
            settings.set_asset_dashboard_period("2026-12-01","2026-01-01")
        settings.save.assert_not_called()

    def test_dashboard_dates_route_to_profile_preferences(self):
        from portefeuille_viewer.config.profile_storage import ProfileStorage
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as root:
            storage=ProfileStorage("onno","unused-shared","unused-local",root=root,machine_id="test")
            for key in ("asset_dashboard_start_date","asset_dashboard_end_date"):
                self.assertEqual(storage.target("app",key),storage.preferences)

    def test_startup_and_initial_tab_share_one_request(self):
        runner=SimpleNamespace(_startup_requested=False,request=Mock())
        self.assertTrue(HistoryIndicatorRunner.request_startup(runner))
        self.assertFalse(HistoryIndicatorRunner.request_startup(runner))
        runner.request.assert_called_once_with(reload_history=True,rebuild_indicators=True,
                                               reason="startup_asset_indicators")


if __name__=="__main__":unittest.main()
