import test from 'node:test';
import assert from 'node:assert/strict';

import * as machine from '../../../app/frontend/child/machine.mjs';

const {
  STATES,
  assertSnapshot,
  controlsFor,
  createInitialSnapshot,
  transition,
} = machine;

const createdAt = '2026-08-23T00:00:00Z';

function child(id = 7, name = '小雨') {
  return { id, name, nickname: null, avatar: null };
}

function draft(overrides = {}) {
  return {
    text: '我喂了小鸭',
    request_id: 'req-1',
    created_at: createdAt,
    ...overrides,
  };
}

function chatResult(overrides = {}) {
  return {
    request_id: 'req-1',
    conversation_id: 9,
    child_message_id: 41,
    diary_message_id: 42,
    reply: '真棒！',
    round: 1,
    ended: true,
    end_reason: 'complete',
    replayed: false,
    ...overrides,
  };
}

function completeResult(overrides = {}) {
  return {
    conversation_id: 9,
    conversation_saved: true,
    status: 'completed',
    completed_at: '2026-08-23T00:01:00Z',
    message_count: 2,
    last_message_id: 42,
    analysis_job_id: 3,
    analysis_status: 'pending',
    replayed: false,
    ...overrides,
  };
}

function error(overrides = {}) {
  return { code: 'NETWORK_ERROR', retryable: true, ...overrides };
}

function submittingSnapshot(overrides = {}) {
  return createInitialSnapshot({ value: 'submitting', child: child(), draft: draft(), ...overrides });
}

function savingSnapshot(overrides = {}) {
  return createInitialSnapshot({
    value: 'saving_conversation',
    child: child(),
    conversationId: 9,
    lastMessageId: 42,
    messages: [
      { id: 41, role: 'child', text: '我喂了小鸭' },
      { id: 42, role: 'diary', text: '真棒！' },
    ],
    ...overrides,
  });
}

function completedSnapshot(overrides = {}) {
  return createInitialSnapshot({
    value: 'completed',
    child: child(),
    conversationId: 9,
    lastMessageId: 42,
    messages: [
      { id: 41, role: 'child', text: '我喂了小鸭' },
      { id: 42, role: 'diary', text: '真棒！' },
    ],
    ...overrides,
  });
}

test('exports exactly the approved child states and immutable initial snapshots', () => {
  assert.deepEqual(Object.keys(machine).sort(), [
    'STATES', 'assertSnapshot', 'controlsFor', 'createInitialSnapshot', 'transition',
  ]);
  assert.deepEqual(STATES, [
    'welcome', 'loading_roster', 'selecting_child', 'opening', 'ready',
    'listening', 'submitting', 'speaking', 'submission_failed',
    'saving_conversation', 'completed', 'recovery',
  ]);

  const first = createInitialSnapshot();
  const second = createInitialSnapshot();
  assert.equal(first.value, 'welcome');
  assert.equal(Object.isFrozen(first), true);
  assert.equal(Object.isFrozen(first.roster), true);
  assert.equal(Object.isFrozen(first.messages), true);
  assert.notEqual(first.roster, second.roster);
  assert.notEqual(first.messages, second.messages);
  assert.equal(assertSnapshot(first), first);
});

test('snapshot revision accepts the active-conversation initial revision zero', () => {
  assert.equal(createInitialSnapshot({ revision: 0 }).revision, 0);
});

test('one event path reaches saved completion through every required state', () => {
  let s = createInitialSnapshot();
  const visited = [s.value];
  const step = event => {
    s = transition(s, event);
    visited.push(s.value);
  };

  step({ type: 'START' });
  step({ type: 'ROSTER_LOADED', children: [child()] });
  step({ type: 'CHILD_SELECTED', childId: 7 });
  step({ type: 'TTS_SETTLED' });
  step({ type: 'RECORD_TOGGLE' });
  step({ type: 'SPEECH_FINAL', draft: draft() });
  step({ type: 'SUBMIT_SUCCEEDED', result: chatResult() });
  assert.equal(s.lastMessageId, 42);
  step({ type: 'TTS_SETTLED' });
  step({ type: 'COMPLETE_SUCCEEDED', result: completeResult() });

  assert.deepEqual(visited, [
    'welcome', 'loading_roster', 'selecting_child', 'opening', 'ready',
    'listening', 'submitting', 'speaking', 'saving_conversation', 'completed',
  ]);
  assert.equal(s.draft, null);
  assert.equal(s.reply, null);
  assert.equal(s.shouldComplete, true);
  assert.equal(assertSnapshot(s), s);
});

test('every explicitly legal transition accepts its documented source', () => {
  const recoverySnapshot = createInitialSnapshot({ value: 'ready', child: child() });
  const cases = [
    [createInitialSnapshot(), { type: 'START' }, 'loading_roster'],
    [createInitialSnapshot({ value: 'loading_roster' }), { type: 'ROSTER_LOADED', children: [child()] }, 'selecting_child'],
    [createInitialSnapshot({ value: 'loading_roster' }), { type: 'ROSTER_FAILED', error: error() }, 'recovery'],
    [createInitialSnapshot({ value: 'loading_roster' }), { type: 'BEGIN_RECOVERY', error: error() }, 'recovery'],
    [createInitialSnapshot({ value: 'selecting_child', roster: [child()] }), { type: 'BEGIN_RECOVERY', error: error() }, 'recovery'],
    [createInitialSnapshot({ value: 'selecting_child', roster: [child()] }), { type: 'CHILD_SELECTED', childId: 7 }, 'opening'],
    [createInitialSnapshot({ value: 'opening', child: child() }), { type: 'BEGIN_RECOVERY', error: error() }, 'recovery'],
    [createInitialSnapshot({ value: 'opening' }), { type: 'TTS_SETTLED' }, 'ready'],
    [createInitialSnapshot({ value: 'ready', child: child() }), { type: 'BEGIN_RECOVERY', error: error() }, 'recovery'],
    [createInitialSnapshot({ value: 'ready' }), { type: 'RECORD_TOGGLE' }, 'listening'],
    [createInitialSnapshot({ value: 'listening', child: child() }), { type: 'BEGIN_RECOVERY', error: error() }, 'recovery'],
    [createInitialSnapshot({ value: 'listening' }), { type: 'RECORD_TOGGLE' }, 'listening'],
    [createInitialSnapshot({ value: 'listening' }), { type: 'SPEECH_EMPTY' }, 'ready'],
    [createInitialSnapshot({ value: 'listening' }), { type: 'SPEECH_FINAL', draft: draft() }, 'submitting'],
    [submittingSnapshot(), { type: 'BEGIN_RECOVERY', error: error() }, 'recovery'],
    [submittingSnapshot(), { type: 'SUBMIT_SUCCEEDED', result: chatResult({ ended: false, end_reason: null }) }, 'speaking'],
    [submittingSnapshot(), { type: 'SUBMIT_FAILED', error: error() }, 'submission_failed'],
    [createInitialSnapshot({ value: 'submission_failed', child: child(), draft: draft(), error: error() }), { type: 'BEGIN_RECOVERY', error: error() }, 'recovery'],
    [createInitialSnapshot({ value: 'submission_failed', child: child(), draft: draft(), error: error() }), { type: 'RETRY_SUBMIT' }, 'submitting'],
    [createInitialSnapshot({ value: 'speaking', child: child() }), { type: 'BEGIN_RECOVERY', error: error() }, 'recovery'],
    [createInitialSnapshot({ value: 'speaking', shouldComplete: false }), { type: 'TTS_SETTLED' }, 'ready'],
    [createInitialSnapshot({
      value: 'speaking', shouldComplete: true, conversationId: 9, lastMessageId: 42,
      messages: [{ id: 42, role: 'diary', text: '真棒！' }],
    }), { type: 'TTS_SETTLED' }, 'saving_conversation'],
    [savingSnapshot(), { type: 'COMPLETE_SUCCEEDED', result: completeResult() }, 'completed'],
    [savingSnapshot(), { type: 'COMPLETE_FAILED', error: error() }, 'recovery'],
    [savingSnapshot(), { type: 'BEGIN_RECOVERY', error: error() }, 'recovery'],
    [completedSnapshot(), { type: 'BEGIN_RECOVERY', error: error() }, 'recovery'],
    [createInitialSnapshot({ value: 'recovery', child: child(), error: error() }), { type: 'BEGIN_RECOVERY', error: error({ code: 'SPEECH_FAILED' }) }, 'recovery'],
    [createInitialSnapshot({ value: 'recovery' }), { type: 'RECOVERY_RESOLVED', snapshot: recoverySnapshot }, 'ready'],
    [createInitialSnapshot({ value: 'recovery' }), { type: 'TEACHER_UNLOCKED' }, 'recovery'],
    [createInitialSnapshot({ value: 'recovery' }), { type: 'RESET' }, 'welcome'],
    [completedSnapshot(), { type: 'RESET' }, 'welcome'],
  ];

  for (const [snapshot, event, expected] of cases) {
    const next = transition(snapshot, event);
    assert.equal(next.value, expected, `${snapshot.value}:${event.type}`);
    assert.equal(assertSnapshot(next), next, `${snapshot.value}:${event.type}`);
    assert.equal(Object.isFrozen(next), true, `${snapshot.value}:${event.type}`);
  }
});

test('BEGIN_RECOVERY rejects every source outside the post-START recovery matrix', () => {
  const legalSources = new Set([
    'loading_roster', 'selecting_child', 'opening', 'ready', 'listening', 'submitting',
    'speaking', 'submission_failed', 'saving_conversation', 'completed', 'recovery',
  ]);

  for (const state of STATES) {
    if (legalSources.has(state)) continue;
    const snapshot = createInitialSnapshot({ value: state });
    assert.throws(() => transition(snapshot, { type: 'BEGIN_RECOVERY', error: error() }),
      new RegExp(`Illegal transition ${state}:BEGIN_RECOVERY`));
  }
});

test('rejects representative illegal state and event pairs', () => {
  for (const [snapshot, event] of [
    [createInitialSnapshot(), { type: 'ROSTER_LOADED', children: [] }],
    [createInitialSnapshot({ value: 'ready' }), { type: 'SPEECH_FINAL', draft: draft() }],
    [createInitialSnapshot({ value: 'submission_failed', child: child(), draft: draft(), error: error({ retryable: false }) }), { type: 'RETRY_SUBMIT' }],
    [completedSnapshot({ teacherUnlocked: true }), { type: 'TEACHER_RECOVERY_RETRY' }],
    [createInitialSnapshot(), { type: 'BEGIN_RECOVERY' }],
  ]) {
    assert.throws(() => transition(snapshot, event), /Illegal transition/);
  }
});

test('loading the roster validates children and keeps each first occurrence in order', () => {
  const first = child(7, '小雨');
  const second = child(8, '小满');
  const duplicate = child(7, '新名字不应覆盖');
  const next = transition(createInitialSnapshot({ value: 'loading_roster' }), {
    type: 'ROSTER_LOADED', children: [first, second, duplicate],
  });

  assert.deepEqual(next.roster, [first, second]);
  assert.throws(() => transition(createInitialSnapshot({ value: 'loading_roster' }), {
    type: 'ROSTER_LOADED', children: [{ id: 0, name: '', nickname: null, avatar: null }],
  }), /child/);
});

test('retryable failure retains the normalized draft and retries its exact request identity', () => {
  const originalDraft = draft({ text: '  我换了水  ', request_id: 'same-id' });
  let s = transition(createInitialSnapshot({ value: 'listening', child: child() }), {
    type: 'SPEECH_FINAL', draft: originalDraft,
  });
  s = transition(s, { type: 'SUBMIT_FAILED', error: error() });
  const retained = s.draft;
  s = transition(s, { type: 'RETRY_SUBMIT' });

  assert.equal(s.value, 'submitting');
  assert.deepEqual(s.draft, { text: '我换了水', request_id: 'same-id', created_at: createdAt });
  assert.equal(s.draft.request_id, retained.request_id);
  assert.equal(s.draft.created_at, retained.created_at);
});

test('nonretryable submission failure enters recovery without losing recovery context', () => {
  const before = submittingSnapshot({
    conversationId: 9,
    lastMessageId: 42,
    messages: [{ id: 42, role: 'diary', text: '上一句' }],
  });
  const next = transition(before, { type: 'SUBMIT_FAILED', error: error({ retryable: false }) });

  assert.equal(next.value, 'recovery');
  assert.equal(next.child.id, 7);
  assert.equal(next.conversationId, 9);
  assert.equal(next.lastMessageId, 42);
  assert.deepEqual(next.messages, [{ id: 42, role: 'diary', text: '上一句' }]);
  assert.deepEqual(next.draft, draft());
});

test('successful submission requires a matching draft request and distinct positive acknowledgement ids', () => {
  const snapshot = submittingSnapshot();
  assert.throws(() => transition(snapshot, {
    type: 'SUBMIT_SUCCEEDED', result: chatResult({ request_id: 'other-request' }),
  }), /request_id/);
  assert.throws(() => transition(snapshot, {
    type: 'SUBMIT_SUCCEEDED', result: chatResult({ child_message_id: 42 }),
  }), /distinct/);
  assert.throws(() => transition(snapshot, {
    type: 'SUBMIT_SUCCEEDED', result: chatResult({ diary_message_id: 0 }),
  }), /positive/);
});

test('successful submission cannot switch an established conversation', () => {
  assert.throws(() => transition(submittingSnapshot({ conversationId: 8 }), {
    type: 'SUBMIT_SUCCEEDED', result: chatResult({ conversation_id: 9 }),
  }), /conversation/);
});

test('successful submission rejects an unfinished result with an end reason', () => {
  assert.throws(() => transition(submittingSnapshot(), {
    type: 'SUBMIT_SUCCEEDED', result: chatResult({ ended: false, end_reason: 'complete' }),
  }), /ended=false/);
});

test('successful submission rejects a finished result without an end reason', () => {
  assert.throws(() => transition(submittingSnapshot(), {
    type: 'SUBMIT_SUCCEEDED', result: chatResult({ ended: true, end_reason: null }),
  }), /ended=true/);
});

test('acknowledgements dedupe sequentially in child then diary order', () => {
  const snapshot = submittingSnapshot({
    messages: [
      { id: 5, role: 'diary', text: '旧消息' },
      { id: 41, role: 'child', text: '我喂了小鸭' },
    ],
  });
  const next = transition(snapshot, { type: 'SUBMIT_SUCCEEDED', result: chatResult() });

  assert.deepEqual(next.messages, [
    { id: 5, role: 'diary', text: '旧消息' },
    { id: 41, role: 'child', text: '我喂了小鸭' },
    { id: 42, role: 'diary', text: '真棒！' },
  ]);
});

test('acknowledgement replay dedupe rejects an existing child or diary ID with different content', () => {
  for (const message of [
    { id: 41, role: 'diary', text: '我喂了小鸭' },
    { id: 42, role: 'diary', text: '不同的日记回复' },
  ]) {
    assert.throws(() => transition(submittingSnapshot({ messages: [message] }), {
      type: 'SUBMIT_SUCCEEDED', result: chatResult(),
    }), /acknowledged message ID conflicts/);
  }
});

test('acknowledgement replay rejects every conflicting duplicate already in message history', () => {
  const snapshot = submittingSnapshot({
    messages: [
      { id: 41, role: 'child', text: '较早的冲突文本' },
      { id: 41, role: 'child', text: '我喂了小鸭' },
    ],
  });
  assert.throws(() => transition(snapshot, {
    type: 'SUBMIT_SUCCEEDED', result: chatResult(),
  }), /acknowledged message ID conflicts/);
});

test('completion enters completed only after saved conversation and all local boundaries match', () => {
  const snapshot = savingSnapshot();
  for (const result of [
    completeResult({ conversation_saved: false }),
    completeResult({ conversation_id: 10 }),
    completeResult({ last_message_id: 41 }),
    completeResult({ message_count: 1 }),
  ]) {
    assert.throws(() => transition(snapshot, { type: 'COMPLETE_SUCCEEDED', result }), /completion/);
  }
  assert.equal(transition(snapshot, { type: 'COMPLETE_SUCCEEDED', result: completeResult() }).value, 'completed');
});

test('saving conversation rejects an empty message history', () => {
  assert.throws(() => createInitialSnapshot({
    value: 'saving_conversation', conversationId: 9, lastMessageId: 42, messages: [],
  }), /at least one message/);
});

test('saving conversation requires lastMessageId to match its final message', () => {
  assert.throws(() => createInitialSnapshot({
    value: 'saving_conversation', conversationId: 9, lastMessageId: 42,
    messages: [{ id: 41, role: 'child', text: '我喂了小鸭' }],
  }), /lastMessageId/);
});

test('completed snapshot keeps the same persisted conversation boundary', () => {
  assert.throws(() => createInitialSnapshot({
    value: 'completed', conversationId: 9, lastMessageId: 42, messages: [],
  }), /at least one message/);
});

test('completion result rejects a nonpositive message_count before comparing the boundary', () => {
  assert.throws(() => transition(savingSnapshot(), {
    type: 'COMPLETE_SUCCEEDED', result: completeResult({ message_count: 0 }),
  }), /message_count.*positive/);
});

test('stopRequested is temporary and cannot leak into a fresh listening cycle', () => {
  let s = transition(createInitialSnapshot({ value: 'ready', stopRequested: true }), { type: 'RECORD_TOGGLE' });
  assert.equal(s.stopRequested, false);
  s = transition(s, { type: 'RECORD_TOGGLE' });
  assert.equal(s.stopRequested, true);
  s = transition(s, { type: 'SPEECH_EMPTY' });
  assert.equal(s.value, 'ready');
  assert.equal(s.stopRequested, false);
  s = transition(s, { type: 'RECORD_TOGGLE' });
  assert.equal(s.stopRequested, false);
});

test('recovery resolution validates then copies and freezes the supplied snapshot', () => {
  const supplied = {
    value: 'ready', roster: [child()], child: child(), conversationId: 9, revision: null,
    lastMessageId: 42, messages: [{ id: 42, role: 'diary', text: '真棒！' }], draft: draft(),
    reply: null, shouldComplete: false, stopRequested: false, error: error(), teacherUnlocked: false,
  };
  const next = transition(createInitialSnapshot({ value: 'recovery' }), {
    type: 'RECOVERY_RESOLVED', snapshot: supplied,
  });

  supplied.roster[0].name = '被篡改';
  supplied.messages.push({ id: 43, role: 'child', text: '注入' });
  supplied.draft.text = '被篡改';
  supplied.error.code = '被篡改';
  assert.notEqual(next, supplied);
  assert.equal(next.roster[0].name, '小雨');
  assert.equal(next.messages.length, 1);
  assert.equal(next.draft.text, '我喂了小鸭');
  assert.equal(next.error.code, 'NETWORK_ERROR');
  assert.equal(Object.isFrozen(next.roster[0]), true);
  assert.equal(Object.isFrozen(next.messages), true);
  assert.throws(() => transition(createInitialSnapshot({ value: 'recovery' }), {
    type: 'RECOVERY_RESOLVED', snapshot: { value: 'unknown' },
  }), /snapshot|Unknown child state/);
});

test('recovery resolution rejects a completed snapshot without persisted message boundaries', () => {
  const incompleteCompleted = {
    value: 'completed', roster: [], child: null, conversationId: 9, revision: null,
    lastMessageId: 42, messages: [], draft: null, reply: null, shouldComplete: false,
    stopRequested: false, error: null, teacherUnlocked: false,
  };
  assert.throws(() => transition(createInitialSnapshot({ value: 'recovery' }), {
    type: 'RECOVERY_RESOLVED', snapshot: incompleteCompleted,
  }), /at least one message/);
});

test('transition rejects an event type inherited from its prototype', () => {
  const inheritedStart = Object.create({ type: 'START' });
  assert.throws(() => transition(createInitialSnapshot(), inheritedStart), TypeError);
});

test('event-owned nested data cannot mutate a reducer-owned snapshot', () => {
  const incomingChild = child();
  let s = transition(createInitialSnapshot({ value: 'loading_roster' }), {
    type: 'ROSTER_LOADED', children: [incomingChild],
  });
  incomingChild.name = '被篡改';
  assert.equal(s.roster[0].name, '小雨');

  s = transition(s, { type: 'CHILD_SELECTED', childId: 7 });
  s = transition(s, { type: 'TTS_SETTLED' });
  s = transition(s, { type: 'RECORD_TOGGLE' });
  const incomingDraft = draft();
  s = transition(s, { type: 'SPEECH_FINAL', draft: incomingDraft });
  incomingDraft.text = '被篡改';
  assert.equal(s.draft.text, '我喂了小鸭');

  const incomingResult = chatResult();
  s = transition(s, { type: 'SUBMIT_SUCCEEDED', result: incomingResult });
  incomingResult.reply = '被篡改';
  assert.equal(s.reply, '真棒！');
  assert.equal(Object.isFrozen(s), true);
  assert.equal(Object.isFrozen(s.messages[0]), true);

  const incomingError = error({ message: '稍后再试' });
  const failed = transition(submittingSnapshot(), { type: 'SUBMIT_FAILED', error: incomingError });
  incomingError.code = '被篡改';
  assert.equal(failed.error.code, 'NETWORK_ERROR');
  assert.equal(Object.isFrozen(failed.error), true);
});

test('nested initial overrides are copied and frozen before callers can mutate them', () => {
  const roster = [child()];
  const selectedChild = child();
  const messages = [{ id: 41, role: 'child', text: '原消息' }];
  const pendingDraft = draft();
  const failure = error();
  const snapshot = createInitialSnapshot({
    value: 'submission_failed', roster, child: selectedChild, messages, draft: pendingDraft, error: failure,
  });

  roster[0].name = '被篡改';
  selectedChild.name = '被篡改';
  messages[0].text = '被篡改';
  pendingDraft.text = '被篡改';
  failure.code = '被篡改';
  assert.deepEqual(snapshot.roster, [child()]);
  assert.equal(snapshot.child.name, '小雨');
  assert.equal(snapshot.messages[0].text, '原消息');
  assert.equal(snapshot.draft.text, '我喂了小鸭');
  assert.equal(snapshot.error.code, 'NETWORK_ERROR');
});

test('controls derive the one child lock for every state without a mutable busy field', () => {
  const busyValues = new Set(['loading_roster', 'opening', 'submitting', 'speaking', 'saving_conversation', 'recovery']);
  for (const value of STATES) {
    const snapshot = createInitialSnapshot({
      value,
      teacherUnlocked: true,
      ...(value === 'submitting' ? { draft: draft(), child: child() } : {}),
      ...(value === 'saving_conversation' ? {
        conversationId: 9, lastMessageId: 42, messages: [{ id: 42, role: 'diary', text: '真棒！' }],
      } : {}),
      ...(value === 'completed' ? {
        conversationId: 9, lastMessageId: 42, messages: [{ id: 42, role: 'diary', text: '真棒！' }],
      } : {}),
      ...(value === 'submission_failed' ? { error: error(), draft: draft(), child: child() } : {}),
    });
    const controls = controlsFor(snapshot);
    assert.equal(controls.busy, busyValues.has(value), value);
    assert.equal(controls.recordDisabled, !['ready', 'listening'].includes(value), value);
    assert.equal(controls.recordAction, value === 'listening' ? 'stop' : 'start', value);
    assert.equal(controls.textDisabled, !['ready', 'submission_failed'].includes(value), value);
    assert.equal(controls.retryDisabled, value !== 'submission_failed', value);
    assert.equal(Object.hasOwn(controls, 'busyLocked'), false, value);
  }
  const lockedFailure = controlsFor(createInitialSnapshot({
    value: 'submission_failed', teacherUnlocked: false, error: error(), draft: draft(), child: child(),
  }));
  assert.equal(lockedFailure.textDisabled, true);
  assert.equal(lockedFailure.retryDisabled, false);
  const terminal = controlsFor(completedSnapshot({ teacherUnlocked: true }));
  assert.equal(terminal.recordDisabled, true);
  assert.equal(terminal.textDisabled, true);
  assert.equal(terminal.retryDisabled, true);
});

test('recovery unlock remains child-locked and reset creates a clean nested snapshot', () => {
  let recovery = transition(createInitialSnapshot({ value: 'recovery', child: child() }), { type: 'TEACHER_UNLOCKED' });
  assert.equal(recovery.teacherUnlocked, true);
  assert.equal(controlsFor(recovery).busy, true);
  assert.equal(controlsFor(recovery).textDisabled, true);

  const reset = transition(recovery, { type: 'RESET' });
  assert.equal(reset.value, 'welcome');
  assert.equal(reset.child, null);
  assert.equal(reset.messages.length, 0);
  assert.notEqual(reset.roster, recovery.roster);
  assert.notEqual(reset.messages, recovery.messages);
});

test('teacher authorization and recovery-only events retain the frozen child boundary', () => {
  const stateSnapshot = value => createInitialSnapshot({
    value,
    ...(value === 'submitting' ? { child: child(), draft: draft() } : {}),
    ...(value === 'submission_failed' ? { child: child(), draft: draft(), error: error() } : {}),
    ...(['saving_conversation', 'completed'].includes(value) ? {
      child: child(),
      conversationId: 9,
      lastMessageId: 42,
      messages: [{ id: 42, role: 'diary', text: '真棒！' }],
    } : {}),
  });

  for (const value of STATES) {
    const locked = stateSnapshot(value);
    const unlocked = transition(locked, { type: 'TEACHER_UNLOCKED' });
    assert.equal(unlocked.value, value);
    assert.equal(unlocked.teacherUnlocked, true);
    assert.deepEqual({ ...unlocked, teacherUnlocked: false }, locked);
    const relocked = transition(unlocked, { type: 'TEACHER_LOCKED' });
    assert.deepEqual(relocked, locked);
    assert.equal(Object.isFrozen(unlocked), true);
  }

  const recovery = createInitialSnapshot({
    value: 'recovery',
    child: child(),
    teacherUnlocked: true,
    error: error(),
  });
  const retried = transition(recovery, { type: 'TEACHER_RECOVERY_RETRY' });
  assert.deepEqual(retried, recovery);
  assert.notEqual(retried, recovery);

  const submitted = transition(recovery, { type: 'TEACHER_TEXT_SUBMITTED', draft: draft() });
  assert.equal(submitted.value, 'submitting');
  assert.deepEqual(submitted.draft, draft());
  assert.equal(submitted.error, null);

  const savedDraft = transition(recovery, { type: 'TEACHER_DRAFT_SAVED', draft: draft() });
  assert.equal(savedDraft.value, 'submission_failed');
  assert.deepEqual(savedDraft.draft, draft());
  assert.deepEqual(savedDraft.error, { code: 'TEACHER_DRAFT_SAVED', retryable: true });

  const listening = transition(recovery, { type: 'TEACHER_RETRY_MICROPHONE' });
  assert.equal(listening.value, 'listening');
  assert.equal(listening.stopRequested, false);
  assert.equal(listening.error, null);

  const boundedRecovery = createInitialSnapshot({
    value: 'recovery',
    child: child(),
    teacherUnlocked: true,
    conversationId: 9,
    lastMessageId: 42,
    messages: [{ id: 42, role: 'diary', text: '真棒！' }],
    error: error(),
  });
  const completing = transition(boundedRecovery, { type: 'TEACHER_COMPLETE_REQUESTED' });
  assert.equal(completing.value, 'saving_conversation');
  assert.equal(completing.shouldComplete, true);
  assert.equal(completing.error, null);

  const recoveryEvents = [
    { type: 'TEACHER_RECOVERY_RETRY' },
    { type: 'TEACHER_TEXT_SUBMITTED', draft: draft() },
    { type: 'TEACHER_DRAFT_SAVED', draft: draft() },
    { type: 'TEACHER_RETRY_MICROPHONE' },
    { type: 'TEACHER_COMPLETE_REQUESTED' },
  ];
  for (const event of recoveryEvents) {
    assert.throws(() => transition(createInitialSnapshot({ value: 'recovery', child: child() }), event), /Illegal transition/);
    assert.throws(() => transition(createInitialSnapshot({ value: 'ready', child: child(), teacherUnlocked: true }), event), /Illegal transition/);
  }
  for (const event of recoveryEvents.slice(1, 4)) {
    assert.throws(() => transition(createInitialSnapshot({
      value: 'recovery', child: child(), teacherUnlocked: true, draft: draft(), error: error(),
    }), event), /Illegal transition/);
    assert.throws(() => transition(createInitialSnapshot({
      value: 'recovery', child: child(), teacherUnlocked: true, shouldComplete: true, error: error(),
    }), event), /Illegal transition/);
  }
  assert.throws(() => transition(recovery, { type: 'TEACHER_COMPLETE_REQUESTED' }), /Illegal transition/);
});

test('teacher controls derive from unlocked safe recovery without another busy field', () => {
  const safe = createInitialSnapshot({
    value: 'recovery', child: child(), teacherUnlocked: true, error: error(),
  });
  const safeControls = controlsFor(safe);
  assert.equal(safeControls.teacherTextDisabled, false);
  assert.equal(safeControls.teacherDraftDisabled, false);
  assert.equal(safeControls.teacherRecoveryRetryDisabled, false);
  assert.equal(safeControls.teacherMicrophoneRetryDisabled, false);
  assert.equal(safeControls.teacherCompleteDisabled, true);
  assert.deepEqual({
    busy: safeControls.busy,
    recordAction: safeControls.recordAction,
    recordDisabled: safeControls.recordDisabled,
    textDisabled: safeControls.textDisabled,
    retryDisabled: safeControls.retryDisabled,
  }, {
    busy: true,
    recordAction: 'start',
    recordDisabled: true,
    textDisabled: true,
    retryDisabled: true,
  });

  const bounded = controlsFor(createInitialSnapshot({
    value: 'recovery',
    child: child(),
    teacherUnlocked: true,
    conversationId: 9,
    lastMessageId: 42,
    messages: [{ id: 42, role: 'diary', text: '真棒！' }],
    error: error(),
  }));
  assert.equal(bounded.teacherCompleteDisabled, false);

  for (const snapshot of [
    createInitialSnapshot({ value: 'recovery', child: child(), error: error() }),
    createInitialSnapshot({ value: 'ready', child: child(), teacherUnlocked: true }),
    createInitialSnapshot({ value: 'recovery', child: child(), teacherUnlocked: true, draft: draft(), error: error() }),
    createInitialSnapshot({ value: 'recovery', child: child(), teacherUnlocked: true, shouldComplete: true, error: error() }),
  ]) {
    const controls = controlsFor(snapshot);
    assert.equal(controls.teacherTextDisabled, true);
    assert.equal(controls.teacherDraftDisabled, true);
    assert.equal(controls.teacherMicrophoneRetryDisabled, true);
    assert.equal(controls.teacherRecoveryRetryDisabled, !(snapshot.value === 'recovery' && snapshot.teacherUnlocked));
  }
  assert.equal(Object.hasOwn(safe, 'busyLocked'), false);
  assert.equal(Object.isFrozen(safeControls), true);
});
