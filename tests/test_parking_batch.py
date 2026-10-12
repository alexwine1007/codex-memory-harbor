"""Shared engine regression tests use synthetic files only."""
import json
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest import mock
from test_project_storage import module, archive

probe = module('volume_probe')


class BatchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.originals = {}; self.items = []
        for i in range(6):
            source = self.root / ('input-%s.bin' % i); content = os.urandom(128*1024)
            source.write_bytes(content); self.originals[source] = content
            self.items.append(dict(source=str(source), target=str(self.root/'external'/source.name),
                                   receipt=str(self.root/'receipt.jsonl')))
        patcher = mock.patch.dict(os.environ, {'CODEX_HARBOR_FILE_LOCK_DIR': str(self.root/'locks')})
        patcher.start(); self.addCleanup(patcher.stop)
        self.identity = lambda: {'volume_uuid': 'TEST-VOL'}

    def run_batch(self, **kwargs):
        return archive.archive_batch(self.items, self.identity, check_handles=lambda path: None, **kwargs)

    def assert_local(self, items=None):
        for item in items or self.items:
            source = Path(item['source'])
            self.assertFalse(source.is_symlink())
            self.assertEqual(source.read_bytes(), self.originals[source])

    def test_every_path_uses_three_fresh_batched_handle_checks_and_independent_hashes(self):
        with mock.patch.object(archive.subprocess, 'run', return_value=mock.Mock(returncode=1, stdout=b'', stderr=b'')) as check, \
             mock.patch.object(archive, 'digest', wraps=archive.digest) as hashes, \
             mock.patch.object(archive.os, 'fsync', wraps=archive.os.fsync) as flush:
            result = archive.archive_batch(self.items, self.identity)
        self.assertEqual(check.call_count, 3)
        self.assertEqual(hashes.call_count, 30)
        self.assertGreaterEqual(flush.call_count, 30)
        for call in check.call_args_list[:2]:
            self.assertEqual(set(call.args[0][3:]), {item['source'] for item in self.items})
        self.assertEqual(len(check.call_args_list[2].args[0][3:]), 12)
        self.assertEqual(result['metrics']['files'], 6)
        self.assertIsNone(result['metrics']['efficiency'])
        for item in self.items:
            source = Path(item['source']); self.assertTrue(source.is_symlink())
            self.assertEqual(source.read_bytes(), self.originals[source])
            archive.restore_file(source, item['target'], item['receipt'], self.identity, lambda path: None)
        self.assert_local()

    def test_open_handle_before_release_rolls_back_all_and_preserves_originals(self):
        response = mock.Mock(returncode=1, stdout=b'', stderr=b'')
        opened = mock.Mock(returncode=0, stdout=b'p123\n', stderr=b'')
        with mock.patch.object(archive.subprocess, 'run', side_effect=[response, response, opened]):
            with self.assertRaises(RuntimeError): archive.archive_batch(self.items, self.identity)
        self.assert_local()

    def test_source_changed_before_link_does_not_release_any_file(self):
        def progress(state):
            if state['phase'] == 'link_verify_receipt':
                source = Path(self.items[-1]['source'])
                source.write_bytes(b'concurrent edit'); self.originals[source] = b'concurrent edit'
        with self.assertRaises(RuntimeError): self.run_batch(progress=progress)
        self.assert_local()

    def test_corrupt_target_stops_batch_and_preserves_committed_or_local_bytes(self):
        def progress(state):
            if state['phase'] == 'release_verify':
                Path(self.items[-1]['target']).write_bytes(b'corrupted')
        with self.assertRaises(RuntimeError): self.run_batch(progress=progress)
        # Earlier files may already be independently committed; each still has exact bytes.
        for item in self.items:
            source = Path(item['source'])
            self.assertEqual(source.read_bytes(), self.originals[source])
        self.assertFalse(Path(self.items[-1]['source']).is_symlink())

    def test_second_receipt_failure_rolls_back_uncommitted_group(self):
        calls = 0
        def write(path, row):
            nonlocal calls; calls += 1
            if calls == 2: raise OSError('disk full')
            archive.append_receipt(path, row)
        for item in self.items: item['write_record'] = write
        with self.assertRaises(OSError): self.run_batch()
        self.assert_local()

    def test_failed_post_release_receipt_reports_committed_count_and_stops(self):
        states = []
        def write(path, row):
            if row['status'] == 'local_entity_released': raise OSError('receipt full')
            archive.append_receipt(path, row)
        for item in self.items: item['write_record'] = write
        with self.assertRaises(OSError): self.run_batch(progress=states.append)
        self.assertEqual(states[-1]['completed'], 1)
        self.assertTrue(Path(self.items[0]['source']).is_symlink())
        self.assert_local(self.items[1:])
        # The persisted pre-release record remains sufficient for byte-verified recovery.
        first = self.items[0]
        archive.restore_file(first['source'], first['target'], first['receipt'], self.identity, lambda path: None)
        self.assert_local()

    def test_volume_lost_after_link_rolls_back(self):
        calls = 0
        def volume():
            nonlocal calls; calls += 1
            if calls == 4: raise RuntimeError('volume offline')
            return {'volume_uuid': 'TEST-VOL'}
        with self.assertRaises(RuntimeError):
            archive.archive_batch(self.items, volume, check_handles=lambda path: None)
        self.assert_local()

    def test_first_failed_group_never_starts_next_large_file(self):
        source = Path(self.items[-1]['source']); source.write_bytes(os.urandom(5*1024*1024))
        def validate(): raise RuntimeError('protected')
        self.items[0]['validate'] = validate
        with self.assertRaises(RuntimeError): self.run_batch()
        self.assertFalse(Path(self.items[-1]['target']).exists())

    def test_duplicate_target_rejected_before_copy(self):
        self.items[-1]['target'] = self.items[0]['target']
        with self.assertRaises(ValueError): self.run_batch()
        self.assert_local()

    def test_large_files_have_individual_handle_checkpoint_groups(self):
        for item in self.items[:2]:
            Path(item['source']).write_bytes(os.urandom(5*1024*1024))
        with mock.patch.object(archive.subprocess, 'run', return_value=mock.Mock(returncode=1, stdout=b'', stderr=b'')) as check:
            archive.archive_batch(self.items, self.identity, keep_local=True)
        self.assertEqual(check.call_count, 9)  # Two large files, then one small group.


class VolumeProbeTests(unittest.TestCase):
    def test_native_check_is_fresh_not_cached(self):
        with mock.patch.object(probe.os.path, 'ismount', return_value=True), \
             mock.patch.object(probe, 'native_uuid', side_effect=['FIRST', 'SECOND']) as query:
            self.assertEqual(probe.fresh_uuid('/Volumes/Fixture'), 'FIRST')
            self.assertEqual(probe.fresh_uuid('/Volumes/Fixture'), 'SECOND')
            self.assertEqual(query.call_count, 2)

    def test_fallback_is_bounded_and_verifies_exact_mountpoint(self):
        with mock.patch.object(probe.os.path, 'ismount', return_value=True), \
             mock.patch.object(probe, 'native_uuid', side_effect=OSError('unsupported')), \
             mock.patch.object(probe.subprocess, 'run', return_value=mock.Mock(stdout=plistlib.dumps(
                 {'MountPoint': '/Volumes/Fixture', 'VolumeUUID': 'abcd'}))) as command:
            self.assertEqual(probe.fresh_uuid('/Volumes/Fixture'), 'ABCD')
            self.assertEqual(command.call_args.kwargs['timeout'], 3)
            command.return_value.stdout = plistlib.dumps({'MountPoint': '/', 'VolumeUUID': 'abcd'})
            with self.assertRaises(RuntimeError): probe.fresh_uuid('/Volumes/Fixture')

    def test_unmounted_and_broad_paths_never_query_uuid(self):
        with mock.patch.object(probe.os.path, 'ismount', return_value=False), \
             mock.patch.object(probe, 'native_uuid') as query:
            for path in ['/Volumes/Offline', '/', '/Volumes/Offline/folder']:
                with self.assertRaises(RuntimeError): probe.fresh_uuid(path)
            query.assert_not_called()
