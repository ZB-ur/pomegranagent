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
