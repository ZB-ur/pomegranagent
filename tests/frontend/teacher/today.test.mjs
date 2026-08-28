import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createTodayRoute,
  displayName,
  queueStatusLabel,
  validateQueueRows,
  validateRetryResponse,
  validateRosterRows,
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
