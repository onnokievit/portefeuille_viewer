import base64
from datetime import datetime
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from uuid import uuid4
import pyodbc
from devtools.harden_stockdata_constraints import audit, apply_constraints
from portefeuille_viewer.data.historical_integrity import assert_unambiguous_source


class ConstraintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='pv-constraints-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.base=Path(cls.temp.name)/'base.accdb'
        schema='Id COUNTER PRIMARY KEY, symbol TEXT(50), datum DATETIME, asset_rollup TEXT(50), [open] DOUBLE, [high] DOUBLE, [low] DOUBLE, [close] DOUBLE, volume DOUBLE, wap DOUBLE'
        statements=[f'CREATE TABLE {name} ({schema})' for name in ('historical_data_correct','temp_stock_prices_temp')]
        script="$ErrorActionPreference='Stop';$e=New-Object -ComObject DAO.DBEngine.120;$d=$e.CreateDatabase('"+str(cls.base).replace("'","''")+"',';LANGID=0x0409;CP=1252;COUNTRY=0',128);"+''.join("$d.Execute('"+sql+"');" for sql in statements)+"$d.Close()"
        subprocess.run(['powershell','-NoProfile','-NonInteractive','-EncodedCommand',base64.b64encode(script.encode('utf-16-le')).decode()],capture_output=True,check=True,timeout=30)

    def setUp(self):
        self.path=self.base.with_name(uuid4().hex+'.accdb');shutil.copy2(self.base,self.path)
        self.conn=pyodbc.connect('DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ='+str(self.path)+';')
        self.addCleanup(self.conn.close)

    def insert(self,table,price):
        self.conn.cursor().execute(f'INSERT INTO [{table}] ([symbol],[datum],[asset_rollup],[close]) VALUES (?,?,?,?)','ABC',datetime(2026,1,2),'ABC',price)
        self.conn.commit()

    def test_identical_duplicates_removed_and_index_enforces_unique_key(self):
        self.insert('historical_data_correct',10);self.insert('historical_data_correct',10)
        report=audit(self.conn);self.conn.commit()
        result=apply_constraints(self.conn,report,True)
        self.assertEqual(result['deleted_identical_rows'],1)
        self.assertTrue(audit(self.conn)['historical_data_correct']['protected'])
        with self.assertRaises(pyodbc.Error):self.insert('historical_data_correct',11)
        self.conn.rollback()
        count=self.conn.cursor().execute('SELECT Count(*) FROM historical_data_correct').fetchone()[0]
        self.assertEqual(count,1)

    def test_conflicting_duplicates_refused_before_modification(self):
        self.insert('historical_data_correct',10);self.insert('historical_data_correct',11)
        report=audit(self.conn);self.conn.commit()
        with self.assertRaisesRegex(RuntimeError,'manual review'):apply_constraints(self.conn,report,True)
        self.assertEqual(self.conn.cursor().execute('SELECT Count(*) FROM historical_data_correct').fetchone()[0],2)

    def test_duplicate_source_is_distinct_and_repeated_merge_is_idempotent(self):
        self.insert('temp_stock_prices_temp',10);self.insert('temp_stock_prices_temp',10)
        root=Path(__file__).resolve().parents[1]
        for script in ('price_update_scripts/1 B - stockprice merge into historical data correct.py','price_update_scripts_single_stock_fetch_long_history/22 - stockprice merge into historical data correct.py'):
            with self.subTest(script=script):
                spec=importlib.util.spec_from_file_location('merge_test_'+uuid4().hex,root/script)
                module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                assert_unambiguous_source(self.conn,module.TEMP_TABLE,module.COLUMNS)
                module.merge_update_insert(self.conn.cursor());self.conn.commit()
                module.merge_update_insert(self.conn.cursor());self.conn.commit()
                self.assertEqual(self.conn.cursor().execute('SELECT Count(*) FROM historical_data_correct').fetchone()[0],1)

    def test_conflicting_source_is_rejected(self):
        self.insert('temp_stock_prices_temp',10);self.insert('temp_stock_prices_temp',11)
        with self.assertRaisesRegex(ValueError,'conflicting daily prices'):
            assert_unambiguous_source(self.conn,'temp_stock_prices_temp',['symbol','datum','asset_rollup','close'])
        self.assertEqual(self.conn.cursor().execute('SELECT Count(*) FROM historical_data_correct').fetchone()[0],0)


if __name__=='__main__':unittest.main()
