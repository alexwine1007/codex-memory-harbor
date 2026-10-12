#!/usr/bin/env python3
"""Bounded old/new safety-pipeline comparison using disposable synthetic files.

No user assets, no raw-media claims, no efficiency estimate without calibration.
The reference is trusted code from this repository's specified Git commit.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import time
import types
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/codex-memory-harbor/scripts'


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS/(name+'.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def run(volume, identity, reference, count, size, keep_local):
    core, probe = load('archive_files'), load('volume_probe')
    old = types.ModuleType('reference_archive')
    source = subprocess.check_output(['git','show',reference+':skills/codex-memory-harbor/scripts/archive_files.py'], cwd=ROOT)
    exec(compile(source, '<trusted-git-reference>', 'exec'), old.__dict__)
    with tempfile.TemporaryDirectory(prefix='harbor-benchmark-local-') as local, \
         tempfile.TemporaryDirectory(prefix='.harbor-benchmark-', dir=volume) as external:
        local, external = Path(local).resolve(), Path(external).resolve()
        originals = []; expected = []
        for number in range(count):
            path = local/('fixture-%04d.bin' % number); data = os.urandom(size)
            path.write_bytes(data); originals.append(path); expected.append(hashlib.sha256(data).hexdigest())
        report = {'count':count, 'bytes':count*size, 'keep_local':keep_local, 'reference':reference, 'runs':[]}
        for label, engine in [('before', old), ('after', core)]:
            calls = {'uuid':0, 'lsof':0, 'sha256_readbacks':0, 'fsync':0}
            def check():
                calls['uuid'] += 1
                if label == 'before':
                    info = plistlib.loads(subprocess.check_output(['diskutil','info','-plist',str(volume)]))
                    if info.get('MountPoint') != str(volume) or info.get('VolumeUUID','').upper() != identity:
                        raise RuntimeError('benchmark volume changed')
                elif probe.fresh_uuid(volume) != identity:
                    raise RuntimeError('benchmark volume changed')
                return {'volume_uuid':identity, 'volume_path':str(volume)}
            items = [dict(source=str(path), target=str(external/label/path.name), receipt=str(external/(label+'-receipt.jsonl'))) for path in originals]
            real_run, real_digest, real_fsync = engine.subprocess.run, engine.digest, engine.os.fsync
            def command(*args, **kwargs):
                if args[0][0] == 'lsof': calls['lsof'] += 1
                return real_run(*args, **kwargs)
            def digest(path):
                calls['sha256_readbacks'] += 1; return real_digest(path)
            def flush(fd):
                calls['fsync'] += 1; return real_fsync(fd)
            with mock.patch.dict(os.environ, {'CODEX_HARBOR_FILE_LOCK_DIR':str(local/'locks')}), \
                 mock.patch.object(engine.subprocess, 'run', side_effect=command), \
                 mock.patch.object(engine, 'digest', side_effect=digest), \
                 mock.patch.object(engine.os, 'fsync', side_effect=flush):
                tick = time.perf_counter()
                if label == 'before':
                    for item in items:
                        engine.archive_file(item['source'], item['target'], item['receipt'], check, keep_local=keep_local)
                    metrics = {}
                else:
                    metrics = engine.archive_batch(items, check, keep_local=keep_local)['metrics']
                elapsed = time.perf_counter()-tick
            pipeline_calls = dict(calls)
            row = dict(version=label, seconds=elapsed, files_per_second=count/elapsed,
                       verified_mib_per_second=count*size/elapsed/1048576, checks=pipeline_calls,
                       stage_seconds=metrics.get('stage_seconds', {}))
            print(json.dumps(row), flush=True)
            # Independent post-run audit plus byte-verified restore at the same original paths.
            for item, wanted in zip(items, expected):
                assert Path(item['source']).is_symlink()
                assert core.digest(item['source']) == wanted == core.digest(item['target'])
                core.restore_file(item['source'], item['target'], item['receipt'], check)
                assert not Path(item['source']).is_symlink() and core.digest(item['source']) == wanted
            report['runs'].append(row)
        report['speedup'] = report['runs'][0]['seconds']/report['runs'][1]['seconds']
        report['scope'] = 'synthetic durable safe pipeline; warm/cold cache uncontrolled; not media ceiling or hardware efficiency'
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--volume', required=True)
    parser.add_argument('--reference', default='32e85aef4f45cfa2a908574eb4c2e29ba0a9643c')
    args = parser.parse_args(); volume = Path(args.volume)
    probe = load('volume_probe'); identity = probe.fresh_uuid(volume)
    actual = plistlib.loads(subprocess.check_output(['diskutil','info','-plist',str(volume)]))
    if identity != actual['VolumeUUID'].upper() or actual['MountPoint'] != str(volume):
        raise RuntimeError('native UUID does not match independent diskutil readback')
    results = [run(volume, identity, args.reference, 32, 128*1024, False),
               run(volume, identity, args.reference, 2, 64*1024*1024, False),
               run(volume, identity, args.reference, 32, 128*1024, True)]
    print(json.dumps({'schema':'memory-harbor-synthetic-parking-benchmark-v1', 'results':results}, indent=2))


if __name__ == '__main__': main()
