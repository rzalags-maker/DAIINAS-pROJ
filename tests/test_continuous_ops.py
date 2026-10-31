"""Offline WAL backup/restore and segmented replay acceptance."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from daiinas.continuous_store import SourceJournal
from daiinas.continuous_paper import PaperLedger
from daiinas.continuous_ops import backup_pair,verify_backup,rotate_source,status
from daiinas.continuous import replay,main
from test_continuous_paper import scan,market


class OpsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.src=self.root/'source.sqlite3';self.out=self.root/'paper.sqlite3'
        s=SourceJournal(self.src);p=PaperLedger(self.out,s.source_id)
        with patch('daiinas.continuous_store.clock_ms',return_value=1000):
            rows=s.append([scan(1000)])
        p.apply(rows);p.close();s.close()
    def tearDown(self):self.tmp.cleanup()

    def test_wal_safe_backup_restore_same_money_and_cursor(self):
        m=backup_pair(self.src,self.out,self.root/'backup')
        self.assertEqual(m,verify_backup(self.root/'backup'))
        a=replay([self.src],self.root/'a.sqlite3')
        b=replay([self.root/'backup'/'source.sqlite3'],self.root/'backup'/'paper.sqlite3')
        self.assertEqual(a,b)
        with self.assertRaises(ValueError):backup_pair(self.src,self.out,self.root/'backup')

    def test_immutable_source_rollover_keeps_account_and_full_replay(self):
        old=replay([self.src],self.out)
        rotate_source(self.src,self.out,self.root/'archive')
        s=SourceJournal(self.src);p=PaperLedger(self.out,s.source_id)
        try:
            with patch('daiinas.continuous_store.clock_ms',return_value=1100):
                rows=s.append([('CLOCK','clock:1100',{})])
            self.assertEqual(rows[0][0],old['source_cursor']+1)
            p.apply(rows);expected=p.report()
        finally:p.close();s.close()
        actual=replay([self.root/'archive'/'source.sqlite3',self.src],self.root/'replica.sqlite3')
        self.assertEqual(actual,expected)
        with self.assertRaisesRegex(ValueError,'Missing or out-of-order'):
            replay([self.src],self.root/'missing-prefix.sqlite3')

    def test_backup_checksum_corruption_detected(self):
        backup_pair(self.src,self.out,self.root/'backup')
        with (self.root/'backup'/'source.sqlite3').open('ab') as f:f.write(b'corrupt')
        with self.assertRaisesRegex(ValueError,'checksum'):verify_backup(self.root/'backup')

    def test_resume_replays_source_committed_before_process_died(self):
        s=SourceJournal(self.src)
        with patch('daiinas.continuous_store.clock_ms',return_value=2000):
            s.append([('CONTROL','pause:orphan',{'action':'pause'})])
        s.close()
        a=replay([self.src],self.out)
        self.assertTrue(a['paused_new_entries'])
        self.assertEqual(replay([self.src],self.out),a)
        self.assertFalse(status(self.src,self.out)['healthy'])

    def test_audit_cannot_be_rewritten(self):
        c=sqlite3.connect(self.out)
        try:
            with self.assertRaises(sqlite3.IntegrityError):c.execute("DELETE FROM audit")
        finally:c.close()
