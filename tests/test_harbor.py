import importlib.util
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import plistlib
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from unittest import mock

REPO_ROOT = Path(__file__).parents[1]
SCRIPT = REPO_ROOT / "skills/codex-memory-harbor/scripts/harbor.py"
spec = importlib.util.spec_from_file_location("harbor", SCRIPT)
harbor = importlib.util.module_from_spec(spec); spec.loader.exec_module(harbor)


class HarborTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        environment = mock.patch.dict(os.environ, {"CODEX_HARBOR_FILE_LOCK_DIR": temporary.name})
        environment.start(); self.addCleanup(environment.stop)
        # Ordinary regression fixtures use temporary directories rather than real mounted disks.
        patcher = mock.patch.object(harbor, "verify_external_volume", return_value=None)
        patcher.start(); self.addCleanup(patcher.stop)

    def test_repository_policy_requires_commits_and_verification(self):
        policy = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("必须创建一个对应的 Git commit", policy)
        self.assertIn("必须编写或更新相关测试", policy)
        self.assertIn("确保所有测试和验证全部通过", policy)

    def test_product_north_star_preserves_safety_and_physical_limit_speed(self):
        contract = (REPO_ROOT / "PRODUCT.md").read_text(encoding="utf-8")
        north_star = (REPO_ROOT / "PRODUCT_NORTH_STAR.zh-CN.md").read_text(encoding="utf-8")
        context = (REPO_ROOT / "CONTEXT.md").read_text(encoding="utf-8")
        runtime_adr = (REPO_ROOT / "docs/adr/0001-runtime-neutral-core.md").read_text(encoding="utf-8")
        self.assertIn("PRODUCT_NORTH_STAR.zh-CN.md", contract)
        self.assertIn("可验证的长期连续性", north_star)
        self.assertIn("能停、能找、能读、能续、不扰、可迁、够快", north_star)
        self.assertIn("纯传输效率 η_copy", north_star)
        self.assertIn("安全流水线效率 η_verified", north_star)
        self.assertIn("持续优化目标不低于 90%", north_star)
        self.assertIn("未验证删除：0 次", north_star)
        self.assertIn("不以关闭 fsync、跳过回读", north_star)
        self.assertIn("当前实现边界", north_star)
        self.assertIn("Codex、Claude Code 和 OpenClaw", north_star)
        self.assertIn("DeepSeek 通常是模型或模型服务提供方", north_star)
        self.assertIn("第二个真实 Runtime Adapter", north_star)
        self.assertIn("runtime-neutral continuity product", contract)
        self.assertIn("**History Object（历史对象）**", context)
        self.assertIn("**Native Continuity（原生连续性）**", context)
        self.assertIn("一个适配器只能提出假设，两个适配器才能验证边界", runtime_adr)

    def test_frontend_foundation_and_handbook_keep_design_and_delivery_separate(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        foundation = (REPO_ROOT / "docs/design/FRONTEND_FOUNDATION.md").read_text(encoding="utf-8")
        handbook = (REPO_ROOT / "docs/handbook/README.md").read_text(encoding="utf-8")
        desktop = (REPO_ROOT / "docs/handbook/desktop-and-dashboard.md").read_text(encoding="utf-8")
        self.assertIn("technical handbook", readme)
        self.assertIn("状态：草案 0.4", foundation)
        self.assertIn("单一工作台", foundation)
        self.assertIn("不再作为当前布局要求", foundation)
        self.assertIn("未来记忆港", foundation)
        for page in ("港湾", "找回记忆", "安全停泊"):
            self.assertIn(page, foundation)
        self.assertIn("设备与连接", foundation)
        self.assertIn("没有候选历史时，界面应该安静地说“今天不用整理”", foundation)
        self.assertIn("Runtime Adapter 开发 | 规划中", handbook)
        self.assertIn("唯一已交付的 Runtime Adapter 是 macOS 上的 Codex", handbook)
        self.assertIn("127.0.0.1，随机可用端口", desktop)
        self.assertIn("当前设计债务", desktop)

    def test_dashboard_separates_history_capacity_from_project_media(self):
        dashboard = REPO_ROOT / "skills/codex-memory-harbor/assets/dashboard"
        html = (dashboard / "index.html").read_text(encoding="utf-8")
        javascript = (dashboard / "app.js").read_text(encoding="utf-8")
        self.assertIn('class="workbench"', html)
        self.assertNotIn('class="hero"', html)
        self.assertIn("mediaView(group)", javascript)
        self.assertIn("mediaSummary", javascript)
        self.assertNotIn("projectFileDialog", javascript)
        self.assertIn("/api/parking-start", javascript)
        self.assertIn("/api/parking-job?", javascript)
        self.assertIn("fmt(plan.history.docked_bytes)", javascript)
        self.assertIn("fmt(plan.files.total_bytes)", javascript)

    def test_chinese_scifi_prototype_is_fixture_only_and_interactive(self):
        prototype = REPO_ROOT / "docs/design/prototype"
        html = (prototype / "index.html").read_text(encoding="utf-8")
        css = (prototype / "prototype.css").read_text(encoding="utf-8")
        javascript = (prototype / "prototype.js").read_text(encoding="utf-8")
        self.assertIn('lang="zh-CN"', html)
        self.assertIn("交互原型 · 全中文 · 使用样例数据 · 不会操作真实历史", html)
        self.assertIn("你走过的路", html)
        for page in ("港湾", "找回记忆", "安全停泊"):
            self.assertIn(page, html)
        for secondary in ("设备与连接", "验证记录", "偏好设置"):
            self.assertIn(secondary, html)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("event.metaKey || event.ctrlKey", javascript)
        self.assertIn("memorySheet", html)
        self.assertIn("runRecall", javascript)
        self.assertNotIn("fetch(", html + javascript)

    def test_skill_and_user_visible_errors_default_to_chinese(self):
        skill = (REPO_ROOT / "skills/codex-memory-harbor/SKILL.md").read_text(encoding="utf-8")
        agent = (REPO_ROOT / "skills/codex-memory-harbor/agents/openai.yaml").read_text(encoding="utf-8")
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("## 中文交付合同", skill)
        self.assertIn("## 体验与表达", skill)
        self.assertIn("想找回哪段经历？", skill)
        self.assertIn("查看停泊方案", skill)
        self.assertIn("打开中文仪表盘", agent)
        self.assertIn('print(f"错误 [{code}]：{message}"', source)
        self.assertNotIn('HarborError("External volume is not mounted', source)
        self.assertEqual(harbor.user_error(PermissionError("raw english")), ("permission_denied", "没有权限访问所需文件或存储设备"))
        self.assertEqual(harbor.user_error(FileNotFoundError("raw english")), ("file_unavailable", "所需文件或存储位置当前不可用"))
        with self.assertRaisesRegex(harbor.HarborError, "必须选择 /Volumes 下的真实挂载卷"):
            harbor.mounted_volume("/tmp")

    def test_public_project_name_is_memory_harbor(self):
        metadata = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn('name = "memory-harbor"', metadata)
        self.assertIn('version = "0.4.6b2"', metadata)
        self.assertEqual(harbor.VERSION, "0.4.6-beta.2")
        self.assertEqual(readme.splitlines()[0], "# Memory Harbor")
        self.assertIn("canonical checkout directory is `memory-harbor`", readme)
        self.assertIn("`codex-memory-harbor` compatibility symlink", readme)

    def test_macos_build_uses_stable_identity_and_privacy_description(self):
        build = (REPO_ROOT / "scripts/build_macos_app.sh").read_text(encoding="utf-8")
        signer = (REPO_ROOT / "scripts/ensure_codesign_identity.sh").read_text(encoding="utf-8")
        self.assertIn("ensure_codesign_identity.sh", build)
        self.assertNotIn("--sign -", build)
        self.assertIn("refuses ad-hoc signing", signer)
        self.assertIn("Memory Harbor/Signing", signer)
        self.assertIn("keychain-password", signer)
        self.assertIn("chmod 600", signer)
        self.assertEqual(build.count("NSRemovableVolumesUsageDescription"), 2)
        self.assertIn("com.alexsolar.memory-harbor", build)
        self.assertNotIn("com.alexsolar.codex-memory-harbor", build)

    def test_macos_installer_retires_legacy_identity_and_uses_absolute_login_path(self):
        install = (REPO_ROOT / "scripts/install_macos.sh").read_text(encoding="utf-8")
        self.assertIn('/Applications/Codex Memory Harbor.app', install)
        self.assertIn('com.alexsolar.codex-memory-harbor', install)
        self.assertIn('com.alexsolar.memory-harbor', install)
        self.assertIn('Add :ProgramArguments:1 string $APP_DEST', install)
        self.assertNotIn('Add :ProgramArguments:1 string -a', install)

    def test_dashboard_helper_uses_owned_dynamic_server_and_real_icon(self):
        helper = (REPO_ROOT / "macos/CodexMemoryHarborDashboard.swift").read_text(encoding="utf-8")
        owner = (REPO_ROOT / "macos/CodexMemoryHarbor.swift").read_text(encoding="utf-8")
        build = (REPO_ROOT / "scripts/build_macos_app.sh").read_text(encoding="utf-8")
        install = (REPO_ROOT / "scripts/install_macos.sh").read_text(encoding="utf-8")
        self.assertIn('"--port", "0", "--parent-pid"', helper)
        self.assertNotIn("private let port = 48765", helper)
        self.assertIn("failStartup", helper)
        self.assertIn("setActivationPolicy(.accessory)", owner)
        self.assertIn('CFBundleIconFile string MemoryHarbor', build)
        self.assertIn('MemoryHarbor.icns" "$HELPER/Contents/Resources', build)
        self.assertIn('$SKILL_DEST/scripts/harbor.py serve', install)
        self.assertIn('NSRemovableVolumesUsageDescription string Memory Harbor 需要访问你选择的存储设备', build)
        self.assertIn('CompactCardView.label(L("随时可以回来")', owner)
        self.assertIn('statusLabel.stringValue = continuityHealthy ? L("停泊历史可读")', owner)
        self.assertIn('NSButton(title: L("打开")', owner)

    def test_dashboard_server_can_bind_an_ephemeral_port(self):
        with tempfile.TemporaryDirectory() as d:
            env = os.environ.copy()
            env["CODEX_HARBOR_CONFIG"] = str(Path(d).resolve() / "config.json")
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--codex-home",
                    d,
                    "serve",
                    "--port",
                    "0",
                    "--parent-pid",
                    str(os.getpid()),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            try:
                payload = json.loads(process.stdout.readline())
                self.assertRegex(payload["url"], r"^http://127\.0\.0\.1:\d+/$")
                self.assertNotIn(":48765/", payload["url"])
                with urllib.request.urlopen(payload["url"], timeout=3) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(b"Memory Harbor", response.read())
            finally:
                process.terminate()
                process.wait(timeout=5)
                process.stdout.close()
                process.stderr.close()

    def test_dashboard_server_exits_when_its_helper_parent_exits(self):
        with tempfile.TemporaryDirectory() as d:
            env = os.environ.copy()
            env["CODEX_HARBOR_CONFIG"] = str(Path(d).resolve() / "config.json")
            parent_code = """
import json, os, subprocess, sys
child = subprocess.Popen(
    [sys.executable, sys.argv[1], '--codex-home', sys.argv[2], 'serve', '--port', '0', '--parent-pid', str(os.getpid())],
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    text=True,
)
payload = json.loads(child.stdout.readline())
print(json.dumps({'pid': child.pid, 'url': payload['url']}), flush=True)
"""
            parent = subprocess.run(
                [sys.executable, "-c", parent_code, str(SCRIPT), d],
                capture_output=True,
                text=True,
                timeout=5,
                env=env,
                check=True,
            )
            payload = json.loads(parent.stdout)
            stopped = False
            try:
                for _ in range(30):
                    try:
                        urllib.request.urlopen(payload["url"], timeout=0.2).close()
                    except Exception:
                        stopped = True
                        break
                    time.sleep(0.1)
                self.assertTrue(stopped, "server stayed reachable after its helper parent exited")
            finally:
                try:
                    os.kill(payload["pid"], 15)
                except ProcessLookupError:
                    pass

    def fixture(self, root: Path, child=True, complete=True):
        path = root / "sessions/2026/01/01/rollout-test.jsonl"; path.parent.mkdir(parents=True)
        first = {"type":"session_meta","payload":{"id":"child-1","parent_thread_id":"parent-1" if child else None,"cwd":"/tmp/example"}}
        events = [first,{"type":"event_msg","payload":{"type":"task_started"}}]
        if complete: events.append({"type":"event_msg","payload":{"type":"task_complete"}})
        path.write_text("\n".join(json.dumps(x) for x in events)+"\n")
        old = time.time()-30*86400; os.utime(path,(old,old)); return path
    def test_main_is_never_eligible(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve(); p=self.fixture(root,child=False)
            item=harbor.session_record(p,14,None)
            self.assertFalse(item["eligible"]); self.assertIn("main_task",item["reasons"])
    def test_incomplete_is_never_eligible(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve(); p=self.fixture(root,complete=False)
            item=harbor.session_record(p,14,None)
            self.assertFalse(item["eligible"]); self.assertIn("last_turn_incomplete",item["reasons"])
    def test_priority_project_is_protected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve(); p=self.fixture(root)
            item=harbor.session_record(p,14,"/tmp")
            self.assertFalse(item["eligible"]); self.assertIn("priority_project",item["reasons"])
    def test_individual_session_pin_overrides_age(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve(); p=self.fixture(root)
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
            "sessions":[
                {"private":"must not escape","linked":True,"target_exists":True},
                {"linked":True,"target_exists":False},
                {"linked":False,"target_exists":True},
            ],
        }
        with mock.patch.object(harbor,"load_config",return_value={"protected_projects":[],"protected_sessions":[]}), \
             mock.patch.object(harbor,"scan",return_value=snapshot):
            result=harbor.compact_summary(Path("/tmp/codex"))
        self.assertEqual(result["eligible_h"],"2 GB")
        self.assertEqual(result["volume_name"],"Archive")
        self.assertEqual(result["docked_files"],2)
        self.assertEqual(result["docked_available"],1)
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
            root=Path(d).resolve(); self.fixture(root)
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
            root=Path(d).resolve(); path=self.fixture(root)
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
            root=Path(d).resolve(); path=self.fixture(root)
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
            root=Path(d).resolve()
            self.assertEqual(harbor.catalog_search(root,"不存在"),[])
            self.assertEqual(harbor.recall_search(root,"不存在"),[])
            self.assertFalse(harbor.catalog_path(root).exists())

    def test_legacy_named_external_manifest_rebuilds_searchable_catalog(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as v:
            self.assertEqual(harbor.DEFAULT_ARCHIVE, "Memory Harbor")
            root=Path(d).resolve(); volume=Path(v).resolve(); manifest=volume/"Codex Memory Harbor/manifests/offload_manifest.jsonl"
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
            root=Path(d).resolve(); source=root/"sessions/2026/01/01/rollout-child.jsonl"; source.parent.mkdir(parents=True)
            source.symlink_to("/Volumes/Old Name/Codex Memory Harbor/sessions/rollout-child.jsonl")
            volume=Path(v).resolve(); target=volume/"Codex Memory Harbor/sessions/rollout-child.jsonl"; target.parent.mkdir(parents=True)
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
            root=Path(d).resolve(); source=root/"sessions/2026/01/01/rollout-child.jsonl"; source.parent.mkdir(parents=True)
            source.symlink_to("/Volumes/Old Name/Codex Memory Harbor/sessions/rollout-child.jsonl")
            volume=Path(v).resolve(); target=volume/"Codex Memory Harbor/sessions/rollout-child.jsonl"; target.parent.mkdir(parents=True)
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
            root=Path(d).resolve(); path=root/"sessions/2026/01/01/rollout-recall.jsonl"; path.parent.mkdir(parents=True)
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
            root=Path(d).resolve(); path=root/"sessions/legacy.jsonl"; path.parent.mkdir(parents=True)
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
            root=Path(d).resolve(); path=root/"sessions/2026/01/01/rollout-memory.jsonl"; path.parent.mkdir(parents=True)
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
            root=Path(d).resolve(); path=root/"sessions/2026/01/01/rollout-memory.jsonl"; path.parent.mkdir(parents=True)
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
            root=Path(d).resolve(); path=root/"sessions/2026/01/01/rollout-child-1.jsonl"; path.parent.mkdir(parents=True)
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
            root=Path(d).resolve(); p=self.fixture(root); volume=Path(v).resolve()
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

    def test_migrate_reaudits_then_removes_local_backup(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as v:
            root=Path(d).resolve(); p=self.fixture(root); volume=Path(v).resolve(); original=p.read_bytes()
            plan={"source":str(p),"destination":str(volume/"Archive/sessions/rollout-test.jsonl"),"backup":str(p)+".offload-local-backup","bytes":p.stat().st_size,"bytes_h":harbor.human_bytes(p.stat().st_size),"sha256":harbor.sha256(p),"id":"child-1","cwd":"/tmp/example","open_handles":0}
            result=harbor.migrate_one(plan,volume,"Archive",root)
            self.assertEqual(result["event"],"migrated_external_primary")
            self.assertEqual(result["bytes_released"],len(original))
            self.assertTrue(p.is_symlink())
            self.assertEqual(p.read_bytes(),original)
            self.assertFalse(Path(plan["backup"]).exists())
            audit=harbor.audit_one(str(p),root)
            self.assertTrue(audit["verified"])
            self.assertFalse(audit["backup_exists"])

    def test_migrate_keeps_local_backup_when_reaudit_fails(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as v:
            root=Path(d).resolve(); p=self.fixture(root); volume=Path(v).resolve()
            plan={"source":str(p),"destination":str(volume/"Archive/sessions/rollout-test.jsonl"),"backup":str(p)+".offload-local-backup","bytes":p.stat().st_size,"bytes_h":harbor.human_bytes(p.stat().st_size),"sha256":harbor.sha256(p),"id":"child-1","cwd":"/tmp/example","open_handles":0}
            with mock.patch.object(harbor,"finalize_one",side_effect=harbor.HarborError("reaudit failed")):
                with self.assertRaisesRegex(harbor.HarborError,"reaudit failed"):
                    harbor.migrate_one(plan,volume,"Archive",root)
            self.assertTrue(p.is_symlink())
            self.assertTrue(Path(plan["backup"]).is_file())
            self.assertTrue(harbor.audit_one(str(p),root)["verified"])

    def test_migrate_api_completes_move_without_local_backup(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as v:
            root=Path(d).resolve(); p=self.fixture(root); volume=Path(v).resolve(); original=p.read_bytes()
            server=harbor.ThreadingHTTPServer(("127.0.0.1",0),harbor.HarborHandler)
            server.app={"assets":Path(d).resolve(),"token":"test-token","codex_home":root,"priority":"","protected_sessions":[],"cache":None,"cache_lock":threading.Lock(),"mutation_lock":threading.Lock()}
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            request=urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/migrate",
                data=json.dumps({"paths":[str(p)],"volume":str(volume),"archive_name":"Archive","min_age":14}).encode(),
                headers={"Content-Type":"application/json","X-Harbor-Token":"test-token"},
                method="POST",
            )
            try:
                with mock.patch.object(harbor,"mounted_volume",return_value=volume), mock.patch.object(harbor,"volume_identity",return_value={"uuid":"TEST-VOL"}):
                    response=json.loads(urllib.request.urlopen(request,timeout=5).read())
            finally:
                server.shutdown();server.server_close();thread.join(timeout=5)
            self.assertTrue(response["ok"])
            self.assertEqual(response["results"][0]["event"],"migrated_external_primary")
            self.assertTrue(p.is_symlink())
            self.assertEqual(p.read_bytes(),original)
            self.assertFalse(Path(str(p)+".offload-local-backup").exists())

    def test_concurrent_migrate_requests_are_serialized_and_idempotent(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as v:
            root=Path(d).resolve(); p=self.fixture(root); volume=Path(v).resolve(); original=p.read_bytes()
            server=harbor.ThreadingHTTPServer(("127.0.0.1",0),harbor.HarborHandler)
            server.app={"assets":Path(d).resolve(),"token":"test-token","codex_home":root,"priority":"","protected_sessions":[],"cache":None,"cache_lock":threading.Lock(),"mutation_lock":threading.Lock()}
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            url=f"http://127.0.0.1:{server.server_port}/api/migrate"
            payload=json.dumps({"paths":[str(p)],"volume":str(volume),"archive_name":"Archive","min_age":14}).encode()
            def send():
                request=urllib.request.Request(url,data=payload,headers={"Content-Type":"application/json","X-Harbor-Token":"test-token"},method="POST")
                return json.loads(urllib.request.urlopen(request,timeout=5).read())
            try:
                with mock.patch.object(harbor,"mounted_volume",return_value=volume), mock.patch.object(harbor,"volume_identity",return_value={"uuid":"TEST-VOL"}):
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        responses=list(executor.map(lambda _:send(),range(2)))
            finally:
                server.shutdown();server.server_close();thread.join(timeout=5)
            self.assertTrue(all(response["ok"] for response in responses))
            self.assertEqual({response["results"][0]["event"] for response in responses},{"migrated_external_primary","already_migrated"})
            self.assertTrue(p.is_symlink());self.assertEqual(p.read_bytes(),original)
            self.assertFalse(Path(str(p)+".offload-local-backup").exists())
            manifest=volume/"Archive/manifests/offload_manifest.jsonl"
            self.assertEqual(len(manifest.read_text().splitlines()),1)


if __name__ == "__main__": unittest.main(verbosity=2)
