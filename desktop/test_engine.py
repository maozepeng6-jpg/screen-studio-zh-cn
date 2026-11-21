import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'desktop'), str(ROOT / 'package/ScreenStudio-ZH-4.1.0-5005')]
import engine
import installer


class AdminBoundaryTests(unittest.TestCase):
    def args(self, *values):
        return installer.parse_args(values)

    def rejected(self, expected, args):
        with self.assertRaises(installer.PatchError) as caught:
            engine.check_admin_arguments(args)
        self.assertEqual(caught.exception.code, expected)

    def test_admin_rejects_user_app_path(self):
        self.rejected('ADMIN_APP_PATH', self.args('install', '--app', '/Users/example/Screen Studio.app'))

    @patch.object(engine, 'root_owned_chain')
    def test_admin_rejects_arbitrary_backup(self, _):
        self.rejected('ADMIN_BACKUP_PATH', self.args('install', '--backup-dir', '/tmp/backup'))

    @patch.object(engine, 'root_owned_chain')
    def test_admin_does_not_default_to_root_home(self, _):
        self.rejected('ADMIN_BACKUP_PATH', self.args('install'))

    @patch.object(engine, 'root_owned_chain')
    def test_exact_system_backup_is_accepted(self, guard):
        engine.check_admin_arguments(self.args('install', '--backup-dir', str(engine.SYSTEM_BACKUPS)))
        guard.assert_called_once_with(engine.SYSTEM_BACKUPS)

    @patch.object(engine, 'root_owned_chain')
    def test_restore_requires_exact_receipt(self, _):
        self.rejected('ADMIN_STATE_PATH', self.args('restore'))
        self.rejected('ADMIN_STATE_PATH', self.args('restore', '--state', '/tmp/state.json'))

    @patch.object(engine, 'root_owned_chain')
    def test_restore_rejects_non_uuid_directory(self, _):
        self.rejected('ADMIN_STATE_PATH', self.args('restore', '--state', str(engine.SYSTEM_BACKUPS / 'oops/state.json')))

    @patch.object(engine, 'root_owned_chain')
    def test_valid_receipt_checks_backup_chain(self, guard):
        receipt = engine.SYSTEM_BACKUPS / '91f923d4-4b0a-442e-8e8a-6e29df3e1022/state.json'
        with patch.object(Path, 'is_dir', return_value=True), patch.object(Path, 'stat', return_value=SimpleNamespace(st_mode=0o40700)):
            engine.check_admin_arguments(self.args('restore', '--state', str(receipt)))
        self.assertEqual([c.args[0] for c in guard.call_args_list],
                         [engine.SYSTEM_BACKUPS, receipt])

    def test_symbolic_link_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / 'real').mkdir()
            (root / 'link').symlink_to(root / 'real', target_is_directory=True)
            with self.assertRaises(installer.PatchError):
                engine.no_symlink_ancestors(root / 'link/missing')

    def test_writable_directory_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp).resolve()
            folder.chmod(0o777)
            with self.assertRaises(installer.PatchError):
                engine.root_owned_chain(folder)

    def test_admin_cannot_use_unfrozen_python(self):
        with patch.object(sys, 'frozen', False, create=True):
            with self.assertRaises(installer.PatchError):
                engine.check_frozen_integrity()

    def test_no_side_effects_during_self_check(self):
        output = io.StringIO()
        with patch.object(installer, 'main', side_effect=AssertionError('no installation')), contextlib.redirect_stdout(output):
            self.assertEqual(engine.main(['--self-check']), 0)
        report = json.loads(output.getvalue())
        self.assertTrue(report['ok'])
        self.assertFalse(report['changes_made'])
        self.assertEqual(report['translation_entries'], 2068)

    def test_admin_error_remains_json(self):
        output = io.StringIO()
        with patch('os.geteuid', return_value=0), patch.object(engine, 'check_frozen_integrity'), contextlib.redirect_stdout(output):
            self.assertEqual(engine.main(['install', '--app', '/tmp/target.app']), 1)
        self.assertEqual(json.loads(output.getvalue())['error']['code'], 'ADMIN_APP_PATH')

    def test_user_operation_preserves_core_arguments(self):
        with patch('os.geteuid', return_value=501), patch.object(installer, 'main', return_value=7) as run:
            self.assertEqual(engine.main(['preflight']), 7)
        run.assert_called_once_with(['preflight'])

    def test_unexpected_guard_failure_returns_json(self):
        output = io.StringIO()
        with patch('os.geteuid', return_value=0), patch.object(engine, 'check_frozen_integrity', side_effect=OSError('test')), contextlib.redirect_stdout(output):
            self.assertEqual(engine.main(['install']), 1)
        self.assertEqual(json.loads(output.getvalue())['error']['code'], 'DESKTOP_ENGINE_ERROR')

    def test_macho_architecture_without_xcode(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "应用 with ' quote"
            exe.write_bytes(struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 2, 0, 0, 0, 0))
            with patch.object(engine, 'CORE_RUN_COMMAND', side_effect=AssertionError('must not run lipo')):
                self.assertEqual(engine.desktop_run_command(['/usr/bin/lipo', '-archs', exe]), 'arm64')
                for content in [b'bad', struct.pack('<8I', 0xfeedfacf, 0x1000007, 0, 2, 0, 0, 0, 0),
                                struct.pack('<8I', 0xcafebabe, 0x100000c, 0, 2, 0, 0, 0, 0)]:
                    exe.write_bytes(content)
                    with self.assertRaises(installer.PatchError):
                        engine.desktop_run_command(['/usr/bin/lipo', '-archs', exe])

    def test_other_commands_are_not_intercepted(self):
        with patch.object(engine, 'CORE_RUN_COMMAND', return_value='ok') as run:
            self.assertEqual(engine.desktop_run_command(['/usr/bin/codesign', '--verify', '/x'], 12), 'ok')
        run.assert_called_once_with(['/usr/bin/codesign', '--verify', '/x'], timeout=12)


if __name__ == '__main__':
    unittest.main()
