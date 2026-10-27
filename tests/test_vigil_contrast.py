"""Every text/background pair used by the VigilOS themes is >= 4.5:1 (3:1 for large or non-text), light, Night and each accent."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/makos'))
from makos import appearance  # noqa: E402


def lum(hex_):
    c = [int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [v / 12.92 if v <= .03928 else ((v + .055) / 1.055) ** 2.4 for v in c]
    return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + .05) / (lb + .05)


def palette(accent='blossom', graphite=False, dark=False):
    base = (ROOT / 'src/makos/theme/gtk-4.0/gtk.css').read_text()
    colors = dict(re.findall(r'@define-color (\w+) (#[0-9a-f]{6});', base))
    colors.update(appearance.tokens(accent, graphite, dark))
    return colors


# (foreground token, background token): the text pairs the stylesheets actually use.
TEXT_PAIRS = [('mk_text', 'mk_window'), ('mk_text', 'mk_base'), ('mk_text', 'mk_bar'), ('mk_text', 'mk_hover'), ('mk_text', 'mk_pressed'),
              ('mk_text', 'mk_alt_row'), ('mk_text', 'mk_sidebar_a'), ('mk_text', 'mk_sidebar_b'), ('mk_text', 'mk_menu'),
              ('mk_text_dim', 'mk_window'), ('mk_text_dim', 'mk_base'), ('mk_text_dim', 'mk_bar'), ('mk_text_dim', 'mk_hover'),
              ('mk_text_dim', 'mk_pressed'), ('mk_text_dim', 'mk_alt_row'), ('mk_text_dim', 'mk_sidebar_a'),
              ('mk_acc_text', 'mk_acc_dark'), ('mk_link', 'mk_window'), ('mk_link', 'mk_base'),
              ('mk_error', 'mk_window'), ('mk_error', 'mk_base'), ('mk_warning', 'mk_window'), ('mk_warning', 'mk_base'),
              ('mk_success', 'mk_window'), ('mk_success', 'mk_base')]
# non-text: control outlines and focus rings against the surfaces they sit on (3:1)
UI_PAIRS = [('mk_border', 'mk_window'), ('mk_border', 'mk_base'), ('mk_focus', 'mk_window'), ('mk_focus', 'mk_base')]


class ContrastTests(unittest.TestCase):
    def check(self, name, **kw):
        p = palette(**kw)
        bad = [(f, b, round(ratio(p[f], p[b]), 2)) for f, b in TEXT_PAIRS if ratio(p[f], p[b]) < 4.5]
        bad += [(f, b, round(ratio(p[f], p[b]), 2)) for f, b in UI_PAIRS if ratio(p[f], p[b]) < 3]
        self.assertEqual(bad, [], name)

    def test_light(self):
        self.check('light')

    def test_night(self):
        self.check('night', dark=True)

    def test_accents_light(self):
        for accent in appearance.ACCENTS:
            self.check(accent, accent=accent, graphite=accent == 'graphite')

    def test_accents_night(self):
        # Night keeps the light-mode accent fills; white text on them is what matters (selected rows, default buttons)
        for accent in appearance.ACCENTS:
            p = palette(accent, accent == 'graphite', True)
            self.assertGreaterEqual(ratio(p['mk_acc_text'], p['mk_acc_dark']), 4.5, accent)

    def test_fixed_pairs(self):
        for fg, bg in [('#ffffff', '#b3001b'), ('#f7eef2', '#1e1422'), ('#f7eef2', '#120a14'), ('#17101a', '#f7eef2'),
                       ('#ffffff', '#d6004a'), ('#d9c8d3', '#120a14'), ('#3d0016', '#ffd6e4'), ('#3b2400', '#fff1c9'),
                       ('#5a0010', '#ffdce1'), ('#0f2a5a', '#e3ecff'), ('#ffe9b0', '#3b2a00'), ('#ffd3da', '#4a0f1a'), ('#d6e4ff', '#12264d')]:
            self.assertGreaterEqual(ratio(fg, bg), 4.5, (fg, bg))


if __name__ == '__main__':
    unittest.main()
