"""Manual browser regression fixture. All storage is disposable, never user files."""
import json
from pathlib import Path
import threading
import os
import sqlite3
import time
from unittest import mock
from test_project_storage import ProjectStorageTests, harbor, archive


def main():
    fixture = ProjectStorageTests(); fixture.setUp()
    # setUp's mocked reader is useful for unit cases but not a settings round trip.
    # Replace it with a real reader/writer bound strictly to disposable preferences.
    fixture.config.stop()
    try:
        # Blank index titles reproduce the user's case without publishing private history.
        with sqlite3.connect(fixture.home/'state_5.sqlite') as connection:
            connection.execute('CREATE TABLE threads (id TEXT, rollout_path TEXT, title TEXT, preview TEXT, cwd TEXT, created_at INTEGER, updated_at INTEGER, created_at_ms INTEGER, updated_at_ms INTEGER, agent_nickname TEXT)')
            for index,(name,description) in enumerate((
                ('video_continuity_check','检查短片角色与镜头的连续性。保留验收记录。'),
                ('avatar_art_direction','检查头像构图与圆形裁切后的辨识度。给出配色建议。'),
                ('storage_research','比较外盘读写策略并记录测试结果。没有修改任何真实文件。'))):
                thread_id=f'demo-task-{index}';agent=f'/root/{name}'
                path=fixture.home/'sessions'/f'rollout-{thread_id}.jsonl'
                path.parent.mkdir(exist_ok=True)
                path.write_text('\n'.join(json.dumps(row,ensure_ascii=False) for row in (
                    {'type':'session_meta','payload':{'id':thread_id,'parent_thread_id':'demo-parent','source':{'subagent':{'thread_spawn':{}}},'agent_path':agent,'cwd':str(fixture.project)}},
                    {'type':'response_item','payload':{'type':'agent_message','recipient':agent,'content':[{'type':'input_text','text':f'Message Type: NEW_TASK\nTask name: {agent}\nPayload:\n<input>{description}</input>'}]}},
                    {'type':'response_item','payload':{'type':'message','role':'assistant','channel':'final','content':[{'type':'output_text','text':description}]}},
                    {'type':'event_msg','payload':{'type':'task_complete'}}))+'\n')
                os.utime(path,(time.time()-40*86400,time.time()-40*86400))
                connection.execute('INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?)',(thread_id,str(path),'','',str(fixture.project),1,2,None,None,'Demo'))
        (fixture.home/'.codex-global-state.json').write_text(json.dumps({'local-projects': {
            'fixture-project': {'name':'Demo media project', 'rootPaths':[str(fixture.project)]}}}))
        volume = {'path':str(fixture.volume), 'name':'Demo drive', 'writable':True, 'free':1024**3, 'free_h':'1 GB', 'uuid':'TEST-VOL'}
        assets = Path(__file__).resolve().parents[1]/'skills/codex-memory-harbor/assets/dashboard'
        server = harbor.ThreadingHTTPServer(('127.0.0.1',0), harbor.HarborHandler)
        server.app = {'token':'synthetic-ui-only', 'assets':assets, 'codex_home':fixture.home, 'priority':'',
                      'protected_sessions':[], 'cache':None, 'cache_lock':threading.Lock(), 'mutation_lock':threading.Lock()}
        with mock.patch.object(harbor, 'config_path', return_value=fixture.root/'preferences.json'), \
             mock.patch.object(harbor, 'mounted_volume', return_value=fixture.volume), \
             mock.patch.object(harbor, 'volume_identity', return_value={'uuid':'TEST-VOL'}), \
             mock.patch.object(harbor, 'verify_external_volume'), \
             mock.patch.object(harbor, 'available_volumes', return_value=[volume]), \
             mock.patch.object(harbor, 'project_archive_module', return_value=archive):
            print('http://127.0.0.1:%s/' % server.server_port, flush=True)
            try: server.serve_forever()
            except KeyboardInterrupt: pass
            finally: server.server_close()
    finally: fixture.doCleanups()


if __name__ == '__main__': main()
