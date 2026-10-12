"""Small, traceable display labels. All task content here is synthetic."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import threading
import urllib.request
import urllib.error
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('label_harbor', ROOT/'skills/codex-memory-harbor/scripts/harbor.py')
harbor = importlib.util.module_from_spec(spec); spec.loader.exec_module(harbor)


class TaskLabelTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.path = self.home/'sessions/rollout-child-1.jsonl'; self.path.parent.mkdir()
        self.meta = {'id':'child-1', 'source':{'subagent':{'thread_spawn':{'parent_thread_id':'parent-1'}}},
                     'parent_thread_id':'parent-1', 'agent_path':'/root/avatar_art_direction', 'cwd':'/tmp/example'}
        # Match the actual metadata nesting used by the current runtime.
        self.meta['source']['subagent']['thread_spawn']['agent_path'] = self.meta['agent_path']
        self.database = self.home/'state_5.sqlite'
        with sqlite3.connect(self.database) as c:
            c.execute('CREATE TABLE threads (id TEXT, rollout_path TEXT, title TEXT, preview TEXT, cwd TEXT, created_at INTEGER, updated_at INTEGER, created_at_ms INTEGER, updated_at_ms INTEGER, agent_nickname TEXT)')
            c.execute('INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?)',('child-1',str(self.path),'','','/tmp/example',1,2,None,None,'Gauss'))

    def write(self, *records):
        first = {'type':'session_meta','payload':self.meta}
        self.path.write_text('\n'.join(json.dumps(row) for row in [first,*records])+'\n')

    def marker(self, instruction='', recipient='/root/avatar_art_direction'):
        return {'type':'response_item','payload':{'type':'agent_message','recipient':recipient,
                'content':[{'type':'input_text','text':f'Message Type: NEW_TASK\nTask name: {recipient}\nPayload:\n{instruction}'},
                           {'type':'encrypted_content','encrypted_content':'opaque-do-not-decrypt'}]}}

    def report(self, text, channel='final'):
        return {'type':'response_item','payload':{'type':'message','role':'assistant','channel':channel,
                'content':[{'type':'output_text','text':text}]}}

    def label(self):
        return harbor.task_labels(self.home,['child-1'])[0]

    def test_blank_codex_title_uses_actual_assigned_task_name(self):
        self.write(self.marker('<input>检查头像构图和配色。不要修改图片。</input>'))
        label = self.label()
        self.assertEqual(label['title'],'avatar art direction')
        self.assertEqual(label['summary'],'检查头像构图和配色。')
        self.assertEqual(label['summary_source'],'instruction')
        self.assertEqual(label['source_line'],2)
        item={'id':'child-1','path':str(self.path),'agent_path':self.meta['agent_path'], 'label_signature':harbor.task_label_signature(self.path)}
        harbor.attach_thread_title(item,harbor.load_thread_catalog(self.home))
        self.assertEqual(item['summary'],label['summary'])
        self.assertTrue(item['task_label_ready'])

    def test_encrypted_instruction_uses_only_own_outward_report(self):
        self.write(self.report('Private inherited parent content.'),self.marker('',recipient='/root/other'),
                   self.report('Other agent report.'),self.marker(),
                   self.report('Private analysis.',channel='analysis'),
                   {'type':'response_item','payload':{'type':'function_call_output','output':'Private raw tool content.'}},
                   self.report('采用近景头像，保留圆形裁切余量。第二句不显示。'))
        label=self.label()
        self.assertEqual(label['summary'],'采用近景头像，保留圆形裁切余量。')
        self.assertEqual(label['summary_source'],'report')
        self.assertEqual(label['source_line'],8)
        record=harbor.task_record(self.home,'child-1')
        self.assertEqual(len(record['messages']),1)
        self.assertNotIn('Private',str(record))
        fragments=harbor.recall_fragments_from_session(self.path)
        self.assertEqual(len(fragments),1)
        self.assertNotIn('Private',str(fragments))

    def test_no_trusted_boundary_does_not_use_parent_preview_or_report(self):
        with sqlite3.connect(self.database) as c:c.execute("UPDATE threads SET preview='Parent preview.'")
        self.write(self.report('Inherited parent report.'))
        label=self.label()
        self.assertEqual(label['summary'],'')
        self.assertEqual(label['summary_source'],'bounded')

    def test_legacy_without_agent_path_stays_metadata_only(self):
        self.meta.pop('agent_path'); self.meta['source']['subagent']['thread_spawn'].pop('agent_path')
        self.write(self.marker('<input>Inherited task.</input>'),self.report('Inherited report.'))
        self.assertEqual(self.label()['summary'],'')

    def test_credentials_redacted_and_markdown_removed(self):
        self.write(self.marker(),self.report('1. **核查图像发布范围**：[官方说明](https://example.test) api_key=super-secret-value。其余内容。'))
        label=self.label()
        self.assertIn('[REDACTED]',label['summary'])
        self.assertNotIn('super-secret',str(label))
        self.assertNotIn('https://',label['summary'])
        self.assertNotIn('**',label['summary'])
        self.assertFalse(label['summary'].startswith('1.'))

    def test_cache_avoids_body_reads_invalidates_and_survives_offline(self):
        self.write(self.marker('<input>第一版任务。</input>')); first=self.label()
        with mock.patch.object(harbor,'bounded_task_summary',side_effect=AssertionError('must use cache')):
            self.assertEqual(self.label()['summary'],first['summary'])
        self.write(self.marker('<input>更新后的任务描述。</input>'))
        self.assertEqual(self.label()['summary'],'更新后的任务描述。')
        self.path.unlink()
        with mock.patch.object(harbor,'bounded_task_summary',side_effect=AssertionError('offline')):
            self.assertEqual(self.label()['summary'],'更新后的任务描述。')

    def test_broken_link_still_displays_cached_identity_without_becoming_eligible(self):
        self.write(self.marker('<input>检查头像设计。</input>'));self.label()
        self.path.unlink();self.path.symlink_to(self.home/'missing-external-file.jsonl')
        item=harbor.session_record(self.path,30,priority='',protected_sessions=[])
        harbor.attach_thread_title(item,harbor.load_thread_catalog(self.home))
        self.assertEqual(item['id'],'child-1')
        self.assertEqual(item['title'],'avatar art direction')
        self.assertEqual(item['summary'],'检查头像设计。')
        self.assertFalse(item['eligible'])

    def test_large_lines_and_total_read_budget_are_bounded(self):
        self.write({'type':'response_item','payload':{'type':'function_call_output','output':'x'*300_000}},
                   self.marker('<input>越过大型工具输出后的自己的指令。</input>'))
        self.assertEqual(self.label()['summary'],'越过大型工具输出后的自己的指令。')
        with mock.patch.object(harbor,'TASK_LABEL_READ_BYTES',100):
            summary=harbor.bounded_task_summary(self.path,harbor.first_metadata(self.path))
            self.assertEqual(summary['summary'],'')

    def test_main_preview_and_original_codex_database_are_preserved(self):
        self.meta['source']='cli';self.meta.pop('parent_thread_id');self.meta.pop('agent_path')
        self.write(self.report('Do not scan this main conversation.'))
        with sqlite3.connect(self.database) as c:c.execute("UPDATE threads SET title='Readable name',preview='Review storage usage. Another sentence.'")
        before=self.database.read_bytes()
        with mock.patch.object(harbor,'bounded_task_summary',side_effect=AssertionError('main body')):
            label=self.label()
        self.assertEqual(label['title'],'Readable name')
        self.assertEqual(label['summary'],'Review storage usage.')
        self.assertEqual(self.database.read_bytes(),before)

    def test_invalid_and_unbounded_requests_rejected(self):
        for ids in (None,[],['x']*5,['../../secrets'],[1]):
            with self.assertRaises(harbor.HarborError):harbor.task_labels(self.home,ids)

    def test_http_labels_are_token_gated_and_bounded(self):
        self.write(self.marker('<input>通过本机接口读取任务简介。</input>'))
        server=harbor.ThreadingHTTPServer(('127.0.0.1',0),harbor.HarborHandler)
        server.app={'token':'synthetic-only','codex_home':self.home}
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            url=f'http://127.0.0.1:{server.server_port}/api/task-labels'
            def request(ids,token):
                return urllib.request.urlopen(urllib.request.Request(url,json.dumps({'ids':ids}).encode(),
                    {'Content-Type':'application/json','X-Harbor-Token':token}),timeout=3)
            with self.assertRaises(urllib.error.HTTPError) as error:request(['child-1'],'wrong')
            self.assertEqual(error.exception.code,403)
            with request(['child-1'],'synthetic-only') as response:
                result=json.load(response)
            self.assertEqual(result['labels'][0]['summary'],'通过本机接口读取任务简介。')
            with self.assertRaises(urllib.error.HTTPError):request(['child-1']*5,'synthetic-only')
        finally:
            server.shutdown();server.server_close();worker.join(timeout=3)


if __name__=='__main__':unittest.main()
