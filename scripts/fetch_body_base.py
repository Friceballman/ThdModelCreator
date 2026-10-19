"""Fetch only official MakeHuman mesh data and its licenses; install nothing."""
import hashlib
import json
from pathlib import Path
import urllib.request

REPO = Path(__file__).resolve().parents[1]
DEST = REPO / 'assets' / 'body-bases' / 'makehuman-hm08'
UPSTREAM = 'makehumancommunity/makehuman'


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'ThdModelCreator-asset-fetch'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main():
    if DEST.exists():
        raise SystemExit('Already present; inspect the manifest instead of overwriting.')
    commit = json.loads(fetch(f'https://api.github.com/repos/{UPSTREAM}/commits/master'))['sha']
    files = {}
    for source in ('makehuman/data/3dobjs/base.obj', 'LICENSE.md', 'LICENSE.ASSETS.md'):
        url = f'https://raw.githubusercontent.com/{UPSTREAM}/{commit}/{source}'
        data = fetch(url)
        files[Path(source).name] = (data, url)
    # Validate the file-specific CC0 declaration before retaining any asset.
    assert b'CC0' in files['base.obj'][0][:1200]
    assert b'CC0' in files['LICENSE.ASSETS.md'][0]
    DEST.mkdir(parents=True)
    manifest = {'upstream': f'https://github.com/{UPSTREAM}', 'commit': commit,
                'license': 'CC0-1.0', 'role': 'body_base_candidate',
                'adopted_for_project': False, 'files': []}
    for name, (data, url) in files.items():
        (DEST / name).write_bytes(data)
        manifest['files'].append({'file': name, 'source_url': url,
                                  'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    (DEST / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    groups = [line for line in files['base.obj'][0].decode().splitlines() if line.startswith(('g ', 'mtllib ', 'usemtl '))]
    print(json.dumps({'directory': str(DEST), 'commit': commit, 'groups': groups}, indent=2))


if __name__ == '__main__':
    main()
