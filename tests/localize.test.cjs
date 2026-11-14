'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../package/ScreenStudio-ZH-4.1.0-5005/payload/localize-renderer.js'), 'utf8');
const dictionary = JSON.parse(fs.readFileSync(path.join(__dirname, '../package/ScreenStudio-ZH-4.1.0-5005/payload/zh-CN.json'), 'utf8'));

/*
 * These tests execute the actual renderer script and dictionary in an isolated VM.
 * The deliberately small DOM substitute supports only the selectors, editable
 * inheritance and mutation records needed for its presentation-layer contract.
 * Mutation notifications are delivered explicitly; this is not a full browser,
 * React reconciliation, IME, shadow DOM or Electron native-menu integration test.
 * No application, private project, account, credential or network is accessed.
 */
class TestNode {
  constructor(nodeType) {
    this.nodeType = nodeType;
    this.parentElement = null;
    this.rootConnected = false;
  }
  get isConnected() {
    return this.rootConnected || Boolean(this.parentElement?.isConnected);
  }
}

class TestText extends TestNode {
  constructor(data) {
    super(3);
    this.data = data;
  }
}

class TestElement extends TestNode {
  constructor(tagName = 'div', attributes = {}) {
    super(1);
    this.tagName = tagName.toLowerCase();
    this.attributes = new Map(Object.entries(attributes));
    this.childNodes = [];
    this.value = '';
  }
  hasAttribute(name) { return this.attributes.has(name); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  appendChild(child) {
    child.parentElement = this;
    this.childNodes.push(child);
    return child;
  }
  matches(selector) {
    const attribute = /^\[([^=\]]+)(?:="([^"]*)")?\]$/.exec(selector);
    if (attribute) return this.hasAttribute(attribute[1]) &&
      (attribute[2] === undefined || this.getAttribute(attribute[1]) === attribute[2]);
    return this.tagName === selector.toLowerCase();
  }
  closest(selectorList) {
    const selectors = selectorList.split(',').map(value => value.trim());
    for (let node = this; node; node = node.parentElement)
      if (selectors.some(selector => node.matches(selector))) return node;
    return null;
  }
  get isContentEditable() {
    const value = this.getAttribute('contenteditable')?.toLowerCase();
    if (value === '' || value === 'true' || value === 'plaintext-only') return true;
    if (value === 'false') return false;
    return this.parentElement?.isContentEditable ?? false;
  }
}

function harness(setup = () => {}) {
  const documentElement = new TestElement('html');
  documentElement.rootConnected = true;
  const head = documentElement.appendChild(new TestElement('head'));
  const body = documentElement.appendChild(new TestElement('body'));
  const microtasks = [];
  const observers = [];
  const document = {
    documentElement, head, body, title: 'Screen Studio Settings', readyState: 'complete',
    createElement: tag => new TestElement(tag),
  };
  const references = setup(document);
  class TestObserver {
    constructor(callback) { this.callback = callback; observers.push(this); }
    observe(target, options) { this.target = target; this.options = options; }
  }
  const context = vm.createContext({
    window: { __screenStudioChineseDictionary: dictionary },
    document, Node: { TEXT_NODE: 3 }, Element: TestElement,
    MutationObserver: TestObserver,
    queueMicrotask: callback => microtasks.push(callback),
  });
  const run = () => vm.runInContext(script, context, { filename: 'localize-renderer.js' });
  run();
  const flush = () => {
    let steps = 0;
    while (microtasks.length) {
      assert(++steps <= 100, 'Unexpected endlessly queued translation work');
      microtasks.shift()();
    }
  };
  const notify = records => {
    for (const observer of observers) observer.callback(records);
    flush();
  };
  return { context, document, observers, references, run, flush, notify,
    translate: context.window.__screenStudioChinese.translate };
}

test('the full dictionary is idempotent under the actual translation function', () => {
  const { translate } = harness();
  const entries = Object.entries(dictionary);
  assert(entries.length > 0, 'The translation dictionary must not be empty');
  for (const [source, translated] of entries) {
    const first = translate(source);
    assert.equal(translate(first), first, `Repeated translation changed ${JSON.stringify(source)}`);
    assert.equal(translate(translate(translated)), translate(translated), `Unstable translation value for ${JSON.stringify(source)}`);
  }
  assert.equal(translate('17 projects'), '17 个项目');
  assert.equal(translate(translate('17 projects')), '17 个项目');
});

test('explicit, empty and plaintext-only editable regions preserve text, including inherited editing', () => {
  for (const mode of ['true', '', 'plaintext-only']) {
    const h = harness(({ body }) => {
      const editor = body.appendChild(new TestElement('div', { contenteditable: mode }));
      const nested = editor.appendChild(new TestElement('span'));
      const text = nested.appendChild(new TestText('Hello!'));
      return { editor, nested, text };
    });
    const { editor, nested, text } = h.references;
    assert.equal(editor.isContentEditable, true);
    assert.equal(nested.isContentEditable, true);
    assert.equal(text.data, 'Hello!', `Initial editable text changed for ${JSON.stringify(mode)}`);
    text.data = 'Color';
    h.notify([{ type: 'characterData', target: text }]);
    assert.equal(text.data, 'Color', `Typed editable text changed for ${JSON.stringify(mode)}`);
    const inserted = nested.appendChild(new TestText('New'));
    h.notify([{ type: 'childList', target: nested, addedNodes: [inserted] }]);
    assert.equal(inserted.data, 'New', `Inserted editable text changed for ${JSON.stringify(mode)}`);
  }
});

test('input and textarea user values remain intact while their UI placeholders translate', () => {
  const h = harness(({ body }) => {
    const input = body.appendChild(new TestElement('input', { placeholder: 'Search projects', value: 'Hello!' }));
    input.value = 'Hello!';
    const textarea = body.appendChild(new TestElement('textarea', { placeholder: 'Enter text to be voiced' }));
    textarea.value = 'Color';
    const text = textarea.appendChild(new TestText('Color'));
    return { input, textarea, text };
  });
  const { input, textarea, text } = h.references;
  assert.equal(input.value, 'Hello!');
  assert.equal(input.getAttribute('value'), 'Hello!');
  assert.equal(textarea.value, 'Color');
  assert.equal(text.data, 'Color');
  assert.equal(input.getAttribute('placeholder'), dictionary['Search projects']);
  assert.equal(textarea.getAttribute('placeholder'), dictionary['Enter text to be voiced']);
  input.value = 'New';
  input.setAttribute('placeholder', 'Video title...');
  h.notify([{ type: 'attributes', target: input, attributeName: 'placeholder' }]);
  assert.equal(input.getAttribute('placeholder'), dictionary['Video title...']);
  assert.equal(input.value, 'New');
});

test('dynamic UI text translates without replacing nodes and handles subsequent text updates', () => {
  const h = harness();
  const label = h.document.body.appendChild(new TestElement('span'));
  const text = label.appendChild(new TestText('Hello!'));
  h.notify([{ type: 'childList', target: h.document.body, addedNodes: [label] }]);
  assert.equal(text.data, dictionary['Hello!']);
  assert.equal(label.childNodes[0], text, 'Translation must retain the original text node');
  text.data = 'Color';
  h.notify([{ type: 'characterData', target: text }]);
  assert.equal(text.data, dictionary.Color);
  assert.equal(label.childNodes[0], text);
  const detached = new TestText('Hello!');
  h.notify([{ type: 'childList', target: h.document.body, addedNodes: [detached] }]);
  assert.equal(detached.data, 'Hello!', 'Detached nodes must not be translated');
});

test('preserved, textbox and code regions remain unchanged on dynamic mutations', () => {
  for (const [tag, attributes] of [
    ['div', { 'data-ss-preserve-text': '' }], ['div', { role: 'textbox' }], ['code', {}], ['pre', {}],
  ]) {
    const h = harness(({ body }) => {
      const region = body.appendChild(new TestElement(tag, attributes));
      return region.appendChild(new TestElement('span')).appendChild(new TestText('Hello!'));
    });
    assert.equal(h.references.data, 'Hello!');
    h.references.data = 'New';
    h.notify([{ type: 'characterData', target: h.references }]);
    assert.equal(h.references.data, 'New');
  }
});

test('each renderer context initializes once and watches dynamic text and UI attributes', () => {
  const first = harness();
  const second = harness();
  for (const h of [first, second]) {
    assert.equal(h.document.documentElement.lang, 'zh-CN');
    assert.equal(h.document.title, 'Screen Studio 设置');
    assert.equal(h.observers.length, 1);
    assert.equal(h.observers[0].options.subtree, true);
    assert.equal(h.observers[0].options.childList, true);
    assert.equal(h.observers[0].options.characterData, true);
    assert(h.observers[0].options.attributeFilter.includes('placeholder'));
    h.run();
    assert.equal(h.observers.length, 1, 'A second injection must not add another observer');
    assert.equal(h.document.head.childNodes.length, 1, 'A second injection must not add another font style');
  }
});
