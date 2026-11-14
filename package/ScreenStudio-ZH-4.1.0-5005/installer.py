#!/usr/bin/env python3
"""Version-pinned, local-only Screen Studio UI localization installer.

Python 3.9+ standard library only. This module has no import-time side effects.
The payload contains localization resources, never an application distribution.
"""

import argparse
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import uuid
from patch_native_menu import patch_native_menu, patch_native_tooltip, render_native_menu_runtime, MENU_SOURCE_PATH, MENU_RUNTIME_PATH, TOOLTIP_SOURCE_PATH


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_APP = Path("/Applications/Screen Studio.app")
DEFAULT_BACKUPS = Path.home() / "Library/Application Support/ScreenStudioChinesePatch/backups"
SUPPORTED_VERSION = "4.1.0-5005"
PACKAGE_VERSION = "1.1.1"
BUNDLE_ID = "com.timpler.screenstudio"
DEVELOPER_TEAM = "SXF593CX2N"
ORIGINAL_ASAR_HASH = "3664b31486eb44652152f4ab408180b5a13f999dce9f104b90ad84dd44d15359"
PAYLOAD_FILES = {"zh-CN.json", "localize-renderer.js", "localize-main.cjs", "localize-native-menu.js"}
ASAR_RELATIVE = Path("Contents/Resources/app.asar")
INFO_RELATIVE = Path("Contents/Info.plist")
SIGNATURE_REQUIREMENT = (
    '=anchor apple generic and identifier "' + BUNDLE_ID
    + '" and certificate leaf[subject.OU] = "' + DEVELOPER_TEAM + '"'
)
CHUNK = 4 * 1024 * 1024


class PatchError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code = code
        self.details = details


def require(condition, code, message, **details):
    if not condition:
        raise PatchError(code, message, **details)


def timestamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def absolute(path):
    # abspath does not silently turn a symlink application into an accepted app.
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def path_exists(path):
    return os.path.lexists(str(path))


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def run_command(arguments, timeout=300):
    try:
        completed = subprocess.run(
            [str(value) for value in arguments], capture_output=True,
            text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PatchError("COMMAND_UNAVAILABLE", "系统命令无法完成。", command=str(arguments[0]), reason=str(error)) from error
    require(
        completed.returncode == 0, "COMMAND_FAILED", "系统命令执行失败。",
        command=str(arguments[0]), returncode=completed.returncode,
        diagnostic=completed.stderr.strip()[-4000:],
    )
    return completed.stdout.strip()


def check_environment():
    require(sys.version_info >= (3, 9), "PYTHON_VERSION", "需要 Python 3.9 或更高版本。")
    require(sys.platform == "darwin", "UNSUPPORTED_OS", "此安装器仅支持 macOS。")


def load_json(path):
    try:
        with Path(path).open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError) as error:
        raise PatchError("INVALID_JSON", "无法读取有效 JSON 文件。", path=str(path), reason=str(error)) from error


def atomic_json(path, data):
    path = Path(path)
    require(not path.is_symlink(), "SYMLINK_REJECTED", "拒绝写入符号链接状态文件。", path=str(path))
    fd, temporary = tempfile.mkstemp(prefix=".state-", suffix=".json", dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def load_package():
    manifest_path = PACKAGE_DIR / "manifest.json"
    require(manifest_path.is_file() and not manifest_path.is_symlink(), "INVALID_MANIFEST", "缺少有效的 manifest.json。")
    manifest = load_json(manifest_path)
    expected = {
        "package_version": PACKAGE_VERSION, "app_version": SUPPORTED_VERSION,
        "bundle_id": BUNDLE_ID, "developer_team": DEVELOPER_TEAM,
        "architecture": "arm64", "original_asar_sha256": ORIGINAL_ASAR_HASH,
    }
    require(isinstance(manifest, dict), "INVALID_MANIFEST", "manifest 必须是 JSON 对象。")
    for key, value in expected.items():
        require(manifest.get(key) == value, "INVALID_MANIFEST", "安装包版本或身份不受支持。", field=key, expected=value)
    hashes = manifest.get("payload_sha256")
    require(isinstance(hashes, dict) and set(hashes) == PAYLOAD_FILES, "INVALID_MANIFEST", "安装包必须仅列出四个规定的汉化资源。")
    payload = {}
    for name in sorted(PAYLOAD_FILES):
        path = PACKAGE_DIR / "payload" / name
        require(path.is_file() and not path.is_symlink(), "PAYLOAD_MISSING", "缺少汉化资源或资源为符号链接。", path=str(path))
        require(path.stat().st_size <= 16 * CHUNK, "PAYLOAD_INVALID", "汉化资源大小异常。", path=str(path))
        content = path.read_bytes()
        require(hashlib.sha256(content).hexdigest() == hashes[name], "PAYLOAD_HASH_MISMATCH", "汉化资源校验失败。", filename=name)
        payload[name] = content
    try:
        dictionary = json.loads(payload["zh-CN.json"].decode("utf-8"))
        valid = isinstance(dictionary, dict) and bool(dictionary) and all(
            isinstance(key, str) and bool(key) and isinstance(value, str) and bool(value)
            for key, value in dictionary.items()
        )
        require(valid, "PAYLOAD_INVALID", "翻译词典格式无效。")
        payload["encoded_dictionary"] = json.dumps(dictionary, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        for name in ("localize-renderer.js", "localize-main.cjs", "localize-native-menu.js"):
            payload[name].decode("utf-8")
    except (UnicodeError, ValueError) as error:
        raise PatchError("PAYLOAD_INVALID", "汉化资源不是有效 UTF-8 文本或 JSON。") from error
    return manifest, payload


def app_info(app):
    require(app.is_dir() and not app.is_symlink(), "INVALID_APP", "应用不存在、不是目录或为符号链接。", app=str(app))
    info_path = app / INFO_RELATIVE
    require(info_path.is_file() and not info_path.is_symlink(), "INVALID_APP", "应用缺少有效 Info.plist。", app=str(app))
    try:
        info = plistlib.loads(info_path.read_bytes())
    except (OSError, ValueError, plistlib.InvalidFileException) as error:
        raise PatchError("INVALID_APP", "无法读取应用信息。", app=str(app)) from error
    require(info.get("CFBundleIdentifier") == BUNDLE_ID, "WRONG_APP", "该应用不是支持的 Screen Studio。")
    for key in ("CFBundleShortVersionString", "CFBundleVersion"):
        require(info.get(key) == SUPPORTED_VERSION, "VERSION_MISMATCH", "仅支持 Screen Studio 4.1.0-5005，拒绝覆盖其他版本。", field=key, actual=info.get(key))
    require(info.get("CFBundleExecutable") == "Screen Studio", "EXECUTABLE_MISMATCH", "应用主程序名称不匹配。")
    executable = app / "Contents/MacOS/Screen Studio"
    require(executable.is_file() and not executable.is_symlink(), "INVALID_APP", "缺少有效主程序。")
    architecture = run_command(["/usr/bin/lipo", "-archs", executable], timeout=30).split()
    require(architecture == ["arm64"], "ARCHITECTURE_MISMATCH", "此汉化包仅匹配 arm64 版本。", actual=architecture)
    archive = app / ASAR_RELATIVE
    require(archive.is_file() and not archive.is_symlink(), "INVALID_APP", "缺少有效 app.asar。")
    return info


def verify_signature(app, official):
    command = ["/usr/bin/codesign", "--verify", "--deep", "--strict"]
    if official:
        command.append("--test-requirement=" + SIGNATURE_REQUIREMENT)
    run_command(command + [app], timeout=300)


def assert_closed(app):
    # Check only the selected bundle. A different /Applications instance does
    # not prevent tests or restoration of an independent copy.
    prefixes = {str(app) + "/Contents/", str(app.resolve()) + "/Contents/"}
    listing = run_command(["/bin/ps", "-axo", "pid=,command="], timeout=30)
    pids = []
    for line in listing.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit() and any(parts[1].startswith(prefix) for prefix in prefixes):
            pids.append(int(parts[0]))
    require(not pids, "APP_RUNNING", "请先保存工作并彻底退出目标 Screen Studio 及其辅助进程。", app=str(app), pids=pids)


def official_app(app):
    info = app_info(app)
    verify_signature(app, official=True)
    actual = sha256_file(app / ASAR_RELATIVE)
    require(actual == ORIGINAL_ASAR_HASH, "ORIGINAL_HASH_MISMATCH", "app.asar 与本包支持的官方版本不一致，拒绝修改。", actual=actual)
    return info


def bundle_inventory(app):
    """Hash bundle files, paths, modes and symlinks without following links."""
    digest = hashlib.sha256()
    total = 0
    count = 0

    def visit(folder, prefix=""):
        nonlocal total, count
        with os.scandir(folder) as entries:
            items = sorted(entries, key=lambda entry: entry.name)
        for entry in items:
            relative = prefix + entry.name
            meta = entry.stat(follow_symlinks=False)
            mode = stat.S_IMODE(meta.st_mode)
            if stat.S_ISLNK(meta.st_mode):
                record = ["link", relative, mode, os.readlink(entry.path)]
            elif stat.S_ISDIR(meta.st_mode):
                record = ["directory", relative, mode]
            elif stat.S_ISREG(meta.st_mode):
                record = ["file", relative, mode, meta.st_size, sha256_file(entry.path)]
                total += meta.st_size
            else:
                raise PatchError("INVALID_APP", "应用中包含不支持的特殊文件。", path=relative)
            digest.update(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
            count += 1
            if stat.S_ISDIR(meta.st_mode):
                visit(entry.path, relative + "/")

    visit(app)
    return {"sha256": digest.hexdigest(), "bytes": total, "entries": count}


def existing_parent(path):
    current = path
    while not current.exists():
        require(current != current.parent, "INVALID_PATH", "找不到目标路径的现有父目录。")
        current = current.parent
    return current


def storage_check(app, backup_root, size):
    require(app.resolve() not in (backup_root.resolve(), *backup_root.resolve().parents), "INVALID_BACKUP_PATH", "备份目录不能位于应用包内部。", path=str(backup_root))
    require(app.parent.is_dir() and os.access(app.parent, os.W_OK | os.X_OK), "WRITE_PERMISSION", "没有应用所在目录的写入权限。", path=str(app.parent))
    backup_parent = existing_parent(backup_root)
    require(backup_parent.is_dir() and os.access(backup_parent, os.W_OK | os.X_OK), "WRITE_PERMISSION", "没有备份目录的写入权限。", path=str(backup_parent))
    reserve = 128 * 1024 * 1024
    same_volume = app.parent.stat().st_dev == backup_parent.stat().st_dev
    app_required = size * (3 if same_volume else 2) + reserve
    app_free = shutil.disk_usage(app.parent).free
    require(app_free >= app_required, "DISK_SPACE", "应用磁盘空间不足以保存备份、构建和回滚副本。", required_bytes=app_required, free_bytes=app_free)
    if not same_volume:
        backup_free = shutil.disk_usage(backup_parent).free
        require(backup_free >= size + reserve, "DISK_SPACE", "备份磁盘空间不足。", required_bytes=size + reserve, free_bytes=backup_free)
    return {"required_bytes_on_app_volume": app_required, "free_bytes_on_app_volume": app_free}


def preflight(app, backup_root, manifest):
    assert_closed(app)
    official_app(app)
    inventory = bundle_inventory(app)
    storage = storage_check(app, backup_root, inventory["bytes"])
    return {
        "compatible": True, "app": str(app), "app_version": SUPPORTED_VERSION,
        "architecture": "arm64", "original_asar_sha256": ORIGINAL_ASAR_HASH,
        "original_bundle": inventory, "backup_root": str(backup_root),
        "storage": storage, "package_version": manifest["package_version"],
    }


def read_asar_header(stream):
    prefix = stream.read(16)
    require(len(prefix) == 16, "ASAR_INVALID", "ASAR 文件头不完整。")
    magic, header_size, pickle_size, json_size = struct.unpack("<4I", prefix)
    require(magic == 4 and header_size == pickle_size + 4 and 0 < json_size <= 64 * CHUNK and json_size + 4 <= pickle_size, "ASAR_INVALID", "ASAR 文件头结构不受支持。")
    raw = stream.read(json_size)
    require(len(raw) == json_size, "ASAR_INVALID", "ASAR 目录不完整。")
    try:
        tree = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise PatchError("ASAR_INVALID", "ASAR 目录不是有效 JSON。") from error
    require(isinstance(tree, dict) and isinstance(tree.get("files"), dict), "ASAR_INVALID", "ASAR 目录结构无效。")
    return tree, 8 + header_size, raw


def flatten(tree, prefix=""):
    for name, node in tree.get("files", {}).items():
        require(isinstance(name, str) and name not in ("", ".", "..") and "/" not in name and isinstance(node, dict), "ASAR_INVALID", "ASAR 目录项无效。")
        path = prefix + name
        if "files" in node:
            yield from flatten(node, path + "/")
        else:
            yield path, node


def asar_bytes(stream, base, nodes, name):
    node = nodes.get(name)
    require(node is not None and "offset" in node and not node.get("unpacked") and "link" not in node, "ASAR_INVALID", "ASAR 缺少预期的内嵌文件。", filename=name)
    offset, size = int(node["offset"]), int(node["size"])
    require(offset >= 0 and 0 <= size <= 64 * CHUNK, "ASAR_INVALID", "待补丁文件的大小或偏移异常。", filename=name)
    stream.seek(base + offset)
    content = stream.read(size)
    require(len(content) == size, "ASAR_INVALID", "ASAR 文件内容不完整。", filename=name)
    return content


def make_changes(source, base, nodes, payload):
    html = asar_bytes(source, base, nodes, "dist/index.html").decode("utf-8")
    main = asar_bytes(source, base, nodes, "dist-electron/index.js")
    require(html.count('<html lang="en">') == 1 and html.count("<script></script>") == 1, "PATCH_ANCHOR_MISMATCH", "HTML 注入位置不符合已验证版本。")
    require(b'localize-main.cjs' not in main, "ALREADY_PATCHED", "目标应用已经包含汉化入口。")
    html = html.replace('<html lang="en">', '<html lang="zh-CN">').replace(
        "<script></script>", '<script src="./zh-CN.js"></script>\n    <script src="./localize-renderer.js"></script>',
    )
    dictionary = payload["encoded_dictionary"]
    try:
        menu = patch_native_menu(asar_bytes(source, base, nodes, MENU_SOURCE_PATH))
        tooltip = patch_native_tooltip(asar_bytes(source, base, nodes, TOOLTIP_SOURCE_PATH))
        menu_runtime = render_native_menu_runtime(payload["localize-native-menu.js"], json.loads(dictionary))
    except (UnicodeError, ValueError) as error:
        raise PatchError("PATCH_ANCHOR_MISMATCH", "原生菜单模块不匹配已验证版本，拒绝修改。") from error
    return {
        MENU_SOURCE_PATH: menu,
        TOOLTIP_SOURCE_PATH: tooltip,
        MENU_RUNTIME_PATH: menu_runtime,
        "dist/index.html": html.encode("utf-8"),
        "dist/zh-CN.js": b"window.__screenStudioChineseDictionary=" + dictionary + b";\n",
        "dist/localize-renderer.js": payload["localize-renderer.js"],
        "dist-electron/index.js": b'require("./localize-main.cjs");\n' + main,
        "dist-electron/localize-main.cjs": payload["localize-main.cjs"],
        "dist-electron/localize-renderer.js": payload["localize-renderer.js"],
        "dist-electron/zh-CN.json": dictionary,
    }


def content_integrity(content):
    return {
        "algorithm": "SHA256", "hash": hashlib.sha256(content).hexdigest(),
        "blockSize": CHUNK,
        "blocks": [hashlib.sha256(content[index:index + CHUNK]).hexdigest() for index in range(0, len(content), CHUNK)],
    }


def build_asar(original, destination, payload):
    """Repack only the customer's archive; destination=None computes expected hashes."""
    output = None
    digest = hashlib.sha256()
    total = 0

    def emit(content):
        nonlocal total
        digest.update(content)
        total += len(content)
        if output is not None:
            output.write(content)

    try:
        with original.open("rb") as source:
            header, base, _ = read_asar_header(source)
            old_nodes = {name: copy.deepcopy(node) for name, node in flatten(header)}
            changes = make_changes(source, base, old_nodes, payload)
            for path, content in changes.items():
                branch = header
                parts = path.split("/")
                for part in parts[:-1]:
                    branch = branch.setdefault("files", {}).setdefault(part, {"files": {}})
                node = branch.setdefault("files", {}).setdefault(parts[-1], {})
                require(not node.get("unpacked") and "link" not in node, "ASAR_INVALID", "补丁目标不能是外置文件或链接。", filename=path)
                node.update(size=len(content), integrity=content_integrity(content))
            current_nodes = dict(flatten(header))
            packed = [(name, node) for name, node in old_nodes.items() if "offset" in node and not node.get("unpacked")]
            packed.sort(key=lambda pair: int(pair[1]["offset"]))
            order = [name for name, _ in packed] + [name for name in changes if name not in old_nodes]
            offset = 0
            for name in order:
                node = current_nodes[name]
                node["offset"] = str(offset)
                offset += int(node["size"])
            raw = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            pickle_payload = struct.pack("<I", len(raw)) + raw
            pickle_payload += b"\0" * ((-len(pickle_payload)) % 4)
            header_pickle = struct.pack("<I", len(pickle_payload)) + pickle_payload
            if destination is not None:
                output = destination.open("xb")
            emit(struct.pack("<II", 4, len(header_pickle)) + header_pickle)
            for name in order:
                if name in changes:
                    emit(changes[name])
                else:
                    node = old_nodes[name]
                    source.seek(base + int(node["offset"]))
                    remaining = int(node["size"])
                    while remaining:
                        content = source.read(min(remaining, CHUNK))
                        require(bool(content), "ASAR_INVALID", "原始 ASAR 意外结束。", filename=name)
                        emit(content)
                        remaining -= len(content)
            if output is not None:
                output.flush()
                os.fsync(output.fileno())
    finally:
        if output is not None:
            output.close()
    return {"sha256": digest.hexdigest(), "header_sha256": hashlib.sha256(raw).hexdigest(), "bytes": total, "changed_files": list(changes)}


def update_localization_metadata(app, header_hash):
    path = app / INFO_RELATIVE
    info = plistlib.loads(path.read_bytes())
    entry = info.get("ElectronAsarIntegrity", {}).get("Resources/app.asar")
    require(isinstance(entry, dict) and entry.get("algorithm") == "SHA256", "INTEGRITY_METADATA", "应用不含预期的 Electron ASAR 完整性元数据。")
    entry["hash"] = header_hash
    info["CFBundleLocalizations"] = ["zh-Hans", "en", "en_GB"]
    info["CFBundleDevelopmentRegion"] = "zh_CN"
    path.write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY))
    locale_dir = app / "Contents/Resources/zh-Hans.lproj"
    require(not locale_dir.is_symlink(), "SYMLINK_REJECTED", "语言资源目录不能是符号链接。")
    locale_dir.mkdir(exist_ok=True)
    descriptions = {
        "NSCameraUsageDescription": "Screen Studio 需要使用摄像头来录制摄像头画面。",
        "NSMicrophoneUsageDescription": "Screen Studio 需要使用麦克风来录制声音。",
        "NSScreenCaptureUsageDescription": "Screen Studio 需要屏幕录制权限来录制屏幕内容。",
        "NSAudioCaptureUsageDescription": "Screen Studio 需要录制系统音频。",
    }
    (locale_dir / "InfoPlist.strings").write_text(
        "\n".join(json.dumps(key) + " = " + json.dumps(value, ensure_ascii=False) + ";" for key, value in descriptions.items()) + "\n", encoding="utf-8",
    )


def verify_patched(app, expected, original, payload):
    info = app_info(app)
    actual = sha256_file(app / ASAR_RELATIVE)
    require(actual == expected["sha256"], "INSTALLED_HASH_MISMATCH", "当前应用不匹配本包从官方原版重建的汉化内容。", actual=actual, expected=expected["sha256"])
    with original.open("rb") as source:
        original_header, original_base, _ = read_asar_header(source)
        changes = make_changes(source, original_base, dict(flatten(original_header)), payload)
    with (app / ASAR_RELATIVE).open("rb") as stream:
        tree, base, raw = read_asar_header(stream)
        nodes = dict(flatten(tree))
        require(hashlib.sha256(raw).hexdigest() == expected["header_sha256"], "ASAR_INVALID", "汉化 ASAR 目录校验失败。")
        for name, content in changes.items():
            require(asar_bytes(stream, base, nodes, name) == content, "ASAR_INVALID", "汉化资源内容不匹配。", filename=name)
    entry = info.get("ElectronAsarIntegrity", {}).get("Resources/app.asar", {})
    require(entry.get("algorithm") == "SHA256" and entry.get("hash") == expected["header_sha256"], "INTEGRITY_METADATA", "Electron ASAR 完整性元数据不匹配。")
    require(info.get("CFBundleLocalizations") == ["zh-Hans", "en", "en_GB"] and info.get("CFBundleDevelopmentRegion") == "zh_CN", "LOCALE_METADATA", "汉化语言元数据不匹配。")
    verify_signature(app, official=False)


def ditto(source, destination):
    require(not path_exists(destination), "PATH_EXISTS", "复制目标已存在，拒绝覆盖。", path=str(destination))
    run_command(["/usr/bin/ditto", "--rsrc", "--extattr", "--acl", source, destination], timeout=1800)


def save_failure(state_path, state, error, rollback):
    state.update(phase="failed", failed_at=timestamp(), failure=str(error), rollback=rollback)
    try:
        atomic_json(state_path, state)
    except Exception:
        # Never lose the original failure or remove a surviving backup if the
        # disk is full or the state file cannot be updated.
        pass


def swap_bundles(app, staged, stage_dir, verify_new, commit):
    previous = stage_dir / "previous.app"
    failed = stage_dir / "uncommitted.app"
    move_started = False
    install_attempted = False
    try:
        assert_closed(app)
        if path_exists(app):
            require(not app.is_symlink(), "SYMLINK_REJECTED", "目标应用不能是符号链接。")
            require(not path_exists(previous), "PATH_EXISTS", "回滚副本路径已存在。")
            move_started = True
            app.rename(previous)
        require(not path_exists(app), "PATH_EXISTS", "目标路径出现新文件，拒绝覆盖。")
        install_attempted = True
        staged.rename(app)
        verify_new()
        commit(previous if move_started else None)
        return previous if move_started else None
    except BaseException as error:
        rollback = {"restored_previous_app": False, "previous_app": str(previous), "staging_dir": str(stage_dir)}
        try:
            # An early failure (for example a running app or a failed rename)
            # must never move the still-original target out of the way.
            installed_here = install_attempted and not path_exists(staged)
            if installed_here and path_exists(app):
                assert_closed(app)
                require(not path_exists(failed), "PATH_EXISTS", "回滚暂存路径已存在。")
                app.rename(failed)
            if move_started and previous.exists():
                require(not path_exists(app), "ROLLBACK_BLOCKED", "目标路径被占用；原应用保留在回滚目录。")
                previous.rename(app)
                rollback["restored_previous_app"] = True
            elif not move_started and installed_here:
                rollback["returned_to_missing_app"] = True
            else:
                rollback["original_app_untouched"] = True
        except BaseException as rollback_error:
            rollback["error"] = str(rollback_error)
        raise PatchError("SWAP_FAILED", "应用替换未完成；副本均保留，请检查回滚结果。", reason=str(error), rollback=rollback) from error


def install(app, backup_root, manifest, payload, accepted):
    require(accepted, "SIGNATURE_CONSENT_REQUIRED", "安装会将应用外层签名改为本机临时签名；确认后请使用 --accept-signature-change。")
    report = preflight(app, backup_root, manifest)
    original_inventory = report["original_bundle"]
    backup_root.mkdir(parents=True, exist_ok=True)
    state_dir = backup_root / str(uuid.uuid4())
    state_dir.mkdir(mode=0o700)
    state_path = state_dir / "state.json"
    backup = state_dir / "original.app"
    state = {
        "schema": 1, "phase": "backing_up", "created_at": timestamp(),
        "app_path": str(app), "app_version": SUPPORTED_VERSION,
        "package_version": manifest["package_version"],
        "original_asar_sha256": ORIGINAL_ASAR_HASH,
        "original_bundle_sha256": original_inventory["sha256"],
        "backup_app": str(backup), "state_path": str(state_path),
    }
    atomic_json(state_dir / "manifest.json", manifest)
    atomic_json(state_path, state)
    stage_dir = None
    try:
        ditto(app, backup)
        official_app(backup)
        require(bundle_inventory(backup)["sha256"] == original_inventory["sha256"], "BACKUP_MISMATCH", "完整备份与安装前应用不一致，拒绝替换。")
        stage_dir = Path(tempfile.mkdtemp(prefix=".screenstudio-zh-", dir=str(app.parent)))
        state.update(phase="building", staging_dir=str(stage_dir))
        atomic_json(state_path, state)
        staged = stage_dir / "localized.app"
        ditto(backup, staged)
        archive = staged / ASAR_RELATIVE
        temporary_asar = archive.with_name("app.asar.zh-new")
        expected = build_asar(backup / ASAR_RELATIVE, temporary_asar, payload)
        require(sha256_file(temporary_asar) == expected["sha256"], "ASAR_INVALID", "写入后的汉化 ASAR 校验失败。")
        os.replace(temporary_asar, archive)
        update_localization_metadata(staged, expected["header_sha256"])
        run_command(["/usr/bin/codesign", "--force", "--sign", "-", "--preserve-metadata=entitlements,flags", staged], timeout=300)
        verify_patched(staged, expected, backup / ASAR_RELATIVE, payload)
        installed_inventory = bundle_inventory(staged)
        assert_closed(app)
        require(bundle_inventory(app)["sha256"] == original_inventory["sha256"], "APP_CHANGED", "备份期间目标应用发生变化，拒绝替换。")
        state.update(phase="prepared", installed_asar_sha256=expected["sha256"], installed_bundle_sha256=installed_inventory["sha256"], asar_header_sha256=expected["header_sha256"], changed_files=expected["changed_files"])
        atomic_json(state_path, state)

        def verify_new():
            verify_patched(app, expected, backup / ASAR_RELATIVE, payload)
            require(bundle_inventory(app)["sha256"] == installed_inventory["sha256"], "INSTALLED_HASH_MISMATCH", "替换后的完整应用校验失败。")

        def commit(previous):
            state.update(phase="installed", installed_at=timestamp(), retained_previous_app=str(previous) if previous else None)
            atomic_json(state_path, state)

        previous = swap_bundles(app, staged, stage_dir, verify_new, commit)
        return {
            "compatible": True, "status": "installed", "app": str(app), "state": str(state_path),
            "backup": str(backup), "retained_previous_app": str(previous) if previous else None,
            "signature": "ad-hoc", "asar_sha256": expected["sha256"], "app_started": False,
            "message": "汉化文件已安装，应用签名已变为本机临时签名。旧权限即使显示开启也可能失效；请本人重新授权并实际测试录屏。安装器未重置或授予权限。",
            "permissions": {
                "status": "not_verified", "reset_by_installer": False,
                "check_command": ["python3", str(PACKAGE_DIR / "repair_permissions.py"), "--check", "--app", str(app)],
                "repair_requires_explicit_confirmation": True,
                "instructions": [
                    "可先运行上方只读检查，或双击包内“检查与修复权限.command”；默认不修改权限。",
                    "只有出现权限故障且用户同意时，才使用 --repair --confirm 定向撤销旧授权；请阅读先读我.md。",
                    "macOS Touch ID/密码和新授权由用户本人完成。进入开始录制界面不代表真实录屏通过，还需录制、停止、预览与导出。",
                ],
            },
        }
    except BaseException as error:
        details = error.details if isinstance(error, PatchError) else {}
        save_failure(state_path, state, error, details.get("rollback"))
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise PatchError("INTERRUPTED", "操作已中断，备份和暂存文件已保留。", state=str(state_path), staging_dir=str(stage_dir) if stage_dir else None) from error
        if isinstance(error, PatchError):
            error.details.update(state=str(state_path), backup=str(backup))
            raise
        raise PatchError("INSTALL_FAILED", "安装失败；未删除备份或暂存文件。", reason=str(error), state=str(state_path), backup=str(backup)) from error


def resolve_state(app, state_option, backup_option):
    if state_option:
        path = absolute(state_option)
        if path.is_dir():
            path = path / "state.json"
    else:
        root = absolute(backup_option) if backup_option else DEFAULT_BACKUPS
        if (root / "state.json").is_file():
            path = root / "state.json"
        else:
            matches = []
            for candidate in root.glob("*/state.json"):
                try:
                    record = load_json(candidate)
                    if record.get("app_path") == str(app) and record.get("phase") in ("installed", "restored"):
                        matches.append(candidate)
                except (PatchError, AttributeError):
                    continue
            require(len(matches) == 1, "STATE_REQUIRED", "请用 --state 指定本次安装的 state.json 或备份目录；未找到唯一匹配记录。", candidates=[str(item) for item in matches])
            path = matches[0]
    require(path.is_file() and not path.is_symlink() and not path.parent.is_symlink(), "INVALID_STATE", "状态文件不存在或为符号链接。", state=str(path))
    state = load_json(path)
    require(isinstance(state, dict) and state.get("schema") == 1, "INVALID_STATE", "状态文件结构不受支持。")
    require(state.get("app_path") == str(app), "STATE_APP_MISMATCH", "状态记录不属于指定应用路径；请传入正确 --app。", recorded_app=state.get("app_path"))
    require(state.get("app_version") == SUPPORTED_VERSION and state.get("package_version") == PACKAGE_VERSION and state.get("original_asar_sha256") == ORIGINAL_ASAR_HASH, "INVALID_STATE", "状态记录不属于本版本汉化包。")
    backup = path.parent / "original.app"
    require(state.get("backup_app") == str(backup), "INVALID_STATE", "状态中的备份路径与所在目录不一致。")
    return path, state, backup


def verified_backup(state, backup):
    # The immutable manifest/version and Apple's developer signature are the
    # authority; editable state values never make a newer/unknown app eligible.
    official_app(backup)
    inventory = bundle_inventory(backup)
    require(inventory["sha256"] == state.get("original_bundle_sha256"), "BACKUP_MISMATCH", "完整原版备份校验失败。")
    return inventory


def verify_installed_state(app, state, backup, payload):
    expected = build_asar(backup / ASAR_RELATIVE, None, payload)
    require(state.get("installed_asar_sha256") == expected["sha256"], "INVALID_STATE", "安装记录与本包实际生成的 ASAR 不匹配。")
    verify_patched(app, expected, backup / ASAR_RELATIVE, payload)
    inventory = bundle_inventory(app)
    require(inventory["sha256"] == state.get("installed_bundle_sha256"), "APP_CHANGED", "当前应用已更新或发生变化，拒绝用旧版备份覆盖。")
    return expected, inventory


def verify(app, state_path, state, backup, payload):
    inventory = verified_backup(state, backup)
    if state.get("phase") == "restored":
        official_app(app)
        require(bundle_inventory(app)["sha256"] == inventory["sha256"], "APP_CHANGED", "已恢复的应用与原版备份不一致。")
        status = "original_verified"
    else:
        verify_installed_state(app, state, backup, payload)
        status = "localized_verified"
    return {"compatible": True, "status": status, "app": str(app), "state": str(state_path), "backup": str(backup)}


def restore(app, state_path, state, backup, payload):
    assert_closed(app)
    original_inventory = verified_backup(state, backup)
    if state.get("phase") == "restored" and path_exists(app):
        result = verify(app, state_path, state, backup, payload)
        result["status"] = "already_restored"
        return result
    current_inventory = None
    if path_exists(app):
        # A rollback, or a shutdown after restoring the bundle but before the
        # receipt commit, can leave an exact original with an older state.
        # Reconcile only that authenticated original; never replace or bless
        # a different version, altered bundle, or merely matching ASAR.
        app_info(app)
        if sha256_file(app / ASAR_RELATIVE) == ORIGINAL_ASAR_HASH:
            official_app(app)
            require(bundle_inventory(app)["sha256"] == original_inventory["sha256"],
                    "APP_CHANGED", "当前原版应用与已验证备份不一致，拒绝修改恢复记录。")
            reconciled = copy.deepcopy(state)
            reconciled.update(phase="restored", restore_phase="complete", reconciled_at=timestamp())
            atomic_json(state_path, reconciled)
            state.clear()
            state.update(reconciled)
            return {"compatible": True, "status": "already_restored", "app": str(app),
                    "state": str(state_path), "backup": str(backup), "signature": "official",
                    "state_reconciled": True, "app_started": False}
        _, current_inventory = verify_installed_state(app, state, backup, payload)
    storage_check(app, state_path.parent, original_inventory["bytes"])
    saved_current = None
    stage_dir = None
    old_state = copy.deepcopy(state)
    try:
        # Preserve the current localized bundle in the state directory even if
        # the backup root is on a different volume.
        if current_inventory is not None:
            saved_current = state_path.parent / ("before-restore-" + str(uuid.uuid4()) + ".app")
            ditto(app, saved_current)
            require(bundle_inventory(saved_current)["sha256"] == current_inventory["sha256"], "BACKUP_MISMATCH", "当前应用的恢复前备份不完整。")
        stage_dir = Path(tempfile.mkdtemp(prefix=".screenstudio-restore-", dir=str(app.parent)))
        staged = stage_dir / "original.app"
        ditto(backup, staged)
        official_app(staged)
        require(bundle_inventory(staged)["sha256"] == original_inventory["sha256"], "BACKUP_MISMATCH", "原版临时副本校验失败。")
        assert_closed(app)
        if current_inventory is not None:
            require(path_exists(app) and bundle_inventory(app)["sha256"] == current_inventory["sha256"], "APP_CHANGED", "恢复准备期间当前应用发生变化，拒绝覆盖。")
        else:
            require(not path_exists(app), "APP_CHANGED", "恢复准备期间目标路径出现应用，拒绝覆盖。")
        state.update(restore_phase="prepared", restore_staging_dir=str(stage_dir), saved_before_restore=str(saved_current) if saved_current else None)
        atomic_json(state_path, state)

        def verify_new():
            official_app(app)
            require(bundle_inventory(app)["sha256"] == original_inventory["sha256"], "RESTORE_HASH_MISMATCH", "恢复后的完整原版校验失败。")

        def commit(previous):
            state.update(phase="restored", restore_phase="complete", restored_at=timestamp(), restore_retained_previous_app=str(previous) if previous else None)
            atomic_json(state_path, state)

        previous = swap_bundles(app, staged, stage_dir, verify_new, commit)
        return {"compatible": True, "status": "restored", "app": str(app), "state": str(state_path), "original_backup": str(backup), "saved_before_restore": str(saved_current) if saved_current else None, "retained_previous_app": str(previous) if previous else None, "signature": "official", "app_started": False}
    except BaseException as error:
        details = error.details if isinstance(error, PatchError) else {}
        old_state.update(restore_phase="failed", restore_failure=str(error), restore_rollback=details.get("rollback"), restore_staging_dir=str(stage_dir) if stage_dir else None, saved_before_restore=str(saved_current) if saved_current else None)
        try:
            atomic_json(state_path, old_state)
        except Exception:
            pass
        if isinstance(error, PatchError):
            error.details.update(state=str(state_path), backup=str(backup), saved_before_restore=str(saved_current) if saved_current else None)
            raise
        raise PatchError("RESTORE_FAILED", "恢复未完成；所有副本保留，请检查状态文件。", reason=str(error), state=str(state_path), staging_dir=str(stage_dir) if stage_dir else None) from error


class JsonParser(argparse.ArgumentParser):
    def error(self, message):
        raise PatchError("INVALID_ARGUMENTS", "命令参数无效。", reason=message)


def parse_args(argv):
    parser = JsonParser(add_help=False)
    parser.add_argument("command", choices=("preflight", "install", "verify", "restore"), nargs="?")
    parser.add_argument("--app", default=str(DEFAULT_APP))
    parser.add_argument("--backup-dir")
    parser.add_argument("--state")
    parser.add_argument("--accept-signature-change", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    require(args.command is not None or args.help, "INVALID_ARGUMENTS", "请指定 preflight、install、verify 或 restore。")
    require(not (args.state and args.backup_dir), "INVALID_ARGUMENTS", "--state 和 --backup-dir 请只指定一个。")
    require(not (args.state and args.command in ("preflight", "install")), "INVALID_ARGUMENTS", "安装前检查与安装请用 --backup-dir；--state 仅用于校验和恢复。")
    return args


def signal_interrupted(signum, _frame):
    raise PatchError("INTERRUPTED", "操作被系统信号中断。", signal=signum)


def main(argv=None):
    command = None
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        command = args.command
        if args.help:
            result = {
                "ok": True, "commands": ["preflight", "install", "verify", "restore"],
                "usage": "python3 installer.py COMMAND [--app PATH] [--backup-dir PATH | --state PATH] [--accept-signature-change]",
                "notes": ["install 必须显式传入 --accept-signature-change。", "verify/restore 的 --state 可为 state.json 或所在目录。", "仅修改匹配版本的应用副本，不联网、不启动应用、不修改项目或系统安全设置。", "安装后签名改变可能需要本人重新授权；repair_permissions.py --check 只读检查，修复须显式 --repair --confirm。安装器不自动重置权限。"],
            }
        else:
            check_environment()
            for number in (signal.SIGTERM, signal.SIGHUP):
                signal.signal(number, signal_interrupted)
            manifest, payload = load_package()
            app = absolute(args.app)
            backup_root = absolute(args.backup_dir) if args.backup_dir else DEFAULT_BACKUPS
            if command == "preflight":
                data = preflight(app, backup_root, manifest)
            elif command == "install":
                data = install(app, backup_root, manifest, payload, args.accept_signature_change)
            else:
                state_path, state, backup = resolve_state(app, args.state, args.backup_dir)
                data = verify(app, state_path, state, backup, payload) if command == "verify" else restore(app, state_path, state, backup, payload)
            result = {"ok": True, "command": command, **data}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except BaseException as error:
        if isinstance(error, PatchError):
            code, details = error.code, error.details
        elif isinstance(error, KeyboardInterrupt):
            code, details = "INTERRUPTED", {}
        else:
            code, details = "UNEXPECTED_ERROR", {"type": type(error).__name__}
        print(json.dumps({"ok": False, "command": command, "compatible": False, "error": {"code": code, "message": str(error) or "操作已中断。", **details}}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
