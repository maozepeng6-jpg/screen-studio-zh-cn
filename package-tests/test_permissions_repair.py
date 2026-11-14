"""Targeted safety tests: temporary bundles and mocked commands only.

Never reads TCC, resets real permissions, queries real processes, or touches an
installed application. Apple permission behavior itself is outside this suite.
"""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest import mock


PACKAGE = Path(__file__).resolve().parents[1] / "package/ScreenStudio-ZH-4.1.0-5005"
SPEC = importlib.util.spec_from_file_location("permissions_repair_under_test", PACKAGE / "repair_permissions.py")
repair = importlib.util.module_from_spec(SPEC)
with mock.patch.object(subprocess, "run", side_effect=AssertionError("No real commands")):
    SPEC.loader.exec_module(repair)


class PermissionRepairTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="screen-studio-permissions-test-")
        self.addCleanup(temporary.cleanup)
        self.app = Path(temporary.name) / "Screen Studio.app"
        executable = self.app / "Contents/MacOS/Screen Studio"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"")
        self.info = {
            "CFBundleIdentifier": "com.timpler.screenstudio",
            "CFBundleShortVersionString": "4.1.0-5005",
            "CFBundleVersion": "4.1.0-5005",
            "CFBundleExecutable": "Screen Studio",
        }
        self.write_info()
        self.commands = []
        self.signature_valid = True
        self.running = False
        self.failed_service = None
        self.ps_count = 0
        self.relaunch_on_ps = None
        guard = mock.patch.object(subprocess, "run", side_effect=AssertionError("Real system commands forbidden"))
        guard.start()
        self.addCleanup(guard.stop)

    def write_info(self):
        (self.app / "Contents/Info.plist").write_bytes(plistlib.dumps(self.info))

    def runner(self, arguments, timeout=30):
        args = list(arguments)
        self.commands.append(args)
        stdout, stderr, returncode = "", "", 0
        if args == ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(self.app)]:
            returncode = 0 if self.signature_valid else 1
        elif args == ["/usr/bin/codesign", "--display", "--verbose=4", str(self.app)]:
            stderr = "Signature=adhoc\nTeamIdentifier=not set\n"
        elif args == ["/bin/ps", "-axo", "pid=,command="]:
            self.ps_count += 1
            if self.running or self.ps_count == self.relaunch_on_ps:
                stdout = "4321 " + str(self.app / "Contents/MacOS/Screen Studio") + "\n"
        elif len(args) == 4 and args[:2] == ["/usr/bin/tccutil", "reset"]:
            self.assertIn(args[2], ("ScreenCapture", "Accessibility", "Microphone", "Camera"))
            self.assertEqual(args[3], "com.timpler.screenstudio")
            returncode = 1 if args[2] == self.failed_service else 0
        else:
            self.fail("Unexpected system operation: " + repr(args))
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)

    def run_repair(self, **kwargs):
        return repair.run_repair(app=self.app, runner=self.runner, platform="darwin", **kwargs)

    def reset_commands(self):
        return [args for args in self.commands if args[0] == "/usr/bin/tccutil"]

    def error(self, code, **kwargs):
        with self.assertRaises(repair.PermissionRepairError) as caught:
            self.run_repair(**kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_default_check_reports_unknown_permissions_without_reset(self):
        self.running = True
        result = self.run_repair()
        self.assertEqual(result["mode"], "check")
        self.assertEqual(result["running_pids"], [4321])
        self.assertEqual(result["permission_status"], "unknown_not_queried")
        self.assertFalse(result["permission_granted_by_tool"])
        self.assertEqual(result["permissions_reset"], [])
        self.assertEqual(result["attempted_commands"], [])
        self.assertEqual(self.reset_commands(), [])

    def test_cli_check_and_dry_run_never_execute_planned_commands(self):
        for mode in ("--check", "--dry-run"):
            with self.subTest(mode=mode), mock.patch.object(repair, "run_command", self.runner), mock.patch.object(repair.sys, "platform", "darwin"):
                output = io.StringIO()
                with redirect_stdout(output):
                    status = repair.main([mode, "--app", str(self.app)])
                result = json.loads(output.getvalue())
                self.assertEqual(status, 0)
                self.assertEqual(result["mode"], "check")
                self.assertEqual(result["attempted_commands"], [])
        self.assertEqual(self.reset_commands(), [])

    def test_repair_requires_explicit_confirmation(self):
        self.error("CONFIRMATION_REQUIRED", repair=True)
        self.error("INVALID_OPTIONS", confirm=True)
        self.assertEqual(self.commands, [])

    def test_all_unknown_empty_or_injected_services_are_rejected(self):
        for services in (("All",), ("ScreenCapture; echo injected",), ("screenCapture",), (), "ScreenCapture"):
            with self.subTest(services=services):
                self.error("INVALID_SERVICE", repair=True, confirm=True, services=services)
        self.assertEqual(self.commands, [])

    def test_wrong_bundle_or_unknown_version_never_calls_system_commands(self):
        self.info["CFBundleIdentifier"] = "com.other.app; echo injected"
        self.write_info()
        self.error("WRONG_APP", repair=True, confirm=True)
        self.info["CFBundleIdentifier"] = repair.BUNDLE_ID
        self.info["CFBundleVersion"] = "5.0.0"
        self.write_info()
        self.error("VERSION_MISMATCH", repair=True, confirm=True)
        self.assertEqual(self.commands, [])

    def test_invalid_signature_and_running_app_block_repair(self):
        self.signature_valid = False
        self.error("SIGNATURE_INVALID", repair=True, confirm=True)
        self.signature_valid = True
        self.running = True
        self.error("APP_RUNNING", repair=True, confirm=True)
        self.assertEqual(self.reset_commands(), [])

    def test_default_repair_resets_only_two_core_services_for_fixed_bundle(self):
        result = self.run_repair(repair=True, confirm=True)
        expected = [["/usr/bin/tccutil", "reset", service, "com.timpler.screenstudio"]
                    for service in ("ScreenCapture", "Accessibility")]
        self.assertEqual(self.reset_commands(), expected)
        self.assertEqual(result["attempted_commands"], expected)
        self.assertEqual(result["permissions_reset"], ["ScreenCapture", "Accessibility"])
        self.assertEqual(self.ps_count, 3)
        self.assertFalse(result["permission_granted_by_tool"])
        self.assertEqual(result["permission_status"], "unknown_not_queried")

    def test_microphone_camera_are_opt_in_and_duplicates_reset_once(self):
        result = self.run_repair(repair=True, confirm=True, services=("Microphone", "Camera", "Camera"))
        self.assertEqual(result["permissions_reset"], ["Microphone", "Camera"])
        self.assertEqual([args[2] for args in self.reset_commands()], ["Microphone", "Camera"])

    def test_partial_reset_failure_reports_successful_and_attempted_operations(self):
        self.failed_service = "Accessibility"
        error = self.error("RESET_FAILED", repair=True, confirm=True)
        self.assertEqual(error.details["service"], "Accessibility")
        self.assertEqual(error.details["permissions_reset"], ["ScreenCapture"])
        self.assertEqual(error.details["attempted_commands"], self.reset_commands())
        self.assertEqual(len(error.details["attempted_commands"]), 2)
        self.assertFalse(error.details["permission_granted_by_tool"])

    def test_app_relaunch_stops_remaining_resets_and_preserves_partial_report(self):
        self.relaunch_on_ps = 3
        error = self.error("APP_RUNNING", repair=True, confirm=True)
        self.assertEqual(error.details["permissions_reset"], ["ScreenCapture"])
        self.assertEqual(error.details["attempted_commands"], self.reset_commands())
        self.assertEqual([args[2] for args in self.reset_commands()], ["ScreenCapture"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
