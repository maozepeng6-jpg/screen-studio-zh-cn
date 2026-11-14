/* Translate native presentation only. Application behavior remains unchanged. */
'use strict';
const fs = require('fs');
const path = require('path');
const electron = require('electron');
const dictionary = JSON.parse(fs.readFileSync(path.join(__dirname, 'zh-CN.json'), 'utf8'));
const clean = value => value.replace(/\u00a0/g, ' ').replace(/…/g, '...');
const exact = new Map(Object.entries(dictionary).map(([a,b]) => [clean(a.trim()), b.trim()]));
function tr(value) {
  if (typeof value !== 'string') return value;
  if (Object.hasOwn(dictionary, value)) return dictionary[value];
  const trimmed = value.trim();
  const found = exact.get(clean(trimmed));
  if (found !== undefined) return value.replace(trimmed, found);
  return value;
}
const roles = {
  appMenu:'Screen Studio',fileMenu:'文件',editMenu:'编辑',viewMenu:'显示',windowMenu:'窗口',
  about:'关于 Screen Studio',services:'服务',hide:'隐藏 Screen Studio',hideOthers:'隐藏其他应用',
  unhide:'显示全部',quit:'退出 Screen Studio',close:'关闭窗口',minimize:'最小化',zoom:'缩放',
  undo:'撤销',redo:'重做',cut:'剪切',copy:'复制',paste:'粘贴',pasteAndMatchStyle:'粘贴并匹配样式',
  delete:'删除',selectAll:'全选',reload:'重新载入',forceReload:'强制重新载入',toggleDevTools:'开发者工具',
  resetZoom:'实际大小',zoomIn:'放大',zoomOut:'缩小',togglefullscreen:'切换全屏',front:'全部置于顶层',
  help:'帮助',recentDocuments:'最近打开',clearRecentDocuments:'清除菜单',toggleSpellChecker:'检查拼写',
  startSpeaking:'开始朗读',stopSpeaking:'停止朗读',window:'窗口'
};
function itemTranslate(item) {
  if (!item || typeof item !== 'object') return item;
  for (const key of ['label','sublabel','toolTip']) if (typeof item[key] === 'string') {
    const next = tr(item[key]);
    if (next !== item[key]) try {item[key] = next;} catch {}
  }
  if (!item.label && roles[item.role]) try {item.label = roles[item.role];} catch {}
  if (Array.isArray(item.submenu)) item.submenu.forEach(itemTranslate);
  else if (item.submenu?.items) item.submenu.items.forEach(itemTranslate);
  return item;
}
const Menu = electron.Menu;
const build = Menu.buildFromTemplate;
Menu.buildFromTemplate = function(template) {
  if (Array.isArray(template)) template.forEach(itemTranslate);
  const result = build.call(this, template);
  result.items.forEach(itemTranslate);
  return result;
};
const setAppMenu = Menu.setApplicationMenu;
Menu.setApplicationMenu = function(menu) {
  menu?.items?.forEach(itemTranslate);
  return setAppMenu.call(this, menu);
};
for (const method of ['append','insert']) {
  const original = Menu.prototype[method];
  Menu.prototype[method] = function(...args) {
    itemTranslate(args[method === 'insert' ? 1 : 0]);
    return original.apply(this, args);
  };
}
const popup = Menu.prototype.popup;
Menu.prototype.popup = function(...args) {
  this.items.forEach(itemTranslate);
  return popup.apply(this, args);
};
function dialogOptions(options) {
  if (!options || typeof options !== 'object') return options;
  const result = {...options};
  for (const key of ['title','message','detail','buttonLabel','checkboxLabel','nameFieldLabel']) if (typeof result[key] === 'string') result[key] = tr(result[key]);
  if (Array.isArray(result.buttons)) result.buttons = result.buttons.map(tr);
  if (Array.isArray(result.filters)) result.filters = result.filters.map(filter => ({...filter, name:tr(filter.name)}));
  return result;
}
for (const method of ['showOpenDialog','showOpenDialogSync','showSaveDialog','showSaveDialogSync','showMessageBox','showMessageBoxSync']) {
  const original = electron.dialog[method];
  electron.dialog[method] = function(...args) {
    const index = args.length > 1 ? 1 : 0;
    args[index] = dialogOptions(args[index]);
    return original.apply(this, args);
  };
}
const errorBox = electron.dialog.showErrorBox;
electron.dialog.showErrorBox = function(title, content) { return errorBox.call(this, tr(title), tr(content)); };
const setTitle = electron.BrowserWindow.prototype.setTitle;
const windowTitles = new Set(['Settings','Preferences','Start Recording','New Recording','Speaker Notes','Export','Exporting','Screen Studio Settings']);
const translateTitle = title => typeof title === 'string' && title.startsWith('Project - ')
  ? '项目 — ' + title.slice('Project - '.length)
  : windowTitles.has(title) ? tr(title) : title;
electron.BrowserWindow.prototype.setTitle = function(title) {return setTitle.call(this, translateTitle(title));};
electron.app.commandLine.appendSwitch('lang', 'zh-CN');
const rendererScript = 'window.__screenStudioChineseDictionary=' + JSON.stringify(dictionary) + ';\n' +
  fs.readFileSync(path.join(__dirname, 'localize-renderer.js'), 'utf8');
electron.app.on('web-contents-created', (_event, contents) => {
  contents.on('dom-ready', () => {
    if (contents.isDestroyed()) return;
    const url = contents.getURL();
    if (url === 'about:blank' || (url.startsWith('file:') && url.includes('/app.asar/'))) {
      contents.executeJavaScript(rendererScript).catch(() => {});
    }
  });
});
electron.app.on('browser-window-created', (_event, win) => {
  const localizeTitle = () => { if (!win.isDestroyed()) {const before=win.getTitle(), after=translateTitle(before);if(before!==after)win.setTitle(after);} };
  win.on('ready-to-show', localizeTitle);
  win.on('page-title-updated', () => setImmediate(localizeTitle));
});
