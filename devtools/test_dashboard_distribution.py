"""Protect legacy distribution math and missing-history behavior."""
import ast
from pathlib import Path
import unittest
from datetime import date
from types import SimpleNamespace
from portefeuille_viewer.services.asset_dashboard_distribution import DashboardDistribution

class DistributionTests(unittest.TestCase):
    def test_legacy_math_unchanged(self):
        root = Path(__file__).resolve().parents[1] / 'portefeuille_viewer'
        old = ast.parse((root / 'ui_logica/single_asset_analyse_tab_logica.py').read_text(encoding='utf-8'))
        new = ast.parse((root / 'services/asset_dashboard_distribution.py').read_text(encoding='utf-8').replace('DashboardDistribution', 'SingleAssetAnalyseTab').replace('self.store', 'SNAPSHOT_STORE'))
        original = {n.name: n for n in ast.walk(old) if isinstance(n, ast.FunctionDef)}
        for node in ast.walk(new):
            if isinstance(node, ast.FunctionDef) and node.name in original and node.name not in ("__init__", "_as_finite_float"):
                self.assertEqual(ast.dump(node), ast.dump(original[node.name]), node.name)

    def test_volume_weight_and_normalization(self):
        rows = [dict(low=10.,high=10.,volume=3.),dict(low=11.,high=11.,volume=1.)]
        values = DashboardDistribution._distribution_from_bucket_centers(rows,[10.,11.],1.,True)
        self.assertEqual(values,[75.,25.])

    def test_missing_history(self):
        self.assertIsNone(DashboardDistribution(SimpleNamespace()).calculate('XLY',[10.,11.]))

if __name__ == '__main__':
    unittest.main()

