"""Isolated installer regression tests; never operate on a real application.

All bundles and packages are tiny synthetic fixtures in TemporaryDirectory.
Every system command is replaced by a strict allowlist stub, and subprocess.run
is forbidden. These tests do not certify Apple signatures, TCC, Gatekeeper,
native recording, activation, GUI behavior, or real ditto ACL preservation.
Historical real macOS checks are documented separately; this suite uses no real app.
"""

import builtins
from contextlib import ExitStack, contextmanager, redirect_stdout
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


PACKAGE = Path(__file__).resolve().parents[1] / "package/ScreenStudio-ZH-4.1.0-5005"
sys.path.insert(0, str(PACKAGE))
import patch_native_menu as native_patch

SPEC = importlib.util.spec_from_file_location("screen_studio_installer_under_test", PACKAGE / "installer.py")
installer = importlib.util.module_from_spec(SPEC)
with mock.patch.object(subprocess, "run", side_effect=AssertionError("No real system commands during import")):
    SPEC.loader.exec_module(installer)


def digest(data):
    return hashlib.sha256(data).hexdigest()


# Tiny independently written inputs containing only the reviewed presentation
# anchors. No original application source is needed or redistributed. The tests
# replace only these modules' expected fingerprints, within each test's mocks;
# production fingerprint constants and package files remain unchanged.
MENU_FIXTURE = (
    b"export const first = {'items':_0x422f63[_0x2207f2(0x1ed)]};\n"
    b"export const second = {'items':_0x439af9[_0x347415(0x1ed)]};\n"
)
TOOLTIP_FIXTURE = (
    b"export function tooltip() {"
    b"return{'anchor':_0x2f4b2f,'label':_0x4b8bca[_0x10f92a(0xe5)]??_0x38692f??'',"
    b"'shortcut':_0x4b8bca[_0x10f92a(0xe5)]?_0x38692f:void 0x0,"
    b"'placement':F(_0x4b8bca[_0x10f92a(0xcd)]),'maxWidth':_0x4b8bca[_0x10f92a(0xc6)]??void 0x0}"
    b";}\n"
)


def fixture_archive(path):
    """Build ASAR using the file format, independently of installer helpers."""
    files = {
        "dist/D33o4ZAo2.js": MENU_FIXTURE,
        "dist/DsfCoJ1J.js": TOOLTIP_FIXTURE,
        "dist/index.html": b'<html lang="en"><head><script></script></head><body>fixture</body></html>',
        "dist-electron/index.js": b'const authUnmodified = "license/check";\nfunction realFeatureGate() { return authUnmodified; }\n',
        "dist/assets/opaque.bin": bytes(range(256)) + b"\0\xff\0",
        "dist/assets/empty.bin": b"",
        "dist/assets/another.js": b'const keepThis = "original UI and business logic";',
    }
    tree = {"files": {}}
    body = bytearray()
    for name, data in files.items():
        branch = tree
        parts = name.split("/")
        for part in parts[:-1]:
            branch = branch["files"].setdefault(part, {"files": {}})
        branch["files"][parts[-1]] = {
            "size": len(data), "offset": str(len(body)),
            "integrity": {"algorithm": "SHA256", "hash": digest(data), "blockSize": 4194304,
                          "blocks": [digest(data)]},
        }
        body.extend(data)
    tree["files"]["native-addon.node"] = {"size": 19, "unpacked": True}
    tree["files"]["asset-link"] = {"link": "dist/assets/opaque.bin"}
    raw = json.dumps(tree, separators=(",", ":")).encode()
    header_payload = struct.pack("<I", len(raw)) + raw
    header_payload += b"\0" * (-len(header_payload) % 4)
    header = struct.pack("<I", len(header_payload)) + header_payload
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<II", 4, len(header)) + header + body)
    return files, digest(raw)


def inspect_archive(path):
    """Independent reader for checking repacked output, not installer helpers."""
    data = path.read_bytes()
    magic, header_length, pickle_length, json_length = struct.unpack("<4I", data[:16])
    assert magic == 4 and header_length == pickle_length + 4
    raw = data[16:16 + json_length]
    tree = json.loads(raw)
    nodes = {}

    def walk(branch, prefix=""):
        for name, value in branch["files"].items():
            key = prefix + name
            if "files" in value:
                walk(value, key + "/")
            else:
                nodes[key] = value

    walk(tree)
    base = 8 + header_length
    contents = {name: data[base + int(node["offset"]):base + int(node["offset"]) + node["size"]]
                for name, node in nodes.items() if "offset" in node}
    return raw, nodes, contents


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="screen-studio-installer-test-")
        self.root = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)
        self.package = self.root / "package"
        self.package.mkdir()
        shutil.copytree(PACKAGE / "payload", self.package / "payload")
        self.manifest = json.loads((PACKAGE / "manifest.json").read_text())
        self.app = self.root / "Applications/Screen Studio.app"
        self.app.mkdir(parents=True)
        self.original_files, self.original_header_hash = fixture_archive(self.app / installer.ASAR_RELATIVE)
        self.original_hash = digest((self.app / installer.ASAR_RELATIVE).read_bytes())
        self.manifest["original_asar_sha256"] = self.original_hash
        (self.package / "manifest.json").write_text(json.dumps(self.manifest))
        self.executable = self.app / "Contents/MacOS/Screen Studio"
        self.executable.parent.mkdir()
        self.executable.write_bytes(b"synthetic-executable-only-no-real-code")
        self.executable.chmod(0o755)
        self.info = {
            "CFBundleIdentifier": installer.BUNDLE_ID,
            "CFBundleShortVersionString": installer.SUPPORTED_VERSION,
            "CFBundleVersion": installer.SUPPORTED_VERSION,
            "CFBundleExecutable": "Screen Studio",
            "ElectronAsarIntegrity": {"Resources/app.asar": {"algorithm": "SHA256", "hash": self.original_header_hash}},
        }
        self.write_info(self.info)
        unpacked = self.app / "Contents/Resources/app.asar.unpacked/native-addon.node"
        unpacked.parent.mkdir()
        unpacked.write_bytes(b"original native data")
        (self.app / "Contents/Resources/native-link").symlink_to("app.asar.unpacked/native-addon.node")
        self.backups = self.root / "backups"
        self.commands = []
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(mock.patch.object(installer, "PACKAGE_DIR", self.package))
        self.patches.enter_context(mock.patch.object(installer, "ORIGINAL_ASAR_HASH", self.original_hash))
        self.patches.enter_context(mock.patch.object(native_patch, "SOURCE_SHA256", digest(MENU_FIXTURE)))
        self.patches.enter_context(mock.patch.object(native_patch, "TOOLTIP_SOURCE_SHA256", digest(TOOLTIP_FIXTURE)))
        self.patches.enter_context(mock.patch.object(installer, "run_command", side_effect=self.fake_command))
        self.patches.enter_context(mock.patch.object(subprocess, "run", side_effect=AssertionError("Real commands are forbidden")))
        self.manifest, self.payload = installer.load_package()

    def write_info(self, info):
        (self.app / installer.INFO_RELATIVE).write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY))

    def fake_command(self, arguments, timeout=300):
        args = [str(arg) for arg in arguments]
        self.commands.append(args)
        if args[:2] == ["/usr/bin/lipo", "-archs"]:
            self.assert_under_tmp(args[-1])
            return "arm64"
        if args == ["/bin/ps", "-axo", "pid=,command="]:
            return ""
        if args[:4] == ["/usr/bin/ditto", "--rsrc", "--extattr", "--acl"] and len(args) == 6:
            self.assert_under_tmp(args[-2]); self.assert_under_tmp(args[-1])
            shutil.copytree(args[-2], args[-1], symlinks=True)
            return ""
        if args[:4] == ["/usr/bin/codesign", "--verify", "--deep", "--strict"]:
            self.assert_under_tmp(args[-1])
            self.assertIn(len(args), (5, 6))
            if len(args) == 6:
                self.assertEqual(args[4], "--test-requirement=" + installer.SIGNATURE_REQUIREMENT)
            return ""
        if args[:6] == ["/usr/bin/codesign", "--force", "--sign", "-", "--preserve-metadata=entitlements,flags", args[-1]]:
            self.assertEqual(len(args), 6)
            self.assert_under_tmp(args[-1])
            return ""
        raise AssertionError("Unexpected or unsafe system command: " + repr(args))

    def assert_under_tmp(self, path):
        self.assertTrue(Path(path).resolve().is_relative_to(self.root), str(path))

    def assert_code(self, code, call, *args, **kwargs):
        with self.assertRaises(installer.PatchError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def do_install(self):
        return installer.install(self.app, self.backups, self.manifest, self.payload, True)

    def installed_state(self, result):
        return installer.resolve_state(self.app, result["state"], None)

    @contextmanager
    def temporary_io_only(self):
        """Guard actual file opens and directory scans during transactional work.

        This is a regression guard, not an OS sandbox: it records the current
        install/restore flow and rejects accidental reads of home/credentials or
        writes outside the fixture. All subprocesses are separately forbidden.
        """
        original_open, original_io_open, original_scandir = builtins.open, io.open, installer.os.scandir
        opened = []

        def check(path):
            if not isinstance(path, int):
                self.assert_under_tmp(path)
                opened.append(str(path))

        def guarded_open(path, *args, **kwargs):
            check(path)
            return original_open(path, *args, **kwargs)

        def guarded_io_open(path, *args, **kwargs):
            check(path)
            return original_io_open(path, *args, **kwargs)

        def guarded_scandir(path):
            check(path)
            return original_scandir(path)

        with mock.patch.object(builtins, "open", guarded_open), mock.patch.object(io, "open", guarded_io_open), mock.patch.object(installer.os, "scandir", guarded_scandir):
            yield opened

    def test_package_validates_exact_supported_manifest(self):
        for key in ("app_version", "original_asar_sha256", "developer_team", "architecture"):
            with self.subTest(key=key):
                altered = copy.deepcopy(self.manifest)
                altered[key] = "unknown"
                (self.package / "manifest.json").write_text(json.dumps(altered))
                self.assert_code("INVALID_MANIFEST", installer.load_package)
        self.assertEqual(self.commands, [])

    def test_corrupt_or_symlink_payload_is_rejected(self):
        target = self.package / "payload/localize-main.cjs"
        original = target.read_bytes()
        target.write_bytes(original + b"\n/*corrupted*/")
        self.assert_code("PAYLOAD_HASH_MISMATCH", installer.load_package)
        target.unlink()
        outside = self.root / "another-script.cjs"
        outside.write_bytes(original)
        target.symlink_to(outside)
        self.assert_code("PAYLOAD_MISSING", installer.load_package)

    def test_preflight_rejects_newer_app_before_mutation(self):
        changed = dict(self.info, CFBundleShortVersionString="5.0.0", CFBundleVersion="5.0.0")
        self.write_info(changed)
        before = installer.bundle_inventory(self.app)
        self.assert_code("VERSION_MISMATCH", installer.preflight, self.app, self.backups, self.manifest)
        self.assertEqual(before, installer.bundle_inventory(self.app))
        self.assertFalse(self.backups.exists())

    def test_preflight_rejects_unknown_archive_even_with_supported_version(self):
        archive = self.app / installer.ASAR_RELATIVE
        archive.write_bytes(archive.read_bytes() + b"different build")
        self.assert_code("ORIGINAL_HASH_MISMATCH", installer.preflight, self.app, self.backups, self.manifest)
        self.assertFalse(self.backups.exists())

    def test_preflight_requires_original_developer_signature(self):
        def deny_official(args, timeout=300):
            if any(str(value).startswith("--test-requirement=") for value in args):
                raise installer.PatchError("COMMAND_FAILED", "fixture: nonofficial signature")
            return self.fake_command(args, timeout)
        with mock.patch.object(installer, "run_command", side_effect=deny_official):
            self.assert_code("COMMAND_FAILED", installer.preflight, self.app, self.backups, self.manifest)
        self.assertFalse(self.backups.exists())
        self.assertEqual(digest((self.app / installer.ASAR_RELATIVE).read_bytes()), self.original_hash)

    def test_architecture_and_running_process_are_not_bypassed(self):
        def intel(args, timeout=300):
            return "x86_64" if str(args[0]) == "/usr/bin/lipo" else self.fake_command(args, timeout)
        with mock.patch.object(installer, "run_command", side_effect=intel):
            self.assert_code("ARCHITECTURE_MISMATCH", installer.official_app, self.app)
        listing = "123 " + str(self.executable) + "\n"
        with mock.patch.object(installer, "run_command", return_value=listing):
            self.assert_code("APP_RUNNING", installer.assert_closed, self.app)

    def test_repack_preserves_every_unmodified_file_and_uses_customer_entries(self):
        original = self.app / installer.ASAR_RELATIVE
        output = self.root / "localized.asar"
        result = installer.build_asar(original, output, self.payload)
        raw, nodes, contents = inspect_archive(output)
        _, original_nodes, _ = inspect_archive(original)
        self.assertEqual(result["sha256"], digest(output.read_bytes()))
        self.assertEqual(result["header_sha256"], digest(raw))
        self.assertEqual(result["bytes"], output.stat().st_size)
        self.assertEqual(contents["dist-electron/index.js"], b'require("./localize-main.cjs");\n' + self.original_files["dist-electron/index.js"])
        self.assertEqual(contents["dist/index.html"].count(b"fixture"), 1)
        for name, data in self.original_files.items():
            if name not in ("dist/index.html", "dist-electron/index.js", installer.MENU_SOURCE_PATH, installer.TOOLTIP_SOURCE_PATH):
                self.assertEqual(contents[name], data)
                old_meta, new_meta = dict(original_nodes[name]), dict(nodes[name])
                old_meta.pop("offset"); new_meta.pop("offset")
                self.assertEqual(new_meta, old_meta)
        for name in ("native-addon.node", "asset-link"):
            self.assertEqual(nodes[name], original_nodes[name])
        self.assertEqual(contents[installer.MENU_SOURCE_PATH], installer.patch_native_menu(self.original_files[installer.MENU_SOURCE_PATH]))
        self.assertEqual(contents[installer.TOOLTIP_SOURCE_PATH], installer.patch_native_tooltip(self.original_files[installer.TOOLTIP_SOURCE_PATH]))
        self.assertIn(b'translateNativeMenuItems', contents[installer.MENU_RUNTIME_PATH])
        self.assertEqual(len(nodes), len(original_nodes) + 6)
        self.assertEqual(installer.build_asar(original, None, self.payload), result)
        self.assertEqual(digest(original.read_bytes()), self.original_hash)
        self.assertFalse((self.package / "source").exists())

    def test_bad_asar_or_ambiguous_injection_anchor_is_rejected(self):
        corrupt = self.root / "bad.asar"
        corrupt.write_bytes(b"not an archive")
        self.assert_code("ASAR_INVALID", installer.build_asar, corrupt, None, self.payload)
        original = self.app / installer.ASAR_RELATIVE
        data = original.read_bytes().replace(b'<html lang="en">', b'<html lang="zz">')
        corrupt.write_bytes(data)
        self.assert_code("PATCH_ANCHOR_MISMATCH", installer.build_asar, corrupt, None, self.payload)

    def test_native_source_fingerprints_still_reject_unreviewed_content(self):
        for patcher, original in ((native_patch.patch_native_menu, MENU_FIXTURE),
                                  (native_patch.patch_native_tooltip, TOOLTIP_FIXTURE)):
            with self.subTest(patcher=patcher.__name__):
                patched = patcher(original)
                self.assertNotEqual(patched, original)
                self.assertEqual(patcher(patched), patched)
                with self.assertRaisesRegex(ValueError, "Unsupported native-"):
                    patcher(original + b"\n// another build\n")

    def test_install_requires_explicit_signature_acknowledgement(self):
        self.assert_code("SIGNATURE_CONSENT_REQUIRED", installer.install, self.app, self.backups, self.manifest, self.payload, False)
        self.assertEqual(self.commands, [])
        self.assertFalse(self.backups.exists())

    def test_install_verify_restore_round_trip_stays_local(self):
        original_inventory = installer.bundle_inventory(self.app)
        with self.temporary_io_only() as accessed:
            result = self.do_install()
            self.assertEqual(result["status"], "installed")
            self.assertFalse(result["app_started"])
            state_path, state, backup = self.installed_state(result)
            self.assertEqual(installer.verify(self.app, state_path, state, backup, self.payload)["status"], "localized_verified")
            info = plistlib.loads((self.app / installer.INFO_RELATIVE).read_bytes())
            header, _, _ = inspect_archive(self.app / installer.ASAR_RELATIVE)
            self.assertEqual(info["ElectronAsarIntegrity"]["Resources/app.asar"]["hash"], digest(header))
            self.assertEqual(installer.bundle_inventory(backup), original_inventory)
            restored = installer.restore(self.app, state_path, state, backup, self.payload)
            self.assertEqual(restored["status"], "restored")
            self.assertEqual(installer.bundle_inventory(self.app), original_inventory)
            self.assertTrue(Path(restored["saved_before_restore"]).is_dir())
            self.assertTrue(backup.is_dir())
            self.assertEqual(installer.restore(self.app, state_path, state, backup, self.payload)["status"], "already_restored")
        self.assertGreater(len(accessed), 20)
        commands = {args[0] for args in self.commands}
        self.assertEqual(commands, {"/bin/ps", "/usr/bin/lipo", "/usr/bin/ditto", "/usr/bin/codesign"})

    def test_interrupted_post_swap_validation_rolls_back_original(self):
        before = installer.bundle_inventory(self.app)
        real_verify = installer.verify_patched

        def interrupt(app, *args):
            if app == self.app:
                raise KeyboardInterrupt("fixture interruption after swap")
            return real_verify(app, *args)

        with mock.patch.object(installer, "verify_patched", side_effect=interrupt):
            error = self.assert_code("SWAP_FAILED", self.do_install)
        self.assertTrue(error.details["rollback"]["restored_previous_app"])
        self.assertEqual(installer.bundle_inventory(self.app), before)
        state = json.loads(Path(error.details["state"]).read_text())
        self.assertEqual(state["phase"], "failed")
        self.assertTrue(Path(error.details["backup"]).is_dir())

    def test_restore_reconciles_original_after_failed_install_rollback(self):
        before = installer.bundle_inventory(self.app)
        real_verify = installer.verify_patched

        def interrupt(app, *args):
            if app == self.app:
                raise KeyboardInterrupt("fixture interruption after swap")
            return real_verify(app, *args)

        with self.temporary_io_only():
            with mock.patch.object(installer, "verify_patched", side_effect=interrupt):
                error = self.assert_code("SWAP_FAILED", self.do_install)
            state_path, state, backup = installer.resolve_state(self.app, error.details["state"], None)
            self.assertEqual(state["phase"], "failed")
            result = installer.restore(self.app, state_path, state, backup, self.payload)
            self.assertEqual(result["status"], "already_restored")
            self.assertTrue(result["state_reconciled"])
            self.assertEqual(installer.bundle_inventory(self.app), before)
            self.assertEqual(json.loads(state_path.read_text())["phase"], "restored")
            self.assertEqual(installer.verify(self.app, state_path, state, backup, self.payload)["status"], "original_verified")

    def interrupted_restore_fixture(self):
        """Model an abrupt shutdown after the original is back, before commit."""
        result = self.do_install()
        state_path, state, backup = self.installed_state(result)
        state["restore_phase"] = "prepared"
        installer.atomic_json(state_path, state)
        self.app.rename(self.root / "retained-localized.app")
        shutil.copytree(backup, self.app, symlinks=True)
        return state_path, state, backup

    def test_restore_reconciles_shutdown_before_receipt_commit(self):
        with self.temporary_io_only():
            state_path, state, backup = self.interrupted_restore_fixture()
            before = installer.bundle_inventory(self.app)
            commands_before = len(self.commands)
            result = installer.restore(self.app, state_path, state, backup, self.payload)
            self.assertEqual(result["status"], "already_restored")
            self.assertTrue(result["state_reconciled"])
            self.assertEqual(installer.bundle_inventory(self.app), before)
            self.assertEqual(state["phase"], "restored")
            self.assertEqual(state["restore_phase"], "complete")
            self.assertEqual(json.loads(state_path.read_text()), state)
            self.assertFalse(any(args[0] == "/usr/bin/ditto" for args in self.commands[commands_before:]))
            self.assertTrue((self.root / "retained-localized.app").is_dir())
            self.assertEqual(installer.restore(self.app, state_path, state, backup, self.payload)["status"], "already_restored")

    def test_restore_does_not_reconcile_changed_original_bundle(self):
        state_path, state, backup = self.interrupted_restore_fixture()
        (self.app / "Contents/changed-file").write_text("not the backed-up application")
        before = installer.bundle_inventory(self.app)
        state_before = state_path.read_bytes()
        self.assert_code("APP_CHANGED", installer.restore, self.app, state_path, state, backup, self.payload)
        self.assertEqual(installer.bundle_inventory(self.app), before)
        self.assertEqual(state_path.read_bytes(), state_before)

    def test_restore_requires_official_signature_before_reconciling(self):
        state_path, state, backup = self.interrupted_restore_fixture()
        state_before = state_path.read_bytes()

        def deny_official_app(args, timeout=300):
            if args[-1] == self.app and any(str(value).startswith("--test-requirement=") for value in args):
                raise installer.PatchError("COMMAND_FAILED", "fixture: current app lacks official signature")
            return self.fake_command(args, timeout)

        with mock.patch.object(installer, "run_command", side_effect=deny_official_app):
            self.assert_code("COMMAND_FAILED", installer.restore, self.app, state_path, state, backup, self.payload)
        self.assertEqual(state_path.read_bytes(), state_before)
        self.assertEqual(installer.bundle_inventory(self.app), installer.bundle_inventory(backup))

    def swap_fixture(self):
        stage = self.root / "swap-staging"
        stage.mkdir()
        staged = stage / "localized.app"
        shutil.copytree(self.app, staged, symlinks=True)
        (staged / "patched-marker").write_text("fixture")
        return stage, staged

    def test_early_swap_failure_never_moves_the_original(self):
        stage, staged = self.swap_fixture()
        before = installer.bundle_inventory(self.app)
        with mock.patch.object(installer, "assert_closed", side_effect=installer.PatchError("APP_RUNNING", "fixture")):
            self.assert_code("SWAP_FAILED", installer.swap_bundles, self.app, staged, stage, lambda: None, lambda previous: None)
        self.assertEqual(installer.bundle_inventory(self.app), before)
        self.assertTrue(staged.is_dir())
        self.assertFalse((stage / "previous.app").exists())
        self.assertFalse((stage / "uncommitted.app").exists())

    def test_first_rename_failure_keeps_original_in_place(self):
        stage, staged = self.swap_fixture()
        before = installer.bundle_inventory(self.app)
        original_rename = Path.rename

        def fail_first(path, target):
            if path == self.app:
                raise PermissionError("fixture failed rename")
            return original_rename(path, target)

        with mock.patch.object(Path, "rename", fail_first):
            self.assert_code("SWAP_FAILED", installer.swap_bundles, self.app, staged, stage, lambda: None, lambda previous: None)
        self.assertEqual(installer.bundle_inventory(self.app), before)
        self.assertTrue(staged.is_dir())
        self.assertFalse((stage / "previous.app").exists())

    def test_commit_failure_rolls_back_but_retains_both_copies(self):
        stage, staged = self.swap_fixture()
        before = installer.bundle_inventory(self.app)

        def fail_commit(_previous):
            raise OSError("fixture full disk during state commit")

        error = self.assert_code("SWAP_FAILED", installer.swap_bundles, self.app, staged, stage, lambda: None, fail_commit)
        self.assertTrue(error.details["rollback"]["restored_previous_app"])
        self.assertEqual(installer.bundle_inventory(self.app), before)
        self.assertTrue((stage / "uncommitted.app/patched-marker").is_file())

    def test_restore_refuses_updated_version_without_overwriting(self):
        result = self.do_install()
        state_path, state, backup = self.installed_state(result)
        info = plistlib.loads((self.app / installer.INFO_RELATIVE).read_bytes())
        info.update(CFBundleShortVersionString="4.2.0-6000", CFBundleVersion="4.2.0-6000")
        self.write_info(info)
        newer = installer.bundle_inventory(self.app)
        self.assert_code("VERSION_MISMATCH", installer.restore, self.app, state_path, state, backup, self.payload)
        self.assertEqual(installer.bundle_inventory(self.app), newer)

    def test_restore_refuses_same_version_changed_bundle(self):
        result = self.do_install()
        state_path, state, backup = self.installed_state(result)
        (self.app / "Contents/new-updater-data").write_text("changed after install")
        changed = installer.bundle_inventory(self.app)
        self.assert_code("APP_CHANGED", installer.restore, self.app, state_path, state, backup, self.payload)
        self.assertEqual(installer.bundle_inventory(self.app), changed)

    def test_restore_does_not_trust_tampered_state_or_backup(self):
        result = self.do_install()
        state_path, state, backup = self.installed_state(result)
        before = installer.bundle_inventory(self.app)
        tampered = dict(state, installed_asar_sha256="0" * 64)
        self.assert_code("INVALID_STATE", installer.restore, self.app, state_path, tampered, backup, self.payload)
        (backup / "Contents/extra-data").write_text("modified backup")
        self.assert_code("BACKUP_MISMATCH", installer.restore, self.app, state_path, state, backup, self.payload)
        self.assertEqual(installer.bundle_inventory(self.app), before)

    def test_cli_has_no_force_or_safety_bypass_flags(self):
        for flag in ("--force", "--skip-signature", "--disable-gatekeeper", "--remove-quarantine"):
            with self.subTest(flag=flag):
                self.assert_code("INVALID_ARGUMENTS", installer.parse_args, ["install", flag])
        self.assertEqual(self.commands, [])

    def test_reimport_has_no_cli_or_filesystem_side_effects(self):
        module = importlib.util.module_from_spec(SPEC)
        output = io.StringIO()
        with redirect_stdout(output), mock.patch.object(Path, "write_bytes", side_effect=AssertionError("Import wrote files")), mock.patch.object(Path, "write_text", side_effect=AssertionError("Import wrote files")):
            SPEC.loader.exec_module(module)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
