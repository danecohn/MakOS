"""Venture profile setup preserves unrelated data and never weakens browser security."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/makos'))
from makos import venture

class VentureTests(unittest.TestCase):
    def test_profile_setup_is_idempotent_and_preserves_data(self):
        with tempfile.TemporaryDirectory() as temp:
            profile=Path(temp)/'profile';profile.mkdir()
            (profile/'user.js').write_text('user_pref("my.preference", 42);\n')
            (profile/'places.sqlite').write_bytes(b'bookmarks fixture')
            for _ in range(3):venture.prepare(profile,ROOT/'src/makos/venture')
            prefs=(profile/'user.js').read_text();css=(profile/'chrome/userChrome.css').read_text()
            self.assertEqual(prefs.count(venture.BEGIN),1)
            self.assertEqual(prefs.count('browser.uiCustomization.state'),1)
            self.assertIn('my.preference',prefs)
            self.assertEqual((profile/'places.sqlite').read_bytes(),b'bookmarks fixture')
            self.assertEqual(css.count('@import'),1)
            for bad in ('sandbox','security.ssl','security.cert','remote.active','marionette'):
                self.assertNotIn(bad,prefs)
    def test_launcher_uses_only_dedicated_profile_and_keeps_urls_as_arguments(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(venture,'prepare',return_value=Path(temp)),patch('makos.venture_runtime.runtime',return_value=Path('/fixture/Venture')):
            args=venture.command(['https://example.invalid/a?b=c'],which=lambda exe:'/usr/bin/amerika-venture' if exe=='amerika-venture' else None)
            self.assertEqual(args,['/fixture/Venture','--name','Venture','--class','Venture','--profile',temp,'https://example.invalid/a?b=c'])
            self.assertNotIn('--no-remote',args)
