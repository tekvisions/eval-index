"""Verify and stage an exact public snapshot without broad Git staging.

Never execute code from the comparison checkout. The caller's verified manifest
implementation plans and fingerprints it, including files absent locally.
"""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import tempfile
from public_assets import collect_public_files, planned_files, fingerprint


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, timeout=60)


@contextmanager
def committed_tree(root, sha):
    # Read the actual Git tree, not git archive: export-ignore/export-subst
    # attributes can make an archive differ from Vercel's Git checkout.
    entries = []
    for record in git(root, 'ls-tree', '-r', '-z', '--full-tree', sha).split(b'\0'):
        if not record: continue
        header, raw_name = record.split(b'\t', 1)
        mode, kind, oid = header.split()
        name = Path(raw_name.decode('utf-8'))
        if (name.is_absolute() or '..' in name.parts or '.git' in name.parts
                or '\\' in str(name) or mode not in (b'100644', b'100755') or kind != b'blob'):
            raise ValueError('Unsupported committed tree path or mode: ' + str(name))
        entries.append((name, oid))
    result = subprocess.run(['git', 'cat-file', '--batch'], cwd=root,
                            input=b''.join(oid + b'\n' for _, oid in entries),
                            stdout=subprocess.PIPE, check=True, timeout=60).stdout
    offset = 0
    with tempfile.TemporaryDirectory(prefix='public-snapshot-') as folder:
        destination = Path(folder)
        for name, oid in entries:
            line_end = result.index(b'\n', offset)
            actual_oid, kind, length = result[offset:line_end].split()
            size = int(length)
            offset = line_end + 1
            body = result[offset:offset + size]
            if actual_oid != oid or kind != b'blob' or len(body) != size or result[offset + size:offset + size + 1] != b'\n':
                raise ValueError('Invalid committed blob response')
            offset += size + 1
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        if offset != len(result): raise ValueError('Unexpected trailing committed blob data')
        yield destination


def verify_committed_publication(root, sha, receipt):
    # Present-file comparisons alone miss unstaged deletions and can republish
    # old legacy routes when the deployment checkout generates its own receipt.
    with committed_tree(root, sha) as snapshot:
        files = planned_files(snapshot)
        if files != receipt['public_files']:
            raise ValueError('Committed publication set differs from sealed local snapshot; review and commit generated removals')
        if fingerprint(snapshot, files) != receipt['sha256']:
            raise ValueError('Committed full input fingerprint differs from sealed local snapshot')


def stage_public_snapshot(root):
    root = Path(root)
    current = collect_public_files(root)
    # Only exact files that the prior committed manifest would publish are
    # eligible deletion targets. Private source deletion is never auto-staged.
    with committed_tree(root, 'HEAD') as snapshot:
        previous = set(planned_files(snapshot))
    deleted = git(root, 'diff', '--name-only', '--diff-filter=D', '-z', 'HEAD').decode().split('\0')
    removals = sorted(name for name in deleted if name and name in previous
                      and name not in current and not (root / name).exists()
                      and not (root / name).is_symlink())
    paths = sorted(set(current) | set(removals))
    if paths:
        subprocess.run(['git', 'add', '--', *paths], cwd=root, check=True, timeout=60)
    return paths


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', action='store_true', required=True)
    parser.parse_args()
    print('Staged exact public snapshot paths:', len(stage_public_snapshot(Path(__file__).resolve().parent)))
