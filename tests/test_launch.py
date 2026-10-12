"""Public first-use and launch contracts; never migrate private history."""
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
REAL_RUN = subprocess.run
spec = importlib.util.spec_from_file_location('harbor_trial', ROOT / 'scripts/try_harbor.py')
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class TrialTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.local = self.root / 'local'
        self.local.mkdir()
        self.volume = self.root / 'volume'
        self.volume.mkdir()
        self.archive = trial.load_module('archive_files')
        self.harbor = SimpleNamespace(
            mounted_volume=mock.Mock(return_value=self.volume),
            volume_identity=mock.Mock(return_value={'uuid': 'TRIAL-VOLUME'}),
            verify_external_volume=mock.Mock())
        patcher = mock.patch.object(trial, 'load_module', side_effect=lambda name:
                                    self.archive if name == 'archive_files' else self.harbor)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(trial.tempfile, 'mkdtemp', return_value=str(self.local))
        patcher.start()
        self.addCleanup(patcher.stop)
        # Unit fixtures don't use system volumes/handles. The public trial does.
        patcher = mock.patch.object(self.archive.subprocess, 'run', return_value=
                                    SimpleNamespace(returncode=1, stdout=b'', stderr=b''))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_command_prints_plan_and_creates_nothing(self):
        env = dict(os.environ, CODEX_HOME='/unreachable/private-home')
        result = REAL_RUN([sys.executable, str(ROOT / 'scripts/try_harbor.py')],
                                capture_output=True, text=True, env=env, check=True)
        plan = json.loads(result.stdout)
        self.assertEqual(plan['mode'], 'plan_only')
        self.assertFalse(plan['creates_files'])
        self.assertFalse(plan['reads_codex_history'])
        self.assertEqual(plan['sample_bytes'], 131072)

    def test_execution_requires_explicit_volume(self):
        with mock.patch.object(sys, 'argv', ['try_harbor.py', '--execute']):
            with self.assertRaises(SystemExit) as result:
                trial.main()
        self.assertEqual(result.exception.code, 2)
        self.harbor.mounted_volume.assert_not_called()

    def test_real_core_restores_new_sample_and_retains_external_copy(self):
        original_environment = os.environ.get('CODEX_HARBOR_FILE_LOCK_DIR')
        events = []
        report = trial.run_trial(str(self.volume), events.append)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['sample_bytes'], 131072)
        self.assertEqual(report['steps'][-1], 'restored_and_both_copies_verified')
        self.assertEqual(len(events), 4)
        source = self.local / 'sample.txt'
        target = Path(report['external_samples']) / 'sample.txt'
        self.assertFalse(source.is_symlink())
        self.assertEqual(source.read_bytes(), target.read_bytes())
        self.assertEqual(self.archive.digest(source), report['sha256'])
        self.assertTrue((target.parent / 'receipt.jsonl').is_file())
        self.assertEqual(os.environ.get('CODEX_HARBOR_FILE_LOCK_DIR'), original_environment)
        self.assertGreaterEqual(self.harbor.verify_external_volume.call_count, 3)

    def test_volume_failure_happens_before_creating_any_sample(self):
        self.harbor.verify_external_volume.side_effect = RuntimeError('missing volume')
        with self.assertRaises(RuntimeError):
            trial.run_trial(str(self.volume))
        self.assertEqual(list(self.volume.iterdir()), [])
        self.assertEqual(list(self.local.iterdir()), [])

    def test_failure_retains_sample_and_writes_error_class(self):
        with mock.patch.object(self.archive, 'archive_file', side_effect=OSError('fixture error')):
            with self.assertRaises(OSError):
                trial.run_trial(str(self.volume))
        self.assertTrue((self.local / 'sample.txt').is_file())
        report = json.loads((self.local / 'trial-report.json').read_text())
        self.assertEqual(report['status'], 'stopped_samples_retained')
        self.assertEqual(report['error'], 'OSError')
        self.assertFalse(report['reads_codex_history'])

    def test_original_path_read_failure_stops_before_restore(self):
        real_digest = self.archive.digest
        def corrupt_read(path):
            if Path(path).is_symlink():
                return 'wrong'
            return real_digest(path)
        # Change the independent trial check only after the production dock finishes.
        real_archive = self.archive.archive_file
        def dock(*args, **kwargs):
            result = real_archive(*args, **kwargs)
            self.archive.digest = corrupt_read
            return result
        with mock.patch.object(self.archive, 'archive_file', side_effect=dock):
            with mock.patch.object(self.archive, 'restore_file') as restore:
                with self.assertRaisesRegex(RuntimeError, 'Original-path'):
                    trial.run_trial(str(self.volume))
                restore.assert_not_called()
        self.assertTrue((self.local / 'sample.txt').is_symlink())
        self.assertTrue((self.local / 'sample.txt.harbor-archive-rollback').is_file())


class LaunchContracts(unittest.TestCase):
    def test_walkthroughs_are_thirty_seconds_and_capture_mime_matches(self):
        renderer = (ROOT / 'scripts/render_walkthrough.mjs').read_text()
        self.assertIn('data:image/jpeg;base64,', renderer)
        self.assertIn('`${phase}.${language}.jpg`', renderer)
        for language in ('en', 'zh-CN'):
            for phase in ('inventory', 'plan', 'complete', 'restore'):
                capture = ROOT / 'docs/launch/captures' / (phase + '.' + language + '.jpg')
                self.assertEqual(capture.read_bytes()[:3], b'\xff\xd8\xff')
            data = (ROOT / 'docs/launch' / ('walkthrough.' + language + '.mp4')).read_bytes()
            self.assertEqual(data[4:8], b'ftyp')
            movie = data.index(b'mvhd')
            self.assertEqual(data[movie + 4], 0)
            timescale, duration = struct.unpack('>II', data[movie + 16:movie + 24])
            self.assertEqual(duration / timescale, 30)

    def test_bilingual_covers_are_shareable_and_have_no_private_content(self):
        for language in ('en', 'zh-CN'):
            png = ROOT / 'docs/launch' / ('social-preview.' + language + '.png')
            data = png.read_bytes()
            self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
            self.assertEqual(struct.unpack('>II', data[16:24]), (1280, 640))
            self.assertLess(len(data), 1_000_000)
            svg = png.with_suffix('.svg').read_text()
            self.assertNotIn('/Users/', svg)
            self.assertIn('SOURCE BETA' if language == 'en' else '源码测试版', svg)

    def test_feedback_is_opt_in_and_private_safe(self):
        form = (ROOT / '.github/ISSUE_TEMPLATE/beta_feedback.yml').read_text()
        for field in ('version', 'medium', 'filesystem', 'outcomes', 'experience', 'privacy'):
            self.assertIn('id: ' + field, form)
        self.assertIn('private session logs', form)
        self.assertNotIn('label: Email', form)
        self.assertIn('required: true', form)

    def test_public_ui_fixture_does_not_publish_real_device_capacity(self):
        fixture = (ROOT / 'tests/ui_fixture_server.py').read_text()
        self.assertIn("mock.patch.object(harbor.shutil, 'disk_usage'", fixture)
        self.assertIn('free=16*1024**3', fixture)

    def test_readmes_offer_trial_demo_and_feedback_without_binary_claim(self):
        for name in ('README.md', 'README.zh-CN.md'):
            text = (ROOT / name).read_text()
            self.assertIn('docs/launch/TRY.md', text)
            self.assertIn('scripts/try_harbor.py', text)
            self.assertIn('template=beta_feedback.yml', text)
        self.assertIn('notarized', (ROOT / 'docs/launch/TRY.md').read_text())

    def test_launch_drafts_keep_goals_and_publication_status_separate(self):
        posts = (ROOT / 'docs/launch/POSTS.md').read_text()
        plan = (ROOT / 'docs/launch/PLAN.md').read_text()
        self.assertIn('None of these posts or invitations has been sent', posts)
        self.assertIn('not claimed users', plan)
        self.assertIn('not a usage result', (ROOT / 'README.md').read_text())
        for name in ('README.md', 'README.zh-CN.md', 'TRY.md', 'POSTS.md', 'PLAN.md'):
            text = (ROOT / 'docs/launch' / name).read_text()
            self.assertNotIn('/Users/alexsolar', text)
            self.assertNotIn('Alex‘s Disk', text)
