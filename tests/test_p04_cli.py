import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from daiinas.continuous import main,settings
from daiinas.continuous_store import SourceJournal
from daiinas.v47 import configuration


class P04CLITests(unittest.TestCase):
    def test_live_mode_is_blocked_before_any_command_is_journaled(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);config=configuration('200','mock-p04-cli',timestamp_ms=0);config['p04_mock']={}
            path=r/'config.json';path.write_text(json.dumps(config))
            source=SourceJournal(r/'source.sqlite');source.close()
            out=io.StringIO()
            with contextlib.redirect_stdout(out):
                result=main(['p04-mode','--mode','START_LIVE','--config',str(path),
                    '--source-db',str(r/'source.sqlite'),'--paper-db',str(r/'paper.sqlite')])
            self.assertEqual(result,2);self.assertEqual(json.loads(out.getvalue())['status'],'BLOCKED')
            source=SourceJournal(r/'source.sqlite')
            try:self.assertFalse(source.after(0))
            finally:source.close()

    def test_cli_start_is_source_acceptance_not_an_offline_worker_ack(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);config=configuration('200','mock-p04-cli',timestamp_ms=0);config['p04_mock']={}
            path=r/'config.json';path.write_text(json.dumps(config))
            source=SourceJournal(r/'source.sqlite');source.close();out=io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(['start','--config',str(path),'--source-db',str(r/'source.sqlite'),
                    '--paper-db',str(r/'paper.sqlite'),'--command-id','paper-start']),0)
            result=json.loads(out.getvalue());self.assertFalse(result['runtime_effect_confirmed'])
            self.assertEqual(result['ack'],'SOURCE_ACCEPTED_AWAITING_WORKER')
            source=SourceJournal(r/'source.sqlite')
            try:self.assertEqual(source.after(0)[0][4]['mode'],'START_PAPER')
            finally:source.close()

    def test_configuration_cannot_select_a_live_or_arbitrary_transport(self):
        with tempfile.TemporaryDirectory() as d:
            config=configuration('200','mock-p04-cli',timestamp_ms=0)
            config['p04_mock']={'transport':'LIVE'};p=Path(d)/'c.json';p.write_text(json.dumps(config))
            with self.assertRaises(TypeError):settings(p)
