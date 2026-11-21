#!/usr/bin/env python3
"""Build the native GUI with a self-contained Python engine (macOS arm64)."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'package/ScreenStudio-ZH-4.1.0-5005'
BUILD = ROOT / 'build-desktop'
DIST = ROOT / 'dist'
NAME = 'Screen Studio 中文安装器'


def run(*args):
    subprocess.run([str(a) for a in args], check=True, cwd=ROOT)


def main():
    if sys.platform != 'darwin':
        raise SystemExit('Build on macOS with Xcode command line tools.')
    BUILD.mkdir(exist_ok=True)
    DIST.mkdir(exist_ok=True)
    # One-folder avoids privileged extraction into a shared temporary directory.
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
               '--console', '--name', 'patch-engine', '--target-arch', 'arm64',
               '--distpath', str(BUILD / 'engine-dist'), '--workpath', str(BUILD / 'engine-work'),
               '--specpath', str(BUILD), '--paths', str(PACKAGE)]
    for name in ['manifest.json', 'payload']:
        command += ['--add-data', str(PACKAGE / name) + ':' + ('.' if name == 'manifest.json' else 'payload')]
    run(*command, ROOT / 'desktop/engine.py')
    delivery = DIST / 'ScreenStudio-中文一键安装包'
    delivery.mkdir(exist_ok=True)
    app = delivery / (NAME + '.app')
    if app.exists():
        shutil.rmtree(app)  # Build output only, never the recipient's app.
    contents = app / 'Contents'
    macos = contents / 'MacOS'
    resources = contents / 'Resources'
    macos.mkdir(parents=True)
    resources.mkdir()
    shutil.copytree(BUILD / 'engine-dist/patch-engine', resources / 'backend', symlinks=True)
    # Select the installed SDK that matches the host Swift toolchain rather
    # than xcrun's newest beta SDK. Override for another build host explicitly.
    sdk = os.environ.get('SCREENSTUDIO_BUILD_SDK', '/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk')
    if not Path(sdk).is_dir():
        sdk = subprocess.check_output(['xcrun', '--show-sdk-path'], text=True).strip()
    run('xcrun', 'swiftc', '-O', '-sdk', sdk, '-target', 'arm64-apple-macos13.0', '-framework', 'AppKit',
        ROOT / 'desktop/InstallerApp.swift', '-o', macos / 'ScreenStudioChineseInstaller')
    info = {
        'CFBundleIdentifier': 'io.github.maozepeng6.screenstudio-chinese-installer',
        'CFBundleName': NAME, 'CFBundleDisplayName': NAME,
        'CFBundleExecutable': 'ScreenStudioChineseInstaller', 'CFBundlePackageType': 'APPL',
        'CFBundleShortVersionString': '1.0.0', 'CFBundleVersion': '1',
        'LSMinimumSystemVersion': '13.0', 'NSHighResolutionCapable': True,
        'NSHumanReadableCopyright': 'Independent Chinese UI patch installer. Not affiliated with Screen Studio.',
    }
    (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
    # Explicit source/doc allowlist: never package original apps or project data.
    for name in ['AGENTS.md', '先读我.md', '验证记录.md', '销售前必读.md', 'LICENSE',
                 'manifest.json', 'installer.py', 'patch_native_menu.py']:
        target = resources / 'Documentation' / name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(PACKAGE / name, target)
    third_party = resources / 'ThirdPartyLicenses'
    third_party.mkdir()
    python_license = Path(sys.base_prefix) / 'lib/python3.9/LICENSE.txt'
    if not python_license.is_file():
        python_license = Path(sys.base_prefix) / ('lib/python%d.%d/LICENSE.txt' % sys.version_info[:2])
    if not python_license.is_file():
        raise RuntimeError('Python redistribution license not found')
    shutil.copyfile(python_license, third_party / 'Python.txt')
    package = importlib.metadata.distribution('pyinstaller')
    licenses = [p for p in package.files if p.name in ('COPYING.txt', 'COPYING')]
    if not licenses:
        raise RuntimeError('PyInstaller bootloader license not found')
    shutil.copyfile(package.locate_file(licenses[0]), third_party / 'PyInstaller.txt')
    shutil.copyfile(ROOT / 'desktop/给朋友看.txt', resources / '给朋友看.txt')
    shutil.copyfile(ROOT / 'desktop/给朋友看.txt', delivery / '先看这里.txt')
    # A local ad-hoc signature provides integrity checking, NOT Developer ID or notarization.
    run('/usr/bin/codesign', '--force', '--deep', '--sign', '-', app)
    run('/usr/bin/codesign', '--verify', '--deep', '--strict', app)
    run(resources / 'backend/patch-engine', '--self-check')
    run(macos / 'ScreenStudioChineseInstaller', '--self-test')
    archive = DIST / 'ScreenStudio-中文一键安装包.zip'
    if archive.exists():
        archive.unlink()
    run('/usr/bin/ditto', '-c', '-k', '--keepParent', delivery, archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (DIST / (archive.name + '.sha256')).write_text(digest + '  ' + archive.name + '\n')
    print(json.dumps({'app': str(app), 'zip': str(archive), 'bytes': archive.stat().st_size,
                      'sha256': digest, 'developer_id_signed': False, 'notarized': False}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
