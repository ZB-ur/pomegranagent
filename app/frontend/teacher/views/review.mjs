import { displayName, validateQueueRows } from './today.mjs';

const DETAIL_KEYS = [
  'id', 'child', 'date', 'started_at', 'completed_at', 'status', 'end_reason',
  'message_count', 'round', 'last_message_id', 'revision', 'analysis',
  'review_status', 'messages', 'review',
];
const CHILD_KEYS = ['id', 'name', 'nickname', 'avatar'];
const MESSAGE_KEYS = ['id', 'role', 'text'];
const ANALYSIS_KEYS = ['job_id', 'status', 'attempt_count', 'max_attempts', 'error', 'updated_at'];
const ANALYSIS_ERROR_KEYS = ['code', 'message'];
const REVIEW_KEYS = ['feeding_logs', 'emotion', 'insight', 'scores', 'overall'];
const FEEDING_LOG_KEYS = ['id', 'category', 'content', 'duck_id'];
const EMOTION_KEYS = ['emotion', 'intensity', 'note'];
const SCORE_KEYS = ['dimension_id', 'dimension_name', 'score', 'reason'];
const DEPENDENCY_KEYS = ['request', 'document', 'createAbortController'];
const END_REASONS = new Set(['max_rounds', 'complete', 'manual']);
const ANALYSIS_STATUSES = new Set(['pending', 'processing', 'succeeded', 'failed']);
const REVIEW_STATUSES = new Set(['pending', 'draft', 'confirmed', 'unavailable']);
const FEEDING_CATEGORIES = new Set(['喂食', '清洁', '观察', '其它']);

function invalidReviewContract() {
  return new TypeError('Review reader contract is invalid.');
}

function readOwnDataRecord(value, keys) {
  try {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) throw invalidReviewContract();
    const descriptors = Object.getOwnPropertyDescriptors(value);
    const actualKeys = Reflect.ownKeys(descriptors);
    if (actualKeys.length !== keys.length || !keys.every(key => actualKeys.includes(key))) {
      throw invalidReviewContract();
    }
    const record = {};
    for (const key of keys) {
      const descriptor = descriptors[key];
      if (!descriptor || !Object.prototype.hasOwnProperty.call(descriptor, 'value')) throw invalidReviewContract();
      record[key] = descriptor.value;
    }
    return record;
  } catch (_error) {
    throw invalidReviewContract();
  }
}

function isPositiveInteger(value) {
  return Number.isSafeInteger(value) && value > 0;
}

function isNonnegativeInteger(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

function isNonblankString(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function isNullableString(value) {
  return value === null || typeof value === 'string';
}

function isParseableDate(value) {
  return typeof value === 'string' && Number.isFinite(Date.parse(value));
}

function validateChild(value) {
  const child = readOwnDataRecord(value, CHILD_KEYS);
  try {
    displayName(child);
  } catch (_error) {
    throw invalidReviewContract();
  }
  return child;
}

function validateMessage(value) {
  const message = readOwnDataRecord(value, MESSAGE_KEYS);
  if (!isPositiveInteger(message.id) || !['child', 'diary'].includes(message.role)
      || typeof message.text !== 'string') {
    throw invalidReviewContract();
  }
  return message;
}

function validateAnalysisError(value) {
  const error = readOwnDataRecord(value, ANALYSIS_ERROR_KEYS);
  if (error.code !== 'ANALYSIS_UPSTREAM_FAILED' || error['message'] !== '分析服务暂时不可用') {
    throw invalidReviewContract();
  }
  return error;
}

function validateAnalysis(value) {
  const analysis = readOwnDataRecord(value, ANALYSIS_KEYS);
  if (!isPositiveInteger(analysis.job_id) || !ANALYSIS_STATUSES.has(analysis.status)
      || !isNonnegativeInteger(analysis.attempt_count) || !isPositiveInteger(analysis.max_attempts)
      || !isParseableDate(analysis.updated_at)) {
    throw invalidReviewContract();
  }
  if (analysis.status === 'failed') {
    validateAnalysisError(analysis.error);
  } else if (analysis.error !== null) {
    throw invalidReviewContract();
  }
  return analysis;
}

function validateFeedingLog(value) {
  const log = readOwnDataRecord(value, FEEDING_LOG_KEYS);
  if (!isPositiveInteger(log.id) || !FEEDING_CATEGORIES.has(log.category)
      || typeof log.content !== 'string' || !(log.duck_id === null || isPositiveInteger(log.duck_id))) {
    throw invalidReviewContract();
  }
  return log;
}

function validateEmotion(value) {
  const emotion = readOwnDataRecord(value, EMOTION_KEYS);
  if (!isNonblankString(emotion.emotion) || !Number.isInteger(emotion.intensity)
      || emotion.intensity < 1 || emotion.intensity > 5 || !isNullableString(emotion.note)) {
    throw invalidReviewContract();
  }
  return emotion;
}

function validateScore(value) {
  const score = readOwnDataRecord(value, SCORE_KEYS);
  if (!isPositiveInteger(score.dimension_id) || !isNonblankString(score.dimension_name)
      || !Number.isInteger(score.score) || score.score < 1 || score.score > 5
      || typeof score.reason !== 'string') {
    throw invalidReviewContract();
  }
  return score;
}

function validateReviewDocument(value) {
  const review = readOwnDataRecord(value, REVIEW_KEYS);
  if (!Array.isArray(review.feeding_logs) || !Array.isArray(review.scores)
      || !isNonblankString(review.insight) || !Number.isFinite(review.overall)) {
    throw invalidReviewContract();
  }
  const feedingLogs = review.feeding_logs.map(validateFeedingLog);
  const emotion = validateEmotion(review.emotion);
  const scores = review.scores.map(validateScore);
  if (new Set(scores.map(score => score.dimension_id)).size !== scores.length) throw invalidReviewContract();
  return { ...review, feeding_logs: feedingLogs, emotion, scores };
}

function validateDependencies(dependencies) {
  const record = readOwnDataRecord(dependencies, DEPENDENCY_KEYS);
  try {
    if (typeof record.request !== 'function' || !record.document
        || typeof record.document.createElement !== 'function'
        || typeof record.createAbortController !== 'function') {
      throw invalidReviewContract();
    }
    validateAbortController(record.createAbortController());
  } catch (_error) {
    throw invalidReviewContract();
  }
  return record;
}

function validateAbortController(controller) {
  try {
    if (controller === null || typeof controller !== 'object' || typeof controller.abort !== 'function') {
      throw invalidReviewContract();
    }
    const signal = controller.signal;
    if (signal === null || typeof signal !== 'object' || typeof signal.aborted !== 'boolean'
        || typeof signal.addEventListener !== 'function' || typeof signal.removeEventListener !== 'function') {
      throw invalidReviewContract();
    }
    return controller;
  } catch (_error) {
    throw invalidReviewContract();
  }
}

export function parseReviewConversationId(params) {
  try {
    if (!(params instanceof URLSearchParams)) throw invalidReviewContract();
    const values = params.getAll('conversation_id');
    if (values.length !== 1 || !/^[1-9]\d*$/.test(values[0])) return null;
    const selectedId = Number(values[0]);
    return isPositiveInteger(selectedId) ? selectedId : null;
  } catch (_error) {
    throw invalidReviewContract();
  }
}

export function analysisStatusLabel(status) {
  const labels = {
    pending: '等待分析',
    processing: '分析中',
    succeeded: '分析已完成',
    failed: '分析失败',
  };
  if (!Object.prototype.hasOwnProperty.call(labels, status)) throw invalidReviewContract();
  return labels[status];
}

export function isSameChildIdentity(first, second) {
  try {
    const left = validateChild(first);
    const right = validateChild(second);
    return CHILD_KEYS.every(key => left[key] === right[key]);
  } catch (_error) {
    throw invalidReviewContract();
  }
}

export function validateReviewDetail(selectedId, value) {
  try {
    if (!isPositiveInteger(selectedId)) throw invalidReviewContract();
    const detail = readOwnDataRecord(value, DETAIL_KEYS);
    const child = validateChild(detail.child);
    const analysis = validateAnalysis(detail.analysis);
    if (!isPositiveInteger(detail.id) || detail.id !== selectedId || !isParseableDate(detail.date)
        || !isParseableDate(detail.started_at) || !isParseableDate(detail.completed_at)
        || detail.status !== 'ended' || !END_REASONS.has(detail.end_reason)
        || !isPositiveInteger(detail.message_count) || !isNonnegativeInteger(detail.round)
        || !isPositiveInteger(detail.last_message_id) || !isNonnegativeInteger(detail.revision)
        || !REVIEW_STATUSES.has(detail.review_status) || !Array.isArray(detail.messages)
        || detail.messages.length !== detail.message_count || detail.messages.length === 0) {
      throw invalidReviewContract();
    }
    const messages = detail.messages.map(validateMessage);
    if (messages[messages.length - 1].id !== detail.last_message_id
        || messages.some((message, index) => index > 0 && message.id <= messages[index - 1].id)
        || messages.filter(message => message.role === 'child').length !== detail.round) {
      throw invalidReviewContract();
    }
    let review = null;
    if (analysis.status === 'succeeded') {
      if (!['pending', 'draft', 'confirmed'].includes(detail.review_status)) throw invalidReviewContract();
      review = validateReviewDocument(detail.review);
    } else if (detail.review_status !== 'unavailable' || detail.review !== null) {
      throw invalidReviewContract();
    }
    return { ...detail, child, analysis, messages, review };
  } catch (_error) {
    throw invalidReviewContract();
  }
}

function createElement(document, tag, attrs, ...children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  }
  for (const child of children) node.append(child);
  return node;
}

function formatCompletedTime(value) {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date(value));
}

function queueRow(state, row) {
  const name = displayName(row.child);
  const link = createElement(state.document, 'a', {
    class: 'review-queue-link', href: `#review?conversation_id=${row.id}`,
    'aria-label': `审阅${name}的会话 #${row.id}`,
  }, name);
  const metadata = createElement(state.document, 'p', { class: 'review-row-metadata muted' },
    `完成于 ${formatCompletedTime(row.completed_at)} · 会话 #${row.id} · ${row.round} 轮 · ${row.review_status === 'draft' ? '草稿' : '待审阅'}`);
  return createElement(state.document, 'article', { class: 'review-queue-row' }, link, metadata);
}

function renderQueueLoading(state) {
  state.queuePanel.setAttribute('aria-busy', 'true');
  state.queueStatus.replaceChildren('正在加载待审阅队列…');
  state.queueBody.replaceChildren(queueReloadButton(state));
}

function queueReloadButton(state) {
  const retry = createElement(state.document, 'button', {
    class: 'btn gray review-queue-reload', type: 'button',
  }, '重新加载队列');
  retry.addEventListener('click', () => { void state.loadQueue(); });
  return retry;
}

function renderQueueError(state) {
  state.queuePanel.removeAttribute('aria-busy');
  state.queueStatus.replaceChildren('加载失败，请重试。');
  state.queueBody.replaceChildren(queueReloadButton(state));
}

function renderQueueRows(state, rows) {
  state.queuePanel.removeAttribute('aria-busy');
  if (!rows.length) {
    state.queueStatus.replaceChildren('暂无待审阅会话');
    state.queueBody.replaceChildren(createElement(state.document, 'a', {
      class: 'review-return-today', href: '#today',
    }, '返回今日任务'));
    return;
  }
  state.queueStatus.replaceChildren();
  state.queueBody.replaceChildren(...rows.map(row => queueRow(state, row)));
}

function detailReloadButton(state) {
  const button = createElement(state.document, 'button', {
    class: 'btn gray review-detail-reload', type: 'button',
  }, '重新加载此会话');
  button.addEventListener('click', () => {
    if (state.selectedId !== null) void state.loadDetail(state.selectedId);
  });
  return button;
}

function renderDetailInstruction(state) {
  state.detailPanel.removeAttribute('aria-busy');
  state.detailBody.replaceChildren(createElement(state.document, 'p', { class: 'muted' }, '请从左侧待审阅队列选择一条会话。'));
}

function renderDetailLoading(state, selectedId) {
  state.detailPanel.setAttribute('aria-busy', 'true');
  state.detailBody.replaceChildren(createElement(state.document, 'p', {
    class: 'review-detail-status muted', role: 'status', 'aria-live': 'polite',
  }, `正在加载会话 #${selectedId}…`), detailReloadButton(state));
}

function renderDetailError(state, selectedId) {
  state.detailPanel.removeAttribute('aria-busy');
  state.detailBody.replaceChildren(
    createElement(state.document, 'p', { class: 'review-detail-error', role: 'alert' }, '加载失败，请重试。'),
    detailReloadButton(state),
  );
  void selectedId;
}

function transcriptView(state, messages) {
  const transcript = createElement(state.document, 'section', { class: 'review-transcript' },
    createElement(state.document, 'h2', null, '原始对话'));
  const log = createElement(state.document, 'div', { class: 'review-message-log', role: 'log' });
  for (const message of messages) {
    const speaker = message.role === 'child' ? '幼儿' : '日记本';
    log.append(createElement(state.document, 'article', { class: `review-message review-message-${message.role}` },
      createElement(state.document, 'p', { class: 'review-speaker' }, speaker),
      createElement(state.document, 'p', { class: 'review-message-text' }, message.text)));
  }
  transcript.append(log);
  return transcript;
}

function resultsView(state, review) {
  const results = createElement(state.document, 'section', { class: 'review-results' },
    createElement(state.document, 'h2', null, '结构化结果'));
  const logs = createElement(state.document, 'section', { class: 'review-result-group' },
    createElement(state.document, 'h3', null, '饲养记录'));
  if (!review.feeding_logs.length) logs.append(createElement(state.document, 'p', { class: 'muted' }, '暂无饲养记录'));
  for (const log of review.feeding_logs) {
    logs.append(createElement(state.document, 'p', null, `${log.category}：${log.content}`));
  }
  const emotion = createElement(state.document, 'section', { class: 'review-result-group' },
    createElement(state.document, 'h3', null, '情绪'),
    createElement(state.document, 'p', null, `${review.emotion.emotion}（强度 ${review.emotion.intensity}）`));
  if (review.emotion.note) emotion.append(createElement(state.document, 'p', { class: 'muted' }, review.emotion.note));
  results.append(logs, emotion, createElement(state.document, 'section', { class: 'review-result-group' },
    createElement(state.document, 'h3', null, '洞察'), createElement(state.document, 'p', null, review.insight)));
  return results;
}

function unavailableResultsView(state, analysisStatus) {
  const results = createElement(state.document, 'section', { class: 'review-results' },
    createElement(state.document, 'h2', null, '结构化结果'),
    createElement(state.document, 'p', { class: 'muted' }, '结构化结果暂不可用'));
  if (analysisStatus === 'failed') {
    results.append(createElement(state.document, 'p', { class: 'review-analysis-failed', role: 'status' }, '分析失败，请返回今日任务重试。'),
      createElement(state.document, 'a', { class: 'review-return-today', href: '#today' }, '返回今日任务'));
  }
  return results;
}

function scoreView(state, review) {
  const scores = createElement(state.document, 'section', { class: 'review-scores' },
    createElement(state.document, 'h2', null, '能力评估'));
  for (const score of review.scores) {
    scores.append(createElement(state.document, 'article', { class: 'review-score-row' },
      createElement(state.document, 'h3', null, score.dimension_name),
      createElement(state.document, 'p', null, `${score.score} 分`),
      createElement(state.document, 'p', { class: 'muted' }, score.reason)));
  }
  return scores;
}

function renderDetailLoaded(state, detail) {
  state.detailPanel.removeAttribute('aria-busy');
  const name = displayName(detail.child);
  const header = createElement(state.document, 'header', { class: 'review-detail-header' },
    createElement(state.document, 'h2', null, name),
    createElement(state.document, 'div', { class: 'review-detail-facts muted' },
      createElement(state.document, 'span', null, `会话 #${detail.id}`),
      createElement(state.document, 'span', null, detail.date),
      createElement(state.document, 'span', null, `完成于 ${formatCompletedTime(detail.completed_at)}`),
      createElement(state.document, 'span', null, `${detail.round} 轮`),
      createElement(state.document, 'span', null, analysisStatusLabel(detail.analysis.status)),
      createElement(state.document, 'span', null, `revision ${detail.revision}`)),
    detailReloadButton(state));
  const workspace = createElement(state.document, 'div', { class: 'review-workspace' },
    transcriptView(state, detail.messages), detail.review === null
      ? unavailableResultsView(state, detail.analysis.status)
      : resultsView(state, detail.review));
  state.detailBody.replaceChildren(header, workspace, ...(detail.review === null ? [] : [scoreView(state, detail.review)]));
}

export function createReviewRoute(dependencies) {
  const validated = validateDependencies(dependencies);
  return function reviewRoute({ root, params, signal, isCurrent }) {
    if (!isCurrent() || signal.aborted) return undefined;
    const selectedId = parseReviewConversationId(params);
    const shell = createElement(validated.document, 'div', { class: 'view active review-view' },
      createElement(validated.document, 'h1', null, '值日审阅'));
    const queueStatus = createElement(validated.document, 'p', {
      class: 'review-queue-status muted', role: 'status', 'aria-live': 'polite',
    }, '正在加载待审阅队列…');
    const queueBody = createElement(validated.document, 'div', { class: 'review-queue-body' });
    const queuePanel = createElement(validated.document, 'section', {
      class: 'card review-panel review-queue-panel', 'data-review-panel': 'queue', 'aria-busy': 'true',
    }, createElement(validated.document, 'h2', null, '待审阅队列'), queueStatus, queueBody);
    const detailBody = createElement(validated.document, 'div', { class: 'review-detail-body' });
    const detailPanel = createElement(validated.document, 'section', {
      class: 'card review-panel review-detail-panel', 'data-review-panel': 'detail',
    }, createElement(validated.document, 'h2', null, '审阅工作区'), detailBody);
    const reviewShell = createElement(validated.document, 'div', { class: 'review-shell', 'data-review-shell': '' }, queuePanel, detailPanel);
    shell.append(reviewShell);
    root.replaceChildren(shell);
    const state = {
      document: validated.document,
      queuePanel,
      queueStatus,
      queueBody,
      detailPanel,
      detailBody,
      selectedId,
      loadQueue: null,
      loadDetail: null,
      queueRows: null,
      loadedDetail: null,
    };
    if (selectedId === null) renderDetailInstruction(state);

    let cleaned = false;
    let queueSequence = 0;
    let detailSequence = 0;
    let queueRecord = null;
    let detailRecord = null;
    const current = () => !cleaned && !signal.aborted && isCurrent();
    const detach = record => {
      if (!record) return;
      try { signal.removeEventListener('abort', record.onOuterAbort); } catch (_error) {}
      try { record.controller.abort(); } catch (_error) {}
    };
    const freshRecord = () => {
      const controller = validateAbortController(validated.createAbortController());
      const onOuterAbort = () => {
        try { controller.abort(); } catch (_error) {}
      };
      if (signal.aborted) onOuterAbort();
      else signal.addEventListener('abort', onOuterAbort);
      return { controller, onOuterAbort };
    };
    const ownsQueue = (record, sequence) => current() && queueSequence === sequence && queueRecord === record
      && !record.controller.signal.aborted;
    const ownsDetail = (record, sequence, conversationId) => current() && detailSequence === sequence
      && detailRecord === record && selectedId === conversationId && !record.controller.signal.aborted;
    const hasChildMismatch = (rows, loadedDetail) => {
      if (!Array.isArray(rows) || !loadedDetail || selectedId === null) return false;
      const queueRow = rows.find(row => row.id === selectedId);
      return Boolean(queueRow) && !isSameChildIdentity(queueRow.child, loadedDetail.child);
    };
    const invalidateDetailForChildMismatch = () => {
      detailSequence += 1;
      detach(detailRecord);
      detailRecord = null;
      state.loadedDetail = null;
      renderDetailError(state, selectedId);
    };
    const loadQueue = () => {
      detach(queueRecord);
      queueRecord = null;
      const sequence = ++queueSequence;
      if (!current()) return Promise.resolve();
      renderQueueLoading(state);
      let record;
      try {
        record = freshRecord();
        queueRecord = record;
      } catch (_error) {
        if (current() && queueSequence === sequence) renderQueueError(state);
        return Promise.resolve();
      }
      return Promise.resolve()
        .then(() => {
          if (!ownsQueue(record, sequence)) return undefined;
          return validated.request('/api/conversations?queue=pending', {
            signal: record.controller.signal,
            sequenceKey: 'teacher-review-queue',
          });
        })
        .then(rows => {
          if (!ownsQueue(record, sequence) || rows === undefined) return undefined;
          const validRows = validateQueueRows('pending', rows);
          if (!ownsQueue(record, sequence)) return undefined;
          state.queueRows = validRows;
          renderQueueRows(state, validRows);
          if (hasChildMismatch(validRows, state.loadedDetail) && ownsQueue(record, sequence)) {
            invalidateDetailForChildMismatch();
          }
          return undefined;
        })
        .catch(() => {
          if (ownsQueue(record, sequence)) renderQueueError(state);
          return undefined;
        });
    };
    const loadDetail = conversationId => {
      detach(detailRecord);
      detailRecord = null;
      const sequence = ++detailSequence;
      if (!current() || selectedId !== conversationId) return Promise.resolve();
      renderDetailLoading(state, conversationId);
      let record;
      try {
        record = freshRecord();
        detailRecord = record;
      } catch (_error) {
        if (current() && detailSequence === sequence) renderDetailError(state, conversationId);
        return Promise.resolve();
      }
      return Promise.resolve()
        .then(() => {
          if (!ownsDetail(record, sequence, conversationId)) return undefined;
          return validated.request(`/api/conversations/${conversationId}`, {
            signal: record.controller.signal,
            sequenceKey: 'teacher-review-detail',
          });
        })
        .then(result => {
          if (!ownsDetail(record, sequence, conversationId) || result === undefined) return undefined;
          const validDetail = validateReviewDetail(conversationId, result);
          if (!ownsDetail(record, sequence, conversationId)) return undefined;
          if (hasChildMismatch(state.queueRows, validDetail)) {
            invalidateDetailForChildMismatch();
            return undefined;
          }
          state.loadedDetail = validDetail;
          renderDetailLoaded(state, validDetail);
          return undefined;
        })
        .catch(() => {
          if (ownsDetail(record, sequence, conversationId)) renderDetailError(state, conversationId);
          return undefined;
        });
    };
    state.loadQueue = loadQueue;
    state.loadDetail = loadDetail;
    void loadQueue();
    if (selectedId !== null) void loadDetail(selectedId);
    return {
      cleanup() {
        if (cleaned) return;
        cleaned = true;
        queueSequence += 1;
        detailSequence += 1;
        detach(queueRecord);
        detach(detailRecord);
        queueRecord = null;
        detailRecord = null;
        state.loadedDetail = null;
      },
    };
  };
}
