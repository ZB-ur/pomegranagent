import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import * as viewModule from '../../../app/frontend/child/view.mjs';
import { createChildView } from '../../../app/frontend/child/view.mjs';
import { createInitialSnapshot } from '../../../app/frontend/child/machine.mjs';

class FakeText {
  constructor(text) {
    this.parentNode = null;
    this.value = String(text);
  }

  get textContent() {
    return this.value;
  }

  set textContent(text) {
    this.value = String(text);
  }
}

class FakeElement {
  constructor(tagName, focusState) {
    this.tagName = String(tagName).toUpperCase();
    this.parentNode = null;
    this.disabled = false;
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.focusState = focusState;
    this.replaceCount = 0;
    this.hidden = false;
    this.open = false;
    this.value = '';
    this.showModalCount = 0;
    this.closeCount = 0;
  }

  append(...nodes) {
    for (const node of nodes) {
      if (!node || typeof node !== 'object') throw new TypeError('node required');
      if (node.parentNode && typeof node.parentNode.removeChild === 'function') {
        node.parentNode.removeChild(node);
      }
      node.parentNode = this;
      this.children.push(node);
    }
  }

  replaceChildren(...nodes) {
    this.replaceCount += 1;
    for (const child of this.children) child.parentNode = null;
    this.children = [];
    this.append(...nodes);
  }

  removeChild(node) {
    const index = this.children.indexOf(node);
    if (index >= 0) {
      this.children.splice(index, 1);
      node.parentNode = null;
    }
  }

  setAttribute(name, value) {
    this.attributes.set(String(name), String(value));
  }

  getAttribute(name) {
    return this.attributes.has(String(name)) ? this.attributes.get(String(name)) : null;
  }

  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type).add(listener);
  }

  removeEventListener(type, listener) {
    this.listeners.get(type)?.delete(listener);
  }

  showModal() {
    this.showModalCount += 1;
    this.open = true;
    this.setAttribute('open', '');
  }

  close() {
    this.closeCount += 1;
    this.open = false;
    this.attributes.delete('open');
  }

  setCustomValidity(message) {
    this.validationMessage = String(message);
  }

  querySelector(selector) {
    return find(this, node => matches(node, selector)) ?? null;
  }

  contains(node) {
    if (node === this) return true;
    return Boolean(find(this, candidate => candidate === node));
  }

  focus() {
    this.focusState.current = this;
  }

  get textContent() {
    return this.children.map(child => child.textContent).join('');
  }

  set textContent(text) {
    this.replaceChildren(new FakeText(text));
  }
}

function matches(node, selector) {
  if (!(node instanceof FakeElement)) return false;
  if (selector.startsWith('#')) return node.getAttribute('id') === selector.slice(1);
  return node.tagName === selector.toUpperCase();
}

function find(node, predicate) {
  if (!(node instanceof FakeElement)) return null;
  for (const child of node.children) {
    if (predicate(child)) return child;
    const nested = find(child, predicate);
    if (nested) return nested;
  }
  return null;
}

function findAll(node, predicate, found = []) {
  if (!(node instanceof FakeElement)) return found;
  for (const child of node.children) {
    if (predicate(child)) found.push(child);
    findAll(child, predicate, found);
  }
  return found;
}

function createFakeDOM() {
  const focusState = { current: null };
  const queued = [];
  const dom = {
    createElement: tag => new FakeElement(tag, focusState),
    createTextNode: text => new FakeText(text),
    queueMicrotask: callback => queued.push(callback),
    isFocused: element => focusState.current === element,
  };
  return {
    dom,
    root: new FakeElement('div', focusState),
    focused: () => focusState.current,
    flush() {
      const pending = queued.splice(0);
      for (const callback of pending) callback();
    },
  };
}

function actions(overrides = {}) {
  return {
    onStart() {},
    onSelectChild() {},
    onRecordToggle() {},
    onRetry() {},
    onReset() {},
    onOpenTeacherHelp() {},
    onSubmitTeacherPin() {},
    onSubmitTeacherText() {},
    onSaveTeacherDraft() {},
    onRetryTeacherRecovery() {},
    onRetryMicrophone() {},
    onEndWithTeacher() {},
    onLockTeacherHelp() {},
    ...overrides,
  };
}

const child = Object.freeze({ id: 7, name: '小雨', nickname: '雨点', avatar: null });
const draft = Object.freeze({
  text: '我给小鸭换了水',
  request_id: '10f1cc1c-4ee6-41af-96de-1b0a3cc329cc',
  created_at: '2026-08-24T00:00:00.000Z',
});
const messages = Object.freeze([
  Object.freeze({ id: 10, role: 'child', text: '我给小鸭换了水' }),
  Object.freeze({ id: 11, role: 'diary', text: '你做得真认真。' }),
]);
const conversationStates = new Set([
  'ready',
  'listening',
  'submitting',
  'speaking',
  'submission_failed',
  'saving_conversation',
  'completed',
  'recovery',
]);
const posterByState = new Map([
  ['welcome', '/assets/duck-front-512.png'],
  ['loading_roster', '/assets/duck-front-512.png'],
  ['selecting_child', '/assets/duck-side-512.png'],
  ['opening', '/assets/duck-encouraging.png'],
  ['ready', '/assets/duck-front-512.png'],
  ['listening', '/assets/duck-listening.png'],
  ['submitting', '/assets/duck-listening.png'],
  ['speaking', '/assets/duck-encouraging.png'],
  ['submission_failed', '/assets/duck-front-512.png'],
  ['saving_conversation', '/assets/duck-listening.png'],
  ['completed', '/assets/duck-happy.png'],
  ['recovery', '/assets/duck-front-512.png'],
]);

function snapshotFor(value, overrides = {}) {
  const common = {
    value,
    child,
    roster: [child],
    messages,
    conversationId: 9,
    revision: 0,
    lastMessageId: 11,
    error: { code: 'NETWORK_ERROR', retryable: true, message: 'untrusted server detail' },
  };
  if (value === 'welcome' || value === 'loading_roster' || value === 'selecting_child') {
    Object.assign(common, { child: null, messages: [], conversationId: null, revision: null, lastMessageId: null, error: null });
  }
  if (value === 'opening' || value === 'ready' || value === 'listening' || value === 'speaking') {
    Object.assign(common, { draft: null, error: null });
  }
  if (value === 'submitting') Object.assign(common, { draft });
  if (value === 'submission_failed') Object.assign(common, { draft });
  if (value === 'saving_conversation' || value === 'completed') Object.assign(common, { draft: null, error: null });
  if (value === 'recovery') Object.assign(common, { draft: null });
  return createInitialSnapshot({ ...common, ...overrides });
}

function byId(root, id) {
  return root.querySelector(`#${id}`);
}

function dispatchClick(root, target) {
  for (const listener of root.listeners.get('click') ?? []) listener({ target });
}

function dispatch(target, type, event = {}) {
  const supplied = {
    target,
    preventDefault() { this.defaultPrevented = true; },
    defaultPrevented: false,
    ...event,
  };
  for (const listener of target.listeners.get(type) ?? []) listener(supplied);
  return supplied;
}

function actionButton(root, token) {
  return find(root, node => node instanceof FakeElement && node.getAttribute('data-child-action') === token);
}

test('exports only createChildView and returns the frozen nine-method surface', () => {
  assert.deepEqual(Object.keys(viewModule), ['createChildView']);
  const fake = createFakeDOM();
  const view = createChildView(fake.root, actions(), fake.dom);
  assert.equal(Object.isFrozen(view), true);
  assert.deepEqual(Object.keys(view).sort(), [
    'announce',
    'clearTeacherPin',
    'closeTeacherHelp',
    'destroy',
    'focus',
    'openTeacherHelp',
    'render',
    'showTeacherHelpError',
    'showTeacherHelpUnlocked',
  ]);
  assert.equal(view.announce('before render'), undefined);
  assert.equal(view.focus('#start-button'), false);
  assert.equal(view.destroy(), undefined);
  assert.equal(view.destroy(), undefined);
  assert.throws(() => view.render(snapshotFor('welcome')), /child view is destroyed/);
  assert.throws(() => view.announce('after destroy'), /child view is destroyed/);
  assert.equal(view.focus('#start-button'), false);
});

test('rejects malformed root, exact action/dom seams, and invalid element seams', () => {
  const fake = createFakeDOM();
  assert.throws(() => createChildView({}, actions(), fake.dom), TypeError);
  assert.throws(() => createChildView(fake.root, { ...actions(), extra() {} }, fake.dom), TypeError);
  assert.throws(() => createChildView(fake.root, { ...actions(), onRetry: null }, fake.dom), TypeError);
  assert.throws(() => createChildView(fake.root, actions({ onOpenTeacherHelp: 1 }), fake.dom), TypeError);
  assert.throws(() => createChildView(fake.root, actions(), { ...fake.dom, extra() {} }), TypeError);
  assert.throws(() => createChildView(fake.root, actions(), { ...fake.dom, isFocused: null }), TypeError);
  assert.throws(() => createChildView(fake.root, actions(), new Proxy(fake.dom, { ownKeys() { throw new Error('trap'); } })), TypeError);
  const badDOM = {
    createElement: () => null,
    createTextNode: fake.dom.createTextNode,
    queueMicrotask: fake.dom.queueMicrotask,
    isFocused: fake.dom.isFocused,
  };
  const view = createChildView(fake.root, actions(), badDOM);
  assert.throws(() => view.render(snapshotFor('welcome')), TypeError);
});

test('owns one delegated root listener and maps each current native action exactly once', () => {
  const calls = [];
  const fake = createFakeDOM();
  const view = createChildView(fake.root, actions({
    onStart: () => calls.push(['start']),
    onSelectChild: id => calls.push(['select', id]),
    onRecordToggle: () => calls.push(['record']),
    onRetry: () => calls.push(['retry']),
    onReset: () => calls.push(['reset']),
    onOpenTeacherHelp: () => calls.push(['help']),
  }), fake.dom);
  assert.equal(fake.root.listeners.get('click').size, 1);

  const cases = [
    ['welcome', 'start', ['start']],
    ['selecting_child', 'select-child', ['select', 7]],
    ['ready', 'record-toggle', ['record']],
    ['submission_failed', 'retry', ['retry']],
    ['completed', 'reset', ['reset']],
    ['recovery', 'open-teacher-help', ['help']],
  ];
  for (const [state, token, expected] of cases) {
    view.render(snapshotFor(state));
    const button = actionButton(fake.root, token);
    assert.ok(button, `${state} has ${token}`);
    assert.equal(button.tagName, 'BUTTON');
    dispatchClick(fake.root, button);
    assert.deepEqual(calls.at(-1), expected);
  }
  assert.equal(calls.length, cases.length);
});

test('suppresses disabled, forged, detached, text, and unknown action targets and cleans them on destroy', () => {
  const calls = [];
  const fake = createFakeDOM();
  const view = createChildView(fake.root, actions({ onStart: () => calls.push('start') }), fake.dom);
  view.render(snapshotFor('welcome'));
  const oldStart = byId(fake.root, 'start-button');
  view.render(snapshotFor('loading_roster'));
  dispatchClick(fake.root, oldStart);
  dispatchClick(fake.root, new FakeText('outside'));
  const forged = fake.dom.createElement('button');
  forged.setAttribute('data-child-action', 'start');
  fake.root.append(forged);
  dispatchClick(fake.root, forged);
  const disabledHelp = byId(fake.root, 'teacher-help-button');
  disabledHelp.disabled = true;
  dispatchClick(fake.root, disabledHelp);
  const unknown = fake.dom.createElement('button');
  unknown.setAttribute('data-child-action', 'unknown');
  fake.root.append(unknown);
  dispatchClick(fake.root, unknown);
  assert.deepEqual(calls, []);
  view.destroy();
  assert.equal((fake.root.listeners.get('click') ?? new Set()).size, 0);
  assert.equal(fake.root.children.length, 0);
  dispatchClick(fake.root, oldStart);
  assert.deepEqual(calls, []);
});

test('keeps mutated current buttons with prototype action names inert without throwing', () => {
  const calls = [];
  const fake = createFakeDOM();
  const view = createChildView(fake.root, actions({ onStart: () => calls.push('start') }), fake.dom);
  view.render(snapshotFor('welcome'));
  const start = byId(fake.root, 'start-button');
  for (const token of ['toString', 'constructor', '__proto__']) {
    start.setAttribute('data-child-action', token);
    assert.doesNotThrow(() => dispatchClick(fake.root, start));
  }
  assert.deepEqual(calls, []);
});

test('rejects action and DOM accessor descriptors before invoking their getters', () => {
  const fake = createFakeDOM();
  const actionSeam = actions();
  let actionGetterCalls = 0;
  Object.defineProperty(actionSeam, 'onStart', {
    enumerable: true,
    get() {
      actionGetterCalls += 1;
      throw new Error('action getter must stay unread');
    },
  });
  assert.throws(() => createChildView(fake.root, actionSeam, fake.dom), TypeError);
  assert.equal(actionGetterCalls, 0);

  const domSeam = { ...fake.dom };
  let domGetterCalls = 0;
  Object.defineProperty(domSeam, 'createElement', {
    enumerable: true,
    get() {
      domGetterCalls += 1;
      return fake.dom.createElement;
    },
  });
  assert.throws(() => createChildView(fake.root, actions(), domSeam), TypeError);
  assert.equal(domGetterCalls, 0);
});

test('normalizes own-key and descriptor proxy trap failures to fresh TypeError values', () => {
  const fake = createFakeDOM();
  const ownKeysError = new Error('ownKeys trap');
  const ownKeysProxy = new Proxy(actions(), {
    ownKeys() {
      throw ownKeysError;
    },
  });
  let thrown;
  try {
    createChildView(fake.root, ownKeysProxy, fake.dom);
  } catch (error) {
    thrown = error;
  }
  assert.equal(thrown instanceof TypeError, true);
  assert.notEqual(thrown, ownKeysError);

  const ownKeysTypeError = new TypeError('ownKeys TypeError trap');
  const ownKeysTypeProxy = new Proxy(actions(), {
    ownKeys() {
      throw ownKeysTypeError;
    },
  });
  thrown = undefined;
  try {
    createChildView(fake.root, ownKeysTypeProxy, fake.dom);
  } catch (error) {
    thrown = error;
  }
  assert.equal(thrown instanceof TypeError, true);
  assert.notEqual(thrown, ownKeysTypeError);

  const descriptorError = new Error('descriptor trap');
  const descriptorProxy = new Proxy(actions(), {
    getOwnPropertyDescriptor() {
      throw descriptorError;
    },
  });
  thrown = undefined;
  try {
    createChildView(fake.root, descriptorProxy, fake.dom);
  } catch (error) {
    thrown = error;
  }
  assert.equal(thrown instanceof TypeError, true);
  assert.notEqual(thrown, descriptorError);

  const domDescriptorError = new Error('DOM descriptor trap');
  const domDescriptorProxy = new Proxy(fake.dom, {
    getOwnPropertyDescriptor() {
      throw domDescriptorError;
    },
  });
  thrown = undefined;
  try {
    createChildView(fake.root, actions(), domDescriptorProxy);
  } catch (error) {
    thrown = error;
  }
  assert.equal(thrown instanceof TypeError, true);
  assert.notEqual(thrown, domDescriptorError);
});

test('renders all twelve states with unique semantic frame, exact status, and focus policy', () => {
  const rows = [
    ['welcome', '准备好后，请按开始', 'start-button'],
    ['loading_roster', '正在加载今天的值日小朋友', 'child-status'],
    ['selecting_child', '请选择今天值日的小朋友', 'app-title'],
    ['opening', '鸭鸭日记本正在和你打招呼', 'child-status'],
    ['ready', '点一下开始说话，也可以按空格键', 'record-button'],
    ['listening', '正在听，停顿后会自动发送', 'record-button'],
    ['submitting', '这句话正在发给鸭鸭日记本', 'child-status'],
    ['speaking', '鸭鸭日记本正在回答', 'child-status'],
    ['submission_failed', '这句话还没有送达，原话已经保留', 'retry-button'],
    ['saving_conversation', '正在安全保存今天的话', 'child-status'],
    ['completed', '今天的话已经安全记下来啦', 'reset-button'],
    ['recovery', '需要老师帮忙恢复这次对话', 'teacher-help-button'],
  ];
  for (const [state, status, focusId] of rows) {
    const fake = createFakeDOM();
    const view = createChildView(fake.root, actions(), fake.dom);
    view.render(snapshotFor(state));
    fake.flush();
    const section = fake.root.children[0];
    assert.equal(section.tagName, 'SECTION');
    assert.equal(section.getAttribute('class'), 'child-view child-shell');
    assert.equal(section.getAttribute('data-state'), state);
    assert.equal(section.getAttribute('aria-labelledby'), 'app-title');
    assert.equal(findAll(fake.root, node => node.getAttribute?.('id') === 'app-title').length, 1);
    assert.ok(find(fake.root, node => node.getAttribute?.('class') === 'child-shell__header'));
    assert.ok(find(fake.root, node => node.getAttribute?.('class') === 'child-shell__content'));
    assert.ok(find(fake.root, node => node.getAttribute?.('class') === 'child-state'));
    assert.equal(byId(fake.root, 'teacher-help-button').parentNode.getAttribute('class'), 'child-shell__header');
    assert.equal(byId(fake.root, 'app-title').parentNode.getAttribute('class'), 'child-state__header');
    assert.equal(byId(fake.root, 'child-status').textContent, status);
    assert.equal(byId(fake.root, 'child-status').getAttribute('role'), 'status');
    assert.equal(byId(fake.root, 'child-status').getAttribute('aria-live'), 'polite');
    assert.equal(byId(fake.root, 'teacher-help-button').tagName, 'BUTTON');
    assert.equal(fake.focused(), byId(fake.root, focusId));
  }
});

test('projects one local PetOrb in every state and one ConversationPanel in conversation states', () => {
  const orbActionByState = new Map([
    ['welcome', 'start-button'],
    ['ready', 'record-button'],
    ['listening', 'record-button'],
    ['submission_failed', 'retry-button'],
    ['completed', 'reset-button'],
  ]);
  for (const [state, poster] of posterByState) {
    const fake = createFakeDOM();
    const view = createChildView(fake.root, actions(), fake.dom);
    view.render(snapshotFor(state));
    const orbs = findAll(fake.root, node => node.getAttribute?.('class') === 'child-pet-orb');
    assert.equal(orbs.length, 1, `${state} must render exactly one PetOrb`);
    const panels = findAll(fake.root, node => node.getAttribute?.('class') === 'child-conversation-panel');
    assert.equal(panels.length, conversationStates.has(state) ? 1 : 0, `${state} ConversationPanel count`);
    const leads = findAll(fake.root, node => node.getAttribute?.('class') === 'child-state__lead');
    assert.equal(leads.length, 1);
    assert.notEqual(leads[0].textContent.trim(), '', `${state} must have local visible lead copy`);
    assert.equal(leads[0].textContent.includes('untrusted server detail'), false);

    const posters = findAll(orbs[0], node => node.tagName === 'IMG');
    assert.equal(posters.length, 1, `${state} PetOrb poster count`);
    assert.equal(posters[0].getAttribute('src'), poster);
    assert.equal(/^\/assets\//.test(posters[0].getAttribute('src')), true);

    const orbActions = findAll(
      orbs[0],
      node => node instanceof FakeElement && node.getAttribute('data-child-action') !== null,
    );
    const expectedAction = orbActionByState.get(state) ?? null;
    assert.equal(orbActions.length, expectedAction === null ? 0 : 1, `${state} PetOrb action count`);
    assert.equal(orbActions[0]?.getAttribute('id') ?? null, expectedAction);
  }
});

test('uses exact diary partner copy without the legacy bare-duck phrases', () => {
  const fake = createFakeDOM();
  const view = createChildView(fake.root, actions(), fake.dom);

  view.render(snapshotFor('submitting'));
  assert.equal(byId(fake.root, 'child-status').textContent, '这句话正在发给鸭鸭日记本');
  assert.equal(fake.root.textContent.includes('送给鸭鸭'), false);
  assert.equal(/发给鸭鸭(?!日记本)/u.test(fake.root.textContent), false);

  view.render(snapshotFor('speaking'));
  assert.equal(byId(fake.root, 'child-status').textContent, '鸭鸭日记本正在回答');
  assert.equal(fake.root.textContent.includes('鸭鸭正在回答'), false);
});

test('uses one click-toggle PetOrb record action without any hold gesture contract', () => {
  const calls = [];
  const fake = createFakeDOM();
  const view = createChildView(fake.root, actions({ onRecordToggle: () => calls.push('toggle') }), fake.dom);

  view.render(snapshotFor('ready'));
  const readyOrb = find(fake.root, node => node.getAttribute?.('class') === 'child-pet-orb');
  const readyRecord = byId(fake.root, 'record-button');
  assert.ok(readyOrb.contains(readyRecord));
  assert.equal(readyRecord.textContent, '开始说话');
  assert.equal(readyRecord.getAttribute('data-child-action'), 'record-toggle');
  assert.equal(findAll(readyOrb, node => node.getAttribute?.('data-child-action') === 'record-toggle').length, 1);
  dispatchClick(fake.root, readyRecord);
  assert.deepEqual(calls, ['toggle']);

  view.render(snapshotFor('listening'));
  const listeningOrb = find(fake.root, node => node.getAttribute?.('class') === 'child-pet-orb');
  const listeningRecord = byId(fake.root, 'record-button');
  assert.ok(listeningOrb.contains(listeningRecord));
  assert.equal(listeningRecord.getAttribute('id'), readyRecord.getAttribute('id'));
  assert.equal(listeningRecord.getAttribute('data-child-action'), readyRecord.getAttribute('data-child-action'));
  assert.equal(listeningRecord.textContent, '结束说话');
  assert.equal(findAll(listeningOrb, node => node.getAttribute?.('data-child-action') === 'record-toggle').length, 1);
  dispatchClick(fake.root, listeningRecord);
  assert.deepEqual(calls, ['toggle', 'toggle']);

  for (const type of ['mousedown', 'pointerdown', 'pointerup', 'touchstart', 'touchend']) {
    assert.equal((fake.root.listeners.get(type) ?? new Set()).size, 0, `${type} must not be registered`);
    assert.equal((listeningRecord.listeners.get(type) ?? new Set()).size, 0, `${type} must not be registered on action`);
  }
});

test('groups empty roster and renders ordered safe local avatar fallbacks with full labels', () => {
  const fake = createFakeDOM();
  const view = createChildView(fake.root, actions(), fake.dom);
  view.render(snapshotFor('selecting_child', { roster: [] }));
  assert.equal(byId(fake.root, 'child-status').textContent, '今天还未排班，请老师帮忙');
  assert.equal(findAll(fake.root, node => node.getAttribute?.('class') === 'child-card').length, 0);
  assert.equal(fake.root.textContent.includes('全部幼儿'), false);
  const emptyPanel = find(
    fake.root,
    node => node.getAttribute?.('class') === 'child-roster-panel child-roster-panel--empty',
  );
  assert.ok(emptyPanel);
  assert.equal(emptyPanel.contains(byId(fake.root, 'roster-empty')), true);

  const hostile = { id: 7, name: '小雨', nickname: null, avatar: 'javascript:alert(1)' };
  const second = { id: 8, name: '乐乐', nickname: '👩🏽‍🔬小科学家', avatar: 'https://example.invalid/avatar.png' };
  view.render(snapshotFor('selecting_child', { roster: [hostile, second] }));
  const rosterPanel = find(fake.root, node => node.getAttribute?.('class') === 'child-roster-panel');
  assert.ok(rosterPanel);
  const cards = findAll(fake.root, node => node.getAttribute?.('class') === 'child-card');
  assert.equal(cards.length, 2);
  assert.deepEqual(cards.map(card => card.getAttribute('data-child-id')), ['7', '8']);
  assert.deepEqual(
    cards.map(card => find(card, node => node.getAttribute?.('class') === 'child-card__label')?.textContent),
    ['小雨', '👩🏽‍🔬小科学家'],
  );
  assert.deepEqual(
    cards.map(card => find(card, node => node.getAttribute?.('class') === 'child-card__avatar')?.textContent),
    ['小', '👩🏽‍🔬'],
  );
  for (const card of cards) {
    const avatar = find(card, node => node.getAttribute?.('class') === 'child-card__avatar');
    assert.equal(avatar?.getAttribute('aria-hidden'), 'true');
    assert.equal(findAll(card, node => node.tagName === 'IMG').length, 0);
  }
  assert.equal(fake.root.textContent.includes('javascript:alert(1)'), false);
  assert.equal(fake.root.textContent.includes('https://example.invalid/avatar.png'), false);
});

test('normalizes one nonblank roster label for native text and avatar fallback', () => {
  const fake = createFakeDOM();
  const view = createChildView(fake.root, actions(), fake.dom);
  const roster = [
    { id: 7, name: '小雨', nickname: '   ', avatar: 'javascript:alert(1)' },
    { id: 8, name: '备用', nickname: '\u200b雨点\ufeff', avatar: null },
    { id: 9, name: '\u200b小林\ufeff', nickname: '\u200b\ufeff', avatar: null },
    { id: 10, name: '备用', nickname: '\u200b👨‍👩‍👧 小队\ufeff', avatar: null },
    { id: 11, name: ' \t\ufeff', nickname: '\u200b\ufeff', avatar: null },
  ];

  view.render(snapshotFor('selecting_child', { roster }));

  const cards = findAll(fake.root, node => node.getAttribute?.('class') === 'child-card');
  assert.deepEqual(
    cards.map(card => find(card, node => node.getAttribute?.('class') === 'child-card__label')?.textContent),
    ['小雨', '雨点', '小林', '👨‍👩‍👧 小队', '小朋友'],
  );
  assert.deepEqual(
    cards.map(card => find(card, node => node.getAttribute?.('class') === 'child-card__avatar')?.textContent),
    ['小', '雨', '小', '👨‍👩‍👧', '小'],
  );
  assert.deepEqual(cards.map(card => card.getAttribute('data-child-id')), ['7', '8', '9', '10', '11']);
  assert.equal(fake.root.textContent.includes('javascript:alert(1)'), false);
});

test('uses panel log semantics, aligned visible speakers, and an in-panel unconfirmed draft', () => {
  const fake = createFakeDOM();
  const view = createChildView(fake.root, actions(), fake.dom);
  view.render(snapshotFor('submission_failed'));
  const panel = find(fake.root, node => node.getAttribute?.('class') === 'child-conversation-panel');
  assert.ok(panel);
  assert.equal(panel.textContent.includes('对话记录'), true);
  assert.ok(find(panel, node => node.getAttribute?.('class') === 'child-conversation-panel__state'));
  const log = find(fake.root, node => node.getAttribute?.('role') === 'log');
  assert.ok(log);
  assert.equal(panel.contains(log), true);
  assert.equal(log.getAttribute('aria-live'), 'polite');
  assert.equal(log.getAttribute('aria-relevant'), 'additions text');
  assert.equal(log.getAttribute('aria-label'), '对话记录');
  assert.equal(log.textContent.includes('雨点'), true);
  assert.equal(log.textContent.includes('鸭鸭日记本'), true);
  assert.equal(log.textContent.includes(draft.text), true);
  const messageRows = findAll(log, node => node.getAttribute?.('class')?.startsWith('child-message child-message--'));
  assert.equal(messageRows[0].getAttribute('class'), 'child-message child-message--child');
  assert.equal(messageRows[1].getAttribute('class'), 'child-message child-message--diary');
  assert.equal(findAll(messageRows[0], node => node.tagName === 'IMG').length, 0);
  const diaryMarks = findAll(messageRows[1], node => node.tagName === 'IMG');
  assert.equal(diaryMarks.length, 1);
  assert.equal(diaryMarks[0].getAttribute('src'), '/assets/diary-mark.svg');
  assert.equal(diaryMarks[0].getAttribute('alt'), '');
  const draftRegion = byId(fake.root, 'pending-draft');
  assert.ok(draftRegion);
  assert.equal(draftRegion.textContent.includes('待发送草稿'), true);
  assert.equal(log.contains(draftRegion), true);
  assert.equal(draftRegion.parentNode, log);
  assert.equal(findAll(fake.root, node => node.getAttribute?.('id') === 'pending-draft').length, 1);
  assert.equal(findAll(fake.root, node => node.getAttribute?.('id') === 'retry-button').length, 1);
  assert.equal(panel.contains(byId(fake.root, 'retry-button')), false);
  assert.equal(fake.root.textContent.includes('untrusted server detail'), false);
  const failure = find(panel, node => node.getAttribute?.('class') === 'child-message child-message--failure');
  assert.ok(failure);
  assert.equal(failure.getAttribute('role'), 'alert');

  view.render(snapshotFor('completed'));
  assert.equal(fake.root.textContent.includes('分析完成'), false);
  view.render(snapshotFor('saving_conversation'));
  assert.equal(fake.root.textContent.includes('分析完成'), false);
});

test('keeps empty and populated recovery errors inside one ConversationPanel log', async t => {
  const recoveryCases = [
    ['empty transcript', {
      child: null,
      messages: [],
      conversationId: null,
      revision: null,
      lastMessageId: null,
    }],
    ['populated transcript', {}],
  ];

  for (const [label, overrides] of recoveryCases) {
    await t.test(label, () => {
      const fake = createFakeDOM();
      const view = createChildView(fake.root, actions(), fake.dom);
      view.render(snapshotFor('recovery', {
        ...overrides,
        error: {
          code: 'MIC_PERMISSION_DENIED',
          retryable: false,
          message: `raw recovery detail: ${label}`,
        },
      }));

      const stage = find(fake.root, node => node.getAttribute?.('class') === 'child-stage');
      const panels = findAll(stage, node => node.getAttribute?.('class') === 'child-conversation-panel');
      const logs = findAll(stage, node => node.getAttribute?.('role') === 'log');
      const alerts = findAll(stage, node => node.getAttribute?.('role') === 'alert');

      assert.equal(panels.length, 1, `${label} panel count`);
      assert.equal(logs.length, 1, `${label} log count`);
      assert.equal(alerts.length, 1, `${label} alert count`);
      assert.equal(panels[0].contains(logs[0]), true, `${label} log must be inside panel`);
      assert.equal(logs[0].contains(alerts[0]), true, `${label} error must be inside log`);
      assert.equal(alerts[0].parentNode, logs[0], `${label} error must be a log row`);
      assert.equal(alerts[0].getAttribute('class'), 'child-message child-message--failure');
      assert.equal(alerts[0].textContent, '发送状态麦克风没有开启，请老师帮忙');
      assert.equal(stage.children.filter(node => node.getAttribute?.('role') === 'alert').length, 0);
      assert.deepEqual(
        stage.children.map(node => node.getAttribute?.('class')),
        ['child-conversation-panel', 'child-pet-orb'],
      );
      assert.equal(fake.root.textContent.includes(`raw recovery detail: ${label}`), false);
    });
  }
});

test('uses machine retry authorization and routes incomplete retry state to enabled teacher help', () => {
  const fake = createFakeDOM();
  const realHelp = createChildView(fake.root, actions(), fake.dom);
  realHelp.render(snapshotFor('submission_failed'));
  assert.equal(byId(fake.root, 'retry-button').disabled, false);
  assert.equal(realHelp.focus('#retry-button'), true);

  const defensive = createFakeDOM();
  const teacherHelp = createChildView(defensive.root, actions(), defensive.dom);
  teacherHelp.render(snapshotFor('submission_failed', { child: null, draft: null }));
  defensive.flush();
  assert.equal(byId(defensive.root, 'retry-button'), null);
  assert.equal(byId(defensive.root, 'child-status').textContent, '这句话没有可重发的草稿，请老师帮忙');
  assert.equal(defensive.focused(), byId(defensive.root, 'teacher-help-button'));
  assert.equal(teacherHelp.focus('#teacher-help-button'), true);
});

test('announces literal text without focus theft and invalidates stale queued focus work', () => {
  const fake = createFakeDOM();
  const view = createChildView(fake.root, actions(), fake.dom);
  view.render(snapshotFor('welcome'));
  view.render(snapshotFor('selecting_child'));
  fake.flush();
  assert.equal(fake.focused(), byId(fake.root, 'app-title'));
  assert.equal(view.announce('<img src=x onerror=boom>'), undefined);
  assert.equal(byId(fake.root, 'child-status').textContent, '<img src=x onerror=boom>');
  assert.equal(fake.focused(), byId(fake.root, 'app-title'));
  const focusBeforeSameStateRender = fake.focused();
  view.render(snapshotFor('selecting_child'));
  fake.flush();
  assert.equal(fake.focused(), focusBeforeSameStateRender);
  assert.notEqual(fake.focused(), byId(fake.root, 'app-title'));
  view.render(snapshotFor('ready'));
  const focusBeforeDestroy = fake.focused();
  view.destroy();
  fake.flush();
  assert.equal(fake.focused(), focusBeforeDestroy);
});

test('accepts machine-valid null children and keeps hostile dynamic content text-only with fixed errors', () => {
  const fake = createFakeDOM();
  const view = createChildView(fake.root, actions(), fake.dom);
  view.render(snapshotFor('opening', { child: null }));
  assert.equal(fake.root.textContent.includes('正在确认小朋友信息'), true);
  const hostile = '<img src="https://example.invalid" onerror="boom">';
  view.render(snapshotFor('recovery', {
    child: { ...child, nickname: hostile, name: hostile },
    messages: [{ id: 12, role: 'child', text: hostile }],
    error: { code: 'MIC_PERMISSION_DENIED', retryable: false, message: hostile },
  }));
  assert.equal(fake.root.textContent.includes(hostile), true);
  const images = findAll(fake.root, node => node.tagName === 'IMG');
  assert.deepEqual(images.map(image => image.getAttribute('src')), [
    '/assets/notebook-mark.svg',
    '/assets/duck-front-512.png',
  ]);
  assert.equal(images.every(image => image.getAttribute('alt') === ''), true);
  assert.equal(fake.root.textContent.includes('MIC_PERMISSION_DENIED'), false);
  assert.equal(byId(fake.root, 'child-status').textContent, '麦克风没有开启，请老师帮忙');
});

test('maps every approved error code to fixed local copy without rendering raw error fields', () => {
  const expected = new Map([
    ['MIC_PERMISSION_DENIED', '麦克风没有开启，请老师帮忙'],
    ['MIC_UNAVAILABLE', '现在找不到麦克风，请老师帮忙'],
    ['SPEECH_UNSUPPORTED', '这个浏览器不能使用语音，请老师帮忙'],
    ['SPEECH_FAILED', '刚才没有听清，请老师帮忙'],
    ['LOCAL_STORAGE_FAILED', '浏览器没有安全保存这次对话，请老师帮忙'],
    ['IDEMPOTENCY_CONFLICT', '这句话的记录状态不一致，请老师确认'],
    ['RECOVERY_CHILD_MISMATCH', '无法安全确认是哪位小朋友的对话'],
    ['RECOVERY_CONVERSATION_MISMATCH', '无法安全确认要恢复哪一次对话'],
    ['RECOVERY_CONVERSATION_MISSING', '原来的对话暂时找不到'],
    ['RECOVERY_COMPLETION_BOUNDARY_MISSING', '结束对话所需的记录不完整'],
    ['MULTIPLE_ACTIVE_CONVERSATIONS', '发现多次未完成对话，需要老师选择'],
    ['ROSTER_CARDINALITY_INVALID', '今天的值日名单需要老师确认'],
    ['UNAPPROVED_CODE', '这次对话需要老师检查后再继续'],
  ]);
  for (const [code, copy] of expected) {
    const fake = createFakeDOM();
    const view = createChildView(fake.root, actions(), fake.dom);
    view.render(snapshotFor('recovery', { error: { code, retryable: false, message: `secret:${code}` } }));
    const alert = find(fake.root, node => node.getAttribute?.('role') === 'alert');
    assert.equal(find(alert, node => node.getAttribute?.('class') === 'child-message__text').textContent, copy);
    assert.equal(fake.root.textContent.includes(`secret:${code}`), false);
  }
});

test('keeps teacher help visibly and natively available in every rendered state', () => {
  const fake = createFakeDOM();
  assert.throws(() => createChildView(fake.root, actions({ onOpenTeacherHelp: null }), fake.dom), TypeError);
  const view = createChildView(fake.root, actions(), fake.dom);
  view.render(snapshotFor('welcome'));
  const help = byId(fake.root, 'teacher-help-button');
  assert.equal(help.disabled, false);
  assert.equal(help.getAttribute('aria-describedby'), 'child-status');
  assert.equal(byId(fake.root, 'teacher-help-unavailable-note'), null);
  assert.equal(view.focus('#teacher-help-button'), true);
});

test('teacher help remains visible and opens a labelled native dialog without unsafe text rendering', () => {
  const fake = createFakeDOM();
  const view = createChildView(fake.root, actions(), fake.dom);
  view.render(snapshotFor('recovery'));
  const opener = byId(fake.root, 'teacher-help-button');
  assert.equal(opener.disabled, false);
  assert.equal(byId(fake.root, 'teacher-help-unavailable-note'), null);

  view.openTeacherHelp({ unlocked: false });
  const dialog = byId(fake.root, 'teacher-help-dialog');
  const pin = byId(fake.root, 'teacher-pin');
  assert.ok(dialog);
  assert.equal(dialog.tagName, 'DIALOG');
  assert.equal(dialog.getAttribute('aria-modal'), 'true');
  assert.equal(dialog.getAttribute('aria-labelledby'), 'teacher-help-title');
  assert.equal(dialog.getAttribute('aria-describedby'), 'teacher-help-description');
  assert.equal(byId(fake.root, 'teacher-help-title').textContent, '老师帮忙');
  assert.equal(byId(fake.root, 'teacher-help-description').textContent, '老师可以帮助继续这次对话。');
  const dialogHeader = find(
    dialog,
    node => node.getAttribute?.('class') === 'teacher-help-dialog__header',
  );
  const dialogFooter = find(
    dialog,
    node => node.getAttribute?.('class') === 'teacher-help-dialog__footer',
  );
  assert.ok(dialogHeader);
  assert.equal(dialogHeader.contains(byId(fake.root, 'teacher-help-title')), true);
  assert.equal(dialogHeader.contains(byId(fake.root, 'teacher-help-description')), true);
  assert.equal(
    byId(fake.root, 'teacher-unlock-form').getAttribute('class'),
    'teacher-help-dialog__section teacher-help-dialog__section--locked',
  );
  assert.equal(
    byId(fake.root, 'teacher-actions').getAttribute('class'),
    'teacher-help-dialog__section teacher-help-dialog__section--unlocked',
  );
  assert.ok(dialogFooter);
  assert.equal(dialogFooter.contains(byId(fake.root, 'teacher-help-close')), true);
  assert.equal(pin.getAttribute('type'), 'password');
  assert.equal(pin.getAttribute('inputmode'), 'numeric');
  assert.equal(pin.getAttribute('pattern'), '[0-9]{4,6}');
  assert.equal(pin.getAttribute('minlength'), '4');
  assert.equal(pin.getAttribute('maxlength'), '6');
  assert.equal(pin.getAttribute('autocomplete'), 'current-password');
  assert.equal(pin.getAttribute('required'), '');
  assert.equal(byId(fake.root, 'teacher-help-error').getAttribute('role'), 'alert');
  assert.equal(byId(fake.root, 'teacher-help-error').getAttribute('aria-live'), 'assertive');
  assert.equal(byId(fake.root, 'teacher-unlock-form').hidden, false);
  assert.equal(byId(fake.root, 'teacher-actions').hidden, true);
  assert.equal(dialog.open, true);
  assert.equal(dialog.showModalCount, 1);
  assert.equal(fake.focused(), pin);

  const sameDialog = dialog;
  const samePin = pin;
  view.showTeacherHelpError('<img src=x onerror=boom>');
  assert.equal(byId(fake.root, 'teacher-help-error').textContent, '<img src=x onerror=boom>');
  const images = findAll(fake.root, node => node.tagName === 'IMG');
  assert.deepEqual(images.map(image => image.getAttribute('src')), [
    '/assets/notebook-mark.svg',
    '/assets/diary-mark.svg',
    '/assets/duck-front-512.png',
  ]);
  assert.equal(images.every(image => image.getAttribute('alt') === ''), true);
  view.render(snapshotFor('submission_failed'));
  assert.equal(byId(fake.root, 'teacher-help-dialog'), sameDialog);
  assert.equal(byId(fake.root, 'teacher-pin'), samePin);
  assert.equal(dialog.open, true);
  view.openTeacherHelp({ unlocked: false });
  assert.equal(dialog.showModalCount, 1);

  view.showTeacherHelpUnlocked();
  assert.equal(byId(fake.root, 'teacher-unlock-form').hidden, true);
  assert.equal(byId(fake.root, 'teacher-actions').hidden, false);
  assert.equal(fake.focused(), byId(fake.root, 'teacher-text'));
});

test('unlocked teacher close and cancel request one relock and wait for confirmed close', () => {
  const calls = [];
  const fake = createFakeDOM();
  const view = createChildView(fake.root, actions({
    onLockTeacherHelp: () => calls.push('lock'),
  }), fake.dom);
  view.render(snapshotFor('recovery', {
    teacherUnlocked: true,
    error: { code: 'SPEECH_FAILED', retryable: true, message: 'raw' },
  }));
  view.openTeacherHelp({ unlocked: true });
  const dialog = byId(fake.root, 'teacher-help-dialog');
  const text = byId(fake.root, 'teacher-text');
  text.value = '机密补录-4826';

  dispatch(dialog, 'click', { target: byId(fake.root, 'teacher-help-close') });
  assert.deepEqual(calls, ['lock']);
  assert.equal(dialog.open, true);
  for (const id of [
    'teacher-pin',
    'teacher-unlock-button',
    'teacher-text',
    'teacher-submit-text',
    'teacher-save-draft',
    'teacher-retry-recovery',
    'teacher-retry-microphone',
    'teacher-end-session',
    'teacher-lock-button',
    'teacher-help-close',
  ]) {
    assert.equal(byId(fake.root, id).disabled, true, `${id} must be disabled while relocking`);
  }

  dispatch(dialog, 'cancel');
  dispatch(dialog, 'click', { target: byId(fake.root, 'teacher-lock-button') });
  assert.deepEqual(calls, ['lock'], 'pending relock must be single-flight');
  assert.equal(dialog.open, true);

  view.showTeacherHelpError('老师帮助暂时不可用，请稍后重试');
  assert.equal(dialog.open, true);
  assert.equal(text.value, '机密补录-4826');
  assert.equal(byId(fake.root, 'teacher-help-close').disabled, false);
  assert.equal(text.disabled, false);

  dispatch(dialog, 'cancel');
  assert.deepEqual(calls, ['lock', 'lock']);
  assert.equal(dialog.open, true);
  view.showTeacherHelpError('老师帮助暂时不可用，请稍后重试');
  view.closeTeacherHelp({ clearText: true, restoreFocus: true });
});

test('failed relock preserves an edited submission draft through pending and error updates', () => {
  const calls = [];
  const fake = createFakeDOM();
  const view = createChildView(fake.root, actions({
    onLockTeacherHelp: () => calls.push('lock'),
  }), fake.dom);
  view.render(snapshotFor('submission_failed', {
    teacherUnlocked: true,
    draft,
    error: { code: 'NETWORK_ERROR', retryable: true, message: 'raw' },
  }));
  view.openTeacherHelp({ unlocked: true });
  const dialog = byId(fake.root, 'teacher-help-dialog');
  const text = byId(fake.root, 'teacher-text');
  const edited = '老师修改后还没有保存的补录';
  assert.equal(text.value, draft.text);
  text.value = edited;

  dispatch(dialog, 'click', { target: byId(fake.root, 'teacher-help-close') });
  assert.deepEqual(calls, ['lock']);
  assert.equal(dialog.open, true);
  assert.equal(text.disabled, true);
  assert.equal(text.value, edited);

  view.showTeacherHelpError('老师帮助暂时不可用，请稍后重试');
  assert.equal(dialog.open, true);
  assert.equal(text.disabled, false);
  assert.equal(text.value, edited);
});

test('locked teacher close and cancel stay local without requesting a relock', () => {
  const calls = [];
  const fake = createFakeDOM();
  const view = createChildView(fake.root, actions({
    onLockTeacherHelp: () => calls.push('lock'),
  }), fake.dom);
  view.render(snapshotFor('recovery'));
  const opener = byId(fake.root, 'teacher-help-button');

  view.openTeacherHelp({ unlocked: false });
  const dialog = byId(fake.root, 'teacher-help-dialog');
  byId(fake.root, 'teacher-pin').value = '4826';
  dispatch(dialog, 'click', { target: byId(fake.root, 'teacher-help-close') });
  assert.deepEqual(calls, []);
  assert.equal(dialog.open, false);
  assert.equal(byId(fake.root, 'teacher-pin').value, '');
  assert.equal(fake.focused(), opener);

  view.openTeacherHelp({ unlocked: false });
  const cancel = dispatch(dialog, 'cancel');
  assert.equal(cancel.defaultPrevented, true);
  assert.deepEqual(calls, []);
  assert.equal(dialog.open, false);
});

test('teacher dialog delegates PIN, text, draft, retry, microphone, end, and lock actions without storing input', () => {
  const calls = [];
  const fake = createFakeDOM();
  const view = createChildView(fake.root, actions({
    onSubmitTeacherPin: value => calls.push(['pin', value]),
    onSubmitTeacherText: value => calls.push(['text', value]),
    onSaveTeacherDraft: value => calls.push(['draft', value]),
    onRetry: () => calls.push(['retry']),
    onRetryTeacherRecovery: () => calls.push(['recovery']),
    onRetryMicrophone: () => calls.push(['microphone']),
    onEndWithTeacher: () => calls.push(['end']),
    onLockTeacherHelp: () => calls.push(['lock']),
  }), fake.dom);
  const recovery = snapshotFor('recovery', {
    teacherUnlocked: true,
    draft: null,
    error: { code: 'SPEECH_FAILED', retryable: true, message: 'raw' },
  });
  view.render(recovery);
  view.openTeacherHelp({ unlocked: false });
  const dialog = byId(fake.root, 'teacher-help-dialog');
  const pin = byId(fake.root, 'teacher-pin');
  const text = byId(fake.root, 'teacher-text');
  pin.value = '4826';
  const submitted = dispatch(byId(fake.root, 'teacher-unlock-form'), 'submit');
  assert.equal(submitted.defaultPrevented, true);
  assert.deepEqual(calls.pop(), ['pin', '4826']);
  assert.equal(fake.root.textContent.includes('4826'), false);

  view.showTeacherHelpUnlocked();
  text.value = '机密补录-4826';
  dispatch(dialog, 'click', { target: byId(fake.root, 'teacher-submit-text') });
  dispatch(dialog, 'click', { target: byId(fake.root, 'teacher-save-draft') });
  dispatch(dialog, 'click', { target: byId(fake.root, 'teacher-retry-recovery') });
  dispatch(dialog, 'click', { target: byId(fake.root, 'teacher-retry-microphone') });
  view.showTeacherHelpError('');
  dispatch(dialog, 'click', { target: byId(fake.root, 'teacher-end-session') });
  view.showTeacherHelpError('');
  dispatch(dialog, 'click', { target: byId(fake.root, 'teacher-lock-button') });
  view.showTeacherHelpError('');
  assert.deepEqual(calls, [
    ['text', '机密补录-4826'],
    ['draft', '机密补录-4826'],
    ['recovery'],
    ['microphone'],
    ['end'],
    ['lock'],
  ]);
  assert.equal(fake.root.textContent.includes('机密补录-4826'), false);

  const sameDialog = dialog;
  const sameText = text;
  view.render(snapshotFor('submitting', { teacherUnlocked: true, draft }));
  assert.equal(byId(fake.root, 'teacher-help-dialog'), sameDialog);
  assert.equal(byId(fake.root, 'teacher-text'), sameText);
  assert.equal(text.value, draft.text);
  assert.equal(byId(fake.root, 'teacher-submit-text').disabled, true);
  assert.equal(byId(fake.root, 'teacher-save-draft').disabled, true);

  calls.length = 0;
  view.render(snapshotFor('submission_failed', {
    teacherUnlocked: true,
    draft,
    error: { code: 'NETWORK_ERROR', retryable: true, message: 'raw' },
  }));
  assert.equal(byId(fake.root, 'teacher-help-dialog'), sameDialog);
  assert.equal(byId(fake.root, 'teacher-text'), sameText);
  assert.equal(text.value, draft.text);
  assert.equal(byId(fake.root, 'teacher-submit-text').textContent, '重新发送这句话');
  assert.equal(byId(fake.root, 'teacher-submit-text').disabled, false);
  dispatch(dialog, 'click', { target: byId(fake.root, 'teacher-submit-text') });
  assert.deepEqual(calls, [['retry']]);

  view.render(snapshotFor('ready', { teacherUnlocked: true }));
  assert.equal(byId(fake.root, 'teacher-actions-note').textContent, '请先在安全恢复状态下操作');
  assert.equal(byId(fake.root, 'teacher-submit-text').disabled, true);
  assert.equal(byId(fake.root, 'teacher-retry-recovery').disabled, true);
});

test('teacher dialog traps Tab, restores focus, clears secrets, and leaves global Space to the injected keyboard policy', () => {
  const calls = [];
  const fake = createFakeDOM();
  const view = createChildView(fake.root, actions({
    onRecordToggle: () => calls.push('record'),
    onLockTeacherHelp: () => calls.push('lock'),
  }), fake.dom);
  view.render(snapshotFor('recovery', {
    teacherUnlocked: true,
    error: { code: 'SPEECH_FAILED', retryable: true, message: 'raw' },
  }));
  fake.flush();
  const firstOpener = byId(fake.root, 'teacher-help-button');
  view.openTeacherHelp({ unlocked: true });
  const dialog = byId(fake.root, 'teacher-help-dialog');
  const text = byId(fake.root, 'teacher-text');
  const close = byId(fake.root, 'teacher-help-close');
  assert.equal(fake.focused(), text);

  let keyEvent = dispatch(dialog, 'keydown', { key: 'Tab', shiftKey: true, target: text });
  assert.equal(keyEvent.defaultPrevented, true);
  assert.equal(fake.focused(), close);
  keyEvent = dispatch(dialog, 'keydown', { key: 'Tab', shiftKey: false, target: close });
  assert.equal(keyEvent.defaultPrevented, true);
  assert.equal(fake.focused(), text);
  dispatch(dialog, 'keydown', { key: ' ', code: 'Space', target: byId(fake.root, 'teacher-help-title') });
  assert.deepEqual(calls, []);

  text.value = '机密补录-4826';
  byId(fake.root, 'teacher-pin').value = '4826';
  view.showTeacherHelpError('固定错误');
  const cancel = dispatch(dialog, 'cancel');
  assert.equal(cancel.defaultPrevented, true);
  assert.deepEqual(calls, ['lock']);
  assert.equal(dialog.open, true);
  assert.equal(dialog.closeCount, 0);
  view.closeTeacherHelp({ clearText: true, restoreFocus: true });
  assert.equal(dialog.open, false);
  assert.equal(dialog.closeCount, 1);
  assert.equal(text.value, '');
  assert.equal(byId(fake.root, 'teacher-pin').value, '');
  assert.equal(byId(fake.root, 'teacher-help-error').textContent, '');
  assert.equal(fake.focused(), firstOpener);

  view.openTeacherHelp({ unlocked: true });
  const staleOpener = firstOpener;
  view.render(snapshotFor('recovery', {
    teacherUnlocked: true,
    error: { code: 'SPEECH_FAILED', retryable: true, message: 'raw' },
  }));
  assert.equal(fake.root.contains(staleOpener), false);
  dispatch(dialog, 'click', { target: close });
  assert.deepEqual(calls, ['lock', 'lock']);
  assert.equal(dialog.closeCount, 1);
  assert.equal(dialog.open, true);
  view.closeTeacherHelp({ clearText: true, restoreFocus: true });
  assert.equal(dialog.closeCount, 2);
  assert.equal(fake.focused(), byId(fake.root, 'teacher-help-button'));

  view.openTeacherHelp({ unlocked: true });
  view.closeTeacherHelp({ clearText: true, restoreFocus: true });
  assert.equal(dialog.closeCount, 3);
  assert.equal(dialog.open, false);
  assert.deepEqual(calls, ['lock', 'lock']);

  view.openTeacherHelp({ unlocked: false });
  const closeCount = dialog.closeCount;
  view.destroy();
  assert.equal(dialog.closeCount, closeCount + 1);
  dispatch(dialog, 'cancel');
  dispatch(dialog, 'keydown', { key: 'Tab', target: byId(dialog, 'teacher-pin') });
  assert.deepEqual(calls, ['lock', 'lock']);
});

test('styles retain the standalone static accessibility and safety contract', () => {
  const css = readFileSync(new URL('../../../app/frontend/child/styles.css', import.meta.url), 'utf8');
  const tokens = new Map([
    ['--child-paper', '#fff8e8'],
    ['--child-ink', '#24352b'],
    ['--child-action', '#2e6f86'],
    ['--child-action-border', '#244d5c'],
    ['--child-sage', '#e4ead8'],
    ['--child-sage-border', '#6b8a5b'],
    ['--child-story', '#f7e8be'],
    ['--child-muted', '#58635d'],
    ['--child-danger', '#9f2d20'],
  ]);
  for (const [name, value] of tokens) {
    assert.match(css, new RegExp(`${name}\\s*:\\s*${value}`, 'i'));
  }
  assert.match(css, /font-family\s*:\s*"Noto Sans SC"\s*,\s*"PingFang SC"\s*,\s*"Microsoft YaHei"\s*,\s*sans-serif/);
  assert.match(css, /font-size\s*:\s*32px[\s\S]*line-height\s*:\s*42px/);
  assert.match(css, /font-size\s*:\s*20px[\s\S]*line-height\s*:\s*30px/);
  assert.match(css, /font-size\s*:\s*18px[\s\S]*line-height\s*:\s*26px/);
  assert.match(css, /font-size\s*:\s*14px[\s\S]*line-height\s*:\s*21px/);
  assert.match(css, /#child-app\s+\.child-view\s+button[\s\S]*min-width\s*:\s*44px/);
  assert.match(css, /min-height\s*:\s*44px/);
  assert.match(css, /:focus-visible[\s\S]*outline\s*:\s*4px/);
  assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)/);
  assert.match(css, /1024px/);
  assert.match(css, /1280px/);
  assert.match(css, /#child-app\s+#teacher-help-dialog[\s\S]*max-block-size[\s\S]*overflow\s*:\s*auto/);
  assert.match(css, /#child-app\s+#teacher-help-dialog\s+textarea[\s\S]*inline-size\s*:\s*100%/);
  assert.match(css, /#child-app\s+#teacher-help-dialog\s+(?:button|input|textarea)[\s\S]*min-block-size\s*:\s*44px/);
  assert.match(css, /#child-app\s+#teacher-help-error[\s\S]*color\s*:\s*#7b1f16/i);
  assert.match(css, /#child-app\s+#teacher-help-dialog\s+:focus-visible[\s\S]*outline/);
  assert.doesNotMatch(css, /overflow\s*:\s*hidden/i);
  assert.doesNotMatch(css, /@import|url\s*\(/i);
});

test('shell styles preserve roster cards and private teacher dialog presentation', () => {
  const css = readFileSync(new URL('../../../app/frontend/child/styles.css', import.meta.url), 'utf8');
  const ruleBody = (selector, occurrence = 0) => {
    let selectorStart = -1;
    for (let index = 0; index <= occurrence; index += 1) {
      selectorStart = css.indexOf(selector, selectorStart + 1);
    }
    assert.notEqual(selectorStart, -1, `missing CSS selector: ${selector}`);
    const bodyStart = css.indexOf('{', selectorStart);
    const bodyEnd = css.indexOf('}', bodyStart);
    return css.slice(bodyStart + 1, bodyEnd);
  };

  const button = ruleBody('#child-app .child-view button {');
  assert.match(button, /padding\s*:\s*10px\s+18px/);
  assert.match(button, /border\s*:\s*3px\s+solid\s+var\(--child-action\)/);
  assert.doesNotMatch(button, /box-shadow|transform|font-size/);
  assert.equal(css.includes('#child-app .child-view button:hover'), false);

  const card = ruleBody('#child-app .child-view .child-card {');
  assert.match(card, /display\s*:\s*grid/);
  assert.match(card, /grid-template-columns\s*:\s*64px\s+minmax\(0,\s*1fr\)/);
  assert.match(card, /border-color\s*:\s*#7a4700/i);
  assert.match(card, /background\s*:\s*#ffbf24/i);
  assert.doesNotMatch(card, /box-shadow/);
  assert.equal(css.includes('#child-app .child-view .child-card:hover'), false);

  const rosterPanel = ruleBody('#child-app .child-roster-panel {');
  assert.match(rosterPanel, /grid-column\s*:\s*1/);
  assert.match(rosterPanel, /grid-row\s*:\s*1/);
  assert.match(rosterPanel, /overflow\s*:\s*auto/);
  const rosterGrid = ruleBody('#child-app .child-roster-panel > ul {');
  assert.match(rosterGrid, /grid-template-columns\s*:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/);
  const avatar = ruleBody('#child-app .child-card__avatar {');
  assert.match(avatar, /inline-size\s*:\s*56px/);
  assert.match(avatar, /block-size\s*:\s*56px/);
  assert.match(avatar, /border-radius\s*:\s*50%/);

  const dialog = ruleBody('#child-app #teacher-help-dialog {');
  assert.match(dialog, /padding\s*:\s*clamp\(18px,\s*3vw,\s*30px\)/);
  assert.match(dialog, /border\s*:\s*3px\s+solid\s+var\(--child-action-border\)/);
  assert.match(dialog, /color\s*:\s*var\(--child-ink\)/);
  assert.match(dialog, /background\s*:\s*#ffffff/i);
  assert.match(dialog, /font-family\s*:\s*"Noto Sans SC",\s*"PingFang SC",\s*"Microsoft YaHei",\s*sans-serif/);
  assert.match(dialog, /font-size\s*:\s*18px/);
  assert.match(dialog, /line-height\s*:\s*26px/);

  const dialogInputs = ruleBody('#child-app #teacher-help-dialog input,\n#child-app #teacher-help-dialog textarea {', 1);
  assert.match(dialogInputs, /border\s*:\s*2px\s+solid\s+var\(--child-sage-border\)/);
  assert.match(dialogInputs, /color\s*:\s*var\(--child-ink\)/);
  const dialogButton = ruleBody('#child-app #teacher-help-dialog button {');
  assert.match(dialogButton, /padding\s*:\s*10px\s+16px/);
  assert.match(dialogButton, /border\s*:\s*3px\s+solid\s+var\(--child-action\)/);
  assert.match(dialogButton, /background\s*:\s*var\(--child-action\)/);
  assert.match(dialogButton, /font-weight\s*:\s*800/);
  assert.match(ruleBody('#child-app #teacher-help-error {'), /min-block-size\s*:\s*44px/);
  const dialogHeader = ruleBody('#child-app .teacher-help-dialog__header {');
  assert.match(dialogHeader, /border-block-end\s*:\s*2px\s+solid\s+var\(--child-sage-border\)/);
  const dialogSection = ruleBody('#child-app .teacher-help-dialog__section {');
  assert.match(dialogSection, /border\s*:\s*2px\s+solid\s+var\(--child-sage-border\)/);
  assert.match(dialogSection, /border-radius\s*:\s*16px/);
  const dialogFooter = ruleBody('#child-app .teacher-help-dialog__footer {');
  assert.match(dialogFooter, /display\s*:\s*flex/);
  assert.match(dialogFooter, /justify-content\s*:\s*flex-end/);
  assert.match(css, /inline-size\s*:\s*min\(96vw,\s*680px\)/);
});
