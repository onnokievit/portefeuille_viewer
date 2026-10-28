from types import SimpleNamespace, MethodType
import unittest

from portefeuille_viewer.services.asset_dashboard_controls import DashboardPayoffControls, validate_controls


def legacy_settings_fixture():
    # Use the actual legacy validation methods, without constructing its UI or opening a DB.
    from portefeuille_viewer.ui_logica.single_asset_analyse_tab_logica import SingleAssetAnalyseTab
    target=SimpleNamespace(_step_settings_by_asset={
        "AAPL":dict(step_size=1.5,step_size_tick=.5,chart_shift=.2,price_decimals=4),
        "UVXY":dict(step_size=3.,step_size_tick=1.,chart_shift=-2.,price_decimals=0)},
        _step_defaults=dict(step_size=2.,step_size_tick=.5,chart_shift=0.,price_decimals=2),
        _step_settings_dirty=False)
    for name in ("_safe_step_value","_safe_step_tick","_safe_chart_shift","_safe_price_decimals","_infer_default_price_decimals"):
        setattr(target,name,MethodType(getattr(SingleAssetAnalyseTab,name),target))
    return target


class ControlsTests(unittest.TestCase):
    def test_reads_all_four_existing_values_per_asset(self):
        editor=DashboardPayoffControls(legacy_settings_fixture())
        self.assertEqual(editor.get("AAPL"),dict(step_pct=1.5,step_tick=.5,shift=.2,decimals=4))
        self.assertEqual(editor.get("UVXY"),dict(step_pct=3.,step_tick=1.,shift=-2.,decimals=0))

    def test_changes_only_selected_asset_and_uses_existing_dirty_flush_flag(self):
        target=legacy_settings_fixture();editor=DashboardPayoffControls(target);before=dict(target._step_settings_by_asset["UVXY"])
        editor.save("AAPL",dict(step_pct=2.,step_tick=.55,shift=.3,decimals=3))
        self.assertEqual(target._step_settings_by_asset["AAPL"],dict(step_size=2.,step_size_tick=.55,chart_shift=.3,price_decimals=3))
        self.assertEqual(target._step_settings_by_asset["UVXY"],before)
        self.assertTrue(target._step_settings_dirty)
        self.assertEqual(DashboardPayoffControls(target).get("AAPL")["step_pct"],2.)

    def test_unchanged_values_are_not_marked_dirty(self):
        target=legacy_settings_fixture();editor=DashboardPayoffControls(target)
        editor.save("AAPL",editor.get("AAPL"));self.assertFalse(target._step_settings_dirty)

    def test_invalid_values_are_rejected(self):
        valid=dict(step_pct=1.5,step_tick=.5,shift=0.,decimals=2)
        for key,value in [("step_tick",0),("step_pct",float("nan")),("shift",10000),("decimals",2.5)]:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):validate_controls({**valid,key:value})


if __name__=="__main__":unittest.main()
