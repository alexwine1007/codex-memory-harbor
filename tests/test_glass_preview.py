from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GlassPreviewTests(unittest.TestCase):
    def test_review_is_isolated_from_real_files_and_runtime(self):
        folder = ROOT / 'docs/design/glass-preview'
        html = (folder / 'index.html').read_text()
        css = (folder / 'glass.css').read_text()
        js = (folder / 'glass.js').read_text()
        self.assertIn('所有数字均为样例，不操作真实文件', html)
        for page in ('港湾', '找回记忆', '停泊'):
            self.assertIn(page, html)
        for forbidden in ('fetch(', '/api/', 'XMLHttpRequest', 'setInterval(', 'requestAnimationFrame(', 'localStorage'):
            self.assertNotIn(forbidden, html + js)
        self.assertIn('prefers-reduced-motion', css)
        self.assertIn('prefers-reduced-transparency', css)
        self.assertIn('prefers-contrast', css)
        self.assertIn('@supports not', css)
        self.assertIn('focus-visible', css)
        self.assertIn('Music Lab', css)
        self.assertIn('blur(22px) saturate(1.45)', css)
        self.assertNotIn('animation:', css.replace('animation:none!important', ''))
        self.assertIn('aria-valuenow', js)
        self.assertIn('本地副本已保留', js)
        self.assertIn('event.metaKey||event.ctrlKey', js)
