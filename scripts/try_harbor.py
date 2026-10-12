#!/usr/bin/env python3
"""A disposable, explicit opt-in byte-transaction trial. Never reads Codex history.

Without --execute this prints a plan and creates nothing. With --execute, only
new sample files are docked and restored, using the production transaction core.
Success retains the two tiny sample directories and receipts for inspection;
failure retains them for diagnosis. No cleanup/delete command is offered.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/codex-memory-harbor/scripts'
SAMPLE_BYTES = 128 * 1024


def load_module(name):
    spec = importlib.util.spec_from_file_location('trial_' + name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def plan(volume=None):
    return {'mode': 'plan_only', 'creates_files': False, 'reads_codex_history': False,
            'volume': volume, 'sample_bytes': SAMPLE_BYTES,
            'steps': ['create new sample', 'verified dock with local rollback',
                      'read through original path', 'restore', 'verify both copies'],
            'execute': 'python3 scripts/try_harbor.py --volume "/Volumes/Your SSD" --execute',
            'boundary': 'byte-transaction trial only; not a Codex restart or remount test'}


def run_trial(volume_value, emit=None):
    archive = load_module('archive_files')
    harbor = load_module('harbor')
    volume = harbor.mounted_volume(volume_value)
    identity = harbor.volume_identity(volume)
    expected_uuid = identity['uuid']
    harbor.verify_external_volume(volume, expected_uuid)
    # Unique, exclusively created destinations. Never accept source paths from a caller.
    trial_id = str(uuid.uuid4())
    local = Path(tempfile.mkdtemp(prefix='memory-harbor-trial-')).resolve()
    external = volume / ('Memory Harbor Trial ' + trial_id)
    external.mkdir(mode=0o700, exist_ok=False)
    source = local / 'sample.txt'
    target = external / 'sample.txt'
    receipt = external / 'receipt.jsonl'
    payload = (b'Memory Harbor disposable sample. No personal history.\n' * 3000)[:SAMPLE_BYTES]
    with source.open('xb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    archive.durable_directory(local)
    expected = archive.digest(source)
    report = {'schema': 'memory-harbor-trial-v1', 'trial_id': trial_id,
              'local_samples': str(local), 'external_samples': str(external),
              'sample_bytes': len(payload), 'sha256': expected, 'steps': [],
              'reads_codex_history': False, 'keeps_local_rollback': True,
              'boundary': 'production byte core; not Codex restart/remount acceptance'}
    report_path = local / 'trial-report.json'

    def persist(step):
        report['steps'].append(step)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        if emit:
            emit({'step': step, 'local_samples': str(local), 'external_samples': str(external)})

    def check_volume():
        harbor.verify_external_volume(volume, expected_uuid)
        return {'volume_uuid': expected_uuid, 'volume_path': str(volume)}

    previous = os.environ.get('CODEX_HARBOR_FILE_LOCK_DIR')
    os.environ['CODEX_HARBOR_FILE_LOCK_DIR'] = str(local / 'locks')
    try:
        persist('created_disposable_sample')
        archive.archive_file(source, target, receipt, check_volume, keep_local=True)
        rollback = source.with_name(source.name + '.harbor-archive-rollback')
        if (not source.is_symlink() or os.readlink(source) != str(target)
                or not rollback.is_file() or archive.digest(rollback) != expected):
            raise RuntimeError('Sample link/rollback verification failed')
        persist('verified_dock_with_local_rollback')
        # This opens the original path, not the target directly.
        if archive.digest(source) != expected or archive.digest(target) != expected:
            raise RuntimeError('Original-path sample read failed')
        persist('original_path_read_verified')
        archive.restore_file(source, target, receipt, check_volume)
        if (source.is_symlink() or archive.digest(source) != expected
                or archive.digest(target) != expected or rollback.exists()):
            raise RuntimeError('Sample restoration failed')
        persist('restored_and_both_copies_verified')
        report['status'] = 'passed'
        report['report_path'] = str(report_path)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        return report
    except Exception as exc:
        report['status'] = 'stopped_samples_retained'
        report['error'] = type(exc).__name__
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print('Trial stopped. Inspect retained samples: ' + str(report_path), file=sys.stderr)
        raise
    finally:
        if previous is None:
            os.environ.pop('CODEX_HARBOR_FILE_LOCK_DIR', None)
        else:
            os.environ['CODEX_HARBOR_FILE_LOCK_DIR'] = previous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--volume', help='exact mounted volume, e.g. /Volumes/Your SSD')
    parser.add_argument('--execute', action='store_true', help='create, dock and restore only new samples')
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps(plan(args.volume), ensure_ascii=False, indent=2))
        return 0
    if not args.volume:
        parser.error('--execute requires --volume')
    try:
        report = run_trial(args.volume, lambda event: print(json.dumps(event), file=sys.stderr, flush=True))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print('Trial stopped: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
