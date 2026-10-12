import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import urllib.request
from unittest import mock
from test_harbor import harbor


def module(name):
    path = Path(__file__).resolve().parents[1] / 'skills/codex-memory-harbor/scripts' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


assets = module('project_files')
archive = module('archive_files')


class ProjectStorageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.project = self.root / 'project'; self.project.mkdir()
        self.home = self.root / 'codex'; self.home.mkdir()
        self.volume = self.root / 'external'; self.volume.mkdir()
        self.source = self.project / 'clips' / 'shot.mp4'; self.source.parent.mkdir()
        self.source.write_bytes(b'fixture video bytes\0' * 128)
        old = time.time() - 60 * 86400; os.utime(self.source, (old, old))
        self.target = self.volume / 'Archive' / 'clips' / 'shot.mp4'
        self.receipt = self.volume / 'receipt.jsonl'
        patcher = mock.patch.object(archive.Path, 'home', return_value=self.root)
        patcher.start(); self.addCleanup(patcher.stop)
        self.config = mock.patch.object(harbor, 'load_config', return_value={'protected_projects': [], 'protected_sessions': []})
        self.config.start(); self.addCleanup(self.config.stop)
        self.identity = lambda: {'volume_uuid': 'VOL-1', 'volume_path': str(self.volume)}

    def copy(self, keep_local=False):
        return archive.archive_file(self.source, self.target, self.receipt, self.identity,
                                    check_handles=lambda path: None, keep_local=keep_local)

    def restore(self):
        return archive.restore_file(self.source, self.target, self.receipt, self.identity,
                                    check_handles=lambda path: None)

    def test_metadata_plan_does_not_read_assets_or_follow_external_links(self):
        (self.project / 'AGENTS.md').write_text('working instructions')
        (self.project / 'external.mov').symlink_to('/Volumes/Offline/hidden.mov')
        env = self.project / '.venv'; env.mkdir(); (env / 'ignored.mp4').write_bytes(b'not inventory')
        with mock.patch.object(Path, 'open', side_effect=AssertionError('content read')):
            plan = assets.asset_plan(str(self.project))
        self.assertEqual(plan['count'], 1)
        self.assertEqual(plan['linked_count'], 1)
        self.assertEqual(plan['skipped_local_directories'], 1)
        self.assertEqual(plan['files'][0]['relative'], 'clips/shot.mp4')
        self.assertFalse(self.source.is_symlink())

    def test_new_files_and_credentials_stay_local(self):
        (self.project / 'fresh.png').write_bytes(b'fresh')
        (self.project / '.env.mp4').write_bytes(b'private')
        plan = assets.asset_plan(str(self.project))
        self.assertEqual(plan['count'], 1)
        reasons = {row['reason'] for row in plan['retained']}
        self.assertIn('too_new', reasons); self.assertIn('secret_name', reasons)

    def test_hardlinks_are_not_proposed(self):
        os.link(self.source, self.project / 'another.mp4')
        self.assertEqual(assets.asset_plan(str(self.project))['count'], 0)

    def test_broad_roots_are_rejected(self):
        with self.assertRaises(ValueError): assets.asset_plan('/')

    def test_symlink_project_root_is_rejected(self):
        link = self.root / 'link'; link.symlink_to(self.project)
        with self.assertRaises(ValueError): assets.asset_plan(str(link))

    def test_frozen_relative_plan_rejects_traversal_and_replaced_source(self):
        plan = assets.asset_plan(str(self.project)); path = self.root / 'plan.json'
        path.write_text(json.dumps(plan)); rows = archive.read_source_plan(path)
        archive.verify_planned_source(rows[0]); self.source.write_bytes(b'new')
        with self.assertRaises(RuntimeError): archive.verify_planned_source(rows[0])
        plan['files'][0]['relative'] = '../outside.mp4'; path.write_text(json.dumps(plan))
        with self.assertRaises(ValueError): archive.read_source_plan(path)

    def test_repeated_filenames_preserve_nested_paths(self):
        other = self.project / 'other' / 'shot.mp4'; other.parent.mkdir(); other.write_bytes(b'other')
        old = time.time() - 60 * 86400; os.utime(other, (old, old))
        plan = assets.asset_plan(str(self.project))
        for row in plan['files']:
            archive.archive_file(Path(row['source']), self.volume / 'Archive' / row['relative'], self.receipt,
                                 self.identity, check_handles=lambda path: None)
        self.assertEqual(self.source.read_bytes(), b'fixture video bytes\0' * 128)
        self.assertEqual(other.read_bytes(), b'other')
        self.assertTrue(self.source.is_symlink()); self.assertTrue(other.is_symlink())

    def test_keep_backup_and_restore_preserve_bytes_and_external_copy(self):
        original = self.source.read_bytes(); self.copy(keep_local=True)
        self.assertTrue(self.source.is_symlink())
        self.assertTrue(self.source.with_name(self.source.name + '.harbor-archive-rollback').is_file())
        self.restore(); self.assertFalse(self.source.is_symlink())
        self.assertEqual(self.source.read_bytes(), original); self.assertEqual(self.target.read_bytes(), original)

    def test_external_only_restore(self):
        original = self.source.read_bytes(); self.copy(); self.restore()
        self.assertEqual(self.source.read_bytes(), original); self.assertFalse(self.source.is_symlink())
        self.assertTrue(self.target.is_file())

    def test_restore_refuses_corrupted_target(self):
        self.copy(); self.target.write_bytes(b'damaged')
        with self.assertRaises(RuntimeError): self.restore()
        self.assertTrue(self.source.is_symlink())

    def test_uuid_change_is_rejected_on_retry(self):
        self.copy(keep_local=True)
        with self.assertRaises(RuntimeError):
            archive.archive_file(self.source, self.target, self.receipt, lambda: {'volume_uuid': 'OTHER'},
                                 check_handles=lambda path: None)
        self.assertTrue(self.source.with_name(self.source.name + '.harbor-archive-rollback').is_file())

    def test_receipt_failure_rolls_back_to_local_file(self):
        original = self.source.read_bytes()
        with mock.patch.object(archive, 'append_receipt', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.copy()
        self.assertFalse(self.source.is_symlink()); self.assertEqual(self.source.read_bytes(), original)

    def test_flush_failure_preserves_original(self):
        original = self.source.read_bytes()
        with mock.patch.object(archive.os, 'fsync', side_effect=OSError('flush failed')):
            with self.assertRaises(OSError): self.copy()
        self.assertFalse(self.source.is_symlink()); self.assertEqual(self.source.read_bytes(), original)

    def test_parallel_same_source_is_rejected_before_copy(self):
        with archive.source_lock(self.source):
            with self.assertRaisesRegex(RuntimeError, '已有停泊'): self.copy()
        self.assertFalse(self.source.is_symlink()); self.assertFalse(self.target.exists())

    def test_target_parent_link_is_rejected_without_writing_elsewhere(self):
        elsewhere = self.root / 'elsewhere'; elsewhere.mkdir()
        (self.volume / 'Archive').symlink_to(elsewhere)
        with self.assertRaises(RuntimeError): self.copy()
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_server_frozen_plan_cannot_be_extended_or_retargeted(self):
        row = assets.asset_plan(str(self.project))['files'][0]
        app = {'project_plans': {'approved': {'rows': {row['source']: row}, 'project_id': 'project-1',
               'root': str(self.project), 'volume': str(self.volume), 'uuid': 'VOL-1', 'created_at': time.time()}}}
        request = {'plan_id': 'approved', 'confirmation': 'DOCK PROJECT FILE', 'path': str(self.source), 'volume': str(self.volume)}
        with self.assertRaises(harbor.HarborError): harbor.offload_project_file(app, dict(request, path='/etc/passwd'))
        with self.assertRaises(harbor.HarborError): harbor.offload_project_file(app, dict(request, volume='/Volumes/Other'))
        with self.assertRaises(harbor.HarborError): harbor.offload_project_file(app, dict(request, confirmation=''))
        app['project_plans']['approved']['created_at'] -= 4000
        with self.assertRaises(harbor.HarborError): harbor.offload_project_file(app, request)

    def test_project_endpoint_defaults_to_backup_and_checks_current_protection(self):
        row = assets.asset_plan(str(self.project))['files'][0]
        app = {'project_plans': {'approved': {'rows': {row['source']: row}, 'project_id': 'project-1',
               'root': str(self.project), 'volume': str(self.volume), 'uuid': 'VOL-1', 'created_at': time.time()}}}
        request = {'plan_id': 'approved', 'confirmation': 'DOCK PROJECT FILE', 'path': str(self.source), 'volume': str(self.volume)}
        with mock.patch.object(harbor, 'verify_external_volume'), mock.patch.object(harbor, 'project_archive_module', return_value=archive):
            result = harbor.offload_project_file(app, request)
        self.assertEqual(result['status'], 'verified_with_local_backup')
        with mock.patch.object(harbor, 'load_config', return_value={'protected_projects': [str(self.project)], 'protected_sessions': []}):
            with self.assertRaises(harbor.HarborError): harbor.offload_project_file(app, request)

    def test_real_http_project_plan_offload_restore_and_protection_bypass(self):
        import threading
        state = {'local-projects': {'project-1': {'name': 'Fixture Project', 'rootPaths': [str(self.project)]}}}
        (self.home / '.codex-global-state.json').write_text(json.dumps(state))
        server = harbor.ThreadingHTTPServer(('127.0.0.1', 0), harbor.HarborHandler)
        server.app = {'token': 'test-token', 'assets': self.root, 'codex_home': self.home, 'priority': '',
                      'protected_sessions': [], 'cache': None, 'cache_lock': threading.Lock(), 'mutation_lock': threading.Lock()}
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        def post(path, value):
            request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}{path}', data=json.dumps(value).encode(),
                      headers={'X-Harbor-Token': 'test-token', 'Content-Type': 'application/json'}, method='POST')
            return json.loads(urllib.request.urlopen(request, timeout=10).read())
        with mock.patch.object(harbor, 'mounted_volume', return_value=self.volume), \
             mock.patch.object(harbor, 'volume_identity', return_value={'uuid': 'VOL-1'}), \
             mock.patch.object(harbor, 'verify_external_volume'), mock.patch.object(harbor, 'available_volumes', return_value=[]), \
             mock.patch.object(harbor, 'project_archive_module', return_value=archive):
            plan = post('/api/project-plan', {'project_id': 'project-1', 'volume': str(self.volume)})['plan']
            self.assertEqual(plan['files']['count'], 1)
            self.assertFalse(self.source.is_symlink())
            request = {'plan_id': plan['plan_id'], 'path': str(self.source), 'volume': str(self.volume), 'confirmation': 'DOCK PROJECT FILE'}
            post('/api/project-file-offload', request)
            self.assertTrue(self.source.is_symlink())
            parked = post('/api/project-plan', {'project_id': 'project-1', 'volume': str(self.volume)})['plan']
            self.assertTrue(parked['files']['parked_files'][0]['restorable'])
            post('/api/project-file-restore', dict(request, plan_id=parked['plan_id'], confirmation='RESTORE PROJECT FILE'))
            self.assertFalse(self.source.is_symlink())
            # Client priority cannot override the server's stored retention choice.
            log = self.home / 'sessions/old.jsonl'; log.parent.mkdir()
            log.write_text(json.dumps({'type':'session_meta','payload':{'id':'child','parent_thread_id':'parent','cwd':str(self.project)}}) + '\n' +
                           json.dumps({'type':'event_msg','payload':{'type':'task_complete'}}) + '\n')
            old = time.time() - 60 * 86400; os.utime(log, (old, old))
            server.app['priority'] = str(self.project)
            with self.assertRaises(urllib.error.HTTPError):
                post('/api/plan', {'paths': [str(log)], 'volume': str(self.volume), 'priority': ''})
            self.assertFalse(log.is_symlink())


    def test_mixed_selection_real_http_job_preserves_legacy_history_and_file_restore(self):
        import threading
        state = {'local-projects': {'project-1': {'name': 'Fixture Project', 'rootPaths': [str(self.project)]}}}
        (self.home / '.codex-global-state.json').write_text(json.dumps(state))
        log = self.home / 'sessions/old.jsonl'; log.parent.mkdir()
        log.write_text(json.dumps({'type':'session_meta','payload':{'id':'child','parent_thread_id':'parent','cwd':str(self.project)}}) + '\n' +
                       json.dumps({'type':'event_msg','payload':{'type':'task_complete'}}) + '\n')
        old = time.time() - 60*86400; os.utime(log, (old, old))
        original_log, original_file = log.read_bytes(), self.source.read_bytes()
        server = harbor.ThreadingHTTPServer(('127.0.0.1', 0), harbor.HarborHandler)
        app = server.app = {'token':'test-token', 'assets':self.root, 'codex_home':self.home, 'priority':'',
                            'protected_sessions':[], 'cache':None, 'cache_lock':threading.Lock(), 'mutation_lock':threading.Lock()}
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        def post(path, value):
            request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}{path}', data=json.dumps(value).encode(),
                      headers={'X-Harbor-Token':'test-token', 'Content-Type':'application/json'}, method='POST')
            return json.loads(urllib.request.urlopen(request, timeout=10).read())
        with mock.patch.object(harbor, 'mounted_volume', return_value=self.volume), \
             mock.patch.object(harbor, 'volume_identity', return_value={'uuid':'VOL-1'}), \
             mock.patch.object(harbor, 'verify_external_volume'), mock.patch.object(harbor, 'available_volumes', return_value=[]), \
             mock.patch.object(harbor, 'project_archive_module', return_value=archive), \
             mock.patch.object(harbor, 'open_handles', return_value=0):
            project_plan = post('/api/project-plan', {'project_id':'project-1', 'volume':str(self.volume)})['plan']
            objects = [{'kind':'history','path':str(log)}, {'kind':'file','path':str(self.source), 'plan_id':project_plan['plan_id']}]
            for invalid in [objects+[objects[0]], [None], [{'kind':'unknown','path':str(log)}],
                            [{'kind':'file','path':'/etc/passwd','plan_id':project_plan['plan_id']}]]:
                with self.assertRaises(urllib.error.HTTPError):
                    post('/api/parking-plan', {'objects':invalid, 'volume':str(self.volume)})
            plan = post('/api/parking-plan', {'objects':objects, 'volume':str(self.volume)})['plan']
            self.assertEqual((plan['history_count'], plan['file_count']), (1,1))
            request = {'plan_id':plan['plan_id'], 'volume':str(self.volume), 'keep_local':False,
                       'confirmation':'DOCK SELECTED OBJECTS'}
            with self.assertRaises(harbor.HarborError): harbor.start_parking(app, dict(request, confirmation=''))
            with self.assertRaises(harbor.HarborError): harbor.start_parking(app, dict(request, volume='/Volumes/Other'))
            started = post('/api/parking-start', request)
            for _ in range(100):
                job = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/parking-job?id={started["job_id"]}').read())
                if job['status'] != 'running': break
                time.sleep(.03)
            self.assertEqual(job['status'], 'complete', job)
            self.assertEqual(job['completed'], 2)
            self.assertEqual(job['bytes'], len(original_log)+len(original_file))
            self.assertEqual(post('/api/parking-start', request)['job_id'], started['job_id'])
            with self.assertRaises(harbor.HarborError): harbor.start_parking(app, dict(request, keep_local=True))
            self.assertTrue(log.is_symlink()); self.assertTrue(self.source.is_symlink())
            self.assertEqual(log.read_bytes(), original_log); self.assertEqual(self.source.read_bytes(), original_file)
            self.assertTrue(harbor.audit_one(str(log), self.home)['verified'])
            self.assertFalse(Path(str(log)+'.offload-local-backup').exists())
            harbor.restore_one(str(log), self.home)
            plan = post('/api/project-plan', {'project_id':'project-1', 'volume':str(self.volume)})['plan']
            post('/api/project-file-restore', {'plan_id':plan['plan_id'], 'path':str(self.source), 'volume':str(self.volume),
                 'confirmation':'RESTORE PROJECT FILE'})
            self.assertFalse(log.is_symlink()); self.assertFalse(self.source.is_symlink())
            self.assertEqual(log.read_bytes(), original_log); self.assertEqual(self.source.read_bytes(), original_file)


class PhysicalVolumeSmokeTest(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('MEMORY_HARBOR_TEST_VOLUME'), 'explicit disposable-volume smoke test only')
    def test_original_path_read_release_and_restore_on_actual_volume(self):
        volume = Path(os.environ['MEMORY_HARBOR_TEST_VOLUME'])
        uuid = harbor.volume_identity(volume)['uuid']
        harbor.verify_external_volume(volume, uuid)
        with tempfile.TemporaryDirectory() as local, tempfile.TemporaryDirectory(prefix='.harbor-smoke-', dir=volume) as external:
            root = Path(local).resolve(); target_root = Path(external).resolve()
            source = root / 'fixture.mp4'; source.write_bytes(b'synthetic project asset\0' * 16384)
            target = target_root / 'clips/fixture.mp4'; receipt = target_root / 'receipt.jsonl'
            def check():
                harbor.verify_external_volume(volume, uuid)
                return {'volume_uuid': uuid, 'volume_path': str(volume)}
            with mock.patch.object(archive.Path, 'home', return_value=root):
                result = archive.archive_file(source, target, receipt, check)
                self.assertEqual(result['status'], 'local_entity_released')
                self.assertTrue(source.is_symlink()); self.assertEqual(archive.digest(source), result['sha256'])
                archive.restore_file(source, target, receipt, check)
                self.assertFalse(source.is_symlink()); self.assertEqual(archive.digest(source), result['sha256'])
                self.assertTrue(target.is_file())


class SessionSafetyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve(); self.home = self.root / 'codex'
        environment = mock.patch.dict(os.environ, {'CODEX_HARBOR_FILE_LOCK_DIR': str(self.root / 'locks')})
        environment.start(); self.addCleanup(environment.stop)
        self.source = self.home / 'sessions' / 'record.jsonl'; self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b'original history')
        self.volume = self.root / 'external'; self.volume.mkdir()
        self.target = self.volume / 'Archive/sessions/record.jsonl'
        self.plan = {'source': str(self.source), 'destination': str(self.target), 'backup': str(self.source) + '.offload-local-backup',
                     'bytes': self.source.stat().st_size, 'sha256': harbor.sha256(self.source), 'volume_uuid': 'VOL-1',
                     'volume_path': str(self.volume), 'source_signature': harbor.file_signature(self.source)}

    def offload(self):
        with mock.patch.object(harbor, 'verify_external_volume'), mock.patch.object(harbor, 'open_handles', return_value=0):
            return harbor.offload_one(self.plan, self.volume, 'Archive')

    def test_lsof_failure_is_fail_closed(self):
        result = mock.Mock(returncode=2, stderr='failure', stdout='')
        with mock.patch.object(harbor.subprocess, 'run', return_value=result):
            with self.assertRaises(harbor.HarborError): harbor.open_handles(self.source)

    def test_lsof_timeout_is_fail_closed(self):
        with mock.patch.object(harbor.subprocess, 'run', side_effect=harbor.subprocess.TimeoutExpired('lsof', 10)):
            with self.assertRaises(harbor.HarborError): harbor.open_handles(self.source)

    def test_persistent_volume_uuid_is_required_and_must_match(self):
        with mock.patch.object(harbor, 'mounted_volume'), mock.patch.object(harbor, 'volume_identity', return_value={'uuid': 'OTHER'}):
            with self.assertRaises(harbor.HarborError): harbor.verify_external_volume(self.volume, 'VOL-1')
            with self.assertRaises(harbor.HarborError): harbor.verify_external_volume(self.volume, '')

    def test_stale_source_plan_never_replaces_original(self):
        self.source.write_bytes(b'new active data')
        with self.assertRaises(harbor.HarborError): self.offload()
        self.assertFalse(self.source.is_symlink()); self.assertFalse(self.target.exists())

    def test_existing_target_is_never_overwritten(self):
        self.target.parent.mkdir(parents=True); self.target.write_bytes(b'other')
        with self.assertRaises(FileExistsError): self.offload()
        self.assertEqual(self.target.read_bytes(), b'other'); self.assertFalse(self.source.is_symlink())

    def test_matching_link_and_target_do_not_validate_corruption(self):
        self.offload(); self.target.write_bytes(b'corrupted')
        backup = self.source.with_name(self.source.name + '.offload-local-backup'); backup.unlink()
        self.assertFalse(harbor.audit_one(str(self.source), self.home)['verified'])
        with self.assertRaises(harbor.HarborError): harbor.restore_one(str(self.source), self.home)

    def test_arbitrary_unrecorded_link_is_not_verified(self):
        self.target.parent.mkdir(parents=True); self.source.rename(self.target); self.source.symlink_to(self.target)
        self.assertFalse(harbor.audit_one(str(self.source), self.home)['verified'])

    def test_broken_protection_config_is_fail_closed(self):
        config = self.root / 'config.json'; config.write_text('{broken')
        with mock.patch.object(harbor, 'config_path', return_value=config):
            with self.assertRaises(harbor.HarborError): harbor.load_config()

    def test_session_path_traversal_and_archive_traversal_are_rejected(self):
        with self.assertRaises(harbor.HarborError): harbor.lexical_session(str(self.source.parent / '../outside.jsonl'), self.home)
        with self.assertRaises(harbor.HarborError): harbor.validate_archive_name('../outside')


if __name__ == '__main__':
    unittest.main()
