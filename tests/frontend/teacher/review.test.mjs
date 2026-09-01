import assert from 'node:assert/strict';
import test from 'node:test';

import {
  analysisStatusLabel,
  createReviewRoute,
  isSameChildIdentity,
  parseReviewConversationId,
  applyReviewAcknowledgement,
  validateReviewAcknowledgement,
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

function fakeDirtyGuard() {
  return {
    activate() {},
    update() {},
    markClean() {},
    isDirty() { return false; },
    confirmLeave() { return Promise.resolve(true); },
    release() {},
  };
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

  dispatch(type, event = {}) {
    for (const listener of [...(this.listeners.get(type) || [])]) listener({ target: this, ...event });
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

function findNodes(root, predicate, matches = []) {
  if (!root || typeof root === 'string') return matches;
  if (predicate(root)) matches.push(root);
  for (const child of root.children || []) findNodes(child, predicate, matches);
  return matches;
}

function nodeWithText(root, tagName, text) {
  const node = findNode(root, candidate => candidate.tagName === tagName && nodeText(candidate) === text);
  assert.ok(node, `missing ${tagName} ${text}`);
  return node;
}

function controlValue(root, id) {
  const control = findNode(root, candidate => candidate.getAttribute?.('id') === id);
  assert.ok(control, `missing control #${id}`);
  return control.value;
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

function createDeferredReviewRoute(
  dirtyGuard = fakeDirtyGuard(),
  createAbortController = () => new FakeController(),
) {
  const calls = [];
  const route = createReviewRoute({
    document: renderDocument(),
    createAbortController,
    dirtyGuard,
    request(path, options) {
      const next = deferred();
      calls.push({ path, options, next });
      return next.promise;
    },
  });
  return { route, calls };
}

function trackedDirtyGuard() {
  const calls = {
    activate: 0,
    update: 0,
    updates: [],
    markClean: 0,
    confirmLeave: 0,
    release: 0,
  };
  let active = false;
  let cleanSnapshot = null;
  let currentSnapshot = null;
  const guard = {
    activate(snapshot) {
      calls.activate += 1;
      active = true;
      currentSnapshot = snapshot;
    },
    update(snapshot) {
      calls.update += 1;
      calls.updates.push(snapshot);
      currentSnapshot = snapshot;
    },
    markClean(snapshot) {
      calls.markClean += 1;
      active = true;
      cleanSnapshot = snapshot;
      currentSnapshot = snapshot;
    },
    isDirty() { return active && currentSnapshot !== cleanSnapshot; },
    confirmLeave() {
      calls.confirmLeave += 1;
      return Promise.resolve(!guard.isDirty());
    },
    release() {
      calls.release += 1;
      active = false;
      cleanSnapshot = null;
      currentSnapshot = null;
    },
  };
  return {
    calls,
    guard,
  };
}

function recordTextWrites(node) {
  const writes = [];
  const replaceChildren = node.replaceChildren.bind(node);
  node.replaceChildren = (...children) => {
    writes.push(children.map(nodeText).join(''));
    replaceChildren(...children);
  };
  return writes;
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
    request() {}, document: fakeDocument(), createAbortController: () => new AbortController(), dirtyGuard: fakeDirtyGuard(),
  }), 'function');

  const getterError = new Error('hostile request getter');
  const accessorDependencies = { document: fakeDocument(), createAbortController: () => new AbortController(), dirtyGuard: fakeDirtyGuard() };
  Object.defineProperty(accessorDependencies, 'request', { get() { throw getterError; }, enumerable: true });
  assertFreshTypeError(() => createReviewRoute(accessorDependencies), getterError);

  const proxyError = new Error('hostile ownKeys');
  const proxyDependencies = new Proxy({}, { ownKeys() { throw proxyError; } });
  assertFreshTypeError(() => createReviewRoute(proxyDependencies), proxyError);
  assertFreshTypeError(() => createReviewRoute({ request() {}, document: fakeDocument(), createAbortController: () => new AbortController() }));
  assertFreshTypeError(() => createReviewRoute({ request: null, document: fakeDocument(), createAbortController: () => new AbortController(), dirtyGuard: fakeDirtyGuard() }));
  assertFreshTypeError(() => createReviewRoute({ request() {}, document: fakeDocument(), createAbortController: null, dirtyGuard: fakeDirtyGuard() }));
  assertFreshTypeError(() => createReviewRoute({ request() {}, document: fakeDocument(), createAbortController: () => new AbortController(), dirtyGuard: {} }));
});

test('Review uses the reflection-safe dirty guard copy when a validated Proxy throws on property access', async () => {
  const calls = { activate: 0, markClean: 0, release: 0 };
  const rawGuard = {
    activate() { calls.activate += 1; },
    update() {},
    markClean() { calls.markClean += 1; },
    isDirty() { return false; },
    confirmLeave() { return Promise.resolve(true); },
    release() { calls.release += 1; },
  };
  const guard = new Proxy(rawGuard, {
    get() { throw new Error('validated proxy must not be read again'); },
  });
  const { route, calls: requests } = createDeferredReviewRoute(guard);
  const root = new FakeNode('main');
  route(reviewContext(root, 42));
  await settle();
  requests.find(call => call.path === '/api/conversations?queue=pending').next.resolve(pendingQueue());
  requests.find(call => call.path === '/api/conversations/42').next.resolve(detail());
  await settle();
  assert.equal(calls.activate, 1);
  assert.equal(calls.markClean, 1);
  assert.equal(calls.release, 2);
});

test('Review rejects an invalid controller produced by the injected factory without leaking its error', () => {
  assertFreshTypeError(() => createReviewRoute({
    request() {}, document: fakeDocument(), createAbortController: () => ({ signal: { aborted: false }, abort() {} }), dirtyGuard: fakeDirtyGuard(),
  }));
  const controllerError = new Error('hostile controller');
  assertFreshTypeError(() => createReviewRoute({
    request() {}, document: fakeDocument(), createAbortController: () => { throw controllerError; }, dirtyGuard: fakeDirtyGuard(),
  }), controllerError);
});

test('Review accepts only a strict matching save acknowledgement and updates nested review state', () => {
  const acknowledgement = {
    saved: true,
    conversation_id: 42,
    review_status: 'draft',
    revision: 3,
    saved_at: '2026-08-23T09:02:00Z',
    review: reviewDocument(),
  };
  assert.deepEqual(validateReviewAcknowledgement(42, 2, 'save_draft', acknowledgement), acknowledgement);
  const applied = applyReviewAcknowledgement(detail(), acknowledgement);
  assert.equal(applied.revision, 3);
  assert.equal(applied.review_status, 'draft');
  assert.deepEqual(applied.review, acknowledgement.review);
  assert.equal(Object.hasOwn(applied, 'feeding_logs'), false);

  const malformedReview = reviewDocument({ scores: [
    { dimension_id: 2, dimension_name: '表达能力', score: 4, reason: '理由' },
    { dimension_id: 2, dimension_name: '重复能力', score: 3, reason: '' },
  ] });
  const accessorError = new Error('hostile acknowledgement getter');
  const accessorAck = { ...acknowledgement };
  Object.defineProperty(accessorAck, 'saved', { enumerable: true, get() { throw accessorError; } });
  const proxyError = new Error('hostile acknowledgement own keys');
  const invalidRows = [
    { label: 'missing key', value: (({ saved_at, ...rest }) => rest)(acknowledgement) },
    { label: 'extra key', value: { ...acknowledgement, unexpected: true } },
    { label: 'accessor', value: accessorAck },
    { label: 'proxy', value: new Proxy({}, { ownKeys() { throw proxyError; } }) },
    { label: 'saved false', value: { ...acknowledgement, saved: false } },
    { label: 'wrong conversation', value: { ...acknowledgement, conversation_id: 43 } },
    { label: 'wrong draft status', value: { ...acknowledgement, review_status: 'confirmed' } },
    { label: 'stale revision', value: { ...acknowledgement, revision: 2 } },
    { label: 'unsafe revision', value: { ...acknowledgement, revision: Number.MAX_SAFE_INTEGER + 1 } },
    { label: 'bad timestamp', value: { ...acknowledgement, saved_at: 'not-a-date' } },
    { label: 'malformed nested review', value: { ...acknowledgement, review: malformedReview } },
    { label: 'invalid feeding id', value: { ...acknowledgement, review: reviewDocument({ feeding_logs: [{ id: 0, category: '喂食', content: '记录', duck_id: 3 }] }) } },
    { label: 'invalid feeding category', value: { ...acknowledgement, review: reviewDocument({ feeding_logs: [{ id: 11, category: '未知', content: '记录', duck_id: 3 }] }) } },
    { label: 'invalid feeding content', value: { ...acknowledgement, review: reviewDocument({ feeding_logs: [{ id: 11, category: '喂食', content: null, duck_id: 3 }] }) } },
    { label: 'invalid feeding duck', value: { ...acknowledgement, review: reviewDocument({ feeding_logs: [{ id: 11, category: '喂食', content: '记录', duck_id: 0 }] }) } },
    { label: 'blank emotion', value: { ...acknowledgement, review: reviewDocument({ emotion: { emotion: ' ', intensity: 4, note: null } }) } },
    { label: 'invalid emotion intensity', value: { ...acknowledgement, review: reviewDocument({ emotion: { emotion: '开心', intensity: 6, note: null } }) } },
    { label: 'invalid emotion note', value: { ...acknowledgement, review: reviewDocument({ emotion: { emotion: '开心', intensity: 4, note: 7 } }) } },
    { label: 'blank insight', value: { ...acknowledgement, review: reviewDocument({ insight: ' ' }) } },
    { label: 'invalid score dimension', value: { ...acknowledgement, review: reviewDocument({ scores: [{ dimension_id: 0, dimension_name: '表达能力', score: 4, reason: '' }] }) } },
    { label: 'invalid score bound', value: { ...acknowledgement, review: reviewDocument({ scores: [{ dimension_id: 2, dimension_name: '表达能力', score: 6, reason: '' }] }) } },
    { label: 'invalid score reason', value: { ...acknowledgement, review: reviewDocument({ scores: [{ dimension_id: 2, dimension_name: '表达能力', score: 4, reason: null }] }) } },
    { label: 'non-finite overall', value: { ...acknowledgement, review: reviewDocument({ overall: Number.POSITIVE_INFINITY }) } },
  ];
  for (const row of invalidRows) {
    assert.throws(() => validateReviewAcknowledgement(42, 2, 'save_draft', row.value), TypeError, row.label);
  }
  assert.throws(() => validateReviewAcknowledgement(42, 2, 'confirm', acknowledgement), TypeError);
  assert.deepEqual(validateReviewAcknowledgement(42, 2, 'confirm', { ...acknowledgement, review_status: 'confirmed' }), {
    ...acknowledgement,
    review_status: 'confirmed',
  });
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

test('Review renders the localized journal-review queue count, selection, and status tags', async () => {
  const { route, calls } = createDeferredReviewRoute();
  const root = new FakeNode('main');
  route(reviewContext(root, 42));
  await settle();

  const secondChild = { id: 8, name: '小风', nickname: '风风', avatar: null };
  const secondRow = pendingQueue(43, secondChild)[0];
  secondRow.review_status = 'pending';
  calls.find(call => call.path === '/api/conversations?queue=pending').next.resolve([
    ...pendingQueue(),
    secondRow,
  ]);
  calls.find(call => call.path === '/api/conversations/42').next.resolve(detail());
  await settle();

  assert.equal(nodeText(findNode(root, node => node.tagName === 'H1')), '日记审阅');
  assert.doesNotMatch(nodeText(root), /值日审阅/);
  const queueHeading = findNode(root, node => node.tagName === 'H2' && /待审阅队列/.test(nodeText(node)));
  assert.ok(queueHeading);
  assert.match(nodeText(queueHeading), /2/);

  const selectedLink = findNode(root, node => node.tagName === 'A'
    && node.getAttribute('href') === '#review?conversation_id=42');
  assert.ok(selectedLink);
  assert.equal(selectedLink.getAttribute('aria-current'), 'page');
  const selectedRow = findNode(root, node => node.tagName === 'ARTICLE'
    && findNode(node, candidate => candidate === selectedLink));
  assert.ok(selectedRow);
  assert.match(nodeText(selectedRow), /当前/);
  assert.ok(findNode(selectedRow, node => nodeText(node) === '草稿'));

  const pendingRow = findNode(root, node => node.tagName === 'ARTICLE'
    && findNode(node, candidate => candidate.getAttribute?.('href') === '#review?conversation_id=43'));
  assert.ok(pendingRow);
  assert.ok(findNode(pendingRow, node => nodeText(node) === '待审阅'));
});

test('Review presents a localized revision, read-only overall, and initial clean status', async () => {
  const { route, calls } = createDeferredReviewRoute();
  const root = new FakeNode('main');
  route(reviewContext(root, 42));
  await settle();
  calls.find(call => call.path === '/api/conversations?queue=pending').next.resolve(pendingQueue());
  calls.find(call => call.path === '/api/conversations/42').next.resolve(detail());
  await settle();

  const rendered = nodeText(root);
  assert.match(rendered, /草稿 · 第 2 版/);
  assert.doesNotMatch(rendered, /\brevision\b/i);
  assert.match(rendered, /综合评分\s*[：:]?\s*4(?:\.0)?/);
  assert.ok(findNode(root, node => node.getAttribute?.('class')?.split(/\s+/).includes('review-save-status')
    && nodeText(node) === '全部修改已保存'));
});

test('Review announces one clean-to-dirty transition across repeated input and change events', async () => {
  const dirtyGuard = trackedDirtyGuard();
  const { route, calls } = createDeferredReviewRoute(dirtyGuard.guard);
  const root = new FakeNode('main');
  route(reviewContext(root, 42));
  await settle();
  calls.find(call => call.path === '/api/conversations?queue=pending').next.resolve(pendingQueue());
  calls.find(call => call.path === '/api/conversations/42').next.resolve(detail());
  await settle();

  const form = findNode(root, node => node.getAttribute?.('data-review-form') === '');
  const status = findNode(form, node => node.getAttribute?.('class')?.split(/\s+/).includes('review-save-status'));
  const insight = findNode(form, node => node.getAttribute?.('id') === 'review-insight');
  assert.ok(form && status && insight);
  const writes = recordTextWrites(status);
  const updatesBefore = dirtyGuard.calls.update;

  insight.value = '第一次输入';
  form.dispatch('input', { target: insight });
  insight.value = '第二次输入';
  form.dispatch('input', { target: insight });
  form.dispatch('change', { target: insight });

  assert.deepEqual(writes, ['有未保存的修改']);
  assert.equal(status.getAttribute('data-save-state'), 'dirty');
  assert.equal(dirtyGuard.calls.update, updatesBefore + 3);
  assert.equal(dirtyGuard.guard.isDirty(), true);
});

test('Review score choices do not repeat the dimension in their visible labels', async () => {
  const { route, calls } = createDeferredReviewRoute();
  const root = new FakeNode('main');
  route(reviewContext(root, 42));
  await settle();
  calls.find(call => call.path === '/api/conversations?queue=pending').next.resolve(pendingQueue());
  calls.find(call => call.path === '/api/conversations/42').next.resolve(detail());
  await settle();

  const radios = findNode(root, node => node.getAttribute?.('class')?.split(/\s+/).includes('review-score-radios'));
  assert.ok(radios);
  assert.doesNotMatch(nodeText(radios), /表达能力/);
  const labels = findNodes(radios, node => node.tagName === 'LABEL');
  assert.deepEqual(labels.map(nodeText), [
    '1 分',
    '2 分',
    '3 分',
    '4 分',
    '5 分',
  ]);
});

test('Review separates the approved insight emotion score feeding and overall card order', async () => {
  const { route, calls } = createDeferredReviewRoute();
  const root = new FakeNode('main');
  route(reviewContext(root, 42));
  await settle();
  calls.find(call => call.path === '/api/conversations?queue=pending').next.resolve(pendingQueue());
  calls.find(call => call.path === '/api/conversations/42').next.resolve(detail());
  await settle();

  const content = findNode(root, node => node.getAttribute?.('class') === 'review-editor-content');
  assert.ok(content);
  const cards = content.children.filter(node => node?.getAttribute?.('class')
    ?.split(/\s+/).includes('review-section-card'));
  const cardHeadings = cards.map(card => {
    const heading = findNode(card, node => ['H2', 'H3'].includes(node.tagName));
    return nodeText(heading);
  });
  assert.deepEqual(cardHeadings, [
    '教育洞察',
    '情绪判断',
    '能力评分',
    '饲养记录',
    '综合评分（只读）',
  ]);
  assert.equal(findNode(cards[2], node => ['H2', 'H3'].includes(node.tagName)).tagName, 'H3');
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

test('Review PUT uses the frozen options and a cleanup-late ignored-signal acknowledgement has no owner effects', async () => {
  const dirtyGuard = trackedDirtyGuard();
  const { route, calls } = createDeferredReviewRoute(dirtyGuard.guard);
  const root = new FakeNode('main');
  const instance = route(reviewContext(root, 42));
  await settle();
  calls.find(call => call.path === '/api/conversations?queue=pending').next.resolve(pendingQueue());
  calls.find(call => call.path === '/api/conversations/42').next.resolve(detail());
  await settle();
  nodeWithText(root, 'BUTTON', '保存草稿').click();
  await settle();
  const mutation = calls.find(call => call.path === '/api/conversations/42/review');
  assert.ok(mutation);
  assert.equal(mutation.options.method, 'PUT');
  assert.equal(mutation.options.timeoutMs, 15000);
  assert.equal(mutation.options.timeout, undefined);
  assert.equal(mutation.options.sequenceKey, 'teacher-review-mutation');
  assert.deepEqual(Object.keys(mutation.options.body).sort(), ['action', 'emotion', 'feeding_logs', 'insight', 'revision', 'scores']);
  const cleanCallsBeforeLate = dirtyGuard.calls.markClean;
  const queueCallsBeforeLate = calls.filter(call => call.path === '/api/conversations?queue=pending').length;
  const textBeforeCleanup = nodeText(root);
  instance.cleanup();
  mutation.next.resolve({
    saved: true,
    conversation_id: 42,
    review_status: 'draft',
    revision: 3,
    saved_at: '2026-08-23T09:03:00Z',
    review: reviewDocument(),
  });
  await settle();
  assert.equal(dirtyGuard.calls.markClean, cleanCallsBeforeLate);
  assert.equal(calls.filter(call => call.path === '/api/conversations?queue=pending').length, queueCallsBeforeLate);
  assert.equal(nodeText(root), textBeforeCleanup);
});

test('Review snapshots a direct DOM edit before PUT and keeps the guard dirty after owning failure', async () => {
  const dirtyGuard = trackedDirtyGuard();
  const { route, calls } = createDeferredReviewRoute(dirtyGuard.guard);
  const root = new FakeNode('main');
  route(reviewContext(root, 42));
  await settle();
  calls.find(call => call.path === '/api/conversations?queue=pending').next.resolve(pendingQueue());
  calls.find(call => call.path === '/api/conversations/42').next.resolve(detail());
  await settle();
  const insight = findNode(root, candidate => candidate.getAttribute?.('id') === 'review-insight');
  const status = findNode(root, candidate => candidate.getAttribute?.('class')?.split(/\s+/).includes('review-save-status'));
  assert.ok(insight && status);
  const writes = recordTextWrites(status);
  insight.value = '  未确认的原样输入  ';
  const cleanCallsBefore = dirtyGuard.calls.markClean;
  const updatesBefore = dirtyGuard.calls.update;
  nodeWithText(root, 'BUTTON', '保存草稿').click();
  await settle();
  const mutation = calls.find(call => call.path === '/api/conversations/42/review');
  assert.ok(mutation);
  assert.deepEqual(writes, ['有未保存的修改', '正在保存…']);
  assert.equal(dirtyGuard.calls.update, updatesBefore + 1);
  assert.equal(JSON.parse(dirtyGuard.calls.updates.at(-1)).insight, '未确认的原样输入');
  assert.equal(dirtyGuard.guard.isDirty(), true);
  const queueCallsBefore = calls.filter(call => call.path === '/api/conversations?queue=pending').length;
  mutation.next.resolve(undefined);
  await settle();
  assert.match(nodeText(root), /保存失败，请稍后重试。/);
  assert.equal(nodeText(status), '保存失败，修改仍未保存');
  assert.equal(status.getAttribute('data-save-state'), 'failure');
  assert.deepEqual(writes, [
    '有未保存的修改',
    '正在保存…',
    '保存失败，修改仍未保存',
  ]);
  assert.equal(dirtyGuard.guard.isDirty(), true);
  assert.equal(await dirtyGuard.guard.confirmLeave(), false);
  assert.doesNotMatch(nodeText(root), /审阅已确认/);
  assert.equal(insight.value, '  未确认的原样输入  ');
  const form = findNode(root, candidate => candidate.getAttribute?.('data-review-form') === '');
  const controls = findNodes(form, candidate => ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(candidate.tagName));
  assert.ok(controls.length > 0);
  assert.equal(controls.every(control => control.disabled === false), true);
  assert.equal(dirtyGuard.calls.markClean, cleanCallsBefore);
  assert.equal(dirtyGuard.calls.update, updatesBefore + 1);
  assert.equal(calls.filter(call => call.path === '/api/conversations?queue=pending').length, queueCallsBefore);
});

test('Review reports owning draft and confirm failures without corrupting clean guard truth', async () => {
  const cases = [
    ['保存草稿', '保存失败，请稍后重试'],
    ['保存并确认', '确认失败，请稍后重试'],
  ];
  for (const [buttonCopy, expectedStatus] of cases) {
    const dirtyGuard = trackedDirtyGuard();
    const { route, calls } = createDeferredReviewRoute(dirtyGuard.guard);
    const root = new FakeNode('main');
    route(reviewContext(root, 42));
    await settle();
    calls.find(call => call.path === '/api/conversations?queue=pending').next.resolve(pendingQueue());
    calls.find(call => call.path === '/api/conversations/42').next.resolve(detail());
    await settle();

    const updatesBefore = dirtyGuard.calls.update;
    nodeWithText(root, 'BUTTON', buttonCopy).click();
    await settle();
    const mutation = calls.find(call => call.path === '/api/conversations/42/review');
    assert.ok(mutation, buttonCopy);
    assert.equal(dirtyGuard.calls.update, updatesBefore + 1, buttonCopy);
    assert.equal(dirtyGuard.guard.isDirty(), false, buttonCopy);
    mutation.next.reject(new Error('fixed owning failure'));
    await settle();

    const status = findNode(root, node => node.getAttribute?.('class')?.split(/\s+/).includes('review-save-status'));
    assert.ok(status, buttonCopy);
    assert.equal(status.getAttribute('data-save-state'), 'failure', buttonCopy);
    assert.equal(nodeText(status), expectedStatus, buttonCopy);
    assert.equal(dirtyGuard.guard.isDirty(), false, buttonCopy);
    assert.equal(await dirtyGuard.guard.confirmLeave(), true, buttonCopy);
  }
});

test('Review reports controller-construction failure while preserving a direct edit as dirty', async () => {
  const dirtyGuard = trackedDirtyGuard();
  let controllerCalls = 0;
  const createAbortController = () => {
    controllerCalls += 1;
    if (controllerCalls === 4) throw new Error('mutation controller unavailable');
    return new FakeController();
  };
  const { route, calls } = createDeferredReviewRoute(dirtyGuard.guard, createAbortController);
  const root = new FakeNode('main');
  route(reviewContext(root, 42));
  await settle();
  calls.find(call => call.path === '/api/conversations?queue=pending').next.resolve(pendingQueue());
  calls.find(call => call.path === '/api/conversations/42').next.resolve(detail());
  await settle();

  const insight = findNode(root, node => node.getAttribute?.('id') === 'review-insight');
  insight.value = '无事件的 controller 失败修改';
  nodeWithText(root, 'BUTTON', '保存草稿').click();
  await settle();

  const status = findNode(root, node => node.getAttribute?.('class')?.split(/\s+/).includes('review-save-status'));
  assert.ok(status);
  assert.equal(controllerCalls, 4);
  assert.equal(calls.filter(call => call.path === '/api/conversations/42/review').length, 0);
  assert.equal(status.getAttribute('data-save-state'), 'failure');
  assert.equal(nodeText(status), '保存失败，修改仍未保存');
  assert.equal(dirtyGuard.guard.isDirty(), true);
  assert.equal(await dirtyGuard.guard.confirmLeave(), false);
});

async function startDeferredMutation({ dirtyGuard = fakeDirtyGuard(), conversationId = 42 } = {}) {
  const { route, calls } = createDeferredReviewRoute(dirtyGuard);
  const root = new FakeNode('main');
  const instance = route(reviewContext(root, conversationId));
  await settle();
  calls.find(call => call.path === '/api/conversations?queue=pending').next.resolve(pendingQueue(conversationId));
  calls.find(call => call.path === `/api/conversations/${conversationId}`).next.resolve(detail({ id: conversationId }));
  await settle();
  nodeWithText(root, 'BUTTON', '保存草稿').click();
  await settle();
  const mutation = calls.find(call => call.path === `/api/conversations/${conversationId}/review`);
  assert.ok(mutation);
  return { route, calls, root, instance, mutation };
}

test('Review absorbs an ignored-signal cleanup-late rejection without stale error, unlock, clean, or queue effects', async () => {
  const dirtyGuard = trackedDirtyGuard();
  const { calls, root, instance, mutation } = await startDeferredMutation({ dirtyGuard: dirtyGuard.guard });
  const before = {
    text: nodeText(root),
    clean: dirtyGuard.calls.markClean,
    queue: calls.filter(call => call.path === '/api/conversations?queue=pending').length,
  };
  instance.cleanup();
  mutation.next.reject(new Error('ignored signal late rejection'));
  await settle();
  assert.equal(nodeText(root), before.text);
  assert.equal(dirtyGuard.calls.markClean, before.clean);
  assert.equal(calls.filter(call => call.path === '/api/conversations?queue=pending').length, before.queue);
});

test('Review detail reload owns the workspace before an ignored-signal old PUT resolves or rejects', async () => {
  for (const outcome of ['resolve', 'reject']) {
    const dirtyGuard = trackedDirtyGuard();
    const { calls, root, mutation } = await startDeferredMutation({ dirtyGuard: dirtyGuard.guard });
    nodeWithText(root, 'BUTTON', '重新加载此会话').click();
    await settle();
    const detailCalls = calls.filter(call => call.path === '/api/conversations/42');
    assert.equal(detailCalls.length, 2, outcome);
    detailCalls[1].next.resolve(detail({ review: reviewDocument({ insight: `新 owner ${outcome}` }) }));
    await settle();
    const newOwnerText = nodeText(root);
    const queueCount = calls.filter(call => call.path === '/api/conversations?queue=pending').length;
    if (outcome === 'resolve') {
      mutation.next.resolve({
        saved: true, conversation_id: 42, review_status: 'draft', revision: 3,
        saved_at: '2026-08-23T09:03:00Z', review: reviewDocument({ insight: '过期保存' }),
      });
    } else {
      mutation.next.reject(new Error('old mutation rejected'));
    }
    await settle();
    assert.equal(nodeText(root), newOwnerText, outcome);
    assert.equal(controlValue(root, 'review-insight'), `新 owner ${outcome}`, outcome);
    assert.doesNotMatch(nodeText(root), /过期保存|保存失败/, outcome);
    assert.equal(calls.filter(call => call.path === '/api/conversations?queue=pending').length, queueCount, outcome);
  }
});

test('Review route A to B gives the new owner immunity from ignored-signal old PUT success and rejection', async () => {
  for (const outcome of ['resolve', 'reject']) {
    const { route, calls, root, instance, mutation } = await startDeferredMutation();
    instance.cleanup();
    route(reviewContext(root, 43));
    await settle();
    const queueCalls = calls.filter(call => call.path === '/api/conversations?queue=pending');
    queueCalls.at(-1).next.resolve(pendingQueue(43, { id: 8, name: '小风', nickname: '风风', avatar: null }));
    calls.find(call => call.path === '/api/conversations/43').next.resolve(detail({
      id: 43,
      child: { id: 8, name: '小风', nickname: '风风', avatar: null },
      review: reviewDocument({ insight: `B owner ${outcome}` }),
    }));
    await settle();
    const newOwnerText = nodeText(root);
    const queueCount = calls.filter(call => call.path === '/api/conversations?queue=pending').length;
    if (outcome === 'resolve') {
      mutation.next.resolve({
        saved: true, conversation_id: 42, review_status: 'draft', revision: 3,
        saved_at: '2026-08-23T09:03:00Z', review: reviewDocument({ insight: '过期 A 保存' }),
      });
    } else {
      mutation.next.reject(new Error('old A mutation rejected'));
    }
    await settle();
    assert.equal(nodeText(root), newOwnerText, outcome);
    assert.equal(controlValue(root, 'review-insight'), `B owner ${outcome}`, outcome);
    assert.doesNotMatch(nodeText(root), /过期 A 保存|保存失败/, outcome);
    assert.equal(calls.filter(call => call.path === '/api/conversations?queue=pending').length, queueCount, outcome);
  }
});

test('Review projects hostile outer errors and fieldErrors without executing traps or rendering server values', async () => {
  const outerAccessor = {};
  Object.defineProperty(outerAccessor, 'status', { get() { throw new Error('must not run'); }, enumerable: true });
  Object.defineProperty(outerAccessor, 'code', { value: 'VALIDATION_ERROR', enumerable: true });
  const outerProxy = new Proxy({}, { ownKeys() { throw new Error('outer trap'); } });
  const fieldAccessor = {};
  Object.defineProperty(fieldAccessor, 'insight', { get() { throw new Error('field trap'); }, enumerable: true });
  const fieldProxy = new Proxy({}, { ownKeys() { throw new Error('field ownKeys trap'); } });
  const cases = [
    ['outer accessor', outerAccessor, '保存失败，请稍后重试。'],
    ['outer proxy', outerProxy, '保存失败，请稍后重试。'],
    ['fieldErrors accessor descriptor', Object.defineProperty({ status: 422, code: 'VALIDATION_ERROR' }, 'fieldErrors', { get() { throw new Error('must not run'); }, enumerable: true }), '保存失败，请稍后重试。'],
    ['missing fieldErrors', { status: 422, code: 'VALIDATION_ERROR' }, '保存失败，请稍后重试。'],
    ['fieldErrors proxy', { status: 422, code: 'VALIDATION_ERROR', fieldErrors: fieldProxy }, '部分内容未通过校验，请检查后重试。'],
    ['fieldErrors nested accessor', { status: 422, code: 'VALIDATION_ERROR', fieldErrors: fieldAccessor }, '部分内容未通过校验，请检查后重试。'],
    ['one body prefix', { status: 422, code: 'VALIDATION_ERROR', fieldErrors: { 'body.insight': ['raw secret'] } }, '部分内容未通过校验，请检查后重试。'],
    ['two body prefixes', { status: 422, code: 'VALIDATION_ERROR', fieldErrors: { 'body.body.insight': ['raw secret'] } }, '部分内容未通过校验，请检查后重试。'],
    ['immutable field', { status: 422, code: 'VALIDATION_ERROR', fieldErrors: { 'feeding_logs.0.id': ['raw secret'] } }, '部分内容未通过校验，请检查后重试。'],
    ['out of range', { status: 422, code: 'REVIEW_VALIDATION_FAILED', fieldErrors: { 'scores.9.reason': ['raw secret'] } }, '部分内容未通过校验，请检查后重试。'],
    ['aggregate', { status: 422, code: 'REVIEW_VALIDATION_FAILED', fieldErrors: { scores: ['raw secret'] } }, '部分内容未通过校验，请检查后重试。'],
  ];
  for (const [label, rejection, expected] of cases) {
    const { calls, root, mutation } = await startDeferredMutation();
    const queueCount = calls.filter(call => call.path === '/api/conversations?queue=pending').length;
    mutation.next.reject(rejection);
    await settle();
    assert.match(nodeText(root), new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')), label);
    assert.doesNotMatch(nodeText(root), /raw secret|must not run|trap/, label);
    assert.equal(calls.filter(call => call.path === '/api/conversations?queue=pending').length, queueCount, label);
    assert.equal(nodeWithText(root, 'BUTTON', '保存草稿').disabled, false, label);
    assert.equal(nodeWithText(root, 'BUTTON', '保存并确认').disabled, false, label);
  }
});
