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
const DEPENDENCY_KEYS = ['request', 'document', 'createAbortController', 'dirtyGuard'];
const DIRTY_GUARD_METHODS = ['activate', 'update', 'markClean', 'isDirty', 'confirmLeave', 'release'];
const ACKNOWLEDGEMENT_KEYS = ['saved', 'conversation_id', 'review_status', 'revision', 'saved_at', 'review'];
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
  let guard;
  try {
    if (typeof record.request !== 'function' || !record.document
        || typeof record.document.createElement !== 'function'
        || typeof record.createAbortController !== 'function' || !record.dirtyGuard) {
      throw invalidReviewContract();
    }
    guard = readOwnDataRecord(record.dirtyGuard, DIRTY_GUARD_METHODS);
    if (!DIRTY_GUARD_METHODS.every(name => typeof guard[name] === 'function')) throw invalidReviewContract();
    validateAbortController(record.createAbortController());
  } catch (_error) {
    throw invalidReviewContract();
  }
  return { ...record, dirtyGuard: guard };
}

export function validateReviewAcknowledgement(selectedId, submittedRevision, action, value) {
  try {
    if (!isPositiveInteger(selectedId) || !isNonnegativeInteger(submittedRevision)
        || !['save_draft', 'confirm'].includes(action)) throw invalidReviewContract();
    const acknowledgement = readOwnDataRecord(value, ACKNOWLEDGEMENT_KEYS);
    const expectedStatus = action === 'confirm' ? 'confirmed' : 'draft';
    if (acknowledgement.saved !== true || acknowledgement.conversation_id !== selectedId
        || acknowledgement.review_status !== expectedStatus
        || !isPositiveInteger(acknowledgement.revision) || acknowledgement.revision <= submittedRevision
        || !isParseableDate(acknowledgement.saved_at)) {
      throw invalidReviewContract();
    }
    const review = validateReviewDocument(acknowledgement.review);
    return { ...acknowledgement, review };
  } catch (_error) {
    throw invalidReviewContract();
  }
}

export function applyReviewAcknowledgement(currentDetail, acknowledgement) {
  try {
    const rawDetail = readOwnDataRecord(currentDetail, DETAIL_KEYS);
    const detail = validateReviewDetail(rawDetail.id, currentDetail);
    const action = acknowledgement && acknowledgement.review_status === 'confirmed' ? 'confirm' : 'save_draft';
    const saved = validateReviewAcknowledgement(detail.id, detail.revision, action, acknowledgement);
    return {
      ...detail,
      revision: saved.revision,
      review_status: saved.review_status,
      review: saved.review,
    };
  } catch (_error) {
    throw invalidReviewContract();
  }
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

function reviewStatusLabel(status) {
  return {
    pending: '待审阅',
    draft: '草稿',
    confirmed: '已确认',
    unavailable: '暂不可用',
  }[status];
}

function reviewRevisionLabel(detail) {
  return `${reviewStatusLabel(detail.review_status)} · 第 ${detail.revision} 版`;
}

function formatOverallScore(value) {
  return String(value);
}

function queueRow(state, row) {
  const name = displayName(row.child);
  const selected = row.id === state.selectedId;
  const link = createElement(state.document, 'a', {
    class: 'review-queue-link', href: `#review?conversation_id=${row.id}`,
    'aria-label': `审阅${name}的会话 #${row.id}`,
  }, name);
  if (selected) link.setAttribute('aria-current', 'page');
  const badges = createElement(state.document, 'div', { class: 'review-row-badges' });
  if (selected) {
    badges.append(createElement(state.document, 'span', { class: 'review-row-current' }, '当前'));
  }
  badges.append(createElement(state.document, 'span', {
    class: `review-row-status review-row-status-${row.review_status}`,
  }, reviewStatusLabel(row.review_status)));
  const heading = createElement(state.document, 'div', { class: 'review-row-heading' }, link, badges);
  const metadata = createElement(state.document, 'p', { class: 'review-row-metadata muted' },
    `完成于 ${formatCompletedTime(row.completed_at)} · 会话 #${row.id} · ${row.round} 轮`);
  return createElement(state.document, 'article', {
    class: `review-queue-row${selected ? ' is-current' : ''}`,
  }, heading, metadata);
}

function renderQueueLoading(state) {
  state.queuePanel.setAttribute('aria-busy', 'true');
  state.queueHeading.replaceChildren('待审阅队列');
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
  state.queueHeading.replaceChildren(`待审阅队列（${rows.length}）`);
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
    if (state.selectedId !== null) void state.reloadDetail?.();
  });
  return button;
}

function renderDetailInstruction(state) {
  releaseEditor(state);
  state.detailPanel.removeAttribute('aria-busy');
  state.detailBody.replaceChildren(createElement(state.document, 'p', { class: 'muted' }, '请从左侧待审阅队列选择一条会话。'));
}

function renderDetailLoading(state, selectedId) {
  releaseEditor(state);
  state.detailPanel.setAttribute('aria-busy', 'true');
  state.detailBody.replaceChildren(createElement(state.document, 'p', {
    class: 'review-detail-status muted', role: 'status', 'aria-live': 'polite',
  }, `正在加载会话 #${selectedId}…`), detailReloadButton(state));
}

function renderDetailError(state, selectedId) {
  releaseEditor(state);
  state.detailPanel.removeAttribute('aria-busy');
  state.detailBody.replaceChildren(
    createElement(state.document, 'p', { class: 'review-detail-error', role: 'alert' }, '加载失败，请重试。'),
    detailReloadButton(state),
  );
  void selectedId;
}

function transcriptView(state, messages) {
  const transcript = createElement(state.document, 'section', { class: 'review-transcript review-section-card' },
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
  const results = createElement(state.document, 'section', { class: 'review-results review-section-card' },
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

function overallCardView(state, overall) {
  const score = createElement(state.document, 'div', { class: 'review-overall-score' },
    createElement(state.document, 'p', { class: 'review-overall-value' },
      `综合评分：${formatOverallScore(overall)}`),
    createElement(state.document, 'span', { class: 'review-overall-scale', 'aria-hidden': 'true' }, '/ 5'));
  return createElement(state.document, 'section', {
    class: 'review-overall-card review-section-card',
  }, createElement(state.document, 'h3', null, '综合评分（只读）'), score);
}

function makeControl(document, tag, attrs, value) {
  const control = createElement(document, tag, attrs);
  if (value !== undefined) control.value = String(value);
  return control;
}

function makeField(state, labelText, control, errorKey) {
  const field = createElement(state.document, 'div', { class: 'review-form-field' });
  const controlId = `review-${errorKey.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
  const errorId = `${controlId}-error`;
  control.setAttribute('id', controlId);
  control.setAttribute('aria-describedby', errorId);
  const label = createElement(state.document, 'label', { for: controlId }, labelText);
  const error = createElement(state.document, 'p', {
    id: errorId, class: 'review-field-error', role: 'alert', 'data-review-error': errorKey,
  });
  field.append(label, control, error);
  state.formState.errorNodes.set(errorKey, { control, error });
  return field;
}

function selectedScore(controls) {
  const selected = controls.radios.find(radio => radio.checked);
  return selected ? Number(selected.value) : null;
}

function editableReviewDocument(formState) {
  return {
    feeding_logs: formState.feeding.map(row => ({
      id: row.id,
      category: row.category.value,
      content: String(row.content.value || '').trim(),
      duck_id: row.duck_id,
    })),
    emotion: {
      emotion: String(formState.emotion.emotion.value || '').trim(),
      intensity: Number(formState.emotion.intensity.value),
      note: String(formState.emotion.note.value || '').trim() || null,
    },
    insight: String(formState.insight.value || '').trim(),
    scores: formState.scores.map(row => ({
      dimension_id: row.dimension_id,
      score: selectedScore(row),
      reason: String(row.reason.value || '').trim(),
    })),
  };
}

function canonicalEditableSnapshot(formState) {
  return JSON.stringify(editableReviewDocument(formState));
}

function setSaveStatus(formState, saveState, copy) {
  if (formState.saveState === saveState && formState.saveCopy === copy) return false;
  formState.saveState = saveState;
  formState.saveCopy = copy;
  formState.status.setAttribute('data-save-state', saveState);
  formState.status.replaceChildren(copy);
  return true;
}

function syncSaveStatus(formState, snapshot = canonicalEditableSnapshot(formState)) {
  const dirty = snapshot !== formState.cleanSnapshot;
  setSaveStatus(
    formState,
    dirty ? 'dirty' : 'clean',
    dirty ? '有未保存的修改' : '全部修改已保存',
  );
  return dirty;
}

function synchronizeEditableSnapshot(state, formState) {
  const snapshot = canonicalEditableSnapshot(formState);
  try { state.dirtyGuard.update(snapshot); } catch (_error) {}
  return { snapshot, dirty: syncSaveStatus(formState, snapshot) };
}

function saveFailureStatusCopy(action, dirty) {
  if (dirty) return '保存失败，修改仍未保存';
  return action === 'confirm' ? '确认失败，请稍后重试' : '保存失败，请稍后重试';
}

function setSaveFailureStatus(formState, action, dirty) {
  setSaveStatus(formState, 'failure', saveFailureStatusCopy(action, dirty));
}

function clearFormErrors(formState) {
  formState.summary.replaceChildren();
  for (const { control, error } of formState.errorNodes.values()) {
    control.removeAttribute('aria-invalid');
    error.replaceChildren();
  }
}

function showFormErrors(formState, errors, summaryCopy = '请检查表单内容。') {
  clearFormErrors(formState);
  formState.summary.replaceChildren(summaryCopy);
  let first = null;
  for (const { key, copy } of errors) {
    const target = formState.errorNodes.get(key);
    if (!target) continue;
    target.control.setAttribute('aria-invalid', 'true');
    target.error.replaceChildren(copy);
    if (!first) first = target.control;
  }
  first?.focus?.();
}

function validateEditableReview(formState, action) {
  const document = editableReviewDocument(formState);
  const errors = [];
  for (const [index, row] of document.feeding_logs.entries()) {
    if (!FEEDING_CATEGORIES.has(row.category)) errors.push({ key: `feeding.${index}.category`, copy: '请选择有效分类。' });
    if (!row.content) errors.push({ key: `feeding.${index}.content`, copy: '请填写饲养记录。' });
  }
  if (!document.emotion.emotion) errors.push({ key: 'emotion.emotion', copy: '请填写情绪。' });
  if (!Number.isInteger(document.emotion.intensity) || document.emotion.intensity < 1 || document.emotion.intensity > 5) {
    errors.push({ key: 'emotion.intensity', copy: '请输入 1 至 5 的整数。' });
  }
  if (!document.insight) errors.push({ key: 'insight', copy: '请填写教育洞察。' });
  for (const [index, row] of document.scores.entries()) {
    if (!Number.isInteger(row.score) || row.score < 1 || row.score > 5) {
      errors.push({ key: `scores.${index}.score`, copy: '请选择 1 至 5 分。' });
    }
    if (action === 'confirm' && !row.reason) {
      errors.push({ key: `scores.${index}.reason`, copy: '请填写评分理由。' });
    }
  }
  return { document, errors };
}

function setFormDisabled(formState, disabled) {
  for (const row of formState.feeding) {
    row.category.disabled = disabled;
    row.content.disabled = disabled;
  }
  formState.emotion.emotion.disabled = disabled;
  formState.emotion.intensity.disabled = disabled;
  formState.emotion.note.disabled = disabled;
  formState.insight.disabled = disabled;
  for (const row of formState.scores) {
    row.reason.disabled = disabled;
    for (const radio of row.radios) radio.disabled = disabled;
  }
  for (const button of formState.actions) button.disabled = disabled;
}

function safeErrorProjection(error) {
  try {
    if (error === null || typeof error !== 'object' || Array.isArray(error)) return null;
    const descriptors = Object.getOwnPropertyDescriptors(error);
    for (const name of ['status', 'code']) {
      const descriptor = descriptors[name];
      if (!descriptor || !Object.prototype.hasOwnProperty.call(descriptor, 'value')) return null;
    }
    if (!Number.isInteger(descriptors.status.value) || typeof descriptors.code.value !== 'string') return null;
    const fieldDescriptor = descriptors.fieldErrors;
    if (!fieldDescriptor || !Object.prototype.hasOwnProperty.call(fieldDescriptor, 'value')) return null;
    return {
      status: descriptors.status.value,
      code: descriptors.code.value,
      fieldErrors: fieldDescriptor.value,
    };
  } catch (_error) {
    return null;
  }
}

function projectFieldErrors(formState, value) {
  try {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) return null;
    const descriptors = Object.getOwnPropertyDescriptors(value);
    const fields = [];
    let summary = false;
    for (const key of Reflect.ownKeys(descriptors)) {
      if (typeof key !== 'string') return null;
      const descriptor = descriptors[key];
      if (!Object.prototype.hasOwnProperty.call(descriptor, 'value') || !Array.isArray(descriptor.value)) return null;
      let path = key;
      if (path.startsWith('body.')) path = path.slice('body.'.length);
      if (path.startsWith('body.')) return null;
      if (path === 'feeding_logs' || path === 'emotion' || path === 'scores') {
        summary = true;
        continue;
      }
      const feeding = /^feeding_logs\.(0|[1-9]\d*)\.(category|content)$/.exec(path);
      if (feeding) {
        const index = Number(feeding[1]);
        if (index >= formState.feeding.length) return null;
        fields.push({ key: `feeding.${index}.${feeding[2]}`, copy: '请检查此项。' });
        continue;
      }
      if (['emotion.emotion', 'emotion.intensity', 'emotion.note'].includes(path)) {
        fields.push({ key: path, copy: '请检查此项。' });
        continue;
      }
      if (path === 'insight') {
        fields.push({ key: 'insight', copy: '请检查此项。' });
        continue;
      }
      const score = /^scores\.(0|[1-9]\d*)\.(score|reason)$/.exec(path);
      if (score) {
        const index = Number(score[1]);
        if (index >= formState.scores.length) return null;
        fields.push({ key: `scores.${index}.${score[2]}`, copy: '请检查此项。' });
        continue;
      }
      return null;
    }
    return { fields, summary };
  } catch (_error) {
    return null;
  }
}

function classifySaveError(error, formState) {
  const projection = safeErrorProjection(error);
  if (!projection) return { copy: '保存失败，请稍后重试。', fields: [] };
  if (projection.status === 409 && projection.code === 'REVIEW_REVISION_CONFLICT') {
    return { copy: '该审阅已在别处更新，请复制当前修改后重新加载。', fields: [] };
  }
  if (projection.status === 422 && ['REVIEW_VALIDATION_FAILED', 'VALIDATION_ERROR'].includes(projection.code)) {
    const mapped = projectFieldErrors(formState, projection.fieldErrors);
    if (!mapped) return { copy: '部分内容未通过校验，请检查后重试。', fields: [] };
    return { copy: '部分内容未通过校验，请检查后重试。', fields: mapped.fields };
  }
  if (projection.status === 401 && projection.code === 'TEACHER_AUTH_REQUIRED') {
    return { copy: '教师会话已失效，请先重新解锁。', fields: [] };
  }
  if (projection.status === 404 && projection.code === 'CONVERSATION_NOT_FOUND') {
    return { copy: '该会话已不可审阅，请重新加载队列。', fields: [] };
  }
  return { copy: '保存失败，请稍后重试。', fields: [] };
}

function releaseEditor(state) {
  state.formState = null;
  try { state.dirtyGuard.release(); } catch (_error) {}
}

function editorView(state, detail) {
  const form = createElement(state.document, 'form', { class: 'review-editor', 'data-review-form': '' });
  const content = createElement(state.document, 'div', { class: 'review-editor-content' });
  const formState = {
    form,
    detail,
    feeding: [],
    emotion: {},
    insight: null,
    scores: [],
    actions: [],
    errorNodes: new Map(),
    summary: createElement(state.document, 'p', { class: 'review-form-summary', role: 'alert' }),
    status: createElement(state.document, 'p', {
      class: 'review-save-status', role: 'status', 'aria-live': 'polite',
      'aria-atomic': 'true', 'data-save-state': 'clean',
    }),
    cleanSnapshot: null,
    saveState: 'clean',
    saveCopy: null,
  };
  state.formState = formState;
  content.append(createElement(state.document, 'h2', null, '结构化结果'), formState.summary);
  const feedingSection = createElement(state.document, 'section', {
    class: 'review-editor-section review-section-card review-feeding-card',
  },
    createElement(state.document, 'h3', null, '饲养记录'));
  for (const [index, row] of detail.review.feeding_logs.entries()) {
    const category = makeControl(state.document, 'select', null, row.category);
    for (const value of ['喂食', '清洁', '观察', '其它']) {
      const option = createElement(state.document, 'option', { value }, value);
      option.selected = value === row.category;
      category.append(option);
    }
    const content = makeControl(state.document, 'textarea', null, row.content);
    const item = { id: row.id, duck_id: row.duck_id, category, content };
    formState.feeding.push(item);
    const group = createElement(state.document, 'div', { class: 'review-feeding-editor' });
    group.append(
      makeField(state, `饲养记录 ${index + 1} 分类`, category, `feeding.${index}.category`),
      makeField(state, `饲养记录 ${index + 1} 内容`, content, `feeding.${index}.content`),
    );
    feedingSection.append(group);
  }
  const emotionSection = createElement(state.document, 'section', {
    class: 'review-editor-section review-section-card review-emotion-card',
  }, createElement(state.document, 'h3', null, '情绪判断'));
  const insightSection = createElement(state.document, 'section', {
    class: 'review-editor-section review-section-card review-insight-card',
  }, createElement(state.document, 'h3', null, '教育洞察'));
  formState.emotion.emotion = makeControl(state.document, 'input', { type: 'text' }, detail.review.emotion.emotion);
  formState.emotion.intensity = makeControl(state.document, 'input', { type: 'number', min: '1', max: '5' }, detail.review.emotion.intensity);
  formState.emotion.note = makeControl(state.document, 'textarea', null, detail.review.emotion.note || '');
  formState.insight = makeControl(state.document, 'textarea', null, detail.review.insight);
  emotionSection.append(
    makeField(state, '情绪', formState.emotion.emotion, 'emotion.emotion'),
    makeField(state, '情绪强度', formState.emotion.intensity, 'emotion.intensity'),
    makeField(state, '情绪备注', formState.emotion.note, 'emotion.note'),
  );
  insightSection.append(makeField(state, '教育洞察', formState.insight, 'insight'));
  const scoresSection = createElement(state.document, 'section', {
    class: 'review-editor-section review-section-card review-scores-card',
  }, createElement(state.document, 'h3', null, '能力评分'));
  for (const [index, score] of detail.review.scores.entries()) {
    const fieldset = createElement(state.document, 'fieldset', { class: 'review-score-editor', 'data-dimension-id': String(score.dimension_id) });
    fieldset.append(createElement(state.document, 'legend', null, score.dimension_name));
    const row = { dimension_id: score.dimension_id, radios: [], reason: null };
    const radios = createElement(state.document, 'div', { class: 'review-score-radios' });
    for (let value = 1; value <= 5; value += 1) {
      const radioId = `review-score-${score.dimension_id}-${value}`;
      const radio = makeControl(state.document, 'input', {
        id: radioId, type: 'radio', name: `review-score-${score.dimension_id}`, value: String(value),
        'aria-label': `${score.dimension_name} ${value} 分`,
      }, value);
      radio.checked = score.score === value;
      const label = createElement(state.document, 'label', { for: radioId }, `${value} 分`);
      radios.append(radio, label);
      row.radios.push(radio);
    }
    row.reason = makeControl(state.document, 'textarea', {
      'aria-label': `${score.dimension_name}评分理由`,
    }, score.reason);
    formState.scores.push(row);
    fieldset.append(radios, makeField(state, '评分理由', row.reason, `scores.${index}.reason`));
    const scoreErrorId = `review-scores-${index}-score-error`;
    const scoreError = createElement(state.document, 'p', { id: scoreErrorId, class: 'review-field-error', role: 'alert', 'data-review-error': `scores.${index}.score` });
    for (const radio of row.radios) radio.setAttribute('aria-describedby', scoreErrorId);
    formState.errorNodes.set(`scores.${index}.score`, { control: row.radios[0], error: scoreError });
    fieldset.append(scoreError);
    scoresSection.append(fieldset);
  }
  content.append(
    insightSection,
    emotionSection,
    scoresSection,
    feedingSection,
    overallCardView(state, detail.review.overall),
  );
  const actions = createElement(state.document, 'div', { class: 'review-actions' });
  const draft = createElement(state.document, 'button', { class: 'btn review-save-draft', type: 'button' }, '保存草稿');
  const confirm = createElement(state.document, 'button', { class: 'btn green review-save-confirm', type: 'button' }, '保存并确认');
  formState.actions.push(draft, confirm);
  draft.addEventListener('click', () => { void state.submitReview?.(formState, 'save_draft'); });
  confirm.addEventListener('click', () => { void state.submitReview?.(formState, 'confirm'); });
  actions.append(formState.status, draft, confirm);
  form.append(content, actions);
  const updateDirty = () => {
    if (state.formState !== formState) return;
    synchronizeEditableSnapshot(state, formState);
  };
  form.addEventListener('input', updateDirty);
  form.addEventListener('change', updateDirty);
  const snapshot = canonicalEditableSnapshot(formState);
  formState.cleanSnapshot = snapshot;
  syncSaveStatus(formState);
  try {
    state.dirtyGuard.activate(snapshot);
    state.dirtyGuard.markClean(snapshot);
  } catch (_error) {}
  return form;
}

function renderDetailLoaded(state, detail, successCopy = null, retainedStatus = null) {
  releaseEditor(state);
  state.detailPanel.removeAttribute('aria-busy');
  const name = displayName(detail.child);
  const titleRow = createElement(state.document, 'div', { class: 'review-detail-title-row' },
    createElement(state.document, 'h2', null, name),
    createElement(state.document, 'div', { class: 'review-detail-badges' },
      createElement(state.document, 'span', {
        class: `review-detail-badge review-status-${detail.review_status}`,
      }, reviewRevisionLabel(detail)),
      createElement(state.document, 'span', {
        class: `review-detail-badge review-analysis-status review-analysis-status-${detail.analysis.status}`,
      }, analysisStatusLabel(detail.analysis.status))));
  const header = createElement(state.document, 'header', { class: 'review-detail-header' },
    titleRow,
    createElement(state.document, 'div', { class: 'review-detail-facts muted' },
      createElement(state.document, 'span', null, `会话 #${detail.id}`),
      createElement(state.document, 'span', null, detail.date),
      createElement(state.document, 'span', null, `完成于 ${formatCompletedTime(detail.completed_at)}`),
      createElement(state.document, 'span', null, `${detail.round} 轮`)),
    detailReloadButton(state));
  const workspace = createElement(state.document, 'div', { class: 'review-workspace' },
    transcriptView(state, detail.messages), detail.review === null
      ? unavailableResultsView(state, detail.analysis.status)
      : editorView(state, detail));
  const replacementStatus = state.formState?.status || null;
  if (retainedStatus && replacementStatus) state.detailPanel.append(retainedStatus);
  state.detailBody.replaceChildren(header, workspace);
  if (retainedStatus && replacementStatus) {
    replacementStatus.replaceWith(retainedStatus);
    state.formState.status = retainedStatus;
  }
  if (successCopy && state.formState) setSaveStatus(state.formState, 'saved', successCopy);
}

export function createReviewRoute(dependencies) {
  const validated = validateDependencies(dependencies);
  return function reviewRoute({ root, params, signal, isCurrent }) {
    if (!isCurrent() || signal.aborted) return undefined;
    const selectedId = parseReviewConversationId(params);
    const shell = createElement(validated.document, 'div', { class: 'view active review-view' },
      createElement(validated.document, 'h1', null, '日记审阅'));
    const queueStatus = createElement(validated.document, 'p', {
      class: 'review-queue-status muted', role: 'status', 'aria-live': 'polite',
    }, '正在加载待审阅队列…');
    const queueBody = createElement(validated.document, 'div', { class: 'review-queue-body' });
    const queueHeading = createElement(validated.document, 'h2', { class: 'review-queue-heading' }, '待审阅队列');
    const queuePanel = createElement(validated.document, 'section', {
      class: 'card review-panel review-queue-panel', 'data-review-panel': 'queue', 'aria-busy': 'true',
    }, queueHeading, queueStatus, queueBody);
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
      queueHeading,
      queueStatus,
      queueBody,
      detailPanel,
      detailBody,
      selectedId,
      dirtyGuard: validated.dirtyGuard,
      loadQueue: null,
      loadDetail: null,
      reloadDetail: null,
      submitReview: null,
      queueRows: null,
      loadedDetail: null,
      formState: null,
    };
    if (selectedId === null) renderDetailInstruction(state);

    let cleaned = false;
    let queueSequence = 0;
    let detailSequence = 0;
    let queueRecord = null;
    let detailRecord = null;
    let mutationSequence = 0;
    let mutationRecord = null;
    let saveInFlight = false;
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
    const detachMutation = (record, abort = true) => {
      if (!record) return;
      try { signal.removeEventListener('abort', record.onOuterAbort); } catch (_error) {}
      if (abort) {
        try { record.controller.abort(); } catch (_error) {}
      }
    };
    const freshMutationRecord = () => {
      const controller = validateAbortController(validated.createAbortController());
      const onOuterAbort = () => {
        try { controller.abort(); } catch (_error) {}
      };
      if (signal.aborted) onOuterAbort();
      else signal.addEventListener('abort', onOuterAbort);
      return { controller, onOuterAbort };
    };
    const invalidateMutation = () => {
      mutationSequence += 1;
      detachMutation(mutationRecord);
      mutationRecord = null;
      saveInFlight = false;
    };
    const ownsQueue = (record, sequence) => current() && queueSequence === sequence && queueRecord === record
      && !record.controller.signal.aborted;
    const ownsDetail = (record, sequence, conversationId) => current() && detailSequence === sequence
      && detailRecord === record && selectedId === conversationId && !record.controller.signal.aborted;
    const ownsMutation = (record, sequence, formState, conversationId, revision) => current()
      && mutationSequence === sequence && mutationRecord === record && state.formState === formState
      && selectedId === conversationId && state.loadedDetail?.revision === revision
      && !record.controller.signal.aborted;
    const hasChildMismatch = (rows, loadedDetail) => {
      if (!Array.isArray(rows) || !loadedDetail || selectedId === null) return false;
      const queueRow = rows.find(row => row.id === selectedId);
      return Boolean(queueRow) && !isSameChildIdentity(queueRow.child, loadedDetail.child);
    };
    const invalidateDetailForChildMismatch = () => {
      detailSequence += 1;
      detach(detailRecord);
      detailRecord = null;
      invalidateMutation();
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
    const submitReview = (formState, action) => {
      if (!current() || saveInFlight || state.formState !== formState || !state.loadedDetail
          || selectedId === null || state.loadedDetail.id !== selectedId) return Promise.resolve();
      const submittedSnapshot = synchronizeEditableSnapshot(state, formState);
      clearFormErrors(formState);
      const validatedForm = validateEditableReview(formState, action);
      if (validatedForm.errors.length) {
        showFormErrors(formState, validatedForm.errors);
        return Promise.resolve();
      }
      const detailId = state.loadedDetail.id;
      const submittedRevision = state.loadedDetail.revision;
      const payload = {
        revision: submittedRevision,
        feeding_logs: validatedForm.document.feeding_logs,
        emotion: validatedForm.document.emotion,
        insight: validatedForm.document.insight,
        scores: validatedForm.document.scores,
        action,
      };
      const sequence = ++mutationSequence;
      let record;
      try {
        record = freshMutationRecord();
        mutationRecord = record;
      } catch (_error) {
        showFormErrors(formState, [], '保存失败，请稍后重试。');
        setSaveFailureStatus(formState, action, submittedSnapshot.dirty);
        return Promise.resolve();
      }
      saveInFlight = true;
      setFormDisabled(formState, true);
      setSaveStatus(formState, 'saving', '正在保存…');
      return Promise.resolve()
        .then(() => {
          if (!ownsMutation(record, sequence, formState, detailId, submittedRevision)) return undefined;
          return validated.request(`/api/conversations/${detailId}/review`, {
            method: 'PUT',
            body: payload,
            signal: record.controller.signal,
            timeoutMs: 15000,
            sequenceKey: 'teacher-review-mutation',
          });
        })
        .then(result => {
          if (!ownsMutation(record, sequence, formState, detailId, submittedRevision)) return undefined;
          const acknowledgement = validateReviewAcknowledgement(detailId, submittedRevision, action, result);
          const nextDetail = applyReviewAcknowledgement(state.loadedDetail, acknowledgement);
          if (!ownsMutation(record, sequence, formState, detailId, submittedRevision)) return undefined;
          detachMutation(record, false);
          mutationRecord = null;
          saveInFlight = false;
          state.loadedDetail = nextDetail;
          renderDetailLoaded(
            state,
            nextDetail,
            action === 'confirm' ? '审阅已确认' : '全部修改已保存',
            formState.status,
          );
          const actionIndex = action === 'confirm' ? 1 : 0;
          state.formState?.actions[actionIndex]?.focus?.();
          void loadQueue();
          return undefined;
        })
        .catch(error => {
          if (!ownsMutation(record, sequence, formState, detailId, submittedRevision)) return undefined;
          saveInFlight = false;
          mutationRecord = null;
          detachMutation(record, false);
          setFormDisabled(formState, false);
          const failure = classifySaveError(error, formState);
          showFormErrors(formState, failure.fields, failure.copy);
          setSaveFailureStatus(formState, action, submittedSnapshot.dirty);
          if (!failure.fields.length) {
            const actionIndex = action === 'confirm' ? 1 : 0;
            formState.actions[actionIndex]?.focus?.();
          }
          return undefined;
        });
    };
    const loadDetail = conversationId => {
      detach(detailRecord);
      detailRecord = null;
      invalidateMutation();
      state.loadedDetail = null;
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
    state.submitReview = submitReview;
    state.reloadDetail = async () => {
      const conversationId = selectedId;
      if (conversationId === null || !current()) return false;
      let allowed = false;
      try { allowed = await state.dirtyGuard.confirmLeave(); } catch (_error) {}
      if (!allowed || !current() || selectedId !== conversationId) return false;
      invalidateMutation();
      releaseEditor(state);
      await loadDetail(conversationId);
      return true;
    };
    void loadQueue();
    if (selectedId !== null) void loadDetail(selectedId);
    return {
      cleanup() {
        if (cleaned) return;
        cleaned = true;
        queueSequence += 1;
        detailSequence += 1;
        invalidateMutation();
        detach(queueRecord);
        detach(detailRecord);
        queueRecord = null;
        detailRecord = null;
        state.loadedDetail = null;
        releaseEditor(state);
      },
    };
  };
}
