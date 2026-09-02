import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import plistlib
import tempfile
import time
import unittest
from unittest import mock

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

    def test_compact_summary_returns_no_session_inventory(self):
        snapshot={
            "totals":{"eligible_h":"2 GB","eligible_files":3},
            "disk":{"free_h":"9 GB"},
            "volumes":[{"writable":True,"name":"Archive","free_h":"80 GB"}],
            "sessions":[{"private":"must not escape"}],
        }
        with mock.patch.object(harbor,"load_config",return_value={"protected_projects":[],"protected_sessions":[]}), \
             mock.patch.object(harbor,"scan",return_value=snapshot):
            result=harbor.compact_summary(Path("/tmp/codex"))
        self.assertEqual(result["eligible_h"],"2 GB")
        self.assertEqual(result["volume_name"],"Archive")
        self.assertNotIn("sessions",result)
    def test_volume_identity_reads_persistent_diskutil_uuid(self):
        payload=plistlib.dumps({"VolumeUUID":"ABC-123","DeviceIdentifier":"disk9s1","FilesystemType":"exfat"})
        result=mock.Mock(returncode=0,stdout=payload)
        with mock.patch.object(harbor.subprocess,"run",return_value=result):
            identity=harbor.volume_identity(Path("/Volumes/Test"))
        self.assertEqual(identity["uuid"],"ABC-123")
        self.assertEqual(identity["device_identifier"],"disk9s1")
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
    def test_scan_uses_codex_title_index_and_loads_preview_on_demand(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); path=self.fixture(root)
            database=root/"state_5.sqlite"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE threads (id TEXT, rollout_path TEXT, title TEXT, preview TEXT, cwd TEXT, created_at INTEGER, updated_at INTEGER, created_at_ms INTEGER, updated_at_ms INTEGER, agent_nickname TEXT)")
                connection.execute("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?)",("child-1",str(path),"Readable task title","Private preview","/tmp/example",1,2,None,None,"Gauss"))
            item=harbor.scan(root,14)["sessions"][0]
            self.assertEqual(item["title"],"Readable task title")
            self.assertNotIn("preview",item)
            detail=harbor.thread_detail(root,"child-1")
            self.assertEqual(detail["preview"],"Private preview")
            self.assertEqual(detail["agent_nickname"],"Gauss")

    def test_local_catalog_remains_searchable_after_source_disappears(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); path=self.fixture(root)
            database=root/"state_5.sqlite"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE threads (id TEXT, rollout_path TEXT, title TEXT, preview TEXT, cwd TEXT, created_at INTEGER, updated_at INTEGER, created_at_ms INTEGER, updated_at_ms INTEGER, agent_nickname TEXT)")
                connection.execute("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?)",("child-1",str(path),"阿狸牙刷杯鉴定","Private preview","/tmp/example",1,2,None,None,"Gauss"))
            harbor.scan(root,14)
            self.assertEqual(harbor.catalog_search(root,"牙刷杯")[0]["thread_id"],"child-1")
            path.unlink()
            harbor.scan(root,14)
            result=harbor.catalog_search(root,"牙刷杯")[0]
            self.assertEqual(result["source_present"],0)
            self.assertEqual(harbor.catalog_status(root)["items"],1)

    def test_search_does_not_create_a_catalog_when_none_exists(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            self.assertEqual(harbor.catalog_search(root,"不存在"),[])
            self.assertEqual(harbor.recall_search(root,"不存在"),[])
            self.assertFalse(harbor.catalog_path(root).exists())

    def test_external_manifest_rebuilds_searchable_catalog(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as v:
            root=Path(d); volume=Path(v); manifest=volume/"Codex Memory Harbor/manifests/offload_manifest.jsonl"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({
                "manifest_version":2,"source":str(root/"sessions/missing.jsonl"),"id":"archived-1",
                "title":"关键历史数据","cwd":"/tmp/archive","bytes":42,"sha256":"abc",
                "archive_relative":"Codex Memory Harbor/sessions/missing.jsonl","recorded_at":123,
            })+"\n")
            count=harbor.import_mounted_manifests(root,[{"path":str(volume),"name":"Archive","uuid":"VOL-1"}])
            self.assertEqual(count,1)
            result=harbor.catalog_search(root,"关键历史")[0]
            self.assertEqual(result["volume_uuid"],"VOL-1")
            self.assertEqual(result["archive_relative"],"Codex Memory Harbor/sessions/missing.jsonl")

    def test_broken_link_repairs_only_with_uuid_and_hash_match(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as v:
            root=Path(d); source=root/"sessions/2026/01/01/rollout-child.jsonl"; source.parent.mkdir(parents=True)
            source.symlink_to("/Volumes/Old Name/Codex Memory Harbor/sessions/rollout-child.jsonl")
            volume=Path(v); target=volume/"Codex Memory Harbor/sessions/rollout-child.jsonl"; target.parent.mkdir(parents=True)
            target.write_text("verified payload")
            with harbor.open_catalog(root) as connection:
                harbor.catalog_upsert(connection,{
                    "source_path":str(source),"thread_id":"child-1","title":"Repair me","linked":True,
                    "source_present":True,"logical":target.stat().st_size,"source_sha256":harbor.sha256(target),
                    "volume_uuid":"VOL-1","archive_relative":"Codex Memory Harbor/sessions/rollout-child.jsonl",
                })
            repaired=harbor.repair_links_by_volume_identity(root,[{"path":str(volume),"name":"New Name","uuid":"VOL-1"}])
            self.assertEqual(len(repaired),1)
            self.assertEqual(source.resolve(),target.resolve())
            self.assertEqual(source.read_text(),"verified payload")

    def test_scan_does_not_repair_links_as_a_side_effect(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as v:
            root=Path(d); source=root/"sessions/2026/01/01/rollout-child.jsonl"; source.parent.mkdir(parents=True)
            source.symlink_to("/Volumes/Old Name/Codex Memory Harbor/sessions/rollout-child.jsonl")
            volume=Path(v); target=volume/"Codex Memory Harbor/sessions/rollout-child.jsonl"; target.parent.mkdir(parents=True)
            target.write_text("verified payload")
            with harbor.open_catalog(root) as connection:
                harbor.catalog_upsert(connection,{
                    "source_path":str(source),"thread_id":"child-1","title":"Do not auto repair","linked":True,
                    "source_present":True,"logical":target.stat().st_size,"source_sha256":harbor.sha256(target),
                    "volume_uuid":"VOL-1","archive_relative":"Codex Memory Harbor/sessions/rollout-child.jsonl",
                })
            volumes=[{"path":str(volume),"name":"New Name","uuid":"VOL-1","writable":True,"free":1,"free_h":"1 B"}]
            with mock.patch.object(harbor,"available_volumes",return_value=volumes):
                harbor.scan(root,14)
            self.assertTrue(source.is_symlink())
            self.assertFalse(source.exists())
            self.assertEqual(os.readlink(source),"/Volumes/Old Name/Codex Memory Harbor/sessions/rollout-child.jsonl")

    def test_recall_index_keeps_task_evidence_not_inherited_history_or_tools(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); path=root/"sessions/2026/01/01/rollout-recall.jsonl"; path.parent.mkdir(parents=True)
            rows=[
                {"type":"session_meta","payload":{"id":"recall-1","parent_thread_id":"parent-1","cwd":"/tmp/example","agent_path":"/root/research"}},
                {"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"继承噪声：喜欢红色。"}]}},
                {"type":"response_item","payload":{"type":"agent_message","recipient":"/root/research","content":[{"type":"input_text","text":"Message Type: NEW_TASK\n<codex_delegation><input>核查海蓝色方案，api_key=supersecretvalue</input></codex_delegation>"}]}},
                {"type":"response_item","payload":{"type":"function_call_output","output":"工具秘密 should-not-index"}},
                {"timestamp":"2026-01-01T00:01:00Z","type":"event_msg","payload":{"type":"agent_message","message":"结论：海蓝色方案已经验证，保留来源证据。"}},
                {"type":"event_msg","payload":{"type":"task_complete"}},
            ]
            path.write_text("\n".join(json.dumps(row,ensure_ascii=False) for row in rows)+"\n")
            old=time.time()-40*86400; os.utime(path,(old,old))
            harbor.scan(root,14)
            first=harbor.index_session_memory(str(path),root)
            second=harbor.index_session_memory(str(path),root)
            self.assertEqual(first["fragments"],2)
            self.assertEqual(second["fragments"],2)
            self.assertFalse(first["unchanged"])
            self.assertTrue(second["unchanged"])
            result=harbor.recall_search(root,"海蓝色")[0]
            self.assertEqual(result["thread_id"],"recall-1")
            self.assertGreater(result["match_source_line"],0)
            self.assertIn("海蓝色",result["match_excerpt"])
            self.assertEqual(harbor.recall_search(root,"继承噪声"),[])
            self.assertEqual(harbor.recall_search(root,"should-not-index"),[])
            self.assertEqual(harbor.recall_search(root,"supersecretvalue"),[])
            with harbor.managed_catalog(root) as connection:
                content="\n".join(row[0] for row in connection.execute("SELECT content FROM harbor_fragments"))
            self.assertIn("[REDACTED]",content)
            self.assertEqual(harbor.catalog_status(root)["recall_sessions"],1)
            cleared=harbor.clear_recall_index(root,[str(path)])
            self.assertEqual(cleared["cleared_fragments"],2)
            self.assertEqual(harbor.recall_search(root,"海蓝色"),[])

    def test_recall_prefilter_rejects_large_tool_output_before_json_decode(self):
        tool_line=json.dumps({"type":"response_item","payload":{"type":"function_call_output","output":"x"*20000}})
        message_line=json.dumps({"type":"event_msg","payload":{"type":"agent_message","message":"useful"}})
        self.assertFalse(harbor.recall_candidate_line(tool_line))
        self.assertTrue(harbor.recall_candidate_line(message_line))

    def test_legacy_child_without_task_boundary_stays_metadata_only(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); path=root/"sessions/legacy.jsonl"; path.parent.mkdir(parents=True)
            rows=[
                {"type":"session_meta","payload":{"id":"legacy-1","parent_thread_id":"parent-1","cwd":"/tmp/example"}},
                {"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"这是继承的父任务隐私"}]}},
                {"type":"event_msg","payload":{"type":"task_complete"}},
            ]
            path.write_text("\n".join(json.dumps(row,ensure_ascii=False) for row in rows)+"\n")
            self.assertEqual(harbor.recall_fragments_from_session(path),[])
            harbor.scan(root,14)
            result=harbor.index_session_memory(str(path),root)
            self.assertEqual(result["thread_id"],"legacy-1")
            self.assertTrue(result["metadata_only"])

    def test_recall_survives_missing_source_with_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); path=root/"sessions/2026/01/01/rollout-memory.jsonl"; path.parent.mkdir(parents=True)
            rows=[
                {"type":"session_meta","payload":{"id":"memory-1","parent_thread_id":"parent-1","cwd":"/tmp/example","agent_path":"/root/audit"}},
                {"type":"response_item","payload":{"type":"agent_message","recipient":"/root/audit","content":[{"type":"input_text","text":"Message Type: NEW_TASK\n<input>记录关键研发代号青鸟七号</input>"}]}},
                {"type":"event_msg","payload":{"type":"task_complete"}},
            ]
            path.write_text("\n".join(json.dumps(row,ensure_ascii=False) for row in rows)+"\n")
            old=time.time()-40*86400; os.utime(path,(old,old))
            harbor.scan(root,14); harbor.index_session_memory(str(path),root)
            path.unlink(); harbor.scan(root,14)
            result=harbor.recall_search(root,"青鸟七号")[0]
            self.assertEqual(result["source_present"],0)
            self.assertEqual(result["match_role"],"instruction")
            self.assertEqual(result["match_source_line"],2)

    def test_recall_critical_path_does_not_probe_external_storage(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); path=root/"sessions/2026/01/01/rollout-memory.jsonl"; path.parent.mkdir(parents=True)
            rows=[
                {"type":"session_meta","payload":{"id":"memory-1","parent_thread_id":"parent-1","cwd":"/tmp/example","agent_path":"/root/audit"}},
                {"type":"response_item","payload":{"type":"agent_message","recipient":"/root/audit","content":[{"type":"input_text","text":"Message Type: NEW_TASK\n<input>保留低延迟关键结论</input>"}]}},
                {"type":"event_msg","payload":{"type":"task_complete"}},
            ]
            path.write_text("\n".join(json.dumps(row,ensure_ascii=False) for row in rows)+"\n")
            harbor.scan(root,14); harbor.index_session_memory(str(path),root)
            path.unlink(); harbor.scan(root,14)
            with mock.patch.object(harbor,"available_volumes",side_effect=AssertionError("external probe on recall path")), \
                 mock.patch.object(harbor,"sha256",side_effect=AssertionError("content hash on recall path")):
                result=harbor.recall_search(root,"低延迟")[0]
            self.assertEqual(result["thread_id"],"memory-1")
            self.assertEqual(result["source_present"],0)

    def test_subagent_record_excludes_inherited_parent_history(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); path=root/"sessions/2026/01/01/rollout-child-1.jsonl"; path.parent.mkdir(parents=True)
            rows=[
                {"type":"session_meta","payload":{"id":"child-1","parent_thread_id":"parent-1","cwd":"/tmp/example","agent_path":"/root/audit","agent_nickname":"Gauss"}},
                {"type":"event_msg","payload":{"type":"agent_message","message":"inherited parent text"}},
                {"type":"response_item","payload":{"type":"agent_message","recipient":"/root/audit","content":[{"type":"input_text","text":"Message Type: NEW_TASK"}]}},
                {"timestamp":"2026-01-01T00:01:00Z","type":"event_msg","payload":{"type":"agent_message","message":"child progress"}},
                {"timestamp":"2026-01-01T00:02:00Z","type":"event_msg","payload":{"type":"agent_message","message":"child final"}},
                {"type":"event_msg","payload":{"type":"task_complete"}},
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows)+"\n")
            database=root/"state_5.sqlite"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE threads (id TEXT, rollout_path TEXT, title TEXT, preview TEXT, cwd TEXT, created_at INTEGER, updated_at INTEGER, created_at_ms INTEGER, updated_at_ms INTEGER, agent_nickname TEXT)")
                connection.execute("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?)",("child-1",str(path),"hello","Preview","/tmp/example",1,2,None,None,"Gauss"))
            record=harbor.task_record(root,"child-1")
            self.assertEqual([item["message"] for item in record["messages"]],["child progress","child final"])
            self.assertEqual(record["title"],"audit")
            self.assertEqual(record["parent_id"],"parent-1")
    def test_delegation_title_is_compacted_to_its_first_sentence(self):
        value="<codex_delegation><source_thread_id>abc</source_thread_id><input>这是 EP04 的正式制作任务。继续读取许多内部说明。</input></codex_delegation>"
        self.assertEqual(harbor.compact_task_title(value),"EP04 的正式制作任务")
        self.assertEqual(harbor.compact_task_title("修复时间线拖拽 [89] user: 后续无关消息"),"修复时间线拖拽")
    def test_offload_audit_finalize_restore_cycle(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as v:
            root=Path(d); p=self.fixture(root); volume=Path(v)
            rows=[json.loads(line) for line in p.read_text().splitlines()]
            rows[0]["payload"]["agent_path"]="/root/test"
            rows.insert(-1,{"type":"response_item","payload":{"type":"agent_message","recipient":"/root/test","content":[{"type":"input_text","text":"Message Type: NEW_TASK"}]}})
            rows.insert(-1,{"type":"event_msg","payload":{"type":"agent_message","message":"关键迁移结论白鹭编号"}})
            p.write_text("\n".join(json.dumps(row,ensure_ascii=False) for row in rows)+"\n")
            original=p.read_bytes()
            plan={"source":str(p),"destination":str(volume/"Archive/sessions/rollout-test.jsonl"),"backup":str(p)+".offload-local-backup","bytes":p.stat().st_size,"bytes_h":harbor.human_bytes(p.stat().st_size),"sha256":harbor.sha256(p),"id":"child-1","cwd":"/tmp/example","open_handles":0}
            harbor.scan(root,14)
            moved=harbor.offload_one(plan,volume,"Archive",root)
            self.assertEqual(moved["recall_fragments"],1)
            self.assertEqual(harbor.recall_search(root,"白鹭编号")[0]["thread_id"],"child-1")
            self.assertTrue(p.is_symlink()); self.assertTrue(Path(moved["backup"]).is_file())
            self.assertTrue(harbor.audit_one(str(p),root)["verified"])
            harbor.finalize_one(str(p),root); self.assertFalse(Path(moved["backup"]).exists())
            harbor.restore_one(str(p),root); self.assertFalse(p.is_symlink()); self.assertEqual(original,p.read_bytes())


if __name__ == "__main__": unittest.main(verbosity=2)
