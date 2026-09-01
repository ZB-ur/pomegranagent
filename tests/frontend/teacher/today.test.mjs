import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createTodayRoute,
  displayName,
  queueStatusLabel,
  validateQueueRows,
  validateRetryResponse,
  validateRosterRows,
  validateWeeklyReport,
} from '../../../app/frontend/teacher/views/today.mjs';

const rosterRow = Object.freeze({
  id: 7,
  name: '小雨',
  nickname: '雨雨',
  avatar: 'rain.png',
});

function queueRow(queue) {
  return {
    id: 42,
    child: { ...rosterRow },
    date: '2026-08-23',
    started_at: '2026-08-23T08:54:00Z',
    completed_at: '2026-08-23T08:59:00Z',
    message_count: 4,
    round: 2,
    status: 'ended',
    end_reason: 'max_rounds',
    analysis_status: queue === 'pending' ? 'succeeded' : queue === 'processing' ? 'processing' : 'failed',
    review_status: queue === 'pending' ? 'draft' : 'unavailable',
    revision: 2,
  };
}

function retryResponse(overrides = {}) {
  return {
    conversation_id: 42,
    analysis_job_id: 19,
    analysis_status: 'pending',
    attempt_count: 0,
    retry_accepted: true,
    replayed: false,
    ...overrides,
  };
}

function fakeDocument() {
  return { createElement() {} };
}

class FakeNode {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.attributes = new Map();
    this.children = [];
    this.listeners = new Map();
    this.disabled = false;
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = children;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || new Set();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  click() {
    for (const listener of [...(this.listeners.get('click') || [])]) listener({ preventDefault() {} });
  }
}

function renderDocument() {
  return { createElement: tagName => new FakeNode(tagName) };
}

function nodeText(value) {
  if (typeof value === 'string') return value;
  if (!value || !Array.isArray(value.children)) return '';
  return value.children.map(nodeText).join('');
}

function findNode(root, predicate) {
  if (!root || typeof root === 'string') return null;
  if (predicate(root)) return root;
  for (const child of root.children || []) {
    const found = findNode(child, predicate);
    if (found) return found;
  }
  return null;
}

function hasClass(node, className) {
  return (node.getAttribute?.('class') || '').split(/\s+/).includes(className);
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
  for (let index = 0; index < 8; index += 1) await Promise.resolve();
}

function weeklyResponse(overrides = {}) {
  return {
    timezone: 'Asia/Shanghai',
    week_start: '2026-08-31',
    week_end_exclusive: '2026-09-07',
    completed_conversations: 5,
    participating_children: 3,
    confirmed_reviews: 2,
    failed_analyses: 1,
    pending_reviews_total: 4,
    ...overrides,
  };
}

function todayHarness() {
  const calls = [];
  const route = createTodayRoute({
    document: renderDocument(),
    now: () => new Date('2026-09-02T01:00:00Z'),
    request(path, options) {
      const next = deferred();
      calls.push({ path, options, next });
      return next.promise;
    },
  });
  const root = new FakeNode('main');
  let current = true;
  const controller = new AbortController();
  const lifecycle = route({
    root,
    params: {},
    signal: controller.signal,
    isCurrent: () => current,
  });
  return {
    calls,
    controller,
    lifecycle,
    root,
    makeStale() { current = false; },
  };
}

function assertFreshTypeError(action, original) {
  assert.throws(action, error => error instanceof TypeError && error !== original);
}

test('Today dependency seam accepts own data dependencies and rejects hostile reflection without leaking the input error', () => {
  const route = createTodayRoute({ request() {}, document: fakeDocument(), now: () => new Date('2026-08-23T00:00:00Z') });
  assert.equal(typeof route, 'function');

  const getterError = new Error('hostile request getter');
  const accessorDependencies = { document: fakeDocument() };
  Object.defineProperty(accessorDependencies, 'request', { get() { throw getterError; }, enumerable: true });
  assertFreshTypeError(() => createTodayRoute(accessorDependencies), getterError);

  const proxyError = new Error('hostile ownKeys');
  const proxyDependencies = new Proxy({}, { ownKeys() { throw proxyError; } });
  assertFreshTypeError(() => createTodayRoute(proxyDependencies), proxyError);
  assertFreshTypeError(() => createTodayRoute({ request: null, document: fakeDocument() }));
  assertFreshTypeError(() => createTodayRoute({ request() {}, document: fakeDocument(), now: null }));
});

test('Today validates roster DTOs and formats safe display names', () => {
  assert.deepEqual(validateRosterRows([rosterRow]), [rosterRow]);
  assert.equal(displayName(rosterRow), '雨雨');
  assert.equal(displayName({ ...rosterRow, nickname: '   ' }), '小雨');
  assert.throws(() => validateRosterRows({}), TypeError);
  assert.throws(() => validateRosterRows([{ ...rosterRow, id: 0 }]), TypeError);
  assert.throws(() => validateRosterRows([{ ...rosterRow, name: '   ' }]), TypeError);
  assert.throws(() => validateRosterRows([{ ...rosterRow, nickname: 3 }]), TypeError);
  assert.throws(() => validateRosterRows([{ ...rosterRow, avatar: false }]), TypeError);
});

test('Today validates every queue DTO shape, fixed labels, and queue-specific combinations', () => {
  for (const queue of ['pending', 'processing', 'failed']) {
    const [row] = validateQueueRows(queue, [queueRow(queue)]);
    assert.equal(row.id, 42);
  }
  assert.equal(queueStatusLabel('pending'), '待审阅');
  assert.equal(queueStatusLabel('processing'), '分析中');
  assert.equal(queueStatusLabel('failed'), '分析失败');

  assert.throws(() => validateQueueRows('failed', [{ ...queueRow('failed'), end_reason: 'bad' }]), TypeError);
  assert.throws(() => validateQueueRows('pending', [{ ...queueRow('pending'), child: { ...rosterRow, nickname: 1 } }]), TypeError);
  assert.throws(() => validateQueueRows('processing', [{ ...queueRow('processing'), review_status: 'draft' }]), TypeError);
  assert.throws(() => validateQueueRows('failed', [{ ...queueRow('failed'), review_status: 'pending' }]), TypeError);
  assert.throws(() => validateQueueRows('pending', [{ ...queueRow('pending'), completed_at: 'not-a-time' }]), TypeError);
  assert.throws(() => validateQueueRows('pending', [{ ...queueRow('pending'), revision: -1 }]), TypeError);
});

test('Today accepts only matching accepted or replayed analysis retry responses', () => {
  assert.deepEqual(validateRetryResponse(42, retryResponse()), retryResponse());
  assert.deepEqual(
    validateRetryResponse(42, retryResponse({ retry_accepted: false, replayed: true })),
    retryResponse({ retry_accepted: false, replayed: true }),
  );
  assert.throws(() => validateRetryResponse(7, retryResponse()), TypeError);
  assert.throws(() => validateRetryResponse(42, retryResponse({ analysis_job_id: 0 })), TypeError);
  assert.throws(() => validateRetryResponse(42, retryResponse({ retry_accepted: true, replayed: true })), TypeError);
  assert.throws(() => validateRetryResponse(42, retryResponse({ retry_accepted: false, replayed: false })), TypeError);
  assert.throws(() => validateRetryResponse(42, retryResponse({ replayed: 'false' })), TypeError);
});

test('Today strictly validates the exact weekly report contract and seven-day Monday window', () => {
  assert.deepEqual(validateWeeklyReport(weeklyResponse()), weeklyResponse());
  for (const malformed of [
    { ...weeklyResponse(), extra: true },
    { ...weeklyResponse(), timezone: 'UTC' },
    { ...weeklyResponse(), week_start: '2026-09-01' },
    { ...weeklyResponse(), week_start: '2026-8-31' },
    { ...weeklyResponse(), week_start: '2026-02-30', week_end_exclusive: '2026-03-09' },
    { ...weeklyResponse(), week_end_exclusive: '2026-09-08' },
    { ...weeklyResponse(), completed_conversations: -1 },
    { ...weeklyResponse(), participating_children: 1.5 },
    { ...weeklyResponse(), pending_reviews_total: Number.MAX_SAFE_INTEGER + 1 },
  ]) assert.throws(() => validateWeeklyReport(malformed), TypeError);

  const accessor = weeklyResponse();
  Object.defineProperty(accessor, 'failed_analyses', { get() { throw new Error('secret getter'); }, enumerable: true });
  assert.throws(() => validateWeeklyReport(accessor), TypeError);
  const proxyError = new Error('hostile weekly proxy');
  assertFreshTypeError(
    () => validateWeeklyReport(new Proxy(weeklyResponse(), { ownKeys() { throw proxyError; } })),
    proxyError,
  );
});

test('Today requests and renders the weekly panel independently with five fixed labels and range', async () => {
  const harness = todayHarness();
  await settle();
  assert.deepEqual(harness.calls.map(call => call.path), [
    '/api/roster/today',
    '/api/conversations?queue=pending',
    '/api/conversations?queue=processing',
    '/api/conversations?queue=failed',
    '/api/reports/weekly',
  ]);
  for (const call of harness.calls.slice(0, 4)) call.next.resolve([]);
  harness.calls[4].next.resolve(weeklyResponse());
  await settle();

  const metrics = findNode(harness.root, node => node.getAttribute?.('data-today-metrics') === 'weekly');
  assert.ok(metrics);
  assert.equal(metrics.getAttribute('data-state'), 'loaded');
  assert.equal(metrics.getAttribute('aria-busy'), null);
  const text = nodeText(metrics);
  for (const label of ['本周完成对话', '参与幼儿', '已确认审阅', '分析失败', '当前待审阅']) {
    assert.ok(text.includes(label), text);
  }
  assert.ok(text.includes('2026年8月31日–9月6日'), text);
  for (const value of ['5', '3', '2', '1', '4']) assert.ok(text.includes(value), text);
  assert.ok(!text.includes('本周指标暂不可用'), text);
});

test('Today weekly failure and retry leave all four business panels and their calls untouched', async () => {
  const harness = todayHarness();
  await settle();
  for (const call of harness.calls.slice(0, 4)) call.next.resolve([]);
  harness.calls[4].next.reject(new Error('raw weekly failure'));
  await settle();

  const panels = ['roster', 'pending', 'processing', 'failed'].map(key => findNode(
    harness.root,
    node => node.getAttribute?.('data-today-panel') === key,
  ));
  assert.deepEqual(panels.map(node => node.getAttribute('data-state')), ['empty', 'empty', 'empty', 'empty']);
  const metrics = findNode(harness.root, node => node.getAttribute?.('data-today-metrics') === 'weekly');
  assert.equal(metrics.getAttribute('data-state'), 'error');
  assert.ok(!nodeText(metrics).includes('raw weekly failure'));
  const retry = findNode(metrics, node => hasClass(node, 'today-metrics-retry'));
  assert.ok(retry);
  retry.click();
  await settle();
  assert.deepEqual(harness.calls.map(call => call.path).slice(5), ['/api/reports/weekly']);
  harness.calls[5].next.resolve(weeklyResponse({ completed_conversations: 0 }));
  await settle();
  assert.deepEqual(panels.map(node => node.getAttribute('data-state')), ['empty', 'empty', 'empty', 'empty']);
  assert.equal(metrics.getAttribute('data-state'), 'loaded');
});

test('Today ignores stale weekly success, error, and completion after a newer generation or cleanup', async () => {
  const harness = todayHarness();
  await settle();
  for (const call of harness.calls.slice(0, 4)) call.next.resolve([]);
  harness.calls[4].next.reject(new Error('initial failure'));
  await settle();
  const metrics = findNode(harness.root, node => node.getAttribute?.('data-today-metrics') === 'weekly');
  const retry = findNode(metrics, node => hasClass(node, 'today-metrics-retry'));
  retry.click();
  await settle();
  retry.click();
  await settle();
  assert.deepEqual(harness.calls.slice(5).map(call => call.path), [
    '/api/reports/weekly', '/api/reports/weekly',
  ]);
  harness.calls[6].next.resolve(weeklyResponse({ completed_conversations: 9 }));
  await settle();
  assert.ok(nodeText(metrics).includes('9'));
  harness.calls[5].next.reject(new Error('stale error'));
  await settle();
  assert.equal(metrics.getAttribute('data-state'), 'loaded');
  assert.ok(nodeText(metrics).includes('9'));
  assert.ok(!nodeText(metrics).includes('stale error'));

  retry.click();
  await settle();
  const staleSuccess = harness.calls.at(-1);
  retry.click();
  await settle();
  const newestSuccess = harness.calls.at(-1);
  newestSuccess.next.resolve(weeklyResponse({ completed_conversations: 10 }));
  await settle();
  staleSuccess.next.resolve(weeklyResponse({ completed_conversations: 99 }));
  await settle();
  assert.equal(metrics.getAttribute('data-state'), 'loaded');
  assert.ok(nodeText(metrics).includes('10'));
  assert.ok(!nodeText(metrics).includes('99'));

  retry.click();
  await settle();
  const pendingAfterCleanup = harness.calls.at(-1);
  harness.lifecycle.cleanup();
  harness.root.replaceChildren('next route');
  pendingAfterCleanup.next.resolve(weeklyResponse({ completed_conversations: 99 }));
  await settle();
  assert.equal(nodeText(harness.root), 'next route');
});
