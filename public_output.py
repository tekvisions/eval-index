"""Build only manifest-approved assets from the exact Git checkout, offline."""
import json
from pathlib import Path
import shutil
from public_assets import seal, collect_public_files, digest

EXPECTED_CONFIG = {'git': {'deploymentEnabled': False}, 'framework': None,
                   'installCommand': '', 'buildCommand': 'python3 public_output.py',
                   'outputDirectory': 'public-output'}


def build(root=None):
    root = Path(root) if root else Path(__file__).resolve().parent
    if json.loads((root / 'vercel.json').read_text()) != EXPECTED_CONFIG:
        raise ValueError('Unexpected public build configuration')
    # The Actions receipt is deliberately private/uncommitted. Revalidate this
    # immutable Git checkout offline; never recompute upstream data at Vercel.
    seal(root)
    files = collect_public_files(root)
    output = root / 'public-output'
    # No recursive deletion: stale/cached output must fail closed.
    output.mkdir(exist_ok=False)
    for name in files:
        if name == 'vercel.json': continue  # Build configuration is not a web asset.
        source, target = root / name, output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if digest(source) != digest(target): raise ValueError('Public copy mismatch')
    expected = set(files) - {'vercel.json'}
    actual = {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()}
    if actual != expected: raise ValueError('Unexpected public output set')
    return sorted(actual)


if __name__ == '__main__':
    print('Verified offline public output:', len(build()), 'files')
