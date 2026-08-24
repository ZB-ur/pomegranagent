import test from 'node:test';
import assert from 'node:assert/strict';

import * as machine from '../../../app/frontend/child/machine.mjs';
import * as sessionStore from '../../../app/frontend/child/session-store.mjs';

const {
  SESSION_KEY,
  createDraft,
  createSessionStore,
  mergeRecovery,
} = sessionStore;
const { assertSnapshot, createInitialSnapshot, transition } = machine;

const REQUEST_ID = '00000000-0000-4000-8000-000000000001';
const CREATED_AT = '2026-08-23T00:00:00.000Z';
const UPDATED_AT = '2026-08-23T00:01:00.000Z';

function child(id = 7, name = '小雨') {
  return { id, name, nickname: null, avatar: null };
}

function message(id = 12, role = 'diary', text = '真棒！') {
  return { id, role, text };
}

function draft(overrides = {}) {
  return { text: '我喂了小鸭', request_id: REQUEST_ID, created_at: CREATED_AT, ...overrides };
}

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  const calls = { get: 0, set: 0, remove: 0 };
  return {
    data,
    calls,
    getItem(key) {
      calls.get += 1;
      return data.get(key) ?? null;
    },
    setItem(key, value) {
      calls.set += 1;
      data.set(key, value);
    },
    removeItem(key) {
      calls.remove += 1;
      data.delete(key);
    },
  };
}

function rawRecord(overrides = {}) {
  return {
    version: 1,
    child: child(),
    conversation_id: 9,
    revision: 0,
    last_message_id: 12,
    state: 'ready',
    messages: [message()],
    draft: null,
    should_complete: false,
    failure: null,
    updated_at: UPDATED_AT,
    ...overrides,
  };
}

function snapshot(overrides = {}) {
  return createInitialSnapshot({
    value: 'ready',
    child: child(),
    conversationId: 9,
    revision: 0,
    lastMessageId: 12,
    messages: [message()],
    ...overrides,
  });
}

function active(overrides = {}) {
  return {
    id: 9,
    child_id: 7,
    status: 'active',
    revision: 0,
    round: 1,
    last_message_id: 12,
    messages: [message()],
    ...overrides,
  };
}

function success(queriedChild = child(), conversation = active()) {
  return { kind: 'success', queriedChild, active: { conversation } };
}

function failure(queriedChild = child(), error = { code: 'NETWORK_ERROR', retryable: true, message: '稍后再试' }) {
  return { kind: 'failure', queriedChild, error };
}

function recordForDraft(overrides = {}) {
  return rawRecord({
    conversation_id: null,
    revision: null,
    last_message_id: null,
    state: 'submission_failed',
    messages: [],
    draft: draft(),
    should_complete: false,
    failure: { code: 'NETWORK_ERROR', retryable: true },
    ...overrides,
  });
}

function outcome(result, value, action) {
  assert.deepEqual(Object.keys(result).sort(), ['snapshot', 'storageAction']);
  assert.equal(result.storageAction, action);
  assert.equal(result.snapshot.value, value);
  assert.equal(result.snapshot.teacherUnlocked, false);
  assert.equal(assertSnapshot(result.snapshot), result.snapshot);
  assertRecursivelyFrozen(result);
  return result.snapshot;
}

function assertRecursivelyFrozen(value) {
  if (value !== null && typeof value === 'object') {
    assert.equal(Object.isFrozen(value), true);
    for (const nested of Object.values(value)) assertRecursivelyFrozen(nested);
  }
}

function completeResult(overrides = {}) {
  return {
    conversation_id: 9,
    conversation_saved: true,
    status: 'completed',
    completed_at: '2026-08-23T00:02:00Z',
    message_count: 2,
    last_message_id: 42,
    analysis_job_id: 3,
    analysis_status: 'pending',
    replayed: false,
    ...overrides,
  };
}

test('exports exactly the approved strict storage surface', () => {
  assert.deepEqual(Object.keys(sessionStore).sort(), [
    'SESSION_KEY', 'createDraft', 'createSessionStore', 'mergeRecovery',
  ]);
  assert.equal(SESSION_KEY, 'duck-diary.child-session.v1');

  const store = createSessionStore(memoryStorage(), { now: () => UPDATED_AT });
  assert.equal(Object.isFrozen(store), true);
  assert.deepEqual(Object.keys(store).sort(), ['clear', 'load', 'save']);
  for (const method of Object.values(store)) assert.equal(typeof method, 'function');
});

test('creates a trimmed, canonical, immutable draft with exactly one UUID and clock read', () => {
  let uuidCalls = 0;
  let nowCalls = 0;
  const result = createDraft('  我  喂了，小鸭！  ', {
    uuid: () => {
      uuidCalls += 1;
      return REQUEST_ID;
    },
    now: () => {
      nowCalls += 1;
      return CREATED_AT;
    },
  });

  assert.deepEqual(result, { text: '我  喂了，小鸭！', request_id: REQUEST_ID, created_at: CREATED_AT });
  assert.deepEqual(Object.keys(result), ['text', 'request_id', 'created_at']);
  assert.equal(uuidCalls, 1);
  assert.equal(nowCalls, 1);
  assertRecursivelyFrozen(result);
});

test('rejects blank draft text and noncanonical injected UUID or timestamp values', () => {
  const valid = { uuid: () => REQUEST_ID, now: () => CREATED_AT };
  for (const text of [null, 4, '', ' \n\t ']) {
    assert.throws(() => createDraft(text, valid), TypeError);
  }
  for (const invalid of [
    { uuid: () => 'fixed-uuid', now: () => CREATED_AT },
    { uuid: () => '00000000-0000-0000-8000-000000000001', now: () => CREATED_AT },
    { uuid: () => '00000000-0000-4000-7000-000000000001', now: () => CREATED_AT },
    { uuid: () => REQUEST_ID, now: () => '2026-08-23T00:00:00Z' },
    { uuid: () => REQUEST_ID, now: () => '2026-02-30T00:00:00.000Z' },
    { uuid: null, now: () => CREATED_AT },
    { uuid: () => REQUEST_ID, now: null },
  ]) {
    assert.throws(() => createDraft('一句话', invalid), TypeError);
  }
});

test('rejects invalid storage construction and propagates storage method errors unchanged', () => {
  for (const storage of [null, {}, { getItem() {}, setItem() {}, removeItem: null }]) {
    assert.throws(() => createSessionStore(storage), TypeError);
  }
  assert.throws(() => createSessionStore(memoryStorage(), { now: null }), TypeError);

  const readError = new Error('read identity');
  const writeError = new Error('write identity');
  const clearError = new Error('clear identity');
  const store = createSessionStore({
    getItem() { throw readError; },
    setItem() { throw writeError; },
    removeItem() { throw clearError; },
  }, { now: () => UPDATED_AT });
  assert.throws(() => store.load(), error => error === readError);
  assert.throws(() => store.save(snapshot()), error => error === writeError);
  assert.throws(() => store.clear(), error => error === clearError);
});

test('save validates the machine snapshot before reading the clock or writing', () => {
  const storage = memoryStorage();
  let nowCalls = 0;
  const store = createSessionStore(storage, { now: () => { nowCalls += 1; return UPDATED_AT; } });
  const invalid = { ...snapshot(), teacherPin: '1234' };

  assert.throws(() => store.save(invalid), TypeError);
  assert.equal(storage.calls.set, 0);
  assert.equal(nowCalls, 0);
});

test('save projects only allowed fields, sanitizes machine error details, and reloads its projection', () => {
  const storage = memoryStorage();
  const store = createSessionStore(storage, { now: () => UPDATED_AT });
  const base = snapshot({
    value: 'recovery',
    error: { code: 'CHAT_TIMEOUT', retryable: true, message: 'provider detail' },
  });
  const input = {
    ...base,
    child: { ...base.child, teacherPin: '1234' },
    messages: [{ ...base.messages[0], privateNote: '不要存' }],
    draft: { ...draft(), pin: '1234' },
    error: { ...base.error, cause: { token: 'secret' } },
    reply: 'transient reply',
  };
  const saved = store.save(input);
  const serialized = storage.data.get(SESSION_KEY);
  const parsed = JSON.parse(serialized);

  assert.deepEqual(Object.keys(parsed).sort(), [
    'child', 'conversation_id', 'draft', 'failure', 'last_message_id', 'messages',
    'revision', 'should_complete', 'state', 'updated_at', 'version',
  ]);
  assert.deepEqual(parsed.child, child());
  assert.deepEqual(parsed.messages, [message()]);
  assert.deepEqual(parsed.draft, draft());
  assert.deepEqual(parsed.failure, { code: 'CHAT_TIMEOUT', retryable: true });
  for (const forbidden of ['1234', 'provider detail', 'secret', 'privateNote', 'reply', 'teacherPin', 'cause']) {
    assert.equal(serialized.includes(forbidden), false, forbidden);
  }
  assertRecursivelyFrozen(saved);
  const loaded = store.load();
  assert.deepEqual(loaded.failure, { code: 'CHAT_TIMEOUT', retryable: true });
  assert.deepEqual(loaded.draft, draft());
  assertRecursivelyFrozen(loaded);
});

test('save and load return isolated frozen records that cannot share caller or prior-result references', () => {
  const storage = memoryStorage();
  const store = createSessionStore(storage, { now: () => UPDATED_AT });
  const source = snapshot({ draft: draft(), value: 'submission_failed', error: { code: 'NETWORK_ERROR', retryable: true } });
  const saved = store.save(source);
  const firstLoad = store.load();
  const secondLoad = store.load();

  assert.notEqual(saved, firstLoad);
  assert.notEqual(firstLoad, secondLoad);
  assert.notEqual(firstLoad.child, secondLoad.child);
  assert.notEqual(firstLoad.messages, secondLoad.messages);
  assert.throws(() => { firstLoad.child.name = '篡改'; }, TypeError);
  assert.deepEqual(secondLoad.child, child());
  assert.equal(JSON.parse(storage.data.get(SESSION_KEY)).child.name, '小雨');
});

test('load treats corrupt, noncanonical, wrong-version, and any unknown nested record as missing without mutation', () => {
  const cases = [
    null,
    '{not-json',
    JSON.stringify(rawRecord({ version: 2 })),
    JSON.stringify(rawRecord({ unexpected: true })),
    JSON.stringify(rawRecord({ child: { ...child(), extra: true } })),
    JSON.stringify(rawRecord({ messages: [{ ...message(), extra: true }] })),
    JSON.stringify(rawRecord({ draft: { ...draft(), extra: true } })),
    JSON.stringify(rawRecord({ failure: { code: 'X', retryable: true, message: 'not stored' } })),
    JSON.stringify(rawRecord({ state: 'not-a-state' })),
    JSON.stringify(rawRecord({ conversation_id: 0 })),
    JSON.stringify(rawRecord({ revision: -1 })),
    JSON.stringify(rawRecord({ last_message_id: 0 })),
    JSON.stringify(rawRecord({ messages: [{ id: 12, role: 'teacher', text: 'x' }] })),
    JSON.stringify(rawRecord({ updated_at: '2026-08-23T00:01:00Z' })),
    JSON.stringify(recordForDraft({ draft: draft({ request_id: 'not-a-uuid' }) })),
    JSON.stringify(recordForDraft({ draft: draft({ created_at: '2026-08-23T00:00:00Z' }) })),
    JSON.stringify(rawRecord({ should_complete: 'yes' })),
    JSON.stringify(rawRecord({ state: 'recovery', failure: null })),
    JSON.stringify(rawRecord({ state: 'ready', should_complete: true })),
    JSON.stringify(rawRecord({ state: 'saving_conversation', should_complete: false })),
    JSON.stringify(recordForDraft({ state: 'submission_failed', failure: { code: 'NETWORK_ERROR', retryable: false } })),
  ];
  for (const serialized of cases) {
    const storage = memoryStorage(serialized === null ? {} : { [SESSION_KEY]: serialized });
    const store = createSessionStore(storage, { now: () => UPDATED_AT });
    assert.equal(store.load(), null);
    assert.equal(storage.calls.set, 0);
    assert.equal(storage.calls.remove, 0);
  }
});

test('store enforces state, failure, completion, child, and time invariants before one write', () => {
  const invalidSnapshots = [
    snapshot({ child: null, draft: draft(), value: 'submission_failed', error: { code: 'NETWORK_ERROR', retryable: true } }),
    snapshot({ value: 'submission_failed', draft: draft(), error: null }),
    snapshot({ value: 'submission_failed', draft: draft(), error: { code: 'NETWORK_ERROR', retryable: false } }),
    snapshot({ value: 'ready', error: { code: 'NETWORK_ERROR', retryable: true } }),
    snapshot({ value: 'saving_conversation', shouldComplete: false }),
    snapshot({ value: 'completed', shouldComplete: false }),
    snapshot({ shouldComplete: true, draft: draft() }),
    snapshot({ draft: draft({ request_id: 'bad' }), value: 'submission_failed', error: { code: 'NETWORK_ERROR', retryable: true } }),
  ];
  for (const source of invalidSnapshots) {
    const storage = memoryStorage();
    let nowCalls = 0;
    const store = createSessionStore(storage, { now: () => { nowCalls += 1; return UPDATED_AT; } });
    assert.throws(() => store.save(source), TypeError);
    assert.equal(storage.calls.set, 0);
    assert.equal(nowCalls, 0);
  }
});

test('save rejects a throwing or noncanonical clock after structural validation with zero writes', () => {
  const clockError = new Error('clock identity');
  for (const now of [() => { throw clockError; }, () => '2026-08-23T00:01:00Z']) {
    const storage = memoryStorage();
    const store = createSessionStore(storage, { now });
    assert.throws(() => store.save(snapshot()), error => now.toString().includes('throw') ? error === clockError : error instanceof TypeError);
    assert.equal(storage.calls.set, 0);
  }
});

test('clear invokes only the scoped remove operation', () => {
  const storage = memoryStorage({ [SESSION_KEY]: JSON.stringify(rawRecord()) });
  const store = createSessionStore(storage, { now: () => UPDATED_AT });
  assert.equal(store.clear(), undefined);
  assert.equal(storage.calls.get, 0);
  assert.equal(storage.calls.set, 0);
  assert.equal(storage.calls.remove, 1);
  assert.equal(storage.data.has(SESSION_KEY), false);
});

test('merge recovery handles missing local success rows with explicit clear effects', () => {
  const noActive = outcome(mergeRecovery(null, success(null, null)), 'loading_roster', 'clear');
  assert.equal(noActive.child, null);

  const activeSession = outcome(mergeRecovery(null, success(child(7, '远端小雨'), active())), 'ready', 'clear');
  assert.deepEqual(activeSession.child, child(7, '远端小雨'));
  assert.equal(activeSession.conversationId, 9);
  assert.equal(activeSession.revision, 0);
  assert.deepEqual(activeSession.messages, [message()]);
});

test('merge recovery uses remote active metadata and fresh queried-child identity for an ordinary local session', () => {
  const local = rawRecord({ child: child(7, '旧名字'), revision: 8, messages: [message(8, 'child', '旧话')], last_message_id: 8 });
  const merged = outcome(mergeRecovery(local, success(child(7, '新名字'), active({ revision: 0 }))), 'ready', 'keep');
  assert.deepEqual(merged.child, child(7, '新名字'));
  assert.equal(merged.revision, 0);
  assert.deepEqual(merged.messages, [message()]);
});

test('unbound and matching bound drafts become child-retryable without changing their request identity', () => {
  const unbound = outcome(mergeRecovery(recordForDraft(), success(child(), active())), 'submission_failed', 'keep');
  assert.deepEqual(unbound.draft, draft());
  assert.deepEqual(unbound.error, { code: 'LOCAL_DRAFT_NOT_CONFIRMED', retryable: true });
  assert.equal(unbound.conversationId, 9);

  const bound = outcome(mergeRecovery(recordForDraft({ conversation_id: 9, revision: 0, last_message_id: 12, messages: [message()] }), success()), 'submission_failed', 'keep');
  assert.deepEqual(bound.draft, draft());
  assert.equal(bound.conversationId, 9);
});

test('a bound local draft cannot cross into another active conversation', () => {
  const local = recordForDraft({ conversation_id: 9, revision: 0, last_message_id: 12, messages: [message()] });
  const merged = outcome(mergeRecovery(local, success(child(), active({ id: 10 }))), 'recovery', 'keep');
  assert.deepEqual(merged.error, { code: 'RECOVERY_CONVERSATION_MISMATCH', retryable: false });
  assert.equal(merged.conversationId, 9);
  assert.deepEqual(merged.draft, draft());
});

test('every individual server-binding form protects a local draft when no remote session exists', () => {
  const forms = [
    { conversation_id: 9 },
    { revision: 0 },
    { last_message_id: 12 },
    { messages: [message()] },
  ];
  for (const binding of forms) {
    const merged = outcome(mergeRecovery(recordForDraft(binding), success(child(), null)), 'recovery', 'keep');
    assert.deepEqual(merged.error, { code: 'RECOVERY_CONVERSATION_MISSING', retryable: false });
    assert.deepEqual(merged.draft, draft());
  }
  const firstTurn = outcome(mergeRecovery(recordForDraft(), success(child(), null)), 'submission_failed', 'keep');
  assert.deepEqual(firstTurn.error, { code: 'LOCAL_DRAFT_NOT_CONFIRMED', retryable: true });
});

test('merge recovery clears ordinary no-draft records but preserves both reachable child mismatch shapes', () => {
  const cleared = outcome(mergeRecovery(rawRecord(), success(child(), null)), 'loading_roster', 'clear');
  assert.equal(cleared.child, null);

  const noActiveMismatch = outcome(mergeRecovery(rawRecord(), success(child(8, '小满'), null)), 'recovery', 'keep');
  assert.deepEqual(noActiveMismatch.error, { code: 'RECOVERY_CHILD_MISMATCH', retryable: false });
  assert.equal(noActiveMismatch.child.id, 7);

  const activeMismatch = outcome(mergeRecovery(rawRecord(), success(child(8, '小满'), active({ child_id: 8 }))), 'recovery', 'keep');
  assert.deepEqual(activeMismatch.error, { code: 'RECOVERY_CHILD_MISMATCH', retryable: false });
  assert.equal(activeMismatch.child.id, 7);
});

test('pending completion keeps the remote completion boundary and never reopens chat', () => {
  const local = rawRecord({
    state: 'speaking',
    draft: null,
    should_complete: true,
    revision: 0,
    last_message_id: 12,
    messages: [message()],
  });
  const merged = outcome(mergeRecovery(local, success()), 'saving_conversation', 'keep');
  assert.equal(merged.shouldComplete, true);
  assert.equal(merged.conversationId, 9);
  assert.equal(merged.lastMessageId, 12);
  assert.equal(merged.draft, null);
  assert.equal(merged.reply, null);
  assert.equal(merged.error, null);

  const missingBoundary = outcome(mergeRecovery(local, success(child(), active({ last_message_id: null, messages: [] }))), 'recovery', 'keep');
  assert.deepEqual(missingBoundary.error, { code: 'RECOVERY_COMPLETION_BOUNDARY_MISSING', retryable: false });
  assert.equal(missingBoundary.shouldComplete, true);
});

test('ended chat saved through the machine restores only the completion path', () => {
  let state = createInitialSnapshot({ value: 'listening', child: child() });
  state = transition(state, { type: 'SPEECH_FINAL', draft: draft() });
  state = transition(state, {
    type: 'SUBMIT_SUCCEEDED',
    result: {
      request_id: REQUEST_ID,
      conversation_id: 9,
      child_message_id: 41,
      diary_message_id: 42,
      reply: '今天完成啦',
      round: 1,
      ended: true,
      end_reason: 'complete',
      replayed: false,
    },
  });
  assert.equal(state.value, 'speaking');
  assert.equal(state.shouldComplete, true);

  const storage = memoryStorage();
  const store = createSessionStore(storage, { now: () => UPDATED_AT });
  const saved = store.save(state);
  const merged = outcome(mergeRecovery(saved, success(child(), active({
    last_message_id: 42,
    messages: [message(41, 'child', '我喂了小鸭'), message(42, 'diary', '今天完成啦')],
  }))), 'saving_conversation', 'keep');
  assert.equal(merged.shouldComplete, true);
  assert.equal(merged.value, 'saving_conversation');
  assert.equal(transition(merged, { type: 'COMPLETE_SUCCEEDED', result: completeResult() }).value, 'completed');
});

test('a COMPLETE_FAILED recovery reload returns to saving_conversation at the same remote boundary', () => {
  const saving = createInitialSnapshot({
    value: 'saving_conversation', child: child(), conversationId: 9, revision: 0, lastMessageId: 42,
    messages: [message(41, 'child', '我喂了小鸭'), message(42, 'diary', '真棒！')], shouldComplete: true,
  });
  const failed = transition(saving, { type: 'COMPLETE_FAILED', error: { code: 'COMPLETE_FAILED', retryable: false } });
  const storage = memoryStorage();
  const store = createSessionStore(storage, { now: () => UPDATED_AT });
  const loaded = store.load();
  assert.equal(loaded, null);
  const saved = store.save(failed);
  const merged = outcome(mergeRecovery(saved, success(child(), active({
    last_message_id: 42,
    messages: [message(41, 'child', '我喂了小鸭'), message(42, 'diary', '真棒！')],
  }))), 'saving_conversation', 'keep');
  assert.equal(merged.lastMessageId, 42);
  assert.equal(merged.shouldComplete, true);
});

test('persisted nonretryable recovery remains teacher-only after matching-active and no-active refreshes', () => {
  const local = rawRecord({
    state: 'recovery',
    draft: draft(),
    failure: { code: 'IDEMPOTENCY_CONFLICT', retryable: false },
  });
  for (const remote of [success(), success(child(), null)]) {
    const merged = outcome(mergeRecovery(local, remote), 'recovery', 'keep');
    assert.deepEqual(merged.error, { code: 'IDEMPOTENCY_CONFLICT', retryable: false });
    assert.deepEqual(merged.draft, draft());
  }

  const retryable = recordForDraft({ state: 'recovery', failure: { code: 'NETWORK_ERROR', retryable: true } });
  const resolved = outcome(mergeRecovery(retryable, success()), 'submission_failed', 'keep');
  assert.deepEqual(resolved.error, { code: 'LOCAL_DRAFT_NOT_CONFIRMED', retryable: true });
});

test('remote failures preserve valid local context and teacher boundaries, and recover cleanly without local state', () => {
  const pending = rawRecord({ state: 'recovery', should_complete: true, failure: { code: 'COMPLETE_FAILED', retryable: false } });
  const merged = outcome(mergeRecovery(pending, failure(child(), { code: 'REMOTE_TIMEOUT', retryable: true, message: '远端详情' })), 'recovery', 'keep');
  assert.equal(merged.shouldComplete, true);
  assert.deepEqual(merged.error, { code: 'COMPLETE_FAILED', retryable: false });

  const ordinary = outcome(mergeRecovery(rawRecord(), failure(child(), { code: 'REMOTE_TIMEOUT', retryable: true, message: '远端详情' })), 'recovery', 'keep');
  assert.deepEqual(ordinary.error, { code: 'REMOTE_TIMEOUT', retryable: true, message: '远端详情' });
  assert.equal(ordinary.child.id, 7);

  const empty = outcome(mergeRecovery(null, failure(null, { code: 'REMOTE_TIMEOUT', retryable: true, message: '远端详情' })), 'recovery', 'clear');
  assert.equal(empty.child, null);
  assert.deepEqual(empty.error, { code: 'REMOTE_TIMEOUT', retryable: true, message: '远端详情' });
});

test('merge treats malformed local data as missing but rejects malformed strict remote unions', () => {
  const local = { ...rawRecord(), unexpected: true };
  const missing = outcome(mergeRecovery(local, success(null, null)), 'loading_roster', 'clear');
  assert.equal(missing.child, null);

  const symbolic = success();
  symbolic[Symbol('unexpected')] = true;
  const invalidRemote = [
    null,
    {},
    symbolic,
    { kind: 'success', queriedChild: child(), active: { conversation: null }, extra: true },
    { kind: 'success', queriedChild: { ...child(), extra: true }, active: { conversation: null } },
    { kind: 'success', queriedChild: null, active: { conversation: active() } },
    { kind: 'success', queriedChild: child(), active: { conversation: active({ child_id: 8 }) } },
    { kind: 'success', queriedChild: child(), active: { conversation: active({ messages: [{ ...message(), extra: true }] }) } },
    { kind: 'failure', queriedChild: child(), error: { code: '', retryable: true } },
    { kind: 'failure', queriedChild: child(), error: { code: 'X', retryable: true, message: '', cause: 'nope' } },
    { kind: 'success', queriedChild: child(), active: { conversation: active({ messages: [message(12), message(11, 'child')] }) } },
  ];
  for (const remote of invalidRemote) assert.throws(() => mergeRecovery(null, remote), TypeError);
});
