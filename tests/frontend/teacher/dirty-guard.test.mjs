import assert from 'node:assert/strict';
import test from 'node:test';

import { createDirtyGuard } from '../../../app/frontend/teacher/dirty-guard.mjs';

class FakeNode {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.attributes = new Map();
    this.children = [];
    this.listeners = new Map();
    this.parentNode = null;
    this.open = false;
    this.removed = false;
  }

  append(...children) {
    for (const child of children) {
      if (child && typeof child === 'object') child.parentNode = this;
      this.children.push(child);
    }
  }

  replaceChildren(...children) {
    this.children = [];
    this.append(...children);
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || new Set();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type, listener) {
    this.listeners.get(type)?.delete(listener);
  }

  dispatch(type, event = {}) {
    for (const listener of [...(this.listeners.get(type) || [])]) listener(event);
  }

  click() {
    this.dispatch('click', { preventDefault() {} });
  }

  showModal() {
    this.open = true;
  }

  close() {
    this.open = false;
  }

  remove() {
    this.removed = true;
    if (!this.parentNode) return;
    this.parentNode.children = this.parentNode.children.filter(child => child !== this);
    this.parentNode = null;
  }
}

class FakeWindow {
  constructor() {
    this.listeners = new Map();
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || new Set();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type, listener) {
    this.listeners.get(type)?.delete(listener);
  }

  listenerCount(type) {
    return this.listeners.get(type)?.size || 0;
  }

  dispatch(type, event = {}) {
    for (const listener of [...(this.listeners.get(type) || [])]) listener(event);
  }
}

function fakeDocument() {
  return {
    body: new FakeNode('body'),
    createElement(tagName) {
      return new FakeNode(tagName);
    },
  };
}

function textOf(node) {
  if (typeof node === 'string') return node;
  return (node?.children || []).map(textOf).join('');
}

function findNode(root, tagName, text) {
  if (!root || typeof root === 'string') return null;
  if (root.tagName === tagName && (text === null || textOf(root) === text)) return root;
  for (const child of root.children || []) {
    const found = findNode(child, tagName, text);
    if (found) return found;
  }
  return null;
}

function assertFreshTypeError(action, original) {
  assert.throws(action, error => error instanceof TypeError && error !== original);
}

test('Dirty guard accepts only exact own-data dependencies without executing hostile accessors', () => {
  const window = new FakeWindow();
  const document = fakeDocument();
  const guard = createDirtyGuard({ window, document });
  assert.equal(typeof guard.activate, 'function');
  assert.equal(typeof guard.release, 'function');

  const accessorError = new Error('hostile window getter');
  const accessor = { document };
  Object.defineProperty(accessor, 'window', { enumerable: true, get() { throw accessorError; } });
  assertFreshTypeError(() => createDirtyGuard(accessor), accessorError);

  const proxyError = new Error('hostile own keys');
  assertFreshTypeError(() => createDirtyGuard(new Proxy({}, { ownKeys() { throw proxyError; } })), proxyError);
  assertFreshTypeError(() => createDirtyGuard({ window }));
  assertFreshTypeError(() => createDirtyGuard({ window: null, document }));
});

test('Dirty guard tracks canonical snapshots with one beforeunload listener and clean fast path', async () => {
  const window = new FakeWindow();
  const document = fakeDocument();
  const guard = createDirtyGuard({ window, document });

  guard.activate('{"insight":"初始"}');
  guard.activate('{"insight":"重复激活"}');
  assert.equal(window.listenerCount('beforeunload'), 1);
  assert.equal(guard.isDirty(), false);
  assert.equal(await guard.confirmLeave(), true);
  assert.equal(document.body.children.length, 0);

  const cleanEvent = { prevented: false, preventDefault() { this.prevented = true; }, returnValue: undefined };
  window.dispatch('beforeunload', cleanEvent);
  assert.equal(cleanEvent.prevented, false);
  assert.equal(cleanEvent.returnValue, undefined);

  guard.update('{"insight":"修改"}');
  assert.equal(guard.isDirty(), true);
  const dirtyEvent = { prevented: false, preventDefault() { this.prevented = true; }, returnValue: undefined };
  window.dispatch('beforeunload', dirtyEvent);
  assert.equal(dirtyEvent.prevented, true);
  assert.notEqual(dirtyEvent.returnValue, undefined);

  guard.markClean('{"insight":"修改"}');
  assert.equal(guard.isDirty(), false);
  guard.release();
  assert.equal(window.listenerCount('beforeunload'), 0);
});

test('Dirty guard shares one dialog promise and handles continue discard Escape release and reactivation', async () => {
  const window = new FakeWindow();
  const document = fakeDocument();
  const guard = createDirtyGuard({ window, document });
  guard.activate('clean');
  guard.update('dirty');

  const first = guard.confirmLeave();
  const second = guard.confirmLeave();
  assert.equal(first, second);
  const dialog = document.body.children[0];
  assert.equal(dialog.tagName, 'DIALOG');
  assert.equal(dialog.open, true);
  assert.match(dialog.getAttribute('class') || '', /(^|\s)teacher-dirty-dialog(\s|$)/);
  const descriptionId = dialog.getAttribute('aria-describedby');
  assert.ok(descriptionId);
  const description = findNode(dialog, 'P', null);
  assert.ok(description);
  assert.equal(description.getAttribute('id'), descriptionId);
  assert.match(description.getAttribute('class') || '', /(^|\s)teacher-dirty-dialog-description(\s|$)/);
  assert.match(textOf(description), /未保存/);
  assert.match(textOf(description), /放弃/);
  const actions = dialog.children.find(child => child?.getAttribute?.('class')
    ?.split(/\s+/).includes('teacher-dirty-dialog-actions'));
  assert.ok(actions);
  assert.match(textOf(dialog), /有未保存的修改/);
  const continueButton = findNode(dialog, 'BUTTON', '继续编辑');
  const discardButton = findNode(dialog, 'BUTTON', '放弃修改');
  assert.ok(continueButton && discardButton);
  assert.ok(actions.children.includes(continueButton));
  assert.ok(actions.children.includes(discardButton));
  continueButton.click();
  assert.equal(await first, false);
  assert.equal(guard.isDirty(), true);
  assert.equal(dialog.removed, true);

  const escaped = guard.confirmLeave();
  const escapeDialog = document.body.children[0];
  escapeDialog.dispatch('cancel', { preventDefault() {} });
  assert.equal(await escaped, false);
  assert.equal(guard.isDirty(), true);

  const discarded = guard.confirmLeave();
  const discardDialog = document.body.children[0];
  findNode(discardDialog, 'BUTTON', '放弃修改').click();
  assert.equal(await discarded, true);
  assert.equal(guard.isDirty(), false);

  guard.update('dirty-again');
  const pending = guard.confirmLeave();
  const pendingDialog = document.body.children[0];
  guard.release();
  guard.release();
  assert.equal(await pending, false);
  assert.equal(pendingDialog.removed, true);
  assert.equal(window.listenerCount('beforeunload'), 0);

  guard.activate('fresh');
  assert.equal(guard.isDirty(), false);
  assert.equal(window.listenerCount('beforeunload'), 1);
  guard.release();
});
