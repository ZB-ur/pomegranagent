export const STATES = Object.freeze([
  'welcome',
  'loading_roster',
  'selecting_child',
  'opening',
  'ready',
  'listening',
  'submitting',
  'speaking',
  'submission_failed',
  'saving_conversation',
  'completed',
  'recovery',
]);

const STATE_SET = new Set(STATES);
const BUSY_STATES = new Set([
  'loading_roster',
  'opening',
  'submitting',
  'speaking',
  'saving_conversation',
  'recovery',
]);
const SNAPSHOT_FIELDS = Object.freeze([
  'value',
  'roster',
  'child',
  'conversationId',
  'revision',
  'lastMessageId',
  'messages',
  'draft',
  'reply',
  'shouldComplete',
  'stopRequested',
  'error',
  'teacherUnlocked',
]);
const SNAPSHOT_FIELD_SET = new Set(SNAPSHOT_FIELDS);

const INITIAL_SNAPSHOT = Object.freeze({
  value: 'welcome',
  roster: Object.freeze([]),
  child: null,
  conversationId: null,
  revision: null,
  lastMessageId: null,
  messages: Object.freeze([]),
  draft: null,
  reply: null,
  shouldComplete: false,
  stopRequested: false,
  error: null,
  teacherUnlocked: false,
});

export function createInitialSnapshot(overrides = {}) {
  requireRecord(overrides, 'overrides');
  return freezeSnapshot({ ...INITIAL_SNAPSHOT, ...overrides });
}

export function transition(snapshot, event) {
  assertSnapshot(snapshot);
  requireRecord(event, 'event');
  if (!Object.hasOwn(event, 'type') || typeof event.type !== 'string' || event.type.length === 0) {
    throw new TypeError('event must have an own non-empty type');
  }

  if (event.type === 'TEACHER_UNLOCKED') {
    return replace(snapshot, { teacherUnlocked: true });
  }
  if (event.type === 'TEACHER_LOCKED') {
    return replace(snapshot, { teacherUnlocked: false });
  }

  switch (`${snapshot.value}:${event.type}`) {
    case 'welcome:START':
      return replace(snapshot, { value: 'loading_roster', error: null });

    case 'loading_roster:ROSTER_LOADED':
      return replace(snapshot, {
        value: 'selecting_child',
        roster: dedupeChildren(event.children),
        error: null,
      });

    case 'loading_roster:ROSTER_FAILED':
      return enterRecovery(snapshot, event.error);

    case 'loading_roster:BEGIN_RECOVERY':
      return enterRecovery(snapshot, event.error);

    case 'selecting_child:BEGIN_RECOVERY':
      return enterRecovery(snapshot, event.error);

    case 'selecting_child:CHILD_SELECTED': {
      const childId = positiveInteger(event.childId, 'childId');
      const selected = snapshot.roster.find(item => item.id === childId);
      if (!selected) {
        throw new TypeError('CHILD_SELECTED requires a roster child');
      }
      return replace(snapshot, { value: 'opening', child: selected, error: null });
    }

    case 'opening:BEGIN_RECOVERY':
      return enterRecovery(snapshot, event.error);

    case 'opening:TTS_SETTLED':
      return replace(snapshot, { value: 'ready' });

    case 'ready:BEGIN_RECOVERY':
      return enterRecovery(snapshot, event.error);

    case 'ready:RECORD_TOGGLE':
      return replace(snapshot, { value: 'listening', stopRequested: false, error: null });

    case 'listening:BEGIN_RECOVERY':
      return enterRecovery(snapshot, event.error);

    case 'listening:RECORD_TOGGLE':
      return replace(snapshot, { stopRequested: true });

    case 'listening:SPEECH_EMPTY':
      if (snapshot.stopRequested !== true) return snapshot;
      return replace(snapshot, { value: 'ready', error: null });

    case 'listening:SPEECH_FINAL':
      if (snapshot.stopRequested !== true) return snapshot;
      return replace(snapshot, {
        value: 'submitting',
        draft: normalizeDraft(event.draft),
        error: null,
      });

    case 'submitting:BEGIN_RECOVERY':
      return enterRecovery(snapshot, event.error);

    case 'submitting:SUBMIT_SUCCEEDED':
      return acceptSubmission(snapshot, event.result);

    case 'submitting:SUBMIT_FAILED':
      return failSubmission(snapshot, event.error);

    case 'submission_failed:BEGIN_RECOVERY':
      return enterRecovery(snapshot, event.error);

    case 'submission_failed:RETRY_SUBMIT':
      if (snapshot.error?.retryable !== true || snapshot.draft === null) {
        throw illegalTransition(snapshot, event);
      }
      return replace(snapshot, { value: 'submitting', error: null });

    case 'speaking:BEGIN_RECOVERY':
      return enterRecovery(snapshot, event.error);

    case 'speaking:TTS_SETTLED':
      return replace(snapshot, {
        value: snapshot.shouldComplete ? 'saving_conversation' : 'ready',
        reply: null,
      });

    case 'saving_conversation:COMPLETE_SUCCEEDED':
      return acceptCompletion(snapshot, event.result);

    case 'saving_conversation:COMPLETE_FAILED':
      return enterRecovery(snapshot, event.error);

    case 'saving_conversation:BEGIN_RECOVERY':
      return enterRecovery(snapshot, event.error);

    case 'completed:BEGIN_RECOVERY':
      return enterRecovery(snapshot, event.error);

    case 'recovery:BEGIN_RECOVERY':
      return enterRecovery(snapshot, event.error);

    case 'recovery:RECOVERY_RESOLVED':
      return resolveRecovery(event.snapshot);

    case 'recovery:TEACHER_RECOVERY_RETRY':
      if (snapshot.teacherUnlocked !== true) throw illegalTransition(snapshot, event);
      return replace(snapshot, {});

    case 'recovery:TEACHER_TEXT_SUBMITTED':
      if (snapshot.teacherUnlocked !== true || snapshot.child === null
        || snapshot.draft !== null || snapshot.shouldComplete !== false) {
        throw illegalTransition(snapshot, event);
      }
      return replace(snapshot, {
        value: 'submitting',
        draft: normalizeDraft(event.draft),
        error: null,
      });

    case 'recovery:TEACHER_DRAFT_SAVED':
      if (snapshot.teacherUnlocked !== true || snapshot.child === null
        || snapshot.draft !== null || snapshot.shouldComplete !== false) {
        throw illegalTransition(snapshot, event);
      }
      return replace(snapshot, {
        value: 'submission_failed',
        draft: normalizeDraft(event.draft),
        error: { code: 'TEACHER_DRAFT_SAVED', retryable: true },
      });

    case 'recovery:TEACHER_RETRY_MICROPHONE':
      if (snapshot.teacherUnlocked !== true || snapshot.child === null
        || snapshot.draft !== null || snapshot.shouldComplete !== false) {
        throw illegalTransition(snapshot, event);
      }
      return replace(snapshot, {
        value: 'listening',
        stopRequested: false,
        error: null,
      });

    case 'recovery:TEACHER_COMPLETE_REQUESTED':
      if (snapshot.teacherUnlocked !== true || snapshot.conversationId === null
        || snapshot.lastMessageId === null || snapshot.messages.length === 0) {
        throw illegalTransition(snapshot, event);
      }
      return replace(snapshot, {
        value: 'saving_conversation',
        shouldComplete: true,
        error: null,
      });

    case 'recovery:RESET':
    case 'completed:RESET':
      return createInitialSnapshot();

    default:
      throw illegalTransition(snapshot, event);
  }
}

export function controlsFor(snapshot) {
  assertSnapshot(snapshot);
  const busy = BUSY_STATES.has(snapshot.value);
  const canRecord = snapshot.value === 'ready'
    || (snapshot.value === 'listening' && snapshot.stopRequested === false);
  const canType = snapshot.teacherUnlocked === true
    && (snapshot.value === 'ready' || snapshot.value === 'submission_failed');
  const canRetry = snapshot.value === 'submission_failed' && snapshot.error?.retryable === true;
  const teacherRecovery = snapshot.value === 'recovery' && snapshot.teacherUnlocked === true;
  const teacherSafeInput = teacherRecovery
    && snapshot.child !== null
    && snapshot.draft === null
    && snapshot.shouldComplete === false;
  const teacherSafeCompletion = teacherRecovery
    && snapshot.conversationId !== null
    && snapshot.lastMessageId !== null
    && snapshot.messages.length > 0
    && snapshot.messages.at(-1).id === snapshot.lastMessageId;

  return Object.freeze({
    busy,
    recordAction: snapshot.value === 'listening' ? 'stop' : 'start',
    recordDisabled: !canRecord,
    textDisabled: !canType,
    retryDisabled: !canRetry,
    teacherTextDisabled: !teacherSafeInput,
    teacherDraftDisabled: !teacherSafeInput,
    teacherRecoveryRetryDisabled: !teacherRecovery,
    teacherMicrophoneRetryDisabled: !teacherSafeInput,
    teacherCompleteDisabled: !teacherSafeCompletion,
  });
}

export function assertSnapshot(snapshot) {
  validateSnapshot(snapshot);
  return snapshot;
}

function replace(snapshot, patch) {
  const next = { ...snapshot, ...patch };
  if (snapshot.value === 'listening' && next.value !== 'listening') {
    next.stopRequested = false;
  }
  return freezeSnapshot(next);
}

function acceptSubmission(snapshot, rawResult) {
  if (snapshot.draft === null) {
    throw new TypeError('SUBMIT_SUCCEEDED requires a draft');
  }
  const result = normalizeChatResult(rawResult);
  if (result.request_id !== snapshot.draft.request_id) {
    throw new TypeError('response request_id must match draft request_id');
  }
  if (snapshot.conversationId !== null && result.conversation_id !== snapshot.conversationId) {
    throw new TypeError('response conversation_id must match the established conversation');
  }

  return replace(snapshot, {
    value: 'speaking',
    conversationId: result.conversation_id,
    lastMessageId: result.diary_message_id,
    messages: appendAcknowledgedMessages(snapshot.messages, snapshot.draft.text, result),
    reply: result.reply,
    shouldComplete: result.ended,
    draft: null,
    error: null,
  });
}

function failSubmission(snapshot, rawError) {
  const error = normalizeError(rawError);
  return replace(snapshot, {
    value: error.retryable ? 'submission_failed' : 'recovery',
    error,
  });
}

function acceptCompletion(snapshot, rawResult) {
  const result = normalizeCompletionResult(rawResult);
  if (result.conversation_saved !== true) {
    throw new TypeError('completion requires conversation_saved=true');
  }
  if (result.conversation_id !== snapshot.conversationId) {
    throw new TypeError('completion conversation boundary does not match');
  }
  if (result.last_message_id !== snapshot.lastMessageId) {
    throw new TypeError('completion last-message boundary does not match');
  }
  if (result.message_count !== snapshot.messages.length) {
    throw new TypeError('completion message-count boundary does not match');
  }
  return replace(snapshot, { value: 'completed', error: null, reply: null });
}

function enterRecovery(snapshot, rawError) {
  return replace(snapshot, {
    value: 'recovery',
    error: rawError === undefined ? snapshot.error : normalizeError(rawError),
  });
}

function resolveRecovery(snapshot) {
  assertSnapshot(snapshot);
  return freezeSnapshot(snapshot);
}

function dedupeChildren(children) {
  if (!Array.isArray(children)) {
    throw new TypeError('children must be an array');
  }
  const ids = new Set();
  const roster = [];
  for (const rawChild of children) {
    const child = normalizeChild(rawChild);
    if (!ids.has(child.id)) {
      ids.add(child.id);
      roster.push(child);
    }
  }
  return roster;
}

function appendAcknowledgedMessages(messages, childText, result) {
  const acknowledged = [
    { id: result.child_message_id, role: 'child', text: childText },
    { id: result.diary_message_id, role: 'diary', text: result.reply },
  ];
  const next = messages.map(normalizeMessage);
  for (const message of acknowledged) {
    const existing = next.filter(candidate => candidate.id === message.id);
    if (existing.length === 0) {
      next.push(message);
    } else if (existing.some(candidate => candidate.role !== message.role || candidate.text !== message.text)) {
      throw new TypeError('acknowledged message ID conflicts with existing role or text');
    }
  }
  return next;
}

function freezeSnapshot(snapshot) {
  const normalized = normalizeSnapshot(snapshot);
  validateSnapshot(normalized);
  return deepFreeze(normalized);
}

function normalizeSnapshot(snapshot) {
  requireRecord(snapshot, 'snapshot');
  for (const key of Object.keys(snapshot)) {
    if (!SNAPSHOT_FIELD_SET.has(key)) {
      throw new TypeError(`Invalid snapshot field: ${key}`);
    }
  }
  for (const field of SNAPSHOT_FIELDS) {
    if (!Object.hasOwn(snapshot, field)) {
      throw new TypeError(`Invalid snapshot: missing ${field}`);
    }
  }
  return {
    value: snapshot.value,
    roster: normalizeChildren(snapshot.roster),
    child: snapshot.child === null ? null : normalizeChild(snapshot.child),
    conversationId: nullablePositiveInteger(snapshot.conversationId, 'conversationId'),
    revision: nullableNonNegativeInteger(snapshot.revision, 'revision'),
    lastMessageId: nullablePositiveInteger(snapshot.lastMessageId, 'lastMessageId'),
    messages: normalizeMessages(snapshot.messages),
    draft: snapshot.draft === null ? null : normalizeDraft(snapshot.draft),
    reply: nullableString(snapshot.reply, 'reply'),
    shouldComplete: boolean(snapshot.shouldComplete, 'shouldComplete'),
    stopRequested: boolean(snapshot.stopRequested, 'stopRequested'),
    error: snapshot.error === null ? null : normalizeError(snapshot.error),
    teacherUnlocked: boolean(snapshot.teacherUnlocked, 'teacherUnlocked'),
  };
}

function validateSnapshot(snapshot) {
  requireRecord(snapshot, 'snapshot');
  for (const key of Object.keys(snapshot)) {
    if (!SNAPSHOT_FIELD_SET.has(key)) {
      throw new TypeError(`Invalid snapshot field: ${key}`);
    }
  }
  for (const field of SNAPSHOT_FIELDS) {
    if (!Object.hasOwn(snapshot, field)) {
      throw new TypeError(`Invalid snapshot: missing ${field}`);
    }
  }
  if (!STATE_SET.has(snapshot.value)) {
    throw new TypeError(`Unknown child state: ${snapshot.value}`);
  }
  normalizeChildren(snapshot.roster);
  if (snapshot.child !== null) {
    normalizeChild(snapshot.child);
  }
  nullablePositiveInteger(snapshot.conversationId, 'conversationId');
  nullableNonNegativeInteger(snapshot.revision, 'revision');
  nullablePositiveInteger(snapshot.lastMessageId, 'lastMessageId');
  normalizeMessages(snapshot.messages);
  if (snapshot.draft !== null) {
    normalizeDraft(snapshot.draft);
  }
  nullableString(snapshot.reply, 'reply');
  boolean(snapshot.shouldComplete, 'shouldComplete');
  boolean(snapshot.stopRequested, 'stopRequested');
  if (snapshot.error !== null) {
    normalizeError(snapshot.error);
  }
  boolean(snapshot.teacherUnlocked, 'teacherUnlocked');
  if (snapshot.value === 'submitting' && snapshot.draft === null) {
    throw new TypeError('submitting requires a persisted draft and request_id');
  }
  if (snapshot.value === 'saving_conversation' || snapshot.value === 'completed') {
    if (snapshot.conversationId === null || snapshot.lastMessageId === null || snapshot.messages.length === 0) {
      throw new TypeError(`${snapshot.value} requires conversationId, lastMessageId, and at least one message`);
    }
    if (snapshot.messages.at(-1).id !== snapshot.lastMessageId) {
      throw new TypeError(`${snapshot.value} requires lastMessageId to match the final message`);
    }
  }
}

function normalizeChildren(children) {
  if (!Array.isArray(children)) {
    throw new TypeError('roster must be an array');
  }
  return children.map(normalizeChild);
}

function normalizeChild(rawChild) {
  requireRecord(rawChild, 'child');
  const name = nonEmptyString(rawChild.name, 'child.name');
  return {
    id: positiveInteger(rawChild.id, 'child.id'),
    name,
    nickname: nullableString(rawChild.nickname, 'child.nickname'),
    avatar: nullableString(rawChild.avatar, 'child.avatar'),
  };
}

function normalizeMessages(messages) {
  if (!Array.isArray(messages)) {
    throw new TypeError('messages must be an array');
  }
  return messages.map(normalizeMessage);
}

function normalizeMessage(rawMessage) {
  requireRecord(rawMessage, 'message');
  if (rawMessage.role !== 'child' && rawMessage.role !== 'diary') {
    throw new TypeError('message.role must be child or diary');
  }
  if (typeof rawMessage.text !== 'string') {
    throw new TypeError('message.text must be a string');
  }
  return {
    id: positiveInteger(rawMessage.id, 'message.id'),
    role: rawMessage.role,
    text: rawMessage.text,
  };
}

function normalizeDraft(rawDraft) {
  requireRecord(rawDraft, 'draft');
  const text = nonEmptyString(rawDraft.text, 'draft.text').trim();
  if (text.length === 0) {
    throw new TypeError('draft.text must contain non-whitespace text');
  }
  return {
    text,
    request_id: nonEmptyString(rawDraft.request_id, 'draft.request_id'),
    created_at: timestamp(rawDraft.created_at, 'draft.created_at'),
  };
}

function normalizeError(rawError) {
  requireRecord(rawError, 'error');
  const error = {
    code: nonEmptyString(rawError.code, 'error.code'),
    retryable: boolean(rawError.retryable, 'error.retryable'),
  };
  if (rawError.message !== undefined) {
    error.message = nonEmptyString(rawError.message, 'error.message');
  }
  return error;
}

function normalizeChatResult(rawResult) {
  requireRecord(rawResult, 'result');
  const childMessageId = positiveInteger(rawResult.child_message_id, 'child_message_id');
  const diaryMessageId = positiveInteger(rawResult.diary_message_id, 'diary_message_id');
  if (childMessageId === diaryMessageId) {
    throw new TypeError('child_message_id and diary_message_id must be distinct');
  }
  if (rawResult.end_reason !== 'max_rounds'
    && rawResult.end_reason !== 'complete'
    && rawResult.end_reason !== null) {
    throw new TypeError('end_reason must be max_rounds, complete, or null');
  }
  const ended = boolean(rawResult.ended, 'ended');
  if (!ended && rawResult.end_reason !== null) {
    throw new TypeError('ended=false requires end_reason=null');
  }
  if (ended && rawResult.end_reason === null) {
    throw new TypeError('ended=true requires an end_reason');
  }
  return {
    request_id: nonEmptyString(rawResult.request_id, 'request_id'),
    conversation_id: positiveInteger(rawResult.conversation_id, 'conversation_id'),
    child_message_id: childMessageId,
    diary_message_id: diaryMessageId,
    reply: nullableString(rawResult.reply, 'reply'),
    round: positiveInteger(rawResult.round, 'round'),
    ended,
    end_reason: rawResult.end_reason,
    replayed: boolean(rawResult.replayed, 'replayed'),
  };
}

function normalizeCompletionResult(rawResult) {
  requireRecord(rawResult, 'result');
  if (rawResult.conversation_saved !== true) {
    throw new TypeError('completion requires conversation_saved=true');
  }
  if (rawResult.status !== 'completed') {
    throw new TypeError('completion status must be completed');
  }
  const analysisStatuses = new Set(['pending', 'processing', 'succeeded', 'failed']);
  if (!analysisStatuses.has(rawResult.analysis_status)) {
    throw new TypeError('completion analysis_status is invalid');
  }
  return {
    conversation_id: positiveInteger(rawResult.conversation_id, 'conversation_id'),
    conversation_saved: true,
    status: 'completed',
    completed_at: timestamp(rawResult.completed_at, 'completed_at'),
    message_count: positiveInteger(rawResult.message_count, 'message_count'),
    last_message_id: positiveInteger(rawResult.last_message_id, 'last_message_id'),
    analysis_job_id: positiveInteger(rawResult.analysis_job_id, 'analysis_job_id'),
    analysis_status: rawResult.analysis_status,
    replayed: boolean(rawResult.replayed, 'replayed'),
  };
}

function requireRecord(value, name) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
}

function positiveInteger(value, name) {
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new TypeError(`${name} must be a positive integer`);
  }
  return value;
}

function nullablePositiveInteger(value, name) {
  return value === null ? null : positiveInteger(value, name);
}

function nullableNonNegativeInteger(value, name) {
  return value === null ? null : nonNegativeInteger(value, name);
}

function nonNegativeInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new TypeError(`${name} must be a non-negative integer`);
  }
  return value;
}

function nonEmptyString(value, name) {
  if (typeof value !== 'string' || value.length === 0) {
    throw new TypeError(`${name} must be a non-empty string`);
  }
  return value;
}

function nullableString(value, name) {
  if (value !== null && typeof value !== 'string') {
    throw new TypeError(`${name} must be a string or null`);
  }
  return value;
}

function timestamp(value, name) {
  if (typeof value !== 'string' || value.length === 0 || Number.isNaN(Date.parse(value))) {
    throw new TypeError(`${name} must be a valid timestamp`);
  }
  return value;
}

function boolean(value, name) {
  if (typeof value !== 'boolean') {
    throw new TypeError(`${name} must be a boolean`);
  }
  return value;
}

function illegalTransition(snapshot, event) {
  return new TypeError(`Illegal transition ${snapshot.value}:${event.type}`);
}

function deepFreeze(value) {
  if (value !== null && typeof value === 'object' && !Object.isFrozen(value)) {
    for (const nestedValue of Object.values(value)) {
      deepFreeze(nestedValue);
    }
    Object.freeze(value);
  }
  return value;
}
