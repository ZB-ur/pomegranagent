const HEALTH_FIELDS = [
  'release_id', 'api_version', 'schema_version', 'db_mode', 'analysis_worker_status',
];
const CHILD_FIELDS = ['id', 'name', 'nickname', 'avatar'];
const ACTIVE_RESPONSE_FIELDS = ['conversation'];
const ACTIVE_CONVERSATION_FIELDS = [
  'id', 'child_id', 'status', 'revision', 'round', 'last_message_id', 'messages',
];
const MESSAGE_FIELDS = ['id', 'role', 'text'];
const CHAT_FIELDS = [
  'request_id', 'conversation_id', 'child_message_id', 'diary_message_id', 'reply',
  'round', 'ended', 'end_reason', 'replayed',
];
const COMPLETE_FIELDS = [
  'conversation_id', 'conversation_saved', 'status', 'completed_at', 'message_count',
  'last_message_id', 'analysis_job_id', 'analysis_status', 'replayed',
];
const CHAT_INPUT_FIELDS = ['request_id', 'child_id', 'text', 'conversation_id', 'max_rounds'];
const ANALYSIS_STATUSES = new Set(['pending', 'processing', 'succeeded', 'failed']);
const END_REASONS = new Set(['max_rounds', 'complete']);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const UTC_TIMESTAMP = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?Z$/;

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function hasOwn(value, key) {
  return Object.hasOwn(value, key);
}

function hasExactOwnKeys(value, keys) {
  if (!isRecord(value)) return false;
  const ownKeys = Reflect.ownKeys(value);
  return ownKeys.length === keys.length
    && ownKeys.every(key => typeof key === 'string' && keys.includes(key));
}

function hasRequiredOwnKeys(value, keys) {
  return isRecord(value) && keys.every(key => hasOwn(value, key));
}

function isPositiveInteger(value) {
  return Number.isSafeInteger(value) && value > 0;
}

function isNonnegativeInteger(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

function isNullableString(value) {
  return value === null || typeof value === 'string';
}

function isCanonicalUUID(value) {
  return typeof value === 'string' && UUID.test(value);
}

function invalidResponse(duckAPI, label) {
  const error = new Error(`Invalid ${label} response`);
  Object.setPrototypeOf(error, duckAPI.APIError.prototype);
  return Object.assign(error, {
    name: 'APIError',
    status: 0,
    code: 'INVALID_RESPONSE',
    fieldErrors: {},
    retryable: true,
    requestId: null,
    cause: null,
  });
}

function assertOrInvalid(duckAPI, label, condition) {
  if (!condition) throw invalidResponse(duckAPI, label);
}

function assertHealth(value, duckAPI) {
  assertOrInvalid(duckAPI, 'health', hasRequiredOwnKeys(value, HEALTH_FIELDS));
  assertOrInvalid(duckAPI, 'health',
    typeof value.release_id === 'string'
    && typeof value.api_version === 'string'
    && typeof value.schema_version === 'string'
    && value.db_mode === 'app'
    && typeof value.analysis_worker_status === 'string');
  return value;
}

function assertChild(value, duckAPI) {
  assertOrInvalid(duckAPI, 'roster child', hasExactOwnKeys(value, CHILD_FIELDS));
  assertOrInvalid(duckAPI, 'roster child',
    isPositiveInteger(value.id)
    && typeof value.name === 'string'
    && isNullableString(value.nickname)
    && isNullableString(value.avatar));
}

function assertRoster(value, duckAPI) {
  assertOrInvalid(duckAPI, 'roster', Array.isArray(value));
  const ids = new Set();
  for (const entry of value) {
    assertChild(entry, duckAPI);
    assertOrInvalid(duckAPI, 'roster', !ids.has(entry.id));
    ids.add(entry.id);
  }
  return value;
}

function assertMessage(value, duckAPI) {
  assertOrInvalid(duckAPI, 'active conversation message', hasExactOwnKeys(value, MESSAGE_FIELDS));
  assertOrInvalid(duckAPI, 'active conversation message',
    isPositiveInteger(value.id)
    && (value.role === 'child' || value.role === 'diary')
    && typeof value.text === 'string');
}

function assertActive(value, childId, duckAPI) {
  assertOrInvalid(duckAPI, 'active conversation', hasExactOwnKeys(value, ACTIVE_RESPONSE_FIELDS));
  if (value.conversation === null) return value;

  const conversation = value.conversation;
  assertOrInvalid(duckAPI, 'active conversation', hasExactOwnKeys(conversation, ACTIVE_CONVERSATION_FIELDS));
  assertOrInvalid(duckAPI, 'active conversation',
    isPositiveInteger(conversation.id)
    && conversation.child_id === childId
    && conversation.status === 'active'
    && isNonnegativeInteger(conversation.revision)
    && isNonnegativeInteger(conversation.round)
    && (conversation.last_message_id === null || isPositiveInteger(conversation.last_message_id))
    && Array.isArray(conversation.messages));

  let previousId = 0;
  for (const entry of conversation.messages) {
    assertMessage(entry, duckAPI);
    assertOrInvalid(duckAPI, 'active conversation', entry.id > previousId);
    previousId = entry.id;
  }
  assertOrInvalid(duckAPI, 'active conversation',
    (conversation.messages.length === 0 && conversation.last_message_id === null)
    || (conversation.messages.length > 0 && conversation.last_message_id === previousId));
  return value;
}

function assertChat(value, input, duckAPI) {
  assertOrInvalid(duckAPI, 'chat', hasExactOwnKeys(value, CHAT_FIELDS));
  assertOrInvalid(duckAPI, 'chat',
    isCanonicalUUID(value.request_id)
    && value.request_id === input.request_id
    && isPositiveInteger(value.conversation_id)
    && (input.conversation_id === null || value.conversation_id === input.conversation_id)
    && isPositiveInteger(value.child_message_id)
    && isPositiveInteger(value.diary_message_id)
    && value.child_message_id !== value.diary_message_id
    && typeof value.reply === 'string'
    && isPositiveInteger(value.round)
    && value.round <= input.max_rounds
    && typeof value.ended === 'boolean'
    && typeof value.replayed === 'boolean');
  assertOrInvalid(duckAPI, 'chat',
    (value.ended && END_REASONS.has(value.end_reason))
    || (!value.ended && value.end_reason === null));
  assertOrInvalid(duckAPI, 'chat',
    value.end_reason !== 'max_rounds' || value.round === input.max_rounds);
  return value;
}

function isValidTimestamp(value) {
  if (typeof value !== 'string') return false;
  const match = value.match(UTC_TIMESTAMP);
  if (!match) return false;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText] = match;
  const [year, month, day, hour, minute, second] = [
    yearText, monthText, dayText, hourText, minuteText, secondText,
  ].map(Number);
  if (hour > 23 || minute > 59 || second > 59) return false;

  const parsed = new Date(0);
  parsed.setUTCFullYear(year, month - 1, day);
  parsed.setUTCHours(hour, minute, second, 0);
  return parsed.getUTCFullYear() === year
    && parsed.getUTCMonth() === month - 1
    && parsed.getUTCDate() === day
    && parsed.getUTCHours() === hour
    && parsed.getUTCMinutes() === minute
    && parsed.getUTCSeconds() === second;
}

function assertComplete(value, conversationId, expectedLastMessageId, duckAPI) {
  assertOrInvalid(duckAPI, 'completion', hasExactOwnKeys(value, COMPLETE_FIELDS));
  assertOrInvalid(duckAPI, 'completion',
    value.conversation_id === conversationId
    && value.conversation_saved === true
    && value.status === 'completed'
    && isValidTimestamp(value.completed_at)
    && isPositiveInteger(value.message_count)
    && value.last_message_id === expectedLastMessageId
    && isPositiveInteger(value.analysis_job_id)
    && ANALYSIS_STATUSES.has(value.analysis_status)
    && typeof value.replayed === 'boolean');
  return value;
}

function assertAuthPair(value, duckAPI, label) {
  assertOrInvalid(duckAPI, label, hasRequiredOwnKeys(value, ['configured', 'authenticated']));
  assertOrInvalid(duckAPI, label,
    typeof value.configured === 'boolean' && typeof value.authenticated === 'boolean');
  return value;
}

function assertAuthStatus(value, duckAPI) {
  assertAuthPair(value, duckAPI, 'teacher status');
  assertOrInvalid(duckAPI, 'teacher status', value.configured || !value.authenticated);
  return value;
}

function assertAuthenticated(value, duckAPI) {
  assertAuthPair(value, duckAPI, 'teacher authentication');
  assertOrInvalid(duckAPI, 'teacher authentication',
    value.configured === true && value.authenticated === true);
  return value;
}

function assertLocked(value, duckAPI) {
  assertAuthPair(value, duckAPI, 'teacher lock');
  assertOrInvalid(duckAPI, 'teacher lock', value.authenticated === false);
  return value;
}

function assertInjectedDuckAPI(duckAPI, requireGate = false) {
  if (!isRecord(duckAPI)
    || typeof duckAPI.APIError !== 'function'
    || typeof duckAPI.ready !== 'function'
    || typeof duckAPI.request !== 'function'
    || (requireGate && typeof duckAPI.bootstrapVersionGate !== 'function')) {
    throw new TypeError('DuckAPI does not satisfy the child adapter contract');
  }
}

function assertInjectedDuckAuth(duckAuth) {
  if (!isRecord(duckAuth)
    || typeof duckAuth.status !== 'function'
    || typeof duckAuth.setup !== 'function'
    || typeof duckAuth.unlock !== 'function'
    || typeof duckAuth.lock !== 'function') {
    throw new TypeError('DuckAuth does not satisfy the child adapter contract');
  }
}

function assertChatInput(input) {
  if (!hasExactOwnKeys(input, CHAT_INPUT_FIELDS)
    || !isCanonicalUUID(input.request_id)
    || !isPositiveInteger(input.child_id)
    || typeof input.text !== 'string'
    || input.text.trim().length === 0
    || input.text.length > 2000
    || (input.conversation_id !== null && !isPositiveInteger(input.conversation_id))
    || input.max_rounds !== 3) {
    throw new TypeError('Invalid chat input');
  }
}

function assertPin(pin) {
  if (typeof pin !== 'string' || !/^[0-9]{4,6}$/.test(pin)) {
    throw new TypeError('Teacher PIN must be a 4–6 digit string');
  }
}

function assertText(text) {
  if (typeof text !== 'string' || text.trim().length === 0) {
    throw new TypeError('TTS text must be nonblank');
  }
}

function assertConversationId(value, label) {
  if (!isPositiveInteger(value)) throw new TypeError(`${label} must be a positive integer`);
}

export function createChildAPI(duckAPI, duckAuth) {
  assertInjectedDuckAPI(duckAPI);
  assertInjectedDuckAuth(duckAuth);

  const json = (path, options) => duckAPI.request(path, { ...options, responseType: 'json' });
  return Object.freeze({
    ready: () => duckAPI.ready().then(value => assertHealth(value, duckAPI)),
    getTodayRoster: () => json('/api/roster/today', {
      sequenceKey: 'child-roster',
    }).then(value => assertRoster(value, duckAPI)),
    getActiveConversation: childId => {
      assertConversationId(childId, 'Child ID');
      return json(`/api/children/${childId}/active-conversation`, {
        sequenceKey: `child-active-${childId}`,
      }).then(value => assertActive(value, childId, duckAPI));
    },
    chat: (input, signal) => {
      assertChatInput(input);
      return json('/api/chat', {
        method: 'POST',
        body: input,
        signal,
        requestId: input.request_id,
        sequenceKey: 'child-chat',
      }).then(value => assertChat(value, input, duckAPI));
    },
    complete: (conversationId, expectedLastMessageId, signal) => {
      assertConversationId(conversationId, 'Conversation ID');
      assertConversationId(expectedLastMessageId, 'Expected last message ID');
      return json(`/api/conversations/${conversationId}/complete`, {
        method: 'POST',
        body: { expected_last_message_id: expectedLastMessageId },
        signal,
        sequenceKey: `child-complete-${conversationId}`,
      }).then(value => assertComplete(value, conversationId, expectedLastMessageId, duckAPI));
    },
    teacherStatus: () => duckAuth.status().then(value => assertAuthStatus(value, duckAPI)),
    teacherSetup: pin => {
      assertPin(pin);
      return duckAuth.setup(pin).then(value => assertAuthenticated(value, duckAPI));
    },
    teacherUnlock: pin => {
      assertPin(pin);
      return duckAuth.unlock(pin).then(value => assertAuthenticated(value, duckAPI));
    },
    teacherLock: () => duckAuth.lock().then(value => assertLocked(value, duckAPI)),
    tts: (text, signal) => {
      assertText(text);
      return duckAPI.request(`/api/tts?text=${encodeURIComponent(text)}`, {
        signal,
        responseType: 'blob',
        timeoutMs: 10000,
        sequenceKey: 'child-tts',
      });
    },
  });
}

export async function bootstrapBrowserChildAPI(globalObject = globalThis) {
  if (!isRecord(globalObject)) {
    throw new TypeError('Browser global object is required');
  }
  const duckAPI = globalObject.DuckAPI;
  const duckAuth = globalObject.DuckAuth;
  assertInjectedDuckAPI(duckAPI, true);
  assertInjectedDuckAuth(duckAuth);
  await duckAPI.bootstrapVersionGate();
  return createChildAPI(duckAPI, duckAuth);
}
