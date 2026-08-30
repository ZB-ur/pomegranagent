import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../../../app/frontend/shared/api.js', import.meta.url), 'utf8');
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
  const settledBootstrap = harness.api.bootstrapVersionGate();
  const settledReady = harness.api.ready();
  assert.strictEqual(settledBootstrap, bootstrap);
  assert.strictEqual(settledReady, bootstrap);
  const [settledBootstrapHealth, settledReadyHealth] = await Promise.all([settledBootstrap, settledReady]);
  assert.strictEqual(settledBootstrapHealth, health);
  assert.strictEqual(settledReadyHealth, health);
  assert.equal(calls.filter(path => path.startsWith('/version.json')).length, 1);
  assert.equal(calls.filter(path => path === '/api/health').length, 1);
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
