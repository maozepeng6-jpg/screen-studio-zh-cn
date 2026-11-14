"""Patch the reviewed 4.1.0 (5005) custom native-menu presentation boundary.

The menu is rendered by Screen Studio's native helper, not Electron.Menu or DOM.
Only the already-serialized display payload is copied/translated; callbacks,
keys, actions, RPC names and live settings retain their original values.
"""
from __future__ import annotations

import hashlib
import json

MENU_SOURCE_PATH = "dist/D33o4ZAo2.js"
MENU_RUNTIME_PATH = "dist/screen-studio-zh-native-menu.js"
SOURCE_SHA256 = "29c1e9f37e5d9264a0d5b97ca785352e4eae1e795bb33078b940cec6dcf19540"
IMPORT = "import { translateNativeMenuItems as __ssZhNativeMenuItems } from './screen-studio-zh-native-menu.js';\n"
SITES = (
    "'items':_0x422f63[_0x2207f2(0x1ed)]",
    "'items':_0x439af9[_0x347415(0x1ed)]",
)
DICTIONARY_TOKEN = "__SCREEN_STUDIO_NATIVE_MENU_DICTIONARY__"
TOOLTIP_SOURCE_PATH = "dist/DsfCoJ1J.js"
TOOLTIP_SOURCE_SHA256 = "2558d486f78de66ea4ac3b65d55ca17e164896f9b8902f110ec12c56794be0e7"
TOOLTIP_IMPORT = "import { translateNativeTooltip as __ssZhNativeTooltip } from './screen-studio-zh-native-menu.js';\n"
TOOLTIP_SITE = (
    "return{'anchor':_0x2f4b2f,'label':_0x4b8bca[_0x10f92a(0xe5)]??_0x38692f??'',"
    "'shortcut':_0x4b8bca[_0x10f92a(0xe5)]?_0x38692f:void 0x0,"
    "'placement':F(_0x4b8bca[_0x10f92a(0xcd)]),'maxWidth':_0x4b8bca[_0x10f92a(0xc6)]??void 0x0}"
)


def _replacement(site: str) -> str:
    return "'items':__ssZhNativeMenuItems(" + site[len("'items':"):] + ")"


def patch_native_menu(source: bytes) -> bytes:
    """Return patched UTF-8 source; reject any unreviewed build or partial patch."""
    text = source.decode("utf-8")
    original = text
    if text.startswith(IMPORT):
        original = text[len(IMPORT):]
        for site in SITES:
            patched = _replacement(site)
            if original.count(patched) != 1:
                raise ValueError("Incomplete native-menu patch: " + site)
            original = original.replace(patched, site, 1)
    if hashlib.sha256(original.encode("utf-8")).hexdigest() != SOURCE_SHA256:
        raise ValueError("Unsupported native-menu source; expected Screen Studio 4.1.0 (5005)")
    for site in SITES:
        if original.count(site) != 1:
            raise ValueError("Native-menu presentation boundary was not found exactly once")
        original = original.replace(site, _replacement(site), 1)
    return (IMPORT + original).encode("utf-8")


def render_native_menu_runtime(template: bytes, dictionary: dict[str, str]) -> bytes:
    """Embed the local dictionary in the ESM runtime, with no window/DOM dependency."""
    text = template.decode("utf-8")
    if text.count(DICTIONARY_TOKEN) != 1:
        raise ValueError("Native-menu runtime must contain one dictionary placeholder")
    if not isinstance(dictionary, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in dictionary.items()
    ):
        raise ValueError("Translation dictionary must map strings to strings")
    return text.replace(
        DICTIONARY_TOKEN, json.dumps(dictionary, ensure_ascii=True, separators=(",", ":")), 1
    ).encode("utf-8")


def patch_native_tooltip(source: bytes) -> bytes:
    """Translate only the label of tooltips.show, leaving placement/shortcut intact."""
    text = source.decode("utf-8")
    replacement = "return __ssZhNativeTooltip(" + TOOLTIP_SITE[len("return"):] + ")"
    original = text
    if text.startswith(TOOLTIP_IMPORT):
        original = text[len(TOOLTIP_IMPORT):]
        if original.count(replacement) != 1:
            raise ValueError("Incomplete native-tooltip patch")
        original = original.replace(replacement, TOOLTIP_SITE, 1)
    if hashlib.sha256(original.encode("utf-8")).hexdigest() != TOOLTIP_SOURCE_SHA256:
        raise ValueError("Unsupported native-tooltip source; expected Screen Studio 4.1.0 (5005)")
    if original.count(TOOLTIP_SITE) != 1:
        raise ValueError("Native-tooltip presentation boundary was not found exactly once")
    return (TOOLTIP_IMPORT + original.replace(TOOLTIP_SITE, replacement, 1)).encode("utf-8")
