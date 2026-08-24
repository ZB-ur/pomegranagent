import test from 'node:test';
import assert from 'node:assert/strict';

import * as childAPI from '../../../app/frontend/child/api.mjs';

const REQUEST_ID = '9b2d8d08-0eaa-4d5c-8f5b-f5d31c2bb25c';

class FakeAPIError extends Error {}

function health(overrides = {}) {
  return {
    release_id: 'release-1',
    api_version: '1.0.0',
    schema_version: '2026.08',
    db_mode: 'app',
    analysis_worker_status: 'running',
    ...overrides,
  };
}

function child(id = 7, overrides = {}) {
  return { id, name: '小雨', nickname: null, avatar: null, ...overrides };
}

function message(id, role = 'child', overrides = {}) {
  return { id, role, text: role === 'child' ? '我喂了小鸭' : '真棒！', ...overrides };
}

function active(overrides = {}) {
  return {
    conversation: {
      id: 4,
      child_id: 7,
      status: 'active',
      revision: 0,
      round: 1,
      last_message_id: 11,
      messages: [message(10), message(11, 'diary')],
    },
    ...overrides,
  };
}

function chatResult(overrides = {}) {
  return {
    request_id: REQUEST_ID,
    conversation_id: 4,
    child_message_id: 10,
    diary_message_id: 11,
    reply: '真棒！',
    round: 1,
    ended: false,
    end_reason: null,
    replayed: false,
    ...overrides,
  };
}

function completeResult(overrides = {}) {
  return {
    conversation_id: 4,
    conversation_saved: true,
    status: 'completed',
    completed_at: '2026-08-23T00:01:00Z',
    message_count: 2,
    last_message_id: 11,
    analysis_job_id: 3,
    analysis_status: 'pending',
    replayed: false,
    ...overrides,
  };
}

function chatInput(overrides = {}) {
  return {
    request_id: REQUEST_ID,
    child_id: 7,
    text: '我喂了小鸭',
    conversation_id: 4,
    max_rounds: 3,
    ...overrides,
  };
}

function dependencies({ request, ready, bootstrapVersionGate, auth = {} } = {}) {
  const requestCalls = [];
  const authCalls = [];
  const duckAPI = {
    APIError: FakeAPIError,
    ready: ready ?? (async () => health()),
    request: (path, options) => {
      requestCalls.push({ path, options });
      return request?.(path, options);
    },
    bootstrapVersionGate: bootstrapVersionGate ?? (async () => health()),
  };
  const duckAuth = {
    status: (...args) => {
      authCalls.push({ method: 'status', args });
      return auth.status?.(...args) ?? Promise.resolve({ configured: false, authenticated: false });
    },
    setup: (...args) => {
      authCalls.push({ method: 'setup', args });
      return auth.setup?.(...args) ?? Promise.resolve({ configured: true, authenticated: true });
    },
    unlock: (...args) => {
      authCalls.push({ method: 'unlock', args });
      return auth.unlock?.(...args) ?? Promise.resolve({ configured: true, authenticated: true });
    },
    lock: (...args) => {
      authCalls.push({ method: 'lock', args });
      return auth.lock?.(...args) ?? Promise.resolve({ configured: true, authenticated: false });
    },
  };
  return { duckAPI, duckAuth, requestCalls, authCalls };
}

async function assertInvalidResponse(invoke) {
  await assert.rejects(invoke, error => {
    assert.ok(error instanceof FakeAPIError);
    assert.equal(error.name, 'APIError');
    assert.equal(error.status, 0);
    assert.equal(error.code, 'INVALID_RESPONSE');
    assert.equal(typeof error.message, 'string');
    assert.notEqual(error.message.length, 0);
    assert.deepEqual(error.fieldErrors, {});
    assert.equal(error.retryable, true);
    assert.equal(error.requestId, null);
    assert.equal(error.cause, null);
    return true;
  });
}

test('exports only the injected child adapter factory and browser composition factory', () => {
  assert.deepEqual(Object.keys(childAPI).sort(), [
    'bootstrapBrowserChildAPI',
    'createChildAPI',
  ]);
});

test('returns one frozen adapter with the approved ten methods', () => {
  const { duckAPI, duckAuth } = dependencies();
  const api = childAPI.createChildAPI(duckAPI, duckAuth);

  assert.equal(Object.isFrozen(api), true);
  assert.deepEqual(Object.keys(api).sort(), [
    'chat', 'complete', 'getActiveConversation', 'getTodayRoster', 'ready',
    'teacherLock', 'teacherSetup', 'teacherStatus', 'teacherUnlock', 'tts',
  ]);
  for (const method of Object.values(api)) assert.equal(typeof method, 'function');
});

test('uses the frozen paths and options for every child HTTP method', async () => {
  const audio = new Blob(['audio']);
  const { duckAPI, duckAuth, requestCalls } = dependencies({
    request: async path => {
      if (path === '/api/roster/today') return [child()];
      if (path === '/api/children/7/active-conversation') return active();
      if (path === '/api/chat') return chatResult();
      if (path === '/api/conversations/4/complete') return completeResult();
      if (path.startsWith('/api/tts?text=')) return audio;
      throw new Error(`unexpected path ${path}`);
    },
  });
  const api = childAPI.createChildAPI(duckAPI, duckAuth);
  const signal = new AbortController().signal;
  const input = chatInput();

  assert.deepEqual(await api.ready(), health());
  await api.getTodayRoster();
  await api.getActiveConversation(7);
  await api.chat(input, signal);
  await api.complete(4, 11, signal);
  assert.equal(await api.tts('你好 &?', signal), audio);

  assert.deepEqual(requestCalls, [
    { path: '/api/roster/today', options: { responseType: 'json', sequenceKey: 'child-roster' } },
    { path: '/api/children/7/active-conversation', options: { responseType: 'json', sequenceKey: 'child-active-7' } },
    { path: '/api/chat', options: {
      method: 'POST', body: input, signal, requestId: REQUEST_ID,
      responseType: 'json', sequenceKey: 'child-chat',
    } },
    { path: '/api/conversations/4/complete', options: {
      method: 'POST', body: { expected_last_message_id: 11 }, signal,
      responseType: 'json', sequenceKey: 'child-complete-4',
    } },
    { path: `/api/tts?text=${encodeURIComponent('你好 &?')}`, options: {
      signal, responseType: 'blob', timeoutMs: 10000, sequenceKey: 'child-tts',
    } },
  ]);
});

test('validates the Foundation health response with string schema version and app database mode', async () => {
  for (const value of [
    health({ schema_version: 2 }),
    health({ db_mode: 'test' }),
    health({ analysis_worker_status: null }),
    { release_id: 'release-1', api_version: '1.0.0', schema_version: '2026.08', db_mode: 'app' },
  ]) {
    const { duckAPI, duckAuth } = dependencies({ ready: async () => value });
    await assertInvalidResponse(() => childAPI.createChildAPI(duckAPI, duckAuth).ready());
  }
});

test('validates every strict roster child field and rejects duplicate or unknown records', async () => {
  const invalid = [
    null,
    {},
    [child(0)],
    [child(7, { name: null })],
    [child(7, { name: '' })],
    [child(7, { nickname: 1 })],
    [child(7), child(7)],
    [child(7, { unknown: true })],
  ];
  for (const value of invalid) {
    const { duckAPI, duckAuth } = dependencies({ request: async () => value });
    await assertInvalidResponse(() => childAPI.createChildAPI(duckAPI, duckAuth).getTodayRoster());
  }
});

test('validates strict active DTO nesting, child scope, ordered message IDs, and last-message boundary', async () => {
  const nestedExtra = active();
  nestedExtra.conversation.messages[0].unexpected = true;
  const unordered = active();
  unordered.conversation.messages = [message(11), message(10, 'diary')];
  const cases = [
    null,
    {},
    { conversation: null, extra: true },
    active({ conversation: { ...active().conversation, child_id: 8 } }),
    active({ conversation: { ...active().conversation, revision: -1 } }),
    active({ conversation: { ...active().conversation, round: -1 } }),
    active({ conversation: { ...active().conversation, status: 'completed' } }),
    active({ conversation: { ...active().conversation, last_message_id: null } }),
    active({ conversation: { ...active().conversation, messages: [] } }),
    unordered,
    nestedExtra,
    active({ conversation: { ...active().conversation, messages: [message(10), message(10, 'diary')] } }),
    active({ conversation: { ...active().conversation, last_message_id: 12 } }),
  ];
  for (const value of cases) {
    const { duckAPI, duckAuth } = dependencies({ request: async () => value });
    await assertInvalidResponse(() => childAPI.createChildAPI(duckAPI, duckAuth).getActiveConversation(7));
  }
});

test('accepts the null active-conversation sentinel and active conversation revision zero', async () => {
  for (const value of [{ conversation: null }, active()]) {
    const { duckAPI, duckAuth } = dependencies({ request: async () => value });
    assert.equal(await childAPI.createChildAPI(duckAPI, duckAuth).getActiveConversation(7), value);
  }
});

test('validates strict chat result semantics, request identity, and established conversation scope', async () => {
  const cases = [
    null,
    { ...chatResult(), unknown: true },
    chatResult({ request_id: 'ac1b75b0-9211-470b-80d1-0c7ece98a170' }),
    chatResult({ conversation_id: 5 }),
    chatResult({ child_message_id: 11 }),
    chatResult({ round: 0 }),
    chatResult({ round: 4 }),
    chatResult({ reply: null }),
    chatResult({ ended: true, end_reason: null }),
    chatResult({ ended: false, end_reason: 'complete' }),
    chatResult({ ended: true, end_reason: 'other' }),
    chatResult({ round: 1, ended: true, end_reason: 'max_rounds' }),
    chatResult({ round: 3, ended: false, end_reason: null }),
    chatResult({ round: 3, ended: true, end_reason: 'complete' }),
    chatResult({ replayed: 'false' }),
  ];
  for (const value of cases) {
    const { duckAPI, duckAuth } = dependencies({ request: async () => value });
    await assertInvalidResponse(() => childAPI.createChildAPI(duckAPI, duckAuth).chat(chatInput(), new AbortController().signal));
  }
});

test('accepts each frozen chat end reason only with ended true', async () => {
  for (const [end_reason, round] of [['complete', 1], ['max_rounds', 3]]) {
    const value = chatResult({ ended: true, end_reason, round });
    const { duckAPI, duckAuth } = dependencies({ request: async () => value });
    assert.equal(await childAPI.createChildAPI(duckAPI, duckAuth).chat(chatInput(), new AbortController().signal), value);
  }
});

test('validates strict completion fields, submitted boundaries, timestamp, and analysis union', async () => {
  const cases = [
    null,
    { ...completeResult(), unknown: true },
    completeResult({ conversation_id: 5 }),
    completeResult({ conversation_saved: false }),
    completeResult({ status: 'active' }),
    completeResult({ completed_at: 'not-a-timestamp' }),
    completeResult({ completed_at: '2026-02-30T00:00:00Z' }),
    completeResult({ message_count: 0 }),
    completeResult({ last_message_id: 12 }),
    completeResult({ analysis_job_id: 0 }),
    completeResult({ analysis_status: 'unknown' }),
    completeResult({ replayed: 0 }),
  ];
  for (const value of cases) {
    const { duckAPI, duckAuth } = dependencies({ request: async () => value });
    await assertInvalidResponse(() => childAPI.createChildAPI(duckAPI, duckAuth).complete(4, 11, new AbortController().signal));
  }

  for (const analysis_status of ['pending', 'processing', 'succeeded', 'failed']) {
    const value = completeResult({ analysis_status });
    const { duckAPI, duckAuth } = dependencies({ request: async () => value });
    assert.equal(await childAPI.createChildAPI(duckAPI, duckAuth).complete(4, 11, new AbortController().signal), value);
  }
});

test('accepts a real UTC RFC3339 leap-day timestamp without normalizing invalid calendar dates', async () => {
  for (const completed_at of ['2024-02-29T23:59:59Z', '2024-02-29T23:59:59.123456789Z']) {
    const valid = completeResult({ completed_at });
    const validDeps = dependencies({ request: async () => valid });
    assert.equal(
      await childAPI.createChildAPI(validDeps.duckAPI, validDeps.duckAuth).complete(4, 11, new AbortController().signal),
      valid,
    );
  }

  for (const completed_at of [
    '0000-01-01T00:00:00Z',
    '2026-02-30T00:00:00Z',
    '2026-13-01T00:00:00Z',
    '2026-08-23T24:00:00Z',
    '2026-08-23T00:00:00+00:00',
  ]) {
    const deps = dependencies({ request: async () => completeResult({ completed_at }) });
    await assertInvalidResponse(
      () => childAPI.createChildAPI(deps.duckAPI, deps.duckAuth).complete(4, 11, new AbortController().signal),
    );
  }
});

test('passes only string PINs to injected auth and enforces each authenticated state', async () => {
  const { duckAPI, duckAuth, authCalls } = dependencies({
    auth: {
      status: async () => ({ configured: false, authenticated: false }),
      setup: async pin => ({ configured: true, authenticated: true, pin }),
      unlock: async pin => ({ configured: true, authenticated: true, pin }),
      lock: async () => ({ configured: true, authenticated: false }),
    },
  });
  const api = childAPI.createChildAPI(duckAPI, duckAuth);

  assert.deepEqual(await api.teacherStatus(), { configured: false, authenticated: false });
  assert.deepEqual(await api.teacherSetup('1234'), { configured: true, authenticated: true, pin: '1234' });
  assert.deepEqual(await api.teacherUnlock('567890'), { configured: true, authenticated: true, pin: '567890' });
  assert.deepEqual(await api.teacherLock(), { configured: true, authenticated: false });
  assert.deepEqual(authCalls, [
    { method: 'status', args: [] },
    { method: 'setup', args: ['1234'] },
    { method: 'unlock', args: ['567890'] },
    { method: 'lock', args: [] },
  ]);

  for (const auth of [
    { status: async () => ({ configured: true, authenticated: 'yes' }) },
    { status: async () => ({ configured: false, authenticated: true }) },
    { setup: async () => ({ configured: true, authenticated: false }) },
    { unlock: async () => ({ configured: false, authenticated: true }) },
    { lock: async () => ({ configured: true, authenticated: true }) },
  ]) {
    const deps = dependencies({ auth });
    const invalidAPI = childAPI.createChildAPI(deps.duckAPI, deps.duckAuth);
    if (auth.status) await assertInvalidResponse(() => invalidAPI.teacherStatus());
    if (auth.setup) await assertInvalidResponse(() => invalidAPI.teacherSetup('1234'));
    if (auth.unlock) await assertInvalidResponse(() => invalidAPI.teacherUnlock('1234'));
    if (auth.lock) await assertInvalidResponse(() => invalidAPI.teacherLock());
  }
});

test('rejects clearly invalid local IDs, chat shapes, text, PINs, and TTS text before transport', () => {
  const { duckAPI, duckAuth, requestCalls, authCalls } = dependencies({
    request: async () => { throw new Error('transport must not run'); },
  });
  const api = childAPI.createChildAPI(duckAPI, duckAuth);
  const signal = new AbortController().signal;
  const invalidInputs = [
    () => api.getActiveConversation(0),
    () => api.complete(0, 11, signal),
    () => api.complete(4, 0, signal),
    () => api.chat(null, signal),
    () => api.chat(chatInput({ request_id: 'not-a-uuid' }), signal),
    () => api.chat(chatInput({ request_id: '9b2d8d08-0eaa-0d5c-8f5b-f5d31c2bb25c' }), signal),
    () => api.chat(chatInput({ request_id: '9b2d8d08-0eaa-4d5c-7f5b-f5d31c2bb25c' }), signal),
    () => api.chat(chatInput({ child_id: 0 }), signal),
    () => api.chat(chatInput({ text: '   ' }), signal),
    () => api.chat(chatInput({ text: 'a'.repeat(2001) }), signal),
    () => api.chat(chatInput({ conversation_id: 0 }), signal),
    () => api.chat(chatInput({ max_rounds: 0 }), signal),
    () => api.chat(chatInput({ max_rounds: 1 }), signal),
    () => api.chat(chatInput({ max_rounds: 4 }), signal),
    () => api.chat({ ...chatInput(), unexpected: true }, signal),
    () => api.teacherSetup(1234),
    () => api.teacherUnlock('short'),
    () => api.tts('   ', signal),
    () => api.tts(3, signal),
  ];
  for (const invoke of invalidInputs) assert.throws(invoke, TypeError);
  assert.deepEqual(requestCalls, []);
  assert.deepEqual(authCalls, []);
});

test('preserves synchronous and asynchronous upstream error object identity', async () => {
  const synchronous = { source: 'sync' };
  const syncDeps = dependencies({ request: () => { throw synchronous; } });
  assert.throws(
    () => childAPI.createChildAPI(syncDeps.duckAPI, syncDeps.duckAuth).getTodayRoster(),
    error => error === synchronous,
  );

  const asynchronous = { source: 'async' };
  const asyncDeps = dependencies({ auth: { status: async () => { throw asynchronous; } } });
  await assert.rejects(
    () => childAPI.createChildAPI(asyncDeps.duckAPI, asyncDeps.duckAuth).teacherStatus(),
    error => error === asynchronous,
  );
});

test('browser bootstrap rejects missing globals before any gate, auth, or business call', async () => {
  for (const globalObject of [{}, { DuckAPI: {} }, { DuckAPI: dependencies().duckAPI }]) {
    await assert.rejects(() => childAPI.bootstrapBrowserChildAPI(globalObject), TypeError);
  }
});

test('browser bootstrap invokes the version gate once, then supplies injected globals without effects', async () => {
  let gates = 0;
  const { duckAPI, duckAuth, requestCalls, authCalls } = dependencies({
    bootstrapVersionGate: async () => {
      gates += 1;
      return health();
    },
  });
  const api = await childAPI.bootstrapBrowserChildAPI({ DuckAPI: duckAPI, DuckAuth: duckAuth });

  assert.equal(gates, 1);
  assert.deepEqual(requestCalls, []);
  assert.deepEqual(authCalls, []);
  assert.deepEqual(Object.keys(api).sort(), [
    'chat', 'complete', 'getActiveConversation', 'getTodayRoster', 'ready',
    'teacherLock', 'teacherSetup', 'teacherStatus', 'teacherUnlock', 'tts',
  ]);
});

test('browser bootstrap propagates the original gate rejection without business or auth effects', async () => {
  const original = { source: 'version gate' };
  let gates = 0;
  const { duckAPI, duckAuth, requestCalls, authCalls } = dependencies({
    bootstrapVersionGate: async () => {
      gates += 1;
      throw original;
    },
  });

  await assert.rejects(
    () => childAPI.bootstrapBrowserChildAPI({ DuckAPI: duckAPI, DuckAuth: duckAuth }),
    error => error === original,
  );
  assert.equal(gates, 1);
  assert.deepEqual(requestCalls, []);
  assert.deepEqual(authCalls, []);
});
