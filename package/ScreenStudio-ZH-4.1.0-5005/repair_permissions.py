#!/usr/bin/env python3
"""Check a local Screen Studio app; optionally reset only explicitly selected grants.

No import-time effects, network, TCC database access, permission granting, or app changes.
Python 3.9+ and macOS system tools only.
"""

import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys


BUNDLE_ID = "com.timpler.screenstudio"
SUPPORTED_VERSION = "4.1.0-5005"
DEFAULT_APP = Path("/Applications/Screen Studio.app")
CORE_SERVICES = ("ScreenCapture", "Accessibility")
ALLOWED_SERVICES = CORE_SERVICES + ("Microphone", "Camera")
SERVICE_LABELS = {"ScreenCapture": "屏幕录制", "Accessibility": "辅助功能", "Microphone": "麦克风", "Camera": "摄像头"}


class PermissionRepairError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code = code
        self.details = details


def require(condition, code, message, **details):
    if not condition:
        raise PermissionRepairError(code, message, **details)


def run_command(arguments, timeout=30):
    try:
        return subprocess.run([str(x) for x in arguments], capture_output=True, text=True,
                              timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PermissionRepairError("COMMAND_UNAVAILABLE", "系统命令无法完成；未绕过系统限制。",
                                    command=str(arguments[0]), reason=str(error)) from error


def selected_services(services):
    require(isinstance(services, (list, tuple)) and bool(services), "INVALID_SERVICE", "至少指定一项白名单服务。")
    require(all(isinstance(item, str) and item in ALLOWED_SERVICES for item in services),
            "INVALID_SERVICE", "只允许 ScreenCapture、Accessibility、Microphone、Camera；禁止 All 或自定义服务。")
    return list(dict.fromkeys(services))


def inspect_app(app):
    app = Path(os.path.abspath(os.path.expanduser(str(app))))
    require(app.is_dir() and not app.is_symlink(), "INVALID_APP", "目标应用不存在或是符号链接。", app=str(app))
    info_path = app / "Contents/Info.plist"
    require(info_path.is_file() and not info_path.is_symlink(), "INVALID_APP", "找不到有效应用信息。")
    try:
        info = plistlib.loads(info_path.read_bytes())
    except (OSError, ValueError, plistlib.InvalidFileException) as error:
        raise PermissionRepairError("INVALID_APP", "无法读取应用信息。") from error
    require(isinstance(info, dict) and info.get("CFBundleIdentifier") == BUNDLE_ID,
            "WRONG_APP", "只允许处理 com.timpler.screenstudio 的权限。")
    require(info.get("CFBundleShortVersionString") == SUPPORTED_VERSION
            and info.get("CFBundleVersion") == SUPPORTED_VERSION,
            "VERSION_MISMATCH", "本包仅验证了 Screen Studio 4.1.0-5005；其他版本请单独诊断。")
    require(info.get("CFBundleExecutable") == "Screen Studio", "INVALID_APP", "应用主程序不匹配。")
    executable = app / "Contents/MacOS/Screen Studio"
    require(executable.is_file() and not executable.is_symlink(), "INVALID_APP", "应用缺少有效主程序。")
    return app


def running_pids(app, runner):
    result = runner(["/bin/ps", "-axo", "pid=,command="], timeout=30)
    require(result.returncode == 0, "PROCESS_CHECK_FAILED", "无法确认应用是否退出，拒绝自动继续。")
    prefixes = {str(app) + "/Contents/", str(app.resolve()) + "/Contents/"}
    pids = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit() and any(parts[1].startswith(prefix) for prefix in prefixes):
            pids.append(int(parts[0]))
    return pids


def instructions(app, services):
    labels = "、".join(SERVICE_LABELS[item] for item in services)
    return [
        "签名变更后，系统设置中已开启的旧授权也可能不匹配当前应用；这是可能原因，本工具没有读取或判定你的实际 TCC 授权。",
        "重置仅撤销所选旧授权，不会自动授予权限，也不保证解决所有权限故障。",
        f"在系统设置 → 隐私与安全性中检查{labels}。屏幕录制/辅助功能可重新添加实际应用：{app}。",
        "麦克风/摄像头需重新打开应用并使用对应功能触发系统请求；只在本人需要使用时授权，勿与修复核心权限捆绑。",
        "Touch ID 或密码验证请本人在 macOS 系统界面完成；不要把密码交给 Agent 或补丁作者。按系统提示退出并重新打开应用。",
        "进入“开始录制”只代表权限引导通过。另用无隐私画面完成短录屏、停止、预览和本地导出；声音与摄像头需分别验证。",
        "失败或遇到企业管理/系统安全策略限制时停止，保留诊断并按安装回执恢复原版；不要全局重置或关闭系统保护。",
    ]


def run_repair(*, repair=False, confirm=False, services=CORE_SERVICES, app=DEFAULT_APP,
               runner=None, platform=None):
    runner = runner or run_command
    platform = sys.platform if platform is None else platform
    services = selected_services(services)
    require(platform == "darwin", "UNSUPPORTED_OS", "此工具仅支持 macOS。")
    require(sys.version_info >= (3, 9), "PYTHON_VERSION", "需要 Python 3.9 或更新版本。")
    require(not repair or confirm, "CONFIRMATION_REQUIRED",
            "修复会撤销所选旧授权。说明后经用户同意，请同时使用 --repair --confirm；默认只检查。")
    require(repair or not confirm, "INVALID_OPTIONS", "--confirm 只能与 --repair 一起使用。")
    app = inspect_app(app)
    signature = runner(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], timeout=120)
    identity = runner(["/usr/bin/codesign", "--display", "--verbose=4", str(app)], timeout=30)
    identity_text = (identity.stdout or "") + "\n" + (identity.stderr or "")
    kind = "ad-hoc" if "Signature=adhoc" in identity_text else "developer-id" if "Authority=Developer ID Application:" in identity_text else "unknown"
    team = next((line.split("=", 1)[1] for line in identity_text.splitlines() if line.startswith("TeamIdentifier=")), None)
    pids = running_pids(app, runner)
    commands = [["/usr/bin/tccutil", "reset", service, BUNDLE_ID] for service in services]
    result = {
        "ok": True, "mode": "repair" if repair else "check", "app": str(app),
        "bundle_id": BUNDLE_ID, "app_version": SUPPORTED_VERSION,
        "signature": {"valid": signature.returncode == 0, "kind": kind, "team": team},
        "running_pids": pids, "services": services,
        "permission_status": "unknown_not_queried", "permission_granted_by_tool": False,
        "planned_commands": commands, "attempted_commands": [], "permissions_reset": [],
        "instructions": instructions(app, services),
        "message": "只读检查完成，未重置任何权限；签名校验通过不等于已获录屏授权。",
    }
    if not repair:
        return result
    require(signature.returncode == 0 and identity.returncode == 0, "SIGNATURE_INVALID",
            "应用签名检查未通过，先核对安装或恢复原版，不重置权限。")
    require(not pids, "APP_RUNNING", "请先保存工作并彻底退出目标应用及其辅助进程，再运行修复。", pids=pids)
    # Re-check immediately before each reset. Never close the app or change permissions silently.
    for service, command in zip(services, commands):
        try:
            require(not running_pids(app, runner), "APP_RUNNING", "应用重新运行，已停止后续重置；请保存并退出后再处理。")
            result["attempted_commands"].append(command)
            reset = runner(command, timeout=30)
            require(reset.returncode == 0, "RESET_FAILED", "系统拒绝权限重置；请停止并检查，不绕过系统限制。",
                    service=service, returncode=reset.returncode)
        except PermissionRepairError as error:
            error.details.update(permissions_reset=list(result["permissions_reset"]),
                                 attempted_commands=list(result["attempted_commands"]),
                                 permission_granted_by_tool=False,
                                 instructions=result["instructions"])
            raise
        result["permissions_reset"].append(service)
    result["message"] = "所选旧授权已撤销；尚未获得新授权。请本人在系统设置重新授权，再退出并重新打开应用及验证录屏。"
    return result


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise PermissionRepairError("INVALID_OPTIONS", "参数无效：" + message)


def main(argv=None):
    parser = JsonArgumentParser(description="Screen Studio 权限检查与定向重置。默认只读；不会授予权限或操作系统确认框。")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="只读检查（默认），显示计划，不执行 tccutil")
    mode.add_argument("--dry-run", action="store_true", help="等同 --check，不修改权限")
    mode.add_argument("--repair", action="store_true", help="撤销明确选择的旧授权，必须同时 --confirm")
    parser.add_argument("--confirm", action="store_true", help="表示用户已知晓并同意本次定向重置，仍需本人重新授权")
    parser.add_argument("--services", nargs="+", choices=ALLOWED_SERVICES, default=list(CORE_SERVICES),
                        help="默认 ScreenCapture Accessibility；麦克风/摄像头只在相应问题出现且用户需要时显式选择")
    parser.add_argument("--app", default=str(DEFAULT_APP), help="目标应用路径；bundle ID 固定，不可覆盖")
    try:
        args = parser.parse_args(argv)
        result = run_repair(repair=args.repair, confirm=args.confirm, services=args.services, app=args.app)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except PermissionRepairError as error:
        print(json.dumps({"ok": False, "error": {"code": error.code, "message": str(error), **error.details}}, ensure_ascii=False, indent=2))
        return 1
    except KeyboardInterrupt:
        print(json.dumps({"ok": False, "error": {"code": "INTERRUPTED", "message": "已停止。若此前已撤销部分权限，请在系统设置中重新授权。"}}, ensure_ascii=False, indent=2))
        return 130
    except Exception as error:
        print(json.dumps({"ok": False, "error": {"code": "UNEXPECTED_ERROR", "message": "检查或修复未完成，请停止并保留错误类型。若已撤销部分权限，需本人在系统设置重新授权。", "type": type(error).__name__}}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
