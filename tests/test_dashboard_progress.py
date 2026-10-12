"""Execute the real, dependency-free progress presentation model in Node."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'skills/codex-memory-harbor/assets/dashboard'


class ProgressTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required for JavaScript regression')
    def test_terminal_progress_and_release_language(self):
        script = r'''
const assert = require('node:assert/strict');
const {state} = require(process.argv[1]);
const format = n => `${n} B`;
const job = {completed:5836,total:5836,bytes:6300,status:'complete',released_bytes:6300};
assert.equal(state(job,format).percent,100);
assert.equal(state({...job,status:'running'},format).percent,99);
assert.equal(state({...job,status:'failed',completed:9,total:11},format).complete,false);
assert.equal(state({...job,completed:9,total:11},format).complete,false);
assert.equal(state({...job,released_bytes:0},format).detail,'已验证 6300 B；本次未移除本地副本。');
assert.match(state({...job,released_bytes:undefined},format).detail,/空间释放情况请查看回执/);
assert.match(state({...job,released_bytes:undefined,metrics:{released_bytes:0}},format).detail,/未移除/);
assert.equal(state({total:0,status:'running'},format).percent,0);
assert.equal(state({total:0,completed:0,status:'complete',released_bytes:0},format).percent,100);
'''
        subprocess.run([shutil.which('node'), '-e', script, str(ASSETS / 'progress-model.js')], check=True)

    def test_native_progress_has_no_partial_width_animation(self):
        html = (ASSETS / 'index.html').read_text()
        css = (ASSETS / 'styles.css').read_text()
        js = (ASSETS / 'app.js').read_text()
        self.assertIn('<progress id="progressFill"', html)
        self.assertLess(html.index('src="progress-model.js"'), html.index('src="app.js"'))
        self.assertNotIn('transition:width', css)
        self.assertIn('data-i18n="transferDetails"', html)
        self.assertIn("HarborProgress.state(job,fmt,t)", js)
        self.assertNotIn('已验证并释放 ${fmt(job.bytes)}', js)
