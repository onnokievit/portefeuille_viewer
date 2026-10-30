import unittest
from types import SimpleNamespace,MethodType
from unittest.mock import patch
import polars as pl
from portefeuille_viewer.services.asset_dashboard_summary import summary_colors

class SummaryTests(unittest.TestCase):
    def test_exact_legacy_colour_methods_are_reused(self):
        from portefeuille_viewer.ui_logica import single_asset_analyse_tab_logica as module
        legacy=SimpleNamespace()
        for name in ('_color_green_red','_pct_gradient_color','_get_portfolio_value_pct_color'):
            setattr(legacy,name,MethodType(getattr(module.SingleAssetAnalyseTab,name),legacy))
        frame=pl.DataFrame({'asset_rollup':['A','B'],'portfolio_total_waarde_lineair_pct':[.028,.1],
            'portfolio_total_waarde_delta_pct':[.031,.2]})
        store=SimpleNamespace(repository_snapshot_portfolio_value_total_combined_put=frame)
        with patch.object(module,'SNAPSHOT_STORE',store):
            colors=summary_colors(legacy,'A',dict(koers=33.,koers_prev=32.,pct_change=-.0076,net_change=10.))
            missing=summary_colors(legacy,'unknown',{})
        self.assertEqual(colors['koers'],'#c6efce')
        self.assertEqual(colors['koers_prev'],'#ddebf7')
        self.assertEqual(colors['pct_change'],'#ffc7ce')
        self.assertEqual(colors['net_change'],'#c6efce')
        self.assertEqual(colors['portfolio_total_waarde_lineair_pct'],'#00b45a')
        self.assertEqual(colors['portfolio_total_waarde_delta_pct'],'#00b45a')
        self.assertEqual(missing['koers'],'');self.assertEqual(missing['portfolio_total_waarde_lineair_pct'],'')

if __name__=='__main__':unittest.main()
