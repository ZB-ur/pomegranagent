import assert from 'node:assert/strict';
import test from 'node:test';

import { createTeacherRouter } from '../../../app/frontend/teacher/router.mjs';
import { createLegacyTeacherRoutes } from '../../../app/frontend/teacher/legacy-routes.mjs';

class Events {
  #listeners = new Map();

  addEventListener(type, listener) {
    const listeners = this.#listeners.get(type) || new Set();
    listeners.add(listener);
    this.#listeners.set(type, listeners);
  }

  removeEventListener(type, listener) {
    this.#listeners.get(type)?.delete(listener);
  }

  emit(type, event = {}) {
    for (const listener of [...(this.#listeners.get(type) || [])]) listener(event);
  }
}

class FakeWindow extends Events {
  constructor(hash = '') {
    super();
    this.location = { pathname: '/teacher.html', hash };
    this.history = {
      calls: [],
      replaceState: (_state, _title, next) => {
        this.history.calls.push(next);
        this.location.hash = String(next).includes('#') ? String(next).slice(String(next).indexOf('#')) : '';
      },
    };
  }

  changeHash(hash) {
    this.location.hash = hash;
    this.emit('hashchange');
  }
}

class FakeButton {
  constructor(route) {
    this.dataset = { v: route };
    this.attributes = new Map();
    this.classList = {
      values: new Set(),
      add: value => this.classList.values.add(value),
      remove: value => this.classList.values.delete(value),
      contains: value => this.classList.values.has(value),
    };
  }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  removeAttribute(name) { this.attributes.delete(name); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  closest(selector) { return selector === 'button' ? this : null; }
}

class FakeNav extends Events {
  constructor(routeNames) {
    super();
    this.buttons = routeNames.map(name => new FakeButton(name));
  }

  querySelectorAll(selector) { return selector === 'button' ? this.buttons : []; }
  click(route) { this.emit('click', { target: this.buttons.find(button => button.dataset.v === route) }); }
}

class FakeRoot {
  constructor() {
    this.replacements = 0;
    this.heading = null;
  }

  replaceChildren(...children) {
    this.replacements += 1;
    this.heading = children.find(child => child?.tagName === 'H1' || child?.tagName === 'H2') || null;
  }

  querySelector(selector) {
    return selector === 'h1, h2' ? this.heading : null;
  }
}

function heading(label) {
  return {
    tagName: 'H2',
    label,
    attributes: new Map(),
    focused: 0,
    setAttribute(name, value) { this.attributes.set(name, String(value)); },
    focus() { this.focused += 1; },
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

async function settle() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

const names = ['overview', 'children', 'ducks', 'roster', 'review', 'growth', 'search'];
const legacyNames = ['children', 'ducks', 'roster', 'growth', 'search'];

function makeRoutes(overrides = {}) {
  return Object.fromEntries(names.map(name => [name, context => {
    const title = heading(name);
    context.root.heading = title;
    return overrides[name]?.(context, title);
  }]));
}

test('empty and unknown fragments are replaced with the overview fragment', async () => {
  for (const initialHash of ['', '#not-a-route?child_id=7']) {
    const window = new FakeWindow(initialHash);
    const root = new FakeRoot();
    const nav = new FakeNav(names);
    const router = createTeacherRouter({ window, root, nav, routes: makeRoutes() });

    assert.equal(await router.start(), true);
    assert.equal(window.location.hash, '#overview');
    assert.deepEqual(window.history.calls, ['#overview']);
    assert.equal(router.current().route, 'overview');
    assert.equal(nav.buttons.filter(button => button.classList.contains('active')).length, 1);
    assert.equal(nav.buttons.find(button => button.dataset.v === 'overview').getAttribute('aria-current'), 'page');
  }
});

test('a valid fragment query is parsed fresh and preserved byte-for-byte', async () => {
  const window = new FakeWindow('#growth?child_id=7&source=history');
  const root = new FakeRoot();
  const nav = new FakeNav(names);
  let loaderParams;
  const routes = makeRoutes({
    growth: context => {
      loaderParams = context.params;
      context.root.heading = heading('growth');
    },
  });
  const router = createTeacherRouter({ window, root, nav, routes });

  assert.equal(await router.start(), true);
  assert.equal(window.location.hash, '#growth?child_id=7&source=history');
  assert.deepEqual(window.history.calls, []);
  assert.equal(loaderParams.get('child_id'), '7');
  loaderParams.set('mutated', 'yes');
  assert.equal(router.current().params.get('mutated'), null);
  assert.equal(root.heading.focused, 1);
});

test('an accepted navigation aborts and cleans the previous epoch exactly once', async () => {
  const window = new FakeWindow('#overview');
  const root = new FakeRoot();
  const nav = new FakeNav(names);
  let overviewSignal;
  let cleanupCalls = 0;
  const router = createTeacherRouter({
    window,
    root,
    nav,
    routes: makeRoutes({
      overview: context => {
        overviewSignal = context.signal;
        context.root.heading = heading('overview');
        return { cleanup: () => { cleanupCalls += 1; } };
      },
    }),
  });

  await router.start();
  window.changeHash('#children');
  await settle();
  assert.equal(overviewSignal.aborted, true);
  assert.equal(cleanupCalls, 1);
  assert.equal(router.current().route, 'children');
  router.stop();
  assert.equal(cleanupCalls, 1);
});

test('a slow old epoch cannot install cleanup, focus a heading, or report an error', async () => {
  const window = new FakeWindow('#overview');
  const root = new FakeRoot();
  const nav = new FakeNav(names);
  const slow = deferred();
  const errors = [];
  let oldHeading;
  let lateCleanupCalls = 0;
  const router = createTeacherRouter({
    window,
    root,
    nav,
    onError: error => errors.push(error),
    routes: makeRoutes({
      overview: (context, title) => {
        oldHeading = title;
        context.root.heading = title;
        return slow.promise;
      },
    }),
  });

  void router.start();
  await settle();
  window.changeHash('#children');
  await settle();
  slow.resolve({ cleanup: () => { lateCleanupCalls += 1; } });
  await settle();

  assert.equal(lateCleanupCalls, 1);
  assert.equal(oldHeading.focused, 0);
  assert.deepEqual(errors, []);
  assert.equal(router.current().route, 'children');
  assert.equal(root.heading.label, 'children');
});

test('AbortError is silent while a current non-abort loader error reports once', async () => {
  const window = new FakeWindow('#overview');
  const root = new FakeRoot();
  const nav = new FakeNav(names);
  const errors = [];
  const router = createTeacherRouter({
    window,
    root,
    nav,
    onError: error => errors.push(error),
    routes: makeRoutes({
      overview: () => Promise.reject(new DOMException('aborted', 'AbortError')),
      children: () => Promise.reject(new Error('current failure')),
    }),
  });

  await router.start();
  window.changeHash('#children');
  await settle();
  assert.deepEqual(errors.map(error => error.message), ['current failure']);
});

test('clicking the current route refreshes with a new epoch without writing history', async () => {
  const window = new FakeWindow('#overview');
  const root = new FakeRoot();
  const nav = new FakeNav(names);
  const epochs = [];
  const router = createTeacherRouter({
    window,
    root,
    nav,
    routes: makeRoutes({ overview: context => { epochs.push(context.epoch); context.root.heading = heading('overview'); } }),
  });

  await router.start();
  nav.click('overview');
  await settle();
  assert.deepEqual(epochs, [1, 2]);
  assert.deepEqual(window.history.calls, []);
  assert.equal(window.location.hash, '#overview');
});

test('only the newest pending leave confirmation may start a route', async () => {
  const window = new FakeWindow('#overview');
  const root = new FakeRoot();
  const nav = new FakeNav(names);
  const confirmations = [];
  const calls = [];
  const router = createTeacherRouter({
    window,
    root,
    nav,
    confirmLeave: () => {
      const next = deferred();
      confirmations.push(next);
      return next.promise;
    },
    routes: makeRoutes({
      children: context => { calls.push(`children:${context.epoch}`); context.root.heading = heading('children'); },
      ducks: context => { calls.push(`ducks:${context.epoch}`); context.root.heading = heading('ducks'); },
    }),
  });

  await router.start();
  window.changeHash('#children');
  window.changeHash('#ducks');
  assert.equal(confirmations.length, 2);
  confirmations[0].resolve(true);
  await settle();
  assert.deepEqual(calls, []);
  confirmations[1].resolve(true);
  await settle();
  assert.deepEqual(calls, ['ducks:2']);
  assert.equal(router.current().route, 'ducks');
});

test('returning to the active hash invalidates an older pending leave confirmation', async () => {
  const window = new FakeWindow('#overview');
  const root = new FakeRoot();
  const nav = new FakeNav(names);
  const leave = deferred();
  let childrenCalls = 0;
  const router = createTeacherRouter({
    window,
    root,
    nav,
    confirmLeave: () => leave.promise,
    routes: makeRoutes({
      children: context => { childrenCalls += 1; context.root.heading = heading('children'); },
    }),
  });

  await router.start();
  window.changeHash('#children');
  await settle();
  window.changeHash('#overview');
  await settle();
  leave.resolve(true);
  await settle();

  assert.equal(window.location.hash, '#overview');
  assert.equal(router.current().route, 'overview');
  assert.equal(childrenCalls, 0);
});

test('clicking the current route restores its hash and invalidates a pending leave confirmation', async () => {
  const window = new FakeWindow('#overview');
  const root = new FakeRoot();
  const nav = new FakeNav(names);
  const leave = deferred();
  let overviewCalls = 0;
  let childrenCalls = 0;
  const router = createTeacherRouter({
    window,
    root,
    nav,
    confirmLeave: () => leave.promise,
    routes: makeRoutes({
      overview: context => { overviewCalls += 1; context.root.heading = heading('overview'); },
      children: context => { childrenCalls += 1; context.root.heading = heading('children'); },
    }),
  });

  await router.start();
  window.changeHash('#children');
  await settle();
  nav.click('overview');
  await settle();
  leave.resolve(true);
  await settle();

  assert.equal(window.location.hash, '#overview');
  assert.equal(router.current().route, 'overview');
  assert.equal(overviewCalls, 2);
  assert.equal(childrenCalls, 0);
});

test('stop prevents late loader and confirmation effects and is idempotent', async () => {
  const window = new FakeWindow('#overview');
  const root = new FakeRoot();
  const nav = new FakeNav(names);
  const slow = deferred();
  const leave = deferred();
  const errors = [];
  let lateCleanup = 0;
  let childrenCalls = 0;
  const router = createTeacherRouter({
    window,
    root,
    nav,
    confirmLeave: () => leave.promise,
    onError: error => errors.push(error),
    routes: makeRoutes({
      overview: context => {
        context.root.heading = heading('overview');
        return slow.promise;
      },
      children: context => { childrenCalls += 1; context.root.heading = heading('children'); },
    }),
  });

  void router.start();
  await settle();
  window.changeHash('#children');
  await settle();
  router.stop();
  router.stop();
  slow.resolve({ cleanup: () => { lateCleanup += 1; } });
  leave.resolve(true);
  await settle();

  assert.equal(lateCleanup, 1);
  assert.equal(childrenCalls, 0);
  assert.equal(router.current(), null);
  assert.deepEqual(errors, []);
  assert.ok(nav.buttons.every(button => button.getAttribute('aria-current') === null));
});

test('all legacy route entries invoke the injected request with their route signal', async () => {
  const calls = [];
  const pending = new Promise(() => {});
  const originalOption = globalThis.Option;
  globalThis.Option = class Option {
    constructor(text, value) {
      this.text = text;
      this.value = value;
    }
  };
  const document = {
    createElement(tagName) {
      return {
        tagName: tagName.toUpperCase(),
        children: [],
        classList: { add() {}, remove() {}, toggle() {} },
        style: {},
        append(...children) { this.children.push(...children); },
        replaceChildren(...children) { this.children = children; },
        setAttribute() {},
        addEventListener() {},
      };
    },
  };
  const routes = createLegacyTeacherRoutes({
    document,
    alert() {},
    request(path, options) {
      calls.push({ path, options });
      return pending;
    },
  });

  try {
    assert.deepEqual(Object.keys(routes).sort(), legacyNames.slice().sort());
    assert.equal(routes.overview, undefined);
    for (const route of legacyNames) {
      const controller = new AbortController();
      routes[route]({
        root: { replaceChildren() {} },
        route,
        params: new URLSearchParams(),
        signal: controller.signal,
        epoch: 1,
        isCurrent: () => true,
      });
    }
    await settle();

    assert.deepEqual(new Set(calls.map(call => call.path)), new Set([
      '/api/children',
      '/api/ducks',
      '/api/roster',
      '/api/conversations',
    ]));
    assert.ok(calls.every(call => call.options.signal instanceof AbortSignal));
  } finally {
    globalThis.Option = originalOption;
  }
});
