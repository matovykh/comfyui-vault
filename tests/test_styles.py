"""Check semantic text/background pairs used across light and dark UI surfaces."""
from pathlib import Path
import re
import unittest

CSS = (Path(__file__).parents[1] / 'app/static/style.css').read_text()


def luminance(color):
    if len(color)==4: color='#'+''.join(c*2 for c in color[1:])
    values = [int(color[i:i+2], 16)/255 for i in (1, 3, 5)]
    values = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in values]
    return sum(v*w for v, w in zip(values, (.2126, .7152, .0722)))


class StyleTests(unittest.TestCase):
    def test_theme_text_pairs_meet_normal_text_contrast(self):
        for selector in (':root', ':root[data-theme=light]', ':root[data-theme=system]'):
            block = CSS.split(selector + ' {', 1)[1].split('}', 1)[0]
            colors = dict(re.findall(r'--([\w-]+):\s*(#[\da-f]{3,6})\b', block))
            for foreground, background in [('text','panel'),('text','panel2'),('muted','panel'),
                    ('muted','sidebar'),('accent','accent-bg'),('danger','danger-bg'),
                    ('warning','warning-bg'),('on-accent','accent'),('badge-text','badge-bg')]:
                with self.subTest(theme=selector, pair=(foreground, background)):
                    a, b = sorted((luminance(colors[foreground]), luminance(colors[background])))
                    self.assertGreaterEqual((b+.05)/(a+.05), 4.5)

    def test_ellipsis_and_typography_have_one_shared_definition(self):
        self.assertIn('--body:1rem', CSS)
        self.assertIn('--small:.875rem', CSS)
        self.assertNotIn('/* Repository browser v2 */', CSS)
        description = CSS.split('.full-description{', 1)[1].split('}', 1)[0]
        for declaration in ('white-space:nowrap', 'overflow:hidden', 'text-overflow:ellipsis'):
            self.assertIn(declaration, description)
