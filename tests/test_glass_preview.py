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
        self.assertIn('id="workspace"', html)
        self.assertIn('id="candidates"', html)
        self.assertNotIn('<nav', html)
        self.assertNotIn('id="harbor"', html)
        self.assertNotIn('id="dock"', html)
        self.assertNotIn('data-page=', html)
        self.assertIn('id="review"', html)
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

    def test_single_workbench_search_and_selection_are_not_navigation(self):
        folder = ROOT / 'docs/design/glass-preview'
        html = (folder / 'index.html').read_text()
        js = (folder / 'glass.js').read_text()
        self.assertIn('搜索内容与记忆', html)
        self.assertIn('查找项目、文件或过去的记录', html)
        self.assertIn('id="searchView" hidden', html)
        self.assertIn('id="clearSearch"', html)
        self.assertIn("$('#query').oninput=", js)
        self.assertIn("$('#selectionBar').hidden=searching", js)
        self.assertIn("$('#candidates').hidden=searching", js)
        self.assertIn("search();selection();", js)
        self.assertNotIn('navigate(', js)
        self.assertIn('!picked.length||!connected', js)
        self.assertNotIn('给现在，', html)
