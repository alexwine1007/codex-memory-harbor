"""Workbench, localization and source-distribution regression gates."""
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'skills/codex-memory-harbor/assets/dashboard'


class WorkbenchTests(unittest.TestCase):
    def node(self, source, *paths):
        if not shutil.which('node'):
            self.skipTest('Node required')
        subprocess.run(['node', '-e', source, *map(str, paths)], check=True)

    def test_selection_is_unbounded_protected_and_volume_plan_bound(self):
        self.node(r'''
const assert=require('node:assert/strict'),m=require(process.argv[1]);
const sessions=Array.from({length:40},(_,i)=>({path:'p'+i,eligible:true,logical:2*1024**3,age_days:40+i}));
sessions.push({path:'protected',eligible:false,logical:1e12},{path:'linked',eligible:false,linked:true});
assert.equal(m.recommendedItems(sessions).length,40); // no 25-item/5-GB truncation
assert.equal(m.sortItems(sessions.slice(0,40),'recent')[0].path,'p39');
assert.equal(m.sortItems([{logical:1,age_days:99},{logical:20,age_days:31}],'size')[0].logical,20);
const selected=new Set(['p0','protected','missing']);m.pruneSelection(sessions,selected);
assert.deepEqual([...selected],['p0']);
const plans=[{plan_id:'A',files:{files:[{source:'f1'}]}},{plan_id:'B',files:{files:[{source:'f2'}]}}];
assert.deepEqual(m.selectedObjects(sessions,plans,selected,new Set(['f1','f2','unauthorized'])),[
 {kind:'history',path:'p0'},{kind:'file',path:'f1',plan_id:'A'},{kind:'file',path:'f2',plan_id:'B'}]);
''', ASSETS / 'workbench-model.js')

    def test_dictionary_parity_interpolation_and_translated_progress(self):
        self.node(r'''
const assert=require('node:assert/strict'),i=require(process.argv[1]),p=require(process.argv[2]);
assert.deepEqual(Object.keys(i.dictionaries.en),Object.keys(i.dictionaries['zh-CN']));
for(const key of Object.keys(i.dictionaries.en)){
 assert.equal(typeof i.dictionaries.en[key],'string');assert.ok(i.dictionaries.en[key]);
 assert.deepEqual((i.dictionaries.en[key].match(/\{\w+\}/g)||[]).sort(),(i.dictionaries['zh-CN'][key].match(/\{\w+\}/g)||[]).sort());
}
assert.equal(i.normalize('zh-TW'),'zh-CN');assert.equal(i.normalize('fr'),'en');
assert.equal(i.translate('en','progressVerified',{percent:100,count:3}),'100% · 3 items verified');
const job={status:'complete',total:1,completed:1,bytes:2048,released_bytes:0};
assert.match(p.state(job,n=>n+' B',(k,v)=>i.translate('en',k,v)).detail,/no local copies removed/);
assert.equal(p.state(job,n=>n+' B',(k,v)=>i.translate('en',k,v)).percent,100);
''', ASSETS / 'i18n.js', ASSETS / 'progress-model.js')

    def test_all_static_translation_keys_exist(self):
        html = (ASSETS / 'index.html').read_text()
        js = (ASSETS / 'app.js').read_text()
        keys = set(re.findall(r'data-(?:i18n|aria|placeholder)="([\w]+)"', html))
        keys.update(re.findall(r"\bt\('([\w]+)'", js))
        self.node('const d=require(process.argv[1]).dictionaries.en;for(const k of JSON.parse(process.argv[2]))if(!d[k])throw Error(k);',
                  ASSETS / 'i18n.js', __import__('json').dumps(sorted(keys)))

    def test_real_api_safety_and_no_idle_polling(self):
        js = (ASSETS / 'app.js').read_text()
        html = (ASSETS / 'index.html').read_text()
        css = (ASSETS / 'styles.css').read_text()
        for path in ('/api/parking-plan', '/api/parking-start', '/api/parking-job?', '/api/project-plan', '/api/restore', '/api/finalize'):
            self.assertIn(path, js)
        self.assertIn("if(!confirmed)return;await executeMigration", js)
        self.assertIn("const generation=++searchGeneration", js)
        self.assertIn("query!==$('#search').value.trim()", js)
        self.assertIn("hasFiles?'checked':''", js)
        self.assertIn("old&&old!==next", js)
        self.assertIn('plans.clear();selectedFiles.clear();selectedParkedFiles.clear()', js)
        self.assertIn("const candidates=HarborWorkbench.recommendedItems(data.sessions),files=fileRows()", js)
        self.assertIn("for(const row of groupFiles(group))", js)
        self.assertIn("(!rows.length&&!mediaPlan)?'—':fmt(size)", js)
        self.assertIn("mediaPlan?'inspected':rows.length?'historyAmount':'unscanned'", js)
        self.assertIn("savePreference('theme',theme);applyTheme()", js)
        self.assertNotIn("savePreference('theme',theme);localize()", js)
        self.assertNotIn('setInterval(', js)
        self.assertNotIn('requestAnimationFrame(', js)
        self.assertNotIn('<nav', html)
        self.assertIn('prefers-reduced-transparency', css)
        self.assertIn('-webkit-backdrop-filter', css)
        self.assertIn('-webkit-appearance:none;appearance:none', css)
        self.assertIn('prefers-reduced-motion', css)
        ids = set(re.findall(r'id="([\w]+)"', html))
        selectors = set(re.findall(r"\$\('#([\w]+)'\)", js))
        self.assertEqual(selectors - ids, {'keepLocalBackup'})  # only confirmation-time control

    def test_native_material_and_localization(self):
        native = (ROOT / 'macos/CodexMemoryHarbor.swift').read_text()
        helper = (ROOT / 'macos/CodexMemoryHarborDashboard.swift').read_text()
        strings = (ROOT / 'macos/en.lproj/Localizable.strings').read_text()
        keys = set(re.findall(r'L\("([^"\n]+)"', native + helper))
        translated = set(re.findall(r'^"([^"]+)"\s*=', strings, re.M))
        self.assertEqual(keys - translated, set())
        self.assertIn('NSVisualEffectView()', native)
        self.assertIn('material.blendingMode = .behindWindow', native)
        self.assertIn('accessibilityDisplayShouldReduceTransparency', native)
        self.assertNotIn('Timer.', native)
        build = (ROOT / 'scripts/build_macos_app.sh').read_text()
        self.assertIn('for language in en zh-Hans', build)
        self.assertIn('0.4.6-beta.2', build)

    def test_workbench_does_not_nest_a_card_inside_the_native_window(self):
        css = (ASSETS / 'styles.css').read_text()
        helper = (ROOT / 'macos/CodexMemoryHarborDashboard.swift').read_text()
        self.assertIn('window.titleVisibility = .hidden', helper)
        self.assertIn('.workbench{width:100%;min-height:100vh;margin:0;border:0;border-radius:0;background:none;box-shadow:none', css)
        self.assertIn('padding:32px 20px 20px;border-radius:0', css)
        self.assertNotIn('width:min(980px,100%)', css)

    def test_manual_fixture_settings_cannot_touch_real_preferences(self):
        fixture = (ROOT / 'tests/ui_fixture_server.py').read_text()
        self.assertIn("mock.patch.object(harbor, 'config_path', return_value=fixture.root/'preferences.json')", fixture)
        self.assertIn('fixture.config.stop()', fixture)

    def test_public_documents_and_translation_contribution(self):
        readme = (ROOT / 'README.md').read_text()
        chinese = (ROOT / 'README.zh-CN.md').read_text()
        self.assertIn('README.zh-CN.md', readme)
        for content in (readme, chinese):
            self.assertIn('scripts/install_macos.sh', content)
            self.assertIn('SHA-256', content)
            self.assertIn('30', content)
        self.assertTrue((ROOT / 'CONTRIBUTING.md').exists())
        self.assertTrue((ROOT / 'docs/i18n.md').exists())


if __name__ == '__main__':
    unittest.main()
