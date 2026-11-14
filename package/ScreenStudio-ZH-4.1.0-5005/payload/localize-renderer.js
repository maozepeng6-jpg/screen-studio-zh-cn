/* Local Simplified Chinese presentation layer. No network or account access. */
(() => {
  'use strict';
  if (window.__screenStudioChinese) return;
  const dictionary = window.__screenStudioChineseDictionary || {};
  const clean = value => value.replace(/\u00a0/g, ' ').replace(/…/g, '...');
  const exact = new Map(Object.entries(dictionary).map(([a, b]) => [clean(a.trim()), b.trim()]));
  const fragments = Object.entries(dictionary)
    .filter(([a]) => a.trim().length >= 12 && /\s$/.test(a))
    .sort((a, b) => b[0].length - a[0].length);
  function translate(value) {
    if (typeof value !== 'string' || !/[A-Za-z]/.test(value)) return value;
    if (Object.hasOwn(dictionary, value)) return dictionary[value];
    const trimmed = value.trim();
    const found = exact.get(clean(trimmed));
    if (found !== undefined) return value.replace(trimmed, found);
    for (const [from, to] of fragments) {
      if (value.startsWith(from)) return to + value.slice(from.length);
    }
    const patterns = [
      [/^(\d+) projects?$/, '$1 个项目'],
      [/^(\d+) files?$/, '$1 个文件'],
      [/^(\d+) items? selected$/, '已选择 $1 项'],
      [/^(\d+) devices?$/, '$1 台设备'],
      [/^(\d+) seconds?$/, '$1 秒'],
      [/^(\d+) minutes?$/, '$1 分钟'],
      [/^(\d+) hours?$/, '$1 小时'],
      [/^(\d+) days? ago$/, '$1 天前'],
      [/^(\d+) minutes? ago$/, '$1 分钟前'],
      [/^(\d+) hours? ago$/, '$1 小时前'],
      [/^Exporting(?:\.\.\.)?\s*(\d+%)$/, '正在导出 $1'],
      [/^Export (\d+) projects?$/, '导出 $1 个项目'],
      [/^Open (\d+) projects?$/, '打开 $1 个项目'],
      [/^Step (\d+) of (\d+)$/, '第 $1 步，共 $2 步'],
      [/^(\d+) of (\d+)$/, '$1 / $2'],
      [/^Last edited (.+)$/, '上次编辑：$1'],
      [/^Default - (.+)$/, '默认 — $1'],
      [/^Screen Studio (Settings|Preferences)$/, 'Screen Studio 设置'],
    ];
    for (const [pattern, replacement] of patterns) {
      if (pattern.test(trimmed)) return value.replace(trimmed, trimmed.replace(pattern, replacement));
    }
    return value;
  }
  const excluded = 'script,style,code,pre,textarea,input,[contenteditable="true"],[role="textbox"],[data-ss-preserve-text],[data-token-kind="word"],.video-timeline-transcript-words,.sc-fcaj7j-4,.sc-omzgq2-1,.sc-69p1br-0,.sc-1ycbnxr-1';
  function isUserContent(element) {
    return Boolean(element && (element.isContentEditable || element.closest(excluded)));
  }
  function translateNode(node) {
    if (node.nodeType === Node.TEXT_NODE) {
      if (node.parentElement && !isUserContent(node.parentElement)) {
        // "Spring" is a wallpaper season here, but a physics setting elsewhere.
        const wallpaperSpring = /^(Spring|弹簧)$/.test(node.data.trim()) &&
          node.parentElement.closest('.sc-u2rr9g-0');
        const next = wallpaperSpring ? node.data.replace(/Spring|弹簧/, '春日') : translate(node.data);
        if (next !== node.data) node.data = next;
      }
      return;
    }
    if (!(node instanceof Element) || node.closest('script,style,code,pre')) return;
    for (const attr of ['title', 'aria-label', 'aria-description', 'placeholder', 'data-tooltip-content']) {
      if (node.hasAttribute(attr)) {
        const previous = node.getAttribute(attr), next = translate(previous);
        if (next !== previous) node.setAttribute(attr, next);
      }
    }
    if (isUserContent(node)) return;
    for (const child of node.childNodes) translateNode(child);
  }
  const pending = new Set();
  let queued = false;
  function enqueue(node) {
    pending.add(node);
    if (queued) return;
    queued = true;
    queueMicrotask(() => {
      queued = false;
      const nodes = [...pending]; pending.clear();
      for (const item of nodes) if (item.isConnected) translateNode(item);
    });
  }
  function start() {
    document.documentElement.lang = 'zh-CN';
    if (document.body) translateNode(document.body);
    document.title = translate(document.title);
    const observer = new MutationObserver(records => {
      for (const record of records) {
        if (record.type === 'childList') for (const node of record.addedNodes) enqueue(node);
        else enqueue(record.target);
      }
    });
    observer.observe(document, {
      subtree: true, childList: true, characterData: true, attributes: true,
      attributeFilter: ['title', 'aria-label', 'aria-description', 'placeholder', 'data-tooltip-content']
    });
    const style = document.createElement('style');
    style.id = 'screen-studio-zh-fonts';
    style.textContent = 'html:lang(zh-CN) {font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", sans-serif;}';
    document.head.appendChild(style);
    window.__screenStudioChinese = Object.freeze({version: '1.0.0', translate, refresh: () => translateNode(document.body)});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();
