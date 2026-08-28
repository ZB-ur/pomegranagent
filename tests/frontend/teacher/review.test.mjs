import assert from 'node:assert/strict';
import test from 'node:test';

import {
  analysisStatusLabel,
  createReviewRoute,
  isSameChildIdentity,
  parseReviewConversationId,
  validateReviewDetail,
} from '../../../app/frontend/teacher/views/review.mjs';

const child = Object.freeze({
  id: 7,
  name: '小雨',
  nickname: '雨雨',
  avatar: 'rain.png',
});

function reviewDocument(overrides = {}) {
  return {
    feeding_logs: [{ id: 11, category: '喂食', content: '喂了菜叶', duck_id: 3 }],
    emotion: { emotion: '开心', intensity: 4, note: null },
    insight: '能够清楚表达照料过程。',
    scores: [{ dimension_id: 2, dimension_name: '表达能力', score: 4, reason: '能说明自己的观察。' }],
    overall: 4,
    ...overrides,
  };
}

function detail(overrides = {}) {
  return {
    id: 42,
    child: { ...child },
    date: '2026-08-23',
    started_at: '2026-08-23T08:54:00Z',
    completed_at: '2026-08-23T08:59:00Z',
    status: 'ended',
    end_reason: 'max_rounds',
    message_count: 3,
    round: 2,
    last_message_id: 9,
    revision: 2,
    analysis: {
      job_id: 19,
      status: 'succeeded',
      attempt_count: 0,
      max_attempts: 3,
      error: null,
      updated_at: '2026-08-23T09:01:00Z',
    },
    review_status: 'draft',
    messages: [
      { id: 5, role: 'child', text: '我喂了小鸭。' },
      { id: 7, role: 'diary', text: '你观察得很仔细。' },
      { id: 9, role: 'child', text: '它很开心。' },
    ],
    review: reviewDocument(),
    ...overrides,
  };
}

function fakeDocument() {
  return { createElement() {} };
}

class FakeSignal {
  constructor() {
    this.aborted = false;
    this.listeners = new Set();
  }

  addEventListener(type, listener) {
    if (type === 'abort') this.listeners.add(listener);
  }

  removeEventListener(type, listener) {
    if (type === 'abort') this.listeners.delete(listener);
  }

  abort() {
    if (this.aborted) return;
    this.aborted = true;
    for (const listener of [...this.listeners]) listener();
  }
}

class FakeController {
  constructor() {
    this.signal = new FakeSignal();
  }

  abort() {
    this.signal.abort();
  }
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

  removeEventListener(type, listener) {
    this.listeners.get(type)?.delete(listener);
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

function nodeWithText(root, tagName, text) {
  const node = findNode(root, candidate => candidate.tagName === tagName && nodeText(candidate) === text);
  assert.ok(node, `missing ${tagName} ${text}`);
  return node;
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
  await Promise.resolve();
}

function pendingQueue(id = 42, selectedChild = child) {
  return [{
    id,
    child: { ...selectedChild },
    date: '2026-08-23',
    started_at: '2026-08-23T08:54:00Z',
    completed_at: '2026-08-23T08:59:00Z',
    message_count: 3,
    round: 2,
    status: 'ended',
    end_reason: 'max_rounds',
    analysis_status: 'succeeded',
    review_status: 'draft',
    revision: 2,
  }];
}

function createDeferredReviewRoute() {
  const calls = [];
  const route = createReviewRoute({
    document: renderDocument(),
    createAbortController: () => new FakeController(),
    request(path, options) {
      const next = deferred();
      calls.push({ path, options, next });
      return next.promise;
    },
  });
  return { route, calls };
}

function reviewContext(root, conversationId, current = () => true) {
  return {
    root,
    params: new URLSearchParams(`conversation_id=${conversationId}`),
    signal: new FakeSignal(),
    isCurrent: current,
  };
}

function assertFreshTypeError(action, original) {
  assert.throws(action, error => error instanceof TypeError && error !== original);
}

test('Review dependency reflection accepts only exact own data and converts hostile dependencies to fresh TypeError', () => {
  assert.equal(typeof createReviewRoute({
    request() {}, document: fakeDocument(), createAbortController: () => new AbortController(),
  }), 'function');

  const getterError = new Error('hostile request getter');
  const accessorDependencies = { document: fakeDocument(), createAbortController: () => new AbortController() };
  Object.defineProperty(accessorDependencies, 'request', { get() { throw getterError; }, enumerable: true });
  assertFreshTypeError(() => createReviewRoute(accessorDependencies), getterError);

  const proxyError = new Error('hostile ownKeys');
  const proxyDependencies = new Proxy({}, { ownKeys() { throw proxyError; } });
  assertFreshTypeError(() => createReviewRoute(proxyDependencies), proxyError);
  assertFreshTypeError(() => createReviewRoute({ request() {}, document: fakeDocument() }));
  assertFreshTypeError(() => createReviewRoute({ request: null, document: fakeDocument(), createAbortController: () => new AbortController() }));
  assertFreshTypeError(() => createReviewRoute({ request() {}, document: fakeDocument(), createAbortController: null }));
});

test('Review rejects an invalid controller produced by the injected factory without leaking its error', () => {
  assertFreshTypeError(() => createReviewRoute({
    request() {}, document: fakeDocument(), createAbortController: () => ({ signal: { aborted: false }, abort() {} }),
  }));
  const controllerError = new Error('hostile controller');
  assertFreshTypeError(() => createReviewRoute({
    request() {}, document: fakeDocument(), createAbortController: () => { throw controllerError; },
  }), controllerError);
});

test('Review parses only one canonical positive safe-integer conversation query', () => {
  for (const value of ['1', '42', String(Number.MAX_SAFE_INTEGER)]) {
    assert.equal(parseReviewConversationId(new URLSearchParams(`conversation_id=${value}`)), Number(value));
  }
  for (const query of [
    '', 'conversation_id=', 'conversation_id=0', 'conversation_id=-1', 'conversation_id=01',
    'conversation_id= 1', 'conversation_id=1 ', 'conversation_id=1e2',
    'conversation_id=9007199254740992', 'conversation_id=1&conversation_id=2', 'child_id=7',
  ]) {
    assert.equal(parseReviewConversationId(new URLSearchParams(query)), null, query);
  }
});

test('Review maps only known analysis statuses to local presentation copy', () => {
  assert.equal(analysisStatusLabel('pending'), '等待分析');
  assert.equal(analysisStatusLabel('processing'), '分析中');
  assert.equal(analysisStatusLabel('succeeded'), '分析已完成');
  assert.equal(analysisStatusLabel('failed'), '分析失败');
  assert.throws(() => analysisStatusLabel('unknown'), TypeError);
});

test('Review validates the exact succeeded detail union and preserves blank draft reasons', () => {
  const valid = detail({ review: reviewDocument({ scores: [{ dimension_id: 2, dimension_name: '表达能力', score: 4, reason: '' }] }) });
  assert.deepEqual(validateReviewDetail(42, valid), valid);

  for (const reviewStatus of ['pending', 'draft', 'confirmed']) {
    assert.equal(validateReviewDetail(42, detail({ review_status: reviewStatus })).review_status, reviewStatus);
  }
  assert.throws(() => validateReviewDetail(42, detail({ id: 7 })), TypeError);
  assert.throws(() => validateReviewDetail(42, detail({ extra: true })), TypeError);
  assert.throws(() => validateReviewDetail(42, detail({ review_status: 'unavailable' })), TypeError);
  assert.throws(() => validateReviewDetail(42, detail({ review: null })), TypeError);
});

test('Review validates every unavailable analysis union without exposing impossible review data', () => {
  const unavailable = ({ status, error }) => detail({
    analysis: { ...detail().analysis, status, error }, review_status: 'unavailable', review: null,
  });
  for (const status of ['pending', 'processing']) {
    const value = unavailable({ status, error: null });
    assert.equal(validateReviewDetail(42, value).analysis.status, status);
  }
  const failed = unavailable({
    status: 'failed', error: { code: 'ANALYSIS_UPSTREAM_FAILED', message: '分析服务暂时不可用' },
  });
  assert.equal(validateReviewDetail(42, failed).analysis.status, 'failed');

  assert.throws(() => validateReviewDetail(42, unavailable({ status: 'pending', error: { code: 'ANALYSIS_UPSTREAM_FAILED', message: '分析服务暂时不可用' } })), TypeError);
  assert.throws(() => validateReviewDetail(42, unavailable({ status: 'failed', error: null })), TypeError);
  assert.throws(() => validateReviewDetail(42, unavailable({ status: 'failed', error: { code: 'OTHER', message: '分析服务暂时不可用' } })), TypeError);
  assert.throws(() => validateReviewDetail(42, detail({ analysis: { ...detail().analysis, status: 'succeeded' }, review_status: 'pending', review: null })), TypeError);
});

test('Review rejects malformed nested data, message boundaries, and duplicate score dimensions', () => {
  assert.throws(() => validateReviewDetail(42, detail({ messages: [{ id: 5, role: 'child', text: 'a' }, { id: 5, role: 'diary', text: 'b' }, { id: 9, role: 'child', text: 'c' }] })), TypeError);
  assert.throws(() => validateReviewDetail(42, detail({ last_message_id: 8 })), TypeError);
  assert.throws(() => validateReviewDetail(42, detail({ round: 1 })), TypeError);
  assert.throws(() => validateReviewDetail(42, detail({ messages: [{ id: 5, role: 'teacher', text: 'a' }, { id: 7, role: 'diary', text: 'b' }, { id: 9, role: 'child', text: 'c' }] })), TypeError);
  assert.throws(() => validateReviewDetail(42, detail({ review: reviewDocument({ scores: [
    { dimension_id: 2, dimension_name: '表达能力', score: 4, reason: '' },
    { dimension_id: 2, dimension_name: '重复', score: 3, reason: '' },
  ] }) })), TypeError);
  assert.throws(() => validateReviewDetail(42, detail({ review: reviewDocument({ emotion: { emotion: '开心', intensity: 6, note: null } }) })), TypeError);
  assert.throws(() => validateReviewDetail(42, detail({ review: reviewDocument({ overall: Number.NaN }) })), TypeError);
});

test('Review rejects hostile DTO reflection and compares cross-source child identity exactly', () => {
  const accessorError = new Error('hostile detail getter');
  const accessorDetail = detail();
  Object.defineProperty(accessorDetail, 'id', { get() { throw accessorError; }, enumerable: true });
  assertFreshTypeError(() => validateReviewDetail(42, accessorDetail), accessorError);

  const proxyError = new Error('hostile own keys');
  assertFreshTypeError(() => validateReviewDetail(42, new Proxy({}, { ownKeys() { throw proxyError; } })), proxyError);
  assert.equal(isSameChildIdentity(child, { ...child }), true);
  assert.equal(isSameChildIdentity(child, { ...child, nickname: null }), false);
  assert.equal(isSameChildIdentity(child, { ...child, avatar: 'other.png' }), false);
  assert.throws(() => isSameChildIdentity(child, { ...child, name: '   ' }), TypeError);
});

test('Review navigation from detail A to B ignores an abort-insensitive old detail response', async () => {
  const { route, calls } = createDeferredReviewRoute();
  const root = new FakeNode('main');
  let currentA = true;
  const oldRoute = route(reviewContext(root, 42, () => currentA));
  await settle();
  const currentB = () => true;
  currentA = false;
  oldRoute.cleanup();
  route(reviewContext(root, 43, currentB));
  await settle();
  const detailA = calls.find(call => call.path === '/api/conversations/42');
  const detailB = calls.find(call => call.path === '/api/conversations/43');
  assert.ok(detailA && detailB);
  detailB.next.resolve(detail({ id: 43, child: { id: 8, name: '小风', nickname: '风风', avatar: null } }));
  await settle();
  assert.match(nodeText(root), /会话 #43/);
  detailA.next.resolve(detail());
  await settle();
  assert.match(nodeText(root), /会话 #43/);
  assert.doesNotMatch(nodeText(root), /会话 #42/);
});

test('Review same-ID persistent reload gives only the newest abort-insensitive detail response ownership', async () => {
  const { route, calls } = createDeferredReviewRoute();
  const root = new FakeNode('main');
  route(reviewContext(root, 42));
  await settle();
  const oldDetail = calls.find(call => call.path === '/api/conversations/42');
  assert.ok(oldDetail);
  nodeWithText(root, 'BUTTON', '重新加载此会话').click();
  await settle();
  const detailCalls = calls.filter(call => call.path === '/api/conversations/42');
  assert.equal(detailCalls.length, 2);
  const latestDetail = detailCalls[1];
  latestDetail.next.resolve(detail({ messages: [
    { id: 5, role: 'child', text: '这是最新内容。' },
    { id: 7, role: 'diary', text: '继续说。' },
    { id: 9, role: 'child', text: '最新结束。' },
  ] }));
  await settle();
  oldDetail.next.resolve(detail({ messages: [
    { id: 5, role: 'child', text: '这是过期内容。' },
    { id: 7, role: 'diary', text: '旧回复。' },
    { id: 9, role: 'child', text: '旧结束。' },
  ] }));
  await settle();
  assert.match(nodeText(root), /这是最新内容。/);
  assert.doesNotMatch(nodeText(root), /这是过期内容。/);
});

test('Review queue reload gives only the newest abort-insensitive queue response ownership', async () => {
  const { route, calls } = createDeferredReviewRoute();
  const root = new FakeNode('main');
  route(reviewContext(root, 42));
  await settle();
  const oldQueue = calls.find(call => call.path === '/api/conversations?queue=pending');
  assert.ok(oldQueue);
  nodeWithText(root, 'BUTTON', '重新加载队列').click();
  await settle();
  const queueCalls = calls.filter(call => call.path === '/api/conversations?queue=pending');
  assert.equal(queueCalls.length, 2);
  queueCalls[1].next.resolve(pendingQueue(42, { ...child, nickname: '最新队列' }));
  await settle();
  oldQueue.next.resolve(pendingQueue(42, { ...child, nickname: '过期队列' }));
  await settle();
  assert.match(nodeText(root), /最新队列/);
  assert.doesNotMatch(nodeText(root), /过期队列/);
});

test('Review queue replacement ignores an abort-insensitive old route response and cleanup absorbs late resolutions', async () => {
  const { route, calls } = createDeferredReviewRoute();
  const root = new FakeNode('main');
  let currentA = true;
  const oldRoute = route(reviewContext(root, 42, () => currentA));
  await settle();
  const oldQueue = calls.find(call => call.path === '/api/conversations?queue=pending');
  assert.ok(oldQueue);
  currentA = false;
  oldRoute.cleanup();
  route(reviewContext(root, 42));
  await settle();
  const queueCalls = calls.filter(call => call.path === '/api/conversations?queue=pending');
  assert.equal(queueCalls.length, 2);
  queueCalls[1].next.resolve(pendingQueue(42, { ...child, nickname: '最新队列' }));
  await settle();
  oldQueue.next.resolve(pendingQueue(42, { ...child, nickname: '过期队列' }));
  await settle();
  assert.match(nodeText(root), /最新队列/);
  assert.doesNotMatch(nodeText(root), /过期队列/);

  const cleanup = route(reviewContext(root, 42));
  await settle();
  const held = calls.at(-1);
  const rootTextBeforeCleanup = nodeText(root);
  cleanup.cleanup();
  cleanup.cleanup();
  held.next.reject(new Error('late failure'));
  await settle();
  assert.equal(nodeText(root), rootTextBeforeCleanup);
});
