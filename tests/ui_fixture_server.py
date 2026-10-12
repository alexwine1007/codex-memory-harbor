"""Manual browser regression fixture. All storage is disposable, never user files."""
import json
from pathlib import Path
import threading
from unittest import mock
from test_project_storage import ProjectStorageTests, harbor, archive


def main():
    fixture = ProjectStorageTests(); fixture.setUp()
    try:
        (fixture.home/'.codex-global-state.json').write_text(json.dumps({'local-projects': {
            'fixture-project': {'name':'停泊交互测试（临时文件）', 'rootPaths':[str(fixture.project)]}}}))
        volume = {'path':str(fixture.volume), 'name':'临时测试盘', 'writable':True, 'free':1024**3, 'free_h':'1 GB', 'uuid':'TEST-VOL'}
        assets = Path(__file__).resolve().parents[1]/'skills/codex-memory-harbor/assets/dashboard'
        server = harbor.ThreadingHTTPServer(('127.0.0.1',0), harbor.HarborHandler)
        server.app = {'token':'synthetic-ui-only', 'assets':assets, 'codex_home':fixture.home, 'priority':'',
                      'protected_sessions':[], 'cache':None, 'cache_lock':threading.Lock(), 'mutation_lock':threading.Lock()}
        with mock.patch.object(harbor, 'mounted_volume', return_value=fixture.volume), \
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
