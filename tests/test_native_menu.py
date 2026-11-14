"""Public regression checks using synthetic inputs, never extracted app sources.

These fixtures exercise the release patcher's transformations and rejection
rules. They do not prove compatibility with any installed Screen Studio build.
Only this test process substitutes fixture fingerprints; production checks and
the distribution payload remain unchanged.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'package/ScreenStudio-ZH-4.1.0-5005'
PAYLOAD = PACKAGE / 'payload'
SPEC = importlib.util.spec_from_file_location(
    'screen_studio_release_native_patch', PACKAGE / 'patch_native_menu.py',
)
native_patch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native_patch)
IMPORT, SITES = native_patch.IMPORT, native_patch.SITES
TOOLTIP_IMPORT, TOOLTIP_SITE = native_patch.TOOLTIP_IMPORT, native_patch.TOOLTIP_SITE
patch_native_menu = native_patch.patch_native_menu
patch_native_tooltip = native_patch.patch_native_tooltip
render_native_menu_runtime = native_patch.render_native_menu_runtime

# Minimal, handwritten modules around the release patcher's public anchors.
# No bundled Screen Studio source file is needed or copied into these fixtures.
MENU_FIXTURE = (
    'export function fixtureMenu() { return [\n'
    + ',\n'.join('{' + site + '}' for site in SITES)
    + '\n]; }\n'
).encode()
TOOLTIP_FIXTURE = (
    'export function fixtureTooltip() { ' + TOOLTIP_SITE + '; }\n'
).encode()


class NativeMenuPatchTests(unittest.TestCase):
    def setUp(self):
        for name, fixture in (
            ('SOURCE_SHA256', MENU_FIXTURE),
            ('TOOLTIP_SOURCE_SHA256', TOOLTIP_FIXTURE),
        ):
            replacement = patch.object(native_patch, name, hashlib.sha256(fixture).hexdigest())
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_tooltip_patch_and_reject_modified_build(self):
        source = TOOLTIP_FIXTURE
        patched = patch_native_tooltip(source)
        self.assertTrue(patched.decode().startswith(TOOLTIP_IMPORT))
        self.assertEqual(patched.decode().count('return __ssZhNativeTooltip('), 1)
        self.assertEqual(patch_native_tooltip(patched), patched)
        with self.assertRaises(ValueError):
            patch_native_tooltip(source + b'\n')
        with self.assertRaises(ValueError):
            patch_native_tooltip(patched.replace(b'__ssZhNativeTooltip(', b'wrongName(', 1))
        result = subprocess.run(['node', '--input-type=module', '--check'], input=patched, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_supported_source_and_idempotence(self):
        source = MENU_FIXTURE
        patched = patch_native_menu(source)
        self.assertTrue(patched.decode().startswith(IMPORT))
        self.assertEqual(patched.decode().count("'items':__ssZhNativeMenuItems("), 2)
        self.assertEqual(patch_native_menu(patched), patched)
        self.assertEqual(len(SITES), 2)
        result = subprocess.run(['node', '--input-type=module', '--check'], input=patched, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_reject_modified_source(self):
        source = MENU_FIXTURE
        with self.assertRaises(ValueError):
            patch_native_menu(source + b'\n')

    def test_reject_partial_patch(self):
        source = MENU_FIXTURE
        patched = patch_native_menu(source)
        with self.assertRaises(ValueError):
            patch_native_menu(patched.replace(b'__ssZhNativeMenuItems(', b'wrongName(', 1))

    def test_menu_behavior(self):
        dictionary = json.loads((PAYLOAD / 'zh-CN.json').read_text())
        runtime = render_native_menu_runtime((PAYLOAD / 'localize-native-menu.js').read_bytes(), dictionary).decode()
        tests = r'''
import assert from 'node:assert/strict';
const labels = ['Before Recording','Countdown','Off','While Recording','Hide Desktop Icons','Hide Dock Icon','Highlight Recorded Area','Show Speaker Notes','After Recording','Open Quick Share Widget','Advanced','Recording Engine','Use Modern Engine If Available','Force Modern Engine','Force Legacy Engine','Settings…'];
const expected = ['录制前','倒计时','关闭','录制期间','隐藏桌面图标','隐藏程序坞图标','高亮录制区域','显示演讲备注','录制后','打开快速分享小窗口','高级','录制引擎','优先使用新版引擎','强制使用新版引擎','强制使用旧版引擎','设置…'];
assert.deepEqual(translateNativeMenuItems(labels.map(label=>({label}))).map(x=>x.label),expected);
assert.deepEqual(translateNativeMenuItems([{label:"Don't record microphone"},{label:"Don't record camera"}]).map(x=>x.label),['不录制麦克风','不录制摄像头']);
const fn=()=>true, userObject=Object.freeze({title:'Before Recording'});
const original=[Object.freeze({type:'segmented',key:'0.1',label:'Countdown',value:'Off',options:[Object.freeze({key:'0.1:0',label:'Off',isSelected:true,onSelect:fn}),Object.freeze({key:'0.1:1',label:'3s',isSelected:false})],action:userObject}),Object.freeze({type:'submenu',label:'Advanced',items:[Object.freeze({label:'Recording Engine',isSectionHeader:true}),Object.freeze({label:'Force Modern Engine',onClick:fn,checked:false})]}),Object.freeze({label:'Settings',fileIconPath:'/Users/test/Settings.app',key:'app',isOn:true}),Object.freeze({label:'Off',deviceId:'custom-device',value:true}),Object.freeze({label:'My Project.mp4',key:'project',fileIconPath:'/tmp/movie.mp4'}),Object.freeze({label:'任意英文 user named item',value:'Countdown'}),Object.freeze({label:'Settings',preserveText:true}),Object.freeze({label:'Off',alternate:{label:'On',key:'alt'},value:42})];
Object.freeze(original);
const output=translateNativeMenuItems(original);
assert.equal(original[0].label,'Countdown');
assert.equal(output[0].label,'倒计时');
assert.equal(output[0].value,'Off');
assert.equal(output[0].action,userObject);
assert.equal(output[0].options[0].onSelect,fn);
assert.equal(output[0].options[0].key,'0.1:0');
assert.equal(output[0].options[0].isSelected,true);
assert.equal(output[0].options[1].label,'3 秒');
assert.equal(output[1].items[1].label,'强制使用新版引擎');
assert.equal(output[1].items[1].onClick,fn);
assert.equal(output[1].items[1].checked,false);
for(let i=2;i<=6;i++) assert.equal(output[i],original[i]);
assert.equal(output[7].alternate.label,'开启');
assert.equal(output[7].alternate.key,'alt');
assert.equal(output[7].value,42);
assert.equal(translateNativeMenuItems(output),output);
assert.equal(translateNativeMenuItems(undefined),undefined);
assert.equal(translateNativeMenuItems([null])[0],null);
// Live contextMenu.update payloads use the same transformation and retain states.
const updated=translateNativeMenuItems([{label:'Hide Desktop Icons',isOn:false}]);
assert.deepEqual(updated,[{label:'隐藏桌面图标',isOn:false}]);
const anchor={x:12,y:20,width:10,height:10}, tooltip=Object.freeze({anchor,label:'Recording options',shortcut:'⌘,',placement:'top',maxWidth:300});
const localizedTooltip=translateNativeTooltip(tooltip);
assert.equal(localizedTooltip.label,'录制选项');
assert.equal(localizedTooltip.anchor,anchor);
assert.equal(localizedTooltip.shortcut,'⌘,');
assert.equal(localizedTooltip.placement,'top');
assert.equal(localizedTooltip.maxWidth,300);
assert.equal(tooltip.label,'Recording options');
assert.equal(translateNativeTooltip(localizedTooltip),localizedTooltip);
const unknownTooltip={label:'My file.mov'}, userTooltip={label:'Settings',projectPath:'/tmp/project'};
assert.equal(translateNativeTooltip(unknownTooltip),unknownTooltip);
assert.equal(translateNativeTooltip(userTooltip),userTooltip);
assert.equal(translateNativeTooltip(null),null);
assert.equal(translateNativeTooltip({label:"Can't record system audio (macOS 13.0+)"}).label,'无法录制系统音频（macOS 13.0+）');
assert.equal(translateNativeTooltip({label:"Can't cut item shorter than 0.1s"}).label,'不能将片段剪得短于 0.1s');
console.log('Native menu display and state preservation checks passed');
'''
        result = subprocess.run(['node', '--input-type=module'], input=runtime + tests, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
