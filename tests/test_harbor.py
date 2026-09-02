import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

SCRIPT = Path(__file__).parents[1] / "skills/codex-memory-harbor/scripts/harbor.py"
spec = importlib.util.spec_from_file_location("harbor", SCRIPT)
harbor = importlib.util.module_from_spec(spec); spec.loader.exec_module(harbor)


class HarborTests(unittest.TestCase):
    def fixture(self, root: Path, child=True, complete=True):
        path = root / "sessions/2026/01/01/rollout-test.jsonl"; path.parent.mkdir(parents=True)
        first = {"type":"session_meta","payload":{"id":"child-1","parent_thread_id":"parent-1" if child else None,"cwd":"/tmp/example"}}
        events = [first,{"type":"event_msg","payload":{"type":"task_started"}}]
        if complete: events.append({"type":"event_msg","payload":{"type":"task_complete"}})
        path.write_text("\n".join(json.dumps(x) for x in events)+"\n")
        old = time.time()-30*86400; os.utime(path,(old,old)); return path
    def test_main_is_never_eligible(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); p=self.fixture(root,child=False)
            item=harbor.session_record(p,14,None)
            self.assertFalse(item["eligible"]); self.assertIn("main_task",item["reasons"])
    def test_incomplete_is_never_eligible(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); p=self.fixture(root,complete=False)
            item=harbor.session_record(p,14,None)
            self.assertFalse(item["eligible"]); self.assertIn("last_turn_incomplete",item["reasons"])
    def test_priority_project_is_protected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); p=self.fixture(root)
            item=harbor.session_record(p,14,"/tmp")
            self.assertFalse(item["eligible"]); self.assertIn("priority_project",item["reasons"])
    def test_individual_session_pin_overrides_age(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); p=self.fixture(root)
            item=harbor.session_record(p,14,None,["child-1"])
            self.assertFalse(item["eligible"]); self.assertIn("protected_session",item["reasons"])
    def test_cloud_provider_is_reserved_but_not_claimed_available(self):
        targets=harbor.available_storage_targets()
        cloud=next(item for item in targets if item["provider"]=="cloud")
        self.assertFalse(cloud["available"])
        with self.assertRaises(harbor.HarborError):
            harbor.resolve_storage_target({"storage_target":{"provider":"cloud","location":"memory-harbor://future"}})
    def test_scan_uses_codex_project_assignments_and_preserves_projectless(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); self.fixture(root)
            state={
                "local-projects":{"project-1":{"name":"Example Project","rootPaths":["/tmp/example"]}},
                "thread-project-assignments":{"parent-1":{"projectKind":"local","projectId":"project-1"}},
                "projectless-thread-ids":[],
            }
            (root/".codex-global-state.json").write_text(json.dumps(state))
            item=harbor.scan(root,14)["sessions"][0]
            self.assertEqual(item["project_id"],"project-1")
            self.assertEqual(item["project_name"],"Example Project")
            self.assertFalse(item["projectless"])
    def test_offload_audit_finalize_restore_cycle(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as v:
            root=Path(d); p=self.fixture(root); volume=Path(v)
            original=p.read_bytes()
            plan={"source":str(p),"destination":str(volume/"Archive/sessions/rollout-test.jsonl"),"backup":str(p)+".offload-local-backup","bytes":p.stat().st_size,"bytes_h":harbor.human_bytes(p.stat().st_size),"sha256":harbor.sha256(p),"id":"child-1","cwd":"/tmp/example","open_handles":0}
            moved=harbor.offload_one(plan,volume,"Archive")
            self.assertTrue(p.is_symlink()); self.assertTrue(Path(moved["backup"]).is_file())
            self.assertTrue(harbor.audit_one(str(p),root)["verified"])
            harbor.finalize_one(str(p),root); self.assertFalse(Path(moved["backup"]).exists())
            harbor.restore_one(str(p),root); self.assertFalse(p.is_symlink()); self.assertEqual(original,p.read_bytes())


if __name__ == "__main__": unittest.main(verbosity=2)
