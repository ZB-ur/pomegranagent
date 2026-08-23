import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../../../app/frontend/shared/api.js', import.meta.url), 'utf8');
const teacherHtml = readFileSync(new URL('../../../app/frontend/teacher.html', import.meta.url), 'utf8');
const teacherSource = teacherHtml.match(/<script>([\s\S]*)<\/script>\s*<\/body>/)[1];
const jsonResponse = value => ({
  ok: true, status: 200,
  headers: new Headers({ 'content-type': 'application/json' }),
  json: async () => value,
});

function loadDuckAPI(fetchImpl) {
  const window = { dispatchEvent() {} };
  const document = {
    documentElement: { dataset: {} },
    getElementById: () => null,
    createElement: () => ({ id: '', innerHTML: '', setAttribute() {} }),
    body: { replaceChildren() {} },
  };
  vm.runInNewContext(source, {
    window, fetch: fetchImpl, Headers, FormData, AbortController, DOMException,
    CustomEvent: class CustomEvent {}, setTimeout, clearTimeout,
    document, console,
  });
  return { api: window.DuckAPI, document };
}

function loadVersionGateHarness(fetchImpl) {
  const dispatched = [];
  const stateWrites = [];
  let appState;
  let maintenancePanel = null;
  const dataset = {};
  Object.defineProperty(dataset, 'appState', {
    get: () => appState,
    set: value => {
      appState = value;
      stateWrites.push(value);
    },
  });
  const window = {
    dispatchEvent(event) { dispatched.push(event); },
  };
  const document = {
    documentElement: { dataset },
    getElementById: id => (id === 'runtime-maintenance' ? maintenancePanel : null),
    createElement: () => ({ id: '', innerHTML: '', setAttribute() {} }),
    body: {
      replacements: [],
      replaceChildren(...children) {
        this.replacements.push(children);
        maintenancePanel = children.find(child => child.id === 'runtime-maintenance') || null;
      },
    },
  };
  vm.runInNewContext(source, {
    window, fetch: fetchImpl, Headers, FormData, AbortController, DOMException,
    CustomEvent: class CustomEvent {
      constructor(type, init = {}) {
        this.type = type;
        this.detail = init.detail;
      }
    },
    setTimeout, clearTimeout, document, console,
  });
  return { api: window.DuckAPI, dispatched, document, stateWrites };
}

function loadTeacherWithPendingGates() {
  const listeners = {};
  const requests = [];
  let statusCalls = 0;
  let resolveReady;
  let rejectReady;
  let resolveStatus;
  let rejectStatus;
  const readyPromise = new Promise((resolve, reject) => { resolveReady = resolve; rejectReady = reject; });
  const statusPromise = new Promise((resolve, reject) => { resolveStatus = resolve; rejectStatus = reject; });
  const button = {
    dataset: { v: 'overview' },
    disabled: false,
    classList: { add() {}, remove() {} },
    closest: () => button,
  };
  const nav = {
    attributes: {},
    addEventListener(type, listener) { listeners[`nav:${type}`] = listener; },
    querySelectorAll: () => [button],
    setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; },
  };
  const genericElement = () => ({
    children: [],
    style: {},
    classList: { add() {}, remove() {}, toggle() {} },
    append(...children) { this.children.push(...children); },
    appendChild(child) { this.children.push(child); },
    replaceChildren(...children) { this.children = children; },
    addEventListener() {},
    setAttribute() {},
    focus() {},
  });
  const main = genericElement();
  const aside = genericElement();
  let runtimeMaintenance = null;
  const document = {
    getElementById: id => ({ nav, main, 'runtime-maintenance': runtimeMaintenance }[id] || null),
    querySelector: selector => (selector === 'aside' ? aside : null),
    querySelectorAll: () => [button],
    createElement: genericElement,
  };
  const window = {
    addEventListener(type, listener) { listeners[type] = listener; },
  };
  const location = { hash: '' };
  vm.runInNewContext(teacherSource, {
    window, document, location,
    DuckAPI: {
      ready: () => readyPromise,
      request: path => {
        requests.push(path);
        return new Promise(() => {});
      },
    },
    DuckAuth: {
      status: () => {
        statusCalls += 1;
        return statusPromise;
      },
    },
    URLSearchParams,
    Object,
    Array,
    Set,
    Math,
    String,
    Number,
    console,
  });
  return {
    button, listeners, nav, main, location, requests, rejectReady, resolveReady, rejectStatus, resolveStatus,
    get statusCalls() { return statusCalls; },
    showRuntimeMaintenance() { runtimeMaintenance = genericElement(); },
  };
}

test('a repeated sequenceKey cancels the older request without a network error', async () => {
  let calls = 0;
  const { api } = loadDuckAPI((_path, { signal }) => {
    calls += 1;
    if (calls === 2) return Promise.resolve(jsonResponse({ current: 2 }));
    return new Promise((_resolve, reject) => signal.addEventListener(
      'abort', () => reject(new DOMException('cancelled', 'AbortError')), { once: true },
    ));
  });
  const first = api.request('/first', { sequenceKey: 'review-detail' });
  const second = api.request('/second', { sequenceKey: 'review-detail' });
  await assert.rejects(first, error => error.name === 'AbortError');
  assert.equal((await second).current, 2);
});

test('caller abort stays AbortError while timeout becomes REQUEST_TIMEOUT', async () => {
  const { api } = loadDuckAPI((_path, { signal }) => new Promise((_resolve, reject) =>
    signal.addEventListener('abort', () => reject(new DOMException('cancelled', 'AbortError')), { once: true })));
  const caller = new AbortController();
  const cancelled = api.request('/cancel', { signal: caller.signal });
  caller.abort();
  await assert.rejects(cancelled, error => error.name === 'AbortError');
  await assert.rejects(api.request('/timeout', { timeoutMs: 5 }), error => error.code === 'REQUEST_TIMEOUT');
});

test('version mismatch enters maintenance before any business request', async () => {
  const seen = [];
  const { api, document } = loadDuckAPI(path => {
    seen.push(path);
    const value = path.startsWith('/version.json')
      ? { release_id: 'disk-new', api_version: '2', schema_version: '2' }
      : { release_id: 'server-old', api_version: '2', schema_version: '2', db_mode: 'app' };
    return Promise.resolve(jsonResponse(value));
  });
  await assert.rejects(api.ready(), error => error.code === 'VERSION_MISMATCH');
  assert.equal(document.documentElement.dataset.appState, 'maintenance');
  assert.equal(seen.length, 2);
});

test('bootstrapVersionGate and ready share one pending successful gate promise', async () => {
  const calls = [];
  let resolveDisk;
  let resolveHealth;
  const disk = { release_id: 'build-1', api_version: '2', schema_version: 2 };
  const health = { ...disk, db_mode: 'app' };
  const harness = loadVersionGateHarness(path => new Promise(resolve => {
    calls.push(path);
    if (path.startsWith('/version.json')) resolveDisk = resolve;
    else resolveHealth = resolve;
  }));

  const bootstrap = harness.api.bootstrapVersionGate();
  const ready = harness.api.ready();

  assert.strictEqual(ready, bootstrap);
  assert.equal(calls.filter(path => path.startsWith('/version.json')).length, 1);
  assert.equal(calls.filter(path => path === '/api/health').length, 1);

  resolveDisk(jsonResponse(disk));
  resolveHealth(jsonResponse(health));
  const [bootstrapHealth, readyHealth] = await Promise.all([bootstrap, ready]);
  assert.strictEqual(bootstrapHealth, health);
  assert.strictEqual(readyHealth, health);
  assert.deepEqual(harness.stateWrites, ['ready']);
  assert.deepEqual(harness.dispatched.map(event => event.type), ['duck:runtime-ready']);
});

test('ready, bootstrapVersionGate, and repeated ready calls share one pending gate promise', async () => {
  const calls = [];
  let resolveDisk;
  let resolveHealth;
  const disk = { release_id: 'build-2', api_version: '2', schema_version: 2 };
  const health = { ...disk, db_mode: 'app' };
  const harness = loadVersionGateHarness(path => new Promise(resolve => {
    calls.push(path);
    if (path.startsWith('/version.json')) resolveDisk = resolve;
    else resolveHealth = resolve;
  }));

  const firstReady = harness.api.ready();
  const bootstrap = harness.api.bootstrapVersionGate();
  const repeatedReady = harness.api.ready();

  assert.strictEqual(bootstrap, firstReady);
  assert.strictEqual(repeatedReady, firstReady);
  assert.equal(calls.filter(path => path.startsWith('/version.json')).length, 1);
  assert.equal(calls.filter(path => path === '/api/health').length, 1);

  resolveDisk(jsonResponse(disk));
  resolveHealth(jsonResponse(health));
  const [firstHealth, bootstrapHealth, repeatedHealth] = await Promise.all([firstReady, bootstrap, repeatedReady]);
  assert.strictEqual(firstHealth, health);
  assert.strictEqual(bootstrapHealth, health);
  assert.strictEqual(repeatedHealth, health);
  assert.deepEqual(harness.stateWrites, ['ready']);
  assert.deepEqual(harness.dispatched.map(event => event.type), ['duck:runtime-ready']);
});

test('a failed gate is shared by later bootstrapVersionGate and ready calls without retrying', async () => {
  const calls = [];
  const disk = { release_id: 'build-new', api_version: '2', schema_version: 2 };
  const health = { ...disk, release_id: 'build-old', db_mode: 'app' };
  const harness = loadVersionGateHarness(path => {
    calls.push(path);
    return Promise.resolve(jsonResponse(path.startsWith('/version.json') ? disk : health));
  });

  const initial = harness.api.ready();
  const [initialResult] = await Promise.allSettled([initial]);
  assert.equal(initialResult.status, 'rejected');
  const initialError = initialResult.reason;
  assert.equal(initialError.code, 'VERSION_MISMATCH');
  const bootstrap = harness.api.bootstrapVersionGate();
  const repeatedReady = harness.api.ready();
  bootstrap.catch(() => {});

  assert.strictEqual(bootstrap, initial);
  assert.strictEqual(repeatedReady, initial);
  const [bootstrapResult, readyResult] = await Promise.allSettled([bootstrap, repeatedReady]);
  assert.equal(bootstrapResult.status, 'rejected');
  assert.equal(readyResult.status, 'rejected');
  assert.strictEqual(bootstrapResult.reason, initialError);
  assert.strictEqual(readyResult.reason, initialError);
  assert.equal(calls.filter(path => path.startsWith('/version.json')).length, 1);
  assert.equal(calls.filter(path => path === '/api/health').length, 1);
  assert.deepEqual(harness.stateWrites, ['maintenance']);
  assert.deepEqual(harness.dispatched.map(event => event.type), ['duck:runtime-blocked']);
  assert.equal(harness.document.body.replacements.length, 1);
  assert.equal(harness.document.body.replacements[0][0].id, 'runtime-maintenance');
});

test('teacher navigation and hash routes cannot start business requests before runtime and authentication readiness', async () => {
  const teacher = loadTeacherWithPendingGates();
  teacher.location.hash = '#children';
  teacher.listeners.hashchange();
  teacher.listeners['nav:click']({ target: teacher.button });
  await Promise.resolve();
  assert.deepEqual(teacher.requests, []);
  assert.equal(teacher.button.disabled, true);
  assert.equal(teacher.nav.attributes['aria-busy'], 'true');

  teacher.resolveReady();
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(teacher.statusCalls, 1);
  assert.deepEqual(teacher.requests, []);
  assert.equal(teacher.button.disabled, true);
  assert.equal(teacher.nav.attributes['aria-busy'], 'true');

  teacher.resolveStatus({ configured: true, authenticated: true });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(teacher.requests, ['/api/children']);
  assert.equal(teacher.button.disabled, false);
  assert.equal(teacher.nav.attributes['aria-busy'], undefined);
});

test('a rejected teacher auth status renders its safe error instead of leaving the main panel blank', async () => {
  const teacher = loadTeacherWithPendingGates();
  teacher.resolveReady();
  await Promise.resolve();
  await Promise.resolve();

  teacher.rejectStatus({ message: '教师认证服务不可用' });
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(teacher.main.children.length, 1);
  assert.equal(teacher.main.children[0].children[1].children[0], '教师认证服务不可用');
  assert.equal(teacher.button.disabled, true);
  assert.equal(teacher.nav.attributes['aria-busy'], 'true');
});

test('a failed runtime readiness check preserves the existing maintenance screen', async () => {
  const teacher = loadTeacherWithPendingGates();
  teacher.showRuntimeMaintenance();
  teacher.rejectReady({ message: '应用正在更新' });
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(teacher.main.children.length, 0);
  assert.equal(teacher.button.disabled, true);
  assert.equal(teacher.nav.attributes['aria-busy'], 'true');
});
