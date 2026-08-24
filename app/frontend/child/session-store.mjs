import { STATES, assertSnapshot, createInitialSnapshot } from './machine.mjs';

export const SESSION_KEY = 'duck-diary.child-session.v1';

const RECORD_FIELDS = [
  'version', 'child', 'conversation_id', 'revision', 'last_message_id', 'state',
  'messages', 'draft', 'should_complete', 'failure', 'updated_at',
];
const CHILD_FIELDS = ['id', 'name', 'nickname', 'avatar'];
const MESSAGE_FIELDS = ['id', 'role', 'text'];
const DRAFT_FIELDS = ['text', 'request_id', 'created_at'];
const FAILURE_FIELDS = ['code', 'retryable'];
const ACTIVE_FIELDS = [
  'id', 'child_id', 'status', 'revision', 'round', 'last_message_id', 'messages',
];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const STATE_SET = new Set(STATES);

export function createDraft(text, { uuid = () => crypto.randomUUID(), now = () => new Date().toISOString() } = {}) {
  if (typeof text !== 'string') throw new TypeError('draft text must be a string');
  if (typeof uuid !== 'function' || typeof now !== 'function') {
    throw new TypeError('draft dependencies must be functions');
  }
  const trimmed = text.trim();
  if (trimmed.length === 0) throw new TypeError('draft text must not be blank');

  const requestId = uuid();
  const createdAt = now();
  if (!isCanonicalUUID(requestId) || !isCanonicalTimestamp(createdAt)) {
    throw new TypeError('draft identity must be canonical');
  }
  return deepFreeze({ text: trimmed, request_id: requestId, created_at: createdAt });
}

export function createSessionStore(storage, { now = () => new Date().toISOString() } = {}) {
  if (!isRecord(storage)
    || typeof storage.getItem !== 'function'
    || typeof storage.setItem !== 'function'
    || typeof storage.removeItem !== 'function'
    || typeof now !== 'function') {
    throw new TypeError('storage and clock must satisfy the session-store contract');
  }

  return Object.freeze({
    load() {
      const serialized = storage.getItem(SESSION_KEY);
      try {
        return decodeRecord(JSON.parse(serialized));
      } catch {
        return null;
      }
    },
    save(snapshot) {
      assertSnapshot(snapshot);
      const record = encodeSnapshot(snapshot);
      const updatedAt = now();
      if (!isCanonicalTimestamp(updatedAt)) throw new TypeError('updated_at must be canonical UTC');
      const saved = decodeRecord({ ...record, updated_at: updatedAt });
      if (saved === null) throw new TypeError('snapshot cannot be stored');
      storage.setItem(SESSION_KEY, JSON.stringify(saved));
      return copyRecord(saved);
    },
    clear() {
      storage.removeItem(SESSION_KEY);
    },
  });
}

export function mergeRecovery(localRecord, remoteRead) {
  const local = decodeRecord(localRecord);
  const remote = normalizeRemoteRead(remoteRead);

  if (remote.kind === 'failure') {
    if (local === null) {
      return freezeOutcome(snapshotFrom({
        value: 'recovery',
        child: remote.queriedChild,
        error: remote.error,
      }), 'clear');
    }
    const error = local.state === 'recovery' && local.failure.retryable === false
      ? local.failure
      : remote.error;
    return freezeOutcome(recoveryFromLocal(local, error), 'keep');
  }

  const active = remote.active.conversation;
  if (local === null) {
    if (active === null) return freezeOutcome(snapshotFrom({ value: 'loading_roster' }), 'clear');
    return freezeOutcome(snapshotFromActive('ready', remote.queriedChild, active), 'clear');
  }

  if (local.child !== null && remote.queriedChild !== null && local.child.id !== remote.queriedChild.id) {
    return freezeOutcome(recoveryFromLocal(local, teacherFailure('RECOVERY_CHILD_MISMATCH')), 'keep');
  }

  const hasServerBinding = local.conversation_id !== null
    || local.revision !== null
    || local.last_message_id !== null
    || local.messages.length !== 0;

  if (active !== null
    && ((local.draft !== null && hasServerBinding) || local.should_complete === true)
    && (local.conversation_id === null || local.conversation_id !== active.id)) {
    return freezeOutcome(recoveryFromLocal(local, teacherFailure('RECOVERY_CONVERSATION_MISMATCH')), 'keep');
  }

  const pendingCompletion = local.draft === null
    && local.should_complete === true
    && (local.state === 'speaking' || local.state === 'saving_conversation' || local.state === 'recovery');
  if (pendingCompletion && active !== null) {
    if (active.messages.length === 0 || active.last_message_id === null) {
      return freezeOutcome(recoveryFromLocal(local, teacherFailure('RECOVERY_COMPLETION_BOUNDARY_MISSING')), 'keep');
    }
    return freezeOutcome(snapshotFromActive('saving_conversation', remote.queriedChild, active, {
      shouldComplete: true,
    }), 'keep');
  }

  if (local.state === 'recovery' && local.failure.retryable === false) {
    return freezeOutcome(recoveryFromLocal(local, local.failure), 'keep');
  }

  if (active !== null) {
    if (local.draft !== null) {
      return freezeOutcome(snapshotFromActive('submission_failed', remote.queriedChild, active, {
        draft: local.draft,
        error: { code: 'LOCAL_DRAFT_NOT_CONFIRMED', retryable: true },
      }), 'keep');
    }
    return freezeOutcome(snapshotFromActive('ready', remote.queriedChild, active), 'keep');
  }

  if (local.draft !== null) {
    if (hasServerBinding) {
      return freezeOutcome(recoveryFromLocal(local, teacherFailure('RECOVERY_CONVERSATION_MISSING')), 'keep');
    }
    return freezeOutcome(snapshotFromLocal(local, {
      value: 'submission_failed',
      error: { code: 'LOCAL_DRAFT_NOT_CONFIRMED', retryable: true },
    }), 'keep');
  }

  return freezeOutcome(snapshotFrom({ value: 'loading_roster' }), 'clear');
}

function encodeSnapshot(snapshot) {
  const record = {
    version: 1,
    child: snapshot.child === null ? null : copyChild(snapshot.child),
    conversation_id: nullablePositiveInteger(snapshot.conversationId),
    revision: nullableNonnegativeInteger(snapshot.revision),
    last_message_id: nullablePositiveInteger(snapshot.lastMessageId),
    state: snapshot.value,
    messages: copyMessages(snapshot.messages),
    draft: snapshot.draft === null ? null : copyDraft(snapshot.draft),
    should_complete: snapshot.shouldComplete,
    failure: snapshot.error === null ? null : copyFailure(snapshot.error),
  };
  if (!isValidRecordShape({ ...record, updated_at: UPDATED_AT_PLACEHOLDER })) {
    throw new TypeError('snapshot violates storage invariants');
  }
  return record;
}

const UPDATED_AT_PLACEHOLDER = '2000-01-01T00:00:00.000Z';

function decodeRecord(raw) {
  if (!isValidRecordShape(raw)) return null;
  try {
    const snapshot = snapshotFromLocal(raw);
    assertSnapshot(snapshot);
    return deepFreeze({
      version: 1,
      child: raw.child === null ? null : copyChild(raw.child),
      conversation_id: raw.conversation_id,
      revision: raw.revision,
      last_message_id: raw.last_message_id,
      state: raw.state,
      messages: copyMessages(raw.messages),
      draft: raw.draft === null ? null : copyDraft(raw.draft),
      should_complete: raw.should_complete,
      failure: raw.failure === null ? null : copyFailure(raw.failure),
      updated_at: raw.updated_at,
    });
  } catch {
    return null;
  }
}

function isValidRecordShape(value) {
  if (!hasExactOwnKeys(value, RECORD_FIELDS)
    || value.version !== 1
    || !STATE_SET.has(value.state)
    || !isNullableChild(value.child, true)
    || !isNullablePositiveInteger(value.conversation_id)
    || !isNullableNonnegativeInteger(value.revision)
    || !isNullablePositiveInteger(value.last_message_id)
    || !Array.isArray(value.messages)
    || !value.messages.every(item => isMessage(item, true))
    || !isNullableDraft(value.draft, true)
    || typeof value.should_complete !== 'boolean'
    || !isNullableFailure(value.failure, true)
    || !isCanonicalTimestamp(value.updated_at)) {
    return false;
  }
  if (value.draft !== null && value.child === null) return false;
  if (value.draft !== null && value.draft.text !== value.draft.text.trim()) return false;
  if (value.should_complete === true && value.draft !== null) return false;
  if (value.should_complete === true && !['speaking', 'saving_conversation', 'completed', 'recovery'].includes(value.state)) return false;
  if ((value.state === 'saving_conversation' || value.state === 'completed') && value.should_complete !== true) return false;
  if (value.state === 'recovery') return value.failure !== null;
  if (value.state === 'submission_failed') {
    return value.draft !== null && value.failure !== null && value.failure.retryable === true;
  }
  return value.failure === null;
}

function normalizeRemoteRead(value) {
  if (!isRecord(value)) throw new TypeError('remote read must be an object');
  if (value.kind === 'success') {
    if (!hasExactOwnKeys(value, ['kind', 'queriedChild', 'active'])
      || !isNullableChild(value.queriedChild, true)
      || !hasExactOwnKeys(value.active, ['conversation'])) {
      throw new TypeError('invalid successful remote read');
    }
    const conversation = value.active.conversation;
    if (conversation !== null && !isActiveConversation(conversation, true)) {
      throw new TypeError('invalid active conversation');
    }
    if (conversation !== null && (value.queriedChild === null || conversation.child_id !== value.queriedChild.id)) {
      throw new TypeError('active conversation child does not match queried child');
    }
    return {
      kind: 'success',
      queriedChild: value.queriedChild === null ? null : copyChild(value.queriedChild),
      active: { conversation: conversation === null ? null : copyActiveConversation(conversation) },
    };
  }
  if (value.kind === 'failure') {
    if (!hasExactOwnKeys(value, ['kind', 'queriedChild', 'error'])
      || !isNullableChild(value.queriedChild, true)
      || !isRemoteFailure(value.error)) {
      throw new TypeError('invalid failed remote read');
    }
    return {
      kind: 'failure',
      queriedChild: value.queriedChild === null ? null : copyChild(value.queriedChild),
      error: copyRemoteFailure(value.error),
    };
  }
  throw new TypeError('remote read kind must be success or failure');
}

function snapshotFromActive(value, queriedChild, active, overrides = {}) {
  return snapshotFrom({
    value,
    child: queriedChild,
    conversationId: active.id,
    revision: active.revision,
    lastMessageId: active.last_message_id,
    messages: active.messages,
    ...overrides,
  });
}

function snapshotFromLocal(local, overrides = {}) {
  return snapshotFrom({
    value: local.state,
    child: local.child,
    conversationId: local.conversation_id,
    revision: local.revision,
    lastMessageId: local.last_message_id,
    messages: local.messages,
    draft: local.draft,
    shouldComplete: local.should_complete,
    error: local.failure,
    ...overrides,
  });
}

function recoveryFromLocal(local, error) {
  return snapshotFromLocal(local, { value: 'recovery', error });
}

function snapshotFrom(overrides) {
  const snapshot = createInitialSnapshot({
    ...overrides,
    child: overrides.child === undefined || overrides.child === null ? (overrides.child ?? null) : copyChild(overrides.child),
    messages: overrides.messages === undefined ? [] : copyMessages(overrides.messages),
    draft: overrides.draft === undefined || overrides.draft === null ? (overrides.draft ?? null) : copyDraft(overrides.draft),
    error: overrides.error === undefined || overrides.error === null ? (overrides.error ?? null) : copyRemoteFailure(overrides.error),
    teacherUnlocked: false,
    reply: null,
    stopRequested: false,
  });
  assertSnapshot(snapshot);
  return snapshot;
}

function freezeOutcome(snapshot, storageAction) {
  return deepFreeze({ snapshot, storageAction });
}

function teacherFailure(code) {
  return { code, retryable: false };
}

function copyRecord(record) {
  return deepFreeze({
    version: 1,
    child: record.child === null ? null : copyChild(record.child),
    conversation_id: record.conversation_id,
    revision: record.revision,
    last_message_id: record.last_message_id,
    state: record.state,
    messages: copyMessages(record.messages),
    draft: record.draft === null ? null : copyDraft(record.draft),
    should_complete: record.should_complete,
    failure: record.failure === null ? null : copyFailure(record.failure),
    updated_at: record.updated_at,
  });
}

function copyActiveConversation(value) {
  return {
    id: value.id,
    child_id: value.child_id,
    status: 'active',
    revision: value.revision,
    round: value.round,
    last_message_id: value.last_message_id,
    messages: copyMessages(value.messages),
  };
}

function copyChild(value) {
  if (!isNullableChild(value, false) || value === null) throw new TypeError('invalid child');
  return { id: value.id, name: value.name, nickname: value.nickname, avatar: value.avatar };
}

function copyMessages(values) {
  if (!Array.isArray(values) || !values.every(value => isMessage(value, false))) {
    throw new TypeError('invalid messages');
  }
  return values.map(value => ({ id: value.id, role: value.role, text: value.text }));
}

function copyDraft(value) {
  if (!isNullableDraft(value, false) || value === null || value.text !== value.text.trim()) {
    throw new TypeError('invalid draft');
  }
  return { text: value.text, request_id: value.request_id, created_at: value.created_at };
}

function copyFailure(value) {
  if (!isNullableFailure(value, false) || value === null) throw new TypeError('invalid failure');
  return { code: value.code, retryable: value.retryable };
}

function copyRemoteFailure(value) {
  if (!isRemoteFailure(value)) throw new TypeError('invalid remote failure');
  const copied = { code: value.code, retryable: value.retryable };
  if (Object.hasOwn(value, 'message')) copied.message = value.message;
  return copied;
}

function isActiveConversation(value, strict) {
  if (!isRecord(value) || (strict && !hasExactOwnKeys(value, ACTIVE_FIELDS))
    || !isPositiveInteger(value.id)
    || !isPositiveInteger(value.child_id)
    || value.status !== 'active'
    || !isNonnegativeInteger(value.revision)
    || !isNonnegativeInteger(value.round)
    || !isNullablePositiveInteger(value.last_message_id)
    || !Array.isArray(value.messages)
    || !value.messages.every(message => isMessage(message, strict))) {
    return false;
  }
  let previousId = 0;
  for (const item of value.messages) {
    if (item.id <= previousId) return false;
    previousId = item.id;
  }
  return (value.messages.length === 0 && value.last_message_id === null)
    || (value.messages.length > 0 && value.last_message_id === previousId);
}

function isNullableChild(value, strict) {
  return value === null || isChild(value, strict);
}

function isChild(value, strict) {
  return isRecord(value)
    && (!strict || hasExactOwnKeys(value, CHILD_FIELDS))
    && isPositiveInteger(value.id)
    && typeof value.name === 'string'
    && value.name.length > 0
    && isNullableString(value.nickname)
    && isNullableString(value.avatar);
}

function isMessage(value, strict) {
  return isRecord(value)
    && (!strict || hasExactOwnKeys(value, MESSAGE_FIELDS))
    && isPositiveInteger(value.id)
    && (value.role === 'child' || value.role === 'diary')
    && typeof value.text === 'string';
}

function isNullableDraft(value, strict) {
  return value === null || isDraft(value, strict);
}

function isDraft(value, strict) {
  return isRecord(value)
    && (!strict || hasExactOwnKeys(value, DRAFT_FIELDS))
    && typeof value.text === 'string'
    && value.text.trim().length > 0
    && isCanonicalUUID(value.request_id)
    && isCanonicalTimestamp(value.created_at);
}

function isNullableFailure(value, strict) {
  return value === null || isFailure(value, strict);
}

function isFailure(value, strict) {
  return isRecord(value)
    && (!strict || hasExactOwnKeys(value, FAILURE_FIELDS))
    && typeof value.code === 'string'
    && value.code.length > 0
    && typeof value.retryable === 'boolean';
}

function isRemoteFailure(value) {
  if (!isRecord(value)) return false;
  const keys = Object.keys(value);
  if (Reflect.ownKeys(value).length !== keys.length
    || !keys.every(key => key === 'code' || key === 'retryable' || key === 'message')
    || !Object.hasOwn(value, 'code')
    || !Object.hasOwn(value, 'retryable')
    || !isFailure(value, false)) {
    return false;
  }
  return !Object.hasOwn(value, 'message') || (typeof value.message === 'string' && value.message.length > 0);
}

function hasExactOwnKeys(value, keys) {
  if (!isRecord(value)) return false;
  const ownKeys = Reflect.ownKeys(value);
  return ownKeys.length === keys.length
    && ownKeys.every(key => typeof key === 'string' && keys.includes(key));
}

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isPositiveInteger(value) {
  return Number.isSafeInteger(value) && value > 0;
}

function isNonnegativeInteger(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

function isNullablePositiveInteger(value) {
  return value === null || isPositiveInteger(value);
}

function isNullableNonnegativeInteger(value) {
  return value === null || isNonnegativeInteger(value);
}

function nullablePositiveInteger(value) {
  if (!isNullablePositiveInteger(value)) throw new TypeError('invalid conversation boundary');
  return value;
}

function nullableNonnegativeInteger(value) {
  if (!isNullableNonnegativeInteger(value)) throw new TypeError('invalid revision');
  return value;
}

function isNullableString(value) {
  return value === null || typeof value === 'string';
}

function isCanonicalUUID(value) {
  return typeof value === 'string' && UUID.test(value);
}

function isCanonicalTimestamp(value) {
  if (typeof value !== 'string') return false;
  try {
    return new Date(value).toISOString() === value;
  } catch {
    return false;
  }
}

function deepFreeze(value) {
  if (value !== null && typeof value === 'object' && !Object.isFrozen(value)) {
    for (const nested of Object.values(value)) deepFreeze(nested);
    Object.freeze(value);
  }
  return value;
}
