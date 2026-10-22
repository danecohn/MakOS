"""Startup watchdog: no live compositor, service activation, authentication agent or user config."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class MakOSSessionTests(unittest.TestCase):
    def run_session(self,body):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp)
            (home/'bin').mkdir();(home/'runtime/makos').mkdir(parents=True)
            shell=home/'bin/makos-shell'
            shell.write_text('#!/bin/sh\nprintf "start\\n" >> "$HOME/starts"\n'+body)
            shell.chmod(0o755)
            env=dict(os.environ,HOME=temp,XDG_STATE_HOME=str(home/'state'),XDG_CONFIG_HOME=str(home/'config'),XDG_RUNTIME_DIR=str(home/'runtime'),MAKOS_BIN=str(home/'bin'),MAKOS_TEST_MODE='1',MAKOS_READY_WAIT_STEPS='2')
            result=subprocess.run(['sh',str(ROOT/'src/makos/session/session-start')],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=20)
            return result.returncode,(home/'starts').read_text().splitlines(),(home/'state/makos/shell.log').read_text()
    def test_missing_ready_marker_restarts_then_fails_closed(self):
        code,starts,log=self.run_session('exec sleep 30\n')
        self.assertEqual(code,1)
        self.assertEqual(len(starts),5)
        self.assertEqual(log.count('ready marker absent'),5)
    def test_ready_clean_exit_ends_without_restart(self):
        code,starts,log=self.run_session('echo $$ > "$XDG_RUNTIME_DIR/makos/shell-ready"\nsleep .8\nexit 0\n')
        self.assertEqual(code,0)
        self.assertEqual(len(starts),1)
        self.assertNotIn('ready marker absent',log)

    def test_clean_exit_without_ready_is_a_startup_failure(self):
        code,starts,log=self.run_session("exit 0\n")
        self.assertEqual(code,1)
        self.assertEqual(len(starts),5)
        self.assertEqual(log.count("exited before reporting ready"),5)
