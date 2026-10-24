from datetime import date, timedelta
import json
import multiprocessing
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import polars as pl

from portefeuille_viewer.services.shared_asset_history import SharedAssetHistory
from portefeuille_viewer.services import asset_indicator_service as service


def concurrent_cache(directory, counter, ready, output):
    cache = SharedAssetHistory('test-stock.accdb', directory)
    def build():
        with open(counter, 'a', encoding='utf-8') as stream:
            stream.write('computed\n')
        time.sleep(.15)
        return {'A': {'score': 7}}
    ready.wait(10)
    output.put(cache.get(pl.DataFrame({'close': [10.]}), ['A'], build, rules='v1'))


class SharedHistoryTests(unittest.TestCase):
    def test_second_instance_reuses_and_source_or_rules_changes_invalidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            frame=pl.DataFrame({'close':[10.]});count=[]
            def build():count.append(1);return {'A': {'score':len(count)}}
            a=SharedAssetHistory('stock.accdb',tmp);b=SharedAssetHistory('stock.accdb',tmp)
            self.assertEqual(a.get(frame,['A'],build,rules='v1')['A']['score'],1)
            self.assertEqual(b.get(frame,['A'],build,rules='v1')['A']['score'],1)
            self.assertEqual(len(count),1)
            b.get(pl.DataFrame({'close':[11.]}),['A'],build,rules='v1')
            b.get(pl.DataFrame({'close':[11.]}),['A'],build,rules='v2')
            self.assertEqual(len(count),3)

    def test_corrupt_cache_rebuilds_and_failed_build_does_not_replace_good_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=SharedAssetHistory('stock.accdb',tmp);frame=pl.DataFrame({'close':[10.]})
            cache.get(frame,['A'],lambda:{'A':{'score':3}},rules='v1')
            good=cache.path.read_bytes()
            def broken():raise RuntimeError('intentional')
            with self.assertRaises(RuntimeError):cache.get(frame,['A'],broken,rules='v2')
            self.assertEqual(cache.path.read_bytes(),good)
            cache.path.write_text('{broken',encoding='utf-8')
            self.assertEqual(cache.get(frame,['A'],lambda:{'A':{'score':4}},rules='v1')['A']['score'],4)

    def test_asset_universe_and_historical_iv_changes_are_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=SharedAssetHistory('stock.accdb',tmp)
            first=pl.DataFrame({'close':[10.],'ibkr_iv_last':[.2]})
            cache.get(first,['A'],lambda:{'A':{'score':1}},rules='v1')
            second=pl.DataFrame({'close':[10.],'ibkr_iv_last':[.4]})
            result=cache.get(second,['A'],lambda:{'A':{'score':2}},rules='v1')
            self.assertEqual(result['A']['score'],2)
            result=cache.get(second,['A','B'],lambda:{'A':{'score':2},'B':{'score':3}},rules='v1')
            self.assertEqual(set(result),{'A','B'})

    def test_three_processes_compute_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx=multiprocessing.get_context('spawn');ready=ctx.Event();output=ctx.Queue()
            counter=str(Path(tmp)/'counter.txt')
            children=[ctx.Process(target=concurrent_cache,args=(tmp,counter,ready,output)) for _ in range(3)]
            try:
                for child in children:child.start()
                ready.set()
                self.assertEqual([output.get(timeout=30) for _ in children],[{'A':{'score':7}}]*3)
                for child in children:child.join(10);self.assertEqual(child.exitcode,0)
                self.assertEqual(Path(counter).read_text(encoding='utf-8').splitlines(),['computed'])
            finally:
                for child in children:
                    if child.is_alive():child.terminate();child.join(5)
                output.close();output.join_thread()

    def test_profiles_share_historical_scores_but_keep_separate_theta(self):
        history=[dict(datum=date(2025,1,1)+timedelta(days=i),asset_rollup='A',
                      open_price=100+i,high_price=102+i,low_price=99+i,
                      close_price=101+i,volume_value=10000+i*5) for i in range(90)]
        core=service._calculate_asset_history(history)
        builder=service.AssetIndicatorService();asset=dict(asset_rollup='A',type='aandeel')
        one=builder._build_asset_row(asset,history,date(2026,1,1),{},historical=core)
        two=builder._build_asset_row(asset,history,date(2026,1,1),
              dict(avg_iv=.5,avg_theta_abs=2,avg_time_per_unit=10,avg_last_px=20,avg_und_px=100),historical=core)
        for key in ('direction_score','volume_score','atr_pct','choppiness_score','realized_volatility_20d_pct'):
            self.assertEqual(one[key],two[key])
        self.assertNotEqual(one['theta_score'],two['theta_score'])
        self.assertNotIn('theta_score',core)


if __name__=='__main__':unittest.main()
