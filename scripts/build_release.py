#!/usr/bin/env python3
"""Deterministically package only reviewed patch files, never the app workspace."""
from pathlib import Path
import hashlib
import json
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'package/ScreenStudio-ZH-4.1.0-5005'
FILES = [
    'README.md', 'LICENSE', 'CHANGELOG.md',
    '先读我.md', 'AGENTS.md', '销售前必读.md', '验证记录.md',
    'installer.py', 'patch_native_menu.py', 'repair_permissions.py',
    '检查与修复权限.command', 'manifest.json',
    'payload/zh-CN.json', 'payload/localize-main.cjs',
    'payload/localize-renderer.js', 'payload/localize-native-menu.js',
]


def main():
    for name in FILES:
        path = PACKAGE / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError('Missing or unsafe package file: ' + name)
        data = path.read_bytes()
        if re.search(rb'/Users/(?!test/)[^/\s]+/', data) or b'verification-errors.log' in data:
            raise RuntimeError('Private development path/log hook: ' + name)
    manifest = json.loads((PACKAGE / 'manifest.json').read_text())
    for name, expected in manifest['payload_sha256'].items():
        actual = hashlib.sha256((PACKAGE / 'payload' / name).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError('Payload checksum mismatch: ' + name)
    dictionary = json.loads((PACKAGE / 'payload/zh-CN.json').read_text())
    if len(dictionary) != manifest['translation_entries']:
        raise RuntimeError('Translation count mismatch')
    version_line = 'PACKAGE_VERSION = ' + json.dumps(manifest['package_version'])
    if version_line not in (PACKAGE / 'installer.py').read_text():
        raise RuntimeError('Installer and manifest version mismatch')
    sums = ''.join(hashlib.sha256((PACKAGE / name).read_bytes()).hexdigest()
                   + '  ' + name + '\n' for name in sorted(FILES))
    (PACKAGE / 'CHECKSUMS.sha256').write_text(sums, encoding='utf-8')
    output = ROOT / 'dist'
    output.mkdir(exist_ok=True)
    archive = output / 'ScreenStudio-ZH-4.1.0-5005-AI.zip'
    year, month, day = map(int, manifest['build_date'].split('-'))
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name in sorted(FILES + ['CHECKSUMS.sha256']):
            item = zipfile.ZipInfo(PACKAGE.name + '/' + name, (year, month, day, 0, 0, 0))
            item.create_system = 3
            mode = 0o100755 if name.endswith('.command') else 0o100644
            item.external_attr = mode << 16
            item.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(item, (PACKAGE / name).read_bytes(), compresslevel=9)
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None or len(bundle.namelist()) != len(FILES) + 1:
            raise RuntimeError('Archive verification failed')
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / (archive.name + '.sha256')).write_text(digest + '  ' + archive.name + '\n')
    print(json.dumps({'archive': archive.name, 'bytes': archive.stat().st_size,
                      'sha256': digest, 'files': len(FILES) + 1}, indent=2))


if __name__ == '__main__':
    main()
