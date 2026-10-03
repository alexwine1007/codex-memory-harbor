import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).parents[1] / "scripts/archive_verified_files.py"
spec = importlib.util.spec_from_file_location("archive_verified_files", SCRIPT)
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)


class VerifiedArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / "local.tar.gz"
        self.target = root / "external.tar.gz"
        self.receipt = root / "receipt.jsonl"
        self.data = b"private backup fixture\0" * 512
        self.source.write_bytes(self.data)

    def run_archive(self, **kwargs):
        return archive.archive_file(self.source, self.target, self.receipt,
                                    kwargs.get("volume", lambda: None),
                                    kwargs.get("handles", lambda path: None))

    def test_verified_copy_link_release_and_idempotent_retry(self):
        result = self.run_archive()
        self.assertEqual(result["status"], "local_entity_released")
        self.assertTrue(self.source.is_symlink())
        self.assertEqual(self.source.read_bytes(), self.data)
        self.assertEqual(archive.digest(self.source), result["sha256"])
        self.assertFalse(Path(str(self.source) + ".harbor-archive-rollback").exists())
        self.assertEqual(self.run_archive()["status"], "already_verified")

    def test_open_handle_aborts_before_copy(self):
        with self.assertRaisesRegex(RuntimeError, "open"):
            self.run_archive(handles=mock.Mock(side_effect=RuntimeError("open")))
        self.assertFalse(self.source.is_symlink())
        self.assertFalse(self.target.exists())

    def test_corrupt_destination_keeps_original(self):
        with mock.patch.object(archive, "digest", return_value="bad"):
            with self.assertRaises(RuntimeError):
                self.run_archive()
        self.assertEqual(self.source.read_bytes(), self.data)
        self.assertFalse(self.source.is_symlink())

    def test_volume_failure_after_link_restores_original(self):
        checker = mock.Mock(side_effect=[None, None, RuntimeError("disconnected")])
        with self.assertRaisesRegex(RuntimeError, "disconnected"):
            self.run_archive(volume=checker)
        self.assertFalse(self.source.is_symlink())
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_link_failure_restores_original(self):
        with mock.patch.object(Path, "symlink_to", side_effect=OSError("link failed")):
            with self.assertRaises(OSError):
                self.run_archive()
        self.assertEqual(self.source.read_bytes(), self.data)
        self.assertFalse(self.source.is_symlink())

    def test_unrecorded_existing_link_is_not_accepted(self):
        self.source.rename(self.target)
        self.source.symlink_to(self.target)
        with self.assertRaisesRegex(RuntimeError, "校验记录"):
            self.run_archive()

    def test_destination_collision_never_overwrites(self):
        self.target.write_bytes(b"other data")
        with self.assertRaises(RuntimeError):
            self.run_archive()
        self.assertEqual(self.target.read_bytes(), b"other data")
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_changed_source_aborts_before_replacement(self):
        original_digest = archive.digest

        def change_during_verification(path):
            result = original_digest(path)
            self.source.write_bytes(self.data + b"changed")
            return result

        with mock.patch.object(archive, "digest", side_effect=change_during_verification):
            with self.assertRaisesRegex(RuntimeError, "来源发生变化"):
                self.run_archive()
        self.assertFalse(self.source.is_symlink())
        self.assertTrue(self.source.read_bytes().endswith(b"changed"))

    def test_handle_opened_before_release_restores_original(self):
        checker = mock.Mock(side_effect=[None, None, RuntimeError("open rollback")])
        with self.assertRaisesRegex(RuntimeError, "open rollback"):
            self.run_archive(handles=checker)
        self.assertFalse(self.source.is_symlink())
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_existing_link_with_changed_target_is_rejected(self):
        self.run_archive()
        self.target.write_bytes(b"damaged")
        with self.assertRaisesRegex(RuntimeError, "校验记录"):
            self.run_archive()
        self.assertTrue(self.source.is_symlink())

    def test_handbook_keeps_runtime_claims_and_git_deletion_out_of_scope(self):
        handbook = (SCRIPT.parents[1] / "docs/handbook/file-archives.md").read_text()
        self.assertIn("不是 OpenClaw Runtime Adapter", handbook)
        self.assertIn("不进行 Git 临时文件清理", handbook)
        self.assertIn("默认只展示方案", handbook)


if __name__ == "__main__":
    unittest.main()
