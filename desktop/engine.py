#!/usr/bin/env python3
"""Frozen, stdlib-only entry point. Never installs Python on the recipient's Mac.

The original version-pinned installer remains the authority for all app changes.
Administrative runs use a separate root-owned recovery tree, never user-supplied
backup directories. No background helper, network, password handling or TCC writes.
"""
import json
import os
from pathlib import Path
import stat
import struct
import sys
import uuid

import installer

SYSTEM_BACKUPS = Path('/Library/Application Support/ScreenStudioChinesePatch/backups')
CORE_RUN_COMMAND = installer.run_command


def desktop_run_command(arguments, timeout=300):
    # /usr/bin/lipo may be an Xcode shim. Read the fixed executable header so a
    # customer's Mac does not need Command Line Tools; retain strict arm64-only.
    if len(arguments) == 3 and [str(x) for x in arguments[:2]] == ['/usr/bin/lipo', '-archs']:
        try:
            with Path(arguments[2]).open('rb') as source:
                header = source.read(32)
        except OSError as error:
            raise installer.PatchError('INVALID_APP', '无法读取 Screen Studio 主程序。') from error
        installer.require(len(header) == 32, 'ARCHITECTURE_MISMATCH', '应用主程序不是支持的 Apple Silicon 构建。')
        magic, cpu, subtype, kind, _, _, _, _ = struct.unpack('<8I', header)
        installer.require((magic, cpu, subtype, kind) == (0xfeedfacf, 0x100000c, 0, 2),
                          'ARCHITECTURE_MISMATCH', '仅支持已验证的 Apple Silicon 构建，不能安装到 Intel 或其他构建。')
        return 'arm64'
    return CORE_RUN_COMMAND(arguments, timeout=timeout)


def no_symlink_ancestors(path):
    for item in [path, *path.parents]:
        installer.require(not item.is_symlink(), 'UNSAFE_ADMIN_PATH',
                          '管理员操作不能使用符号链接路径。', path=str(item))


def root_owned_chain(path):
    no_symlink_ancestors(path)
    for item in [path, *path.parents]:
        if item.exists():
            meta = item.lstat()
            installer.require(meta.st_uid == 0 and not stat.S_IMODE(meta.st_mode) & 0o022,
                              'UNSAFE_ADMIN_PATH', '系统备份目录权限不符合要求，请保留原状并联系维护者。',
                              path=str(item))


def check_admin_arguments(args):
    """This is only an extra restriction; it never relaxes installer checks."""
    app = installer.absolute(args.app)
    installer.require(app.parent == Path('/Applications') or Path('/Applications') in app.parents,
                      'ADMIN_APP_PATH', '需要管理员权限时，只支持“应用程序”文件夹内的 Screen Studio。')
    no_symlink_ancestors(app)
    root_owned_chain(SYSTEM_BACKUPS)
    if args.command in ('install', 'preflight'):
        installer.require(args.backup_dir is not None and installer.absolute(args.backup_dir) == SYSTEM_BACKUPS,
                          'ADMIN_BACKUP_PATH', '管理员安装必须使用固定的系统备份目录。')
    else:
        installer.require(bool(args.state) and not args.backup_dir, 'ADMIN_STATE_PATH',
                          '管理员恢复需要本次安装保存的恢复记录。')
        state = installer.absolute(args.state)
        try:
            valid_uuid = str(uuid.UUID(state.parent.name)) == state.parent.name
        except ValueError:
            valid_uuid = False
        installer.require(state.name == 'state.json' and state.parent.parent == SYSTEM_BACKUPS and valid_uuid,
                          'ADMIN_STATE_PATH', '恢复记录不在本安装器的系统备份目录中。')
        root_owned_chain(state)
        installer.require(state.parent.is_dir() and not stat.S_IMODE(state.parent.stat().st_mode) & 0o077,
                          'UNSAFE_ADMIN_PATH', '系统恢复记录目录必须仅管理员可访问。')
        # ditto preserves the official app's original owner/modes. A root-only
        # receipt directory protects that separate copy without recursive chown.
        no_symlink_ancestors(state.parent / 'original.app')


def check_frozen_integrity():
    installer.require(getattr(sys, 'frozen', False), 'ADMIN_RUNTIME',
                      '管理员操作只能使用完整的桌面安装器。')
    executable = Path(sys.executable)
    bundle = executable.parents[3]
    installer.require(bundle.suffix == '.app' and executable.relative_to(bundle).as_posix() ==
                      'Contents/Resources/backend/patch-engine', 'ADMIN_RUNTIME', '安装器目录结构无效。')
    no_symlink_ancestors(bundle)
    installer.require(not stat.S_IMODE(bundle.lstat().st_mode) & 0o022, 'ADMIN_RUNTIME',
                      '安装器目录可被其他用户改写，请重新解压安装包。')
    # Normal internal Python.framework symlinks are allowed only within the app.
    for folder, dirs, files in os.walk(bundle, followlinks=False):
        for name in dirs + files:
            entry = Path(folder) / name
            if entry.is_symlink():
                installer.require(entry.resolve().is_relative_to(bundle.resolve()), 'ADMIN_RUNTIME',
                                  '安装器包含指向外部的运行库链接。')
            else:
                installer.require(not stat.S_IMODE(entry.lstat().st_mode) & 0o022, 'ADMIN_RUNTIME',
                                  '安装器文件可被其他用户改写，请重新解压安装包。')
    installer.run_command(['/usr/bin/codesign', '--verify', '--deep', '--strict', bundle], timeout=120)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv == ['--self-check']:
            manifest, payload = installer.load_package()
            print(json.dumps({'ok': True, 'frozen': bool(getattr(sys, 'frozen', False)),
                              'package_version': manifest['package_version'],
                              'translation_entries': manifest['translation_entries'],
                              'resource_count': len(payload), 'changes_made': False}, ensure_ascii=False))
            return 0
        args = installer.parse_args(argv)
        if not args.help and os.geteuid() == 0:
            check_frozen_integrity()
            check_admin_arguments(args)
        installer.run_command = desktop_run_command
        return installer.main(argv)
    except installer.PatchError as error:
        print(json.dumps({'ok': False, 'compatible': False,
                          'error': {'code': error.code, 'message': str(error), **error.details}}, ensure_ascii=False))
        return 1
    except Exception as error:
        print(json.dumps({'ok': False, 'compatible': False,
                          'error': {'code': 'DESKTOP_ENGINE_ERROR',
                                    'message': '安装器检查未完成，未继续修改应用。',
                                    'type': type(error).__name__}}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
