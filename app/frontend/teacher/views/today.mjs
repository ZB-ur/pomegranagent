const ROSTER_KEYS = ['id', 'name', 'nickname', 'avatar'];
const QUEUE_KEYS = [
  'id', 'child', 'date', 'started_at', 'completed_at', 'message_count', 'round',
  'status', 'end_reason', 'analysis_status', 'review_status', 'revision',
];
const RETRY_KEYS = [
  'conversation_id', 'analysis_job_id', 'analysis_status', 'attempt_count', 'retry_accepted', 'replayed',
];
const END_REASONS = new Set(['max_rounds', 'complete', 'manual']);
const ANALYSIS_STATUSES = new Set(['pending', 'processing', 'succeeded', 'failed']);
const REVIEW_STATUSES = new Set(['pending', 'draft', 'confirmed', 'unavailable']);
const DEFAULT_NOW = () => new Date();

function invalidTodayContract() {
  return new TypeError('Today workbench contract is invalid.');
}

function readOwnDataRecord(value, keys) {
  try {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) throw invalidTodayContract();
    const descriptors = Object.getOwnPropertyDescriptors(value);
    const actualKeys = Reflect.ownKeys(descriptors);
    if (actualKeys.length !== keys.length || !keys.every(key => actualKeys.includes(key))) throw invalidTodayContract();
    const result = {};
    for (const key of keys) {
      const descriptor = descriptors[key];
      if (!descriptor || !Object.prototype.hasOwnProperty.call(descriptor, 'value')) throw invalidTodayContract();
      result[key] = descriptor.value;
    }
    return result;
  } catch (_error) {
    throw invalidTodayContract();
  }
}

function isPositiveInteger(value) {
  return Number.isInteger(value) && value > 0;
}

function isNonnegativeInteger(value) {
  return Number.isInteger(value) && value >= 0;
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

function validateRosterRecord(value) {
  const row = readOwnDataRecord(value, ROSTER_KEYS);
  if (!isPositiveInteger(row.id) || !isNonblankString(row.name)
      || !isNullableString(row.nickname) || !isNullableString(row.avatar)) {
    throw invalidTodayContract();
  }
  return row;
}

function validateQueueRecord(queue, value) {
  const row = readOwnDataRecord(value, QUEUE_KEYS);
  const child = validateRosterRecord(row.child);
  if (!isPositiveInteger(row.id) || !isParseableDate(row.date)
      || !isParseableDate(row.started_at) || !isParseableDate(row.completed_at)
      || !isPositiveInteger(row.message_count) || !isNonnegativeInteger(row.round)
      || row.status !== 'ended' || !END_REASONS.has(row.end_reason)
      || !ANALYSIS_STATUSES.has(row.analysis_status) || !REVIEW_STATUSES.has(row.review_status)
      || !isNonnegativeInteger(row.revision)) {
    throw invalidTodayContract();
  }
  const queueValid = (queue === 'pending' && row.analysis_status === 'succeeded'
      && (row.review_status === 'pending' || row.review_status === 'draft'))
    || (queue === 'processing' && (row.analysis_status === 'pending' || row.analysis_status === 'processing')
      && row.review_status === 'unavailable')
    || (queue === 'failed' && row.analysis_status === 'failed' && row.review_status === 'unavailable');
  if (!queueValid) throw invalidTodayContract();
  return { ...row, child };
}

function validateRetryRecord(conversationId, value) {
  const response = readOwnDataRecord(value, RETRY_KEYS);
  const validPair = (response.retry_accepted === true && response.replayed === false)
    || (response.retry_accepted === false && response.replayed === true);
  if (!isPositiveInteger(conversationId) || response.conversation_id !== conversationId
      || !isPositiveInteger(response.analysis_job_id) || response.analysis_status !== 'pending'
      || !isNonnegativeInteger(response.attempt_count)
      || typeof response.retry_accepted !== 'boolean' || typeof response.replayed !== 'boolean'
      || !validPair) {
    throw invalidTodayContract();
  }
  return response;
}

function validateDependencies(dependencies) {
  let record;
  try {
    if (dependencies === null || typeof dependencies !== 'object' || Array.isArray(dependencies)) {
      throw invalidTodayContract();
    }
    const descriptors = Object.getOwnPropertyDescriptors(dependencies);
    const keys = Reflect.ownKeys(descriptors);
    const requiredKeys = Object.prototype.hasOwnProperty.call(descriptors, 'now')
      ? ['request', 'document', 'now']
      : ['request', 'document'];
    if (keys.length !== requiredKeys.length || !requiredKeys.every(key => keys.includes(key))) {
      throw invalidTodayContract();
    }
    record = {};
    for (const key of requiredKeys) {
      const descriptor = descriptors[key];
      if (!descriptor || !Object.prototype.hasOwnProperty.call(descriptor, 'value')) throw invalidTodayContract();
      record[key] = descriptor.value;
    }
    if (typeof record.request !== 'function' || !record.document || typeof record.document.createElement !== 'function'
        || (record.now !== undefined && typeof record.now !== 'function')) {
      throw invalidTodayContract();
    }
  } catch (_error) {
    throw invalidTodayContract();
  }
  return { request: record.request, document: record.document, now: record.now || DEFAULT_NOW };
}

export function displayName(child) {
  const row = validateRosterRecord(child);
  return row.nickname && row.nickname.trim() ? row.nickname : row.name;
}

export function queueStatusLabel(queue) {
  if (queue === 'pending') return '待审阅';
  if (queue === 'processing') return '分析中';
  if (queue === 'failed') return '分析失败';
  throw invalidTodayContract();
}

export function validateRosterRows(rows) {
  try {
    if (!Array.isArray(rows)) throw invalidTodayContract();
    return rows.map(validateRosterRecord);
  } catch (_error) {
    throw invalidTodayContract();
  }
}

export function validateQueueRows(queue, rows) {
  try {
    if (!['pending', 'processing', 'failed'].includes(queue) || !Array.isArray(rows)) throw invalidTodayContract();
    return rows.map(row => validateQueueRecord(queue, row));
  } catch (_error) {
    throw invalidTodayContract();
  }
}

export function validateRetryResponse(conversationId, response) {
  try {
    return validateRetryRecord(conversationId, response);
  } catch (_error) {
    throw invalidTodayContract();
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

function localDateLabel(now) {
  try {
    const value = now();
    if (!(value instanceof Date) || !Number.isFinite(value.getTime())) throw invalidTodayContract();
    return new Intl.DateTimeFormat('zh-CN', {
      year: 'numeric', month: 'long', day: 'numeric', weekday: 'long',
    }).format(value);
  } catch (_error) {
    throw invalidTodayContract();
  }
}

function createPanel(document, key, title, subtitle, loadingCopy, tone) {
  const status = createElement(document, 'p', {
    class: 'today-panel-status today-status-badge muted', role: 'status', 'aria-live': 'polite',
  }, loadingCopy);
  const body = createElement(document, 'div', { class: 'today-panel-body' });
  const heading = createElement(document, 'div', { class: 'today-panel-heading' },
    createElement(document, 'h2', null, title),
    createElement(document, 'p', { class: 'today-panel-subtitle muted' }, subtitle));
  const header = createElement(document, 'header', { class: 'today-panel-header' }, heading, status);
  const panel = createElement(document, 'section', {
    class: 'card today-panel', 'data-today-panel': key, 'data-tone': tone,
    'data-state': 'loading', 'aria-busy': 'true',
  }, header, body);
  return { panel, status, body };
}

const PANEL_SPECS = Object.freeze({
  roster: Object.freeze({
    path: '/api/roster/today', loading: '正在加载今日排班…', empty: '今天还未排班', reload: '重新加载今日值日生',
    validate: validateRosterRows,
  }),
  pending: Object.freeze({
    path: '/api/conversations?queue=pending', loading: '正在加载待审阅会话…', empty: '暂无待审阅会话', reload: '重新加载待审阅',
    validate: rows => validateQueueRows('pending', rows),
  }),
  processing: Object.freeze({
    path: '/api/conversations?queue=processing', loading: '正在加载分析中会话…', empty: '暂无分析中的会话', reload: '重新加载分析中',
    validate: rows => validateQueueRows('processing', rows),
  }),
  failed: Object.freeze({
    path: '/api/conversations?queue=failed', loading: '正在加载分析失败会话…', empty: '暂无分析失败会话', reload: '重新加载分析失败',
    validate: rows => validateQueueRows('failed', rows),
  }),
});

function setPanelLoading(state, key) {
  const spec = PANEL_SPECS[key];
  state.panels[key].panel.setAttribute('data-state', 'loading');
  state.panels[key].panel.setAttribute('aria-busy', 'true');
  state.panels[key].status.replaceChildren(spec.loading);
  state.panels[key].body.replaceChildren();
}

function setPanelEmpty(state, key) {
  const spec = PANEL_SPECS[key];
  const panel = state.panels[key];
  panel.panel.setAttribute('data-state', 'empty');
  panel.panel.removeAttribute('aria-busy');
  panel.status.replaceChildren(spec.empty);
  panel.body.replaceChildren();
  if (key === 'roster') {
    const link = createElement(state.document, 'a', {
      class: 'today-panel-link', href: '#roster',
    }, '前往值日排班');
    panel.body.append(link);
  }
}

function setPanelError(state, key) {
  const spec = PANEL_SPECS[key];
  const panel = state.panels[key];
  panel.panel.setAttribute('data-state', 'error');
  panel.panel.removeAttribute('aria-busy');
  panel.status.replaceChildren('加载失败，请重试。');
  const retry = createElement(state.document, 'button', {
    class: 'btn gray today-panel-retry', type: 'button',
  }, spec.reload);
  retry.addEventListener('click', () => { void state.loadPanel(key); });
  panel.body.replaceChildren(retry);
}

function formatCompletedTime(value) {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date(value));
}

function queueRowView(state, queue, row) {
  const name = displayName(row.child);
  const container = createElement(state.document, 'article', { class: 'today-panel-row today-queue-row' });
  const label = queue === 'pending'
    ? createElement(state.document, 'a', {
      class: 'today-review-link', href: `#review?conversation_id=${row.id}`,
      'aria-label': `审阅${name}的会话 #${row.id}`,
    }, name)
    : createElement(state.document, 'p', { class: 'today-row-name' }, name);
  const conversation = createElement(state.document, 'span', { class: 'today-conversation-id' }, `会话 #${row.id}`);
  const details = createElement(state.document, 'p', { class: 'muted today-row-details' },
    `完成于 ${formatCompletedTime(row.completed_at)} · `, conversation,
    ` · ${row.round} 轮 · ${queueStatusLabel(queue)}`);
  const tag = createElement(state.document, 'span', { class: 'today-row-tag' }, queueStatusLabel(queue));
  container.append(label, details, tag);
  if (queue === 'failed') {
    const action = createElement(state.document, 'button', {
      class: 'btn gray today-analysis-retry', type: 'button',
      'aria-label': `重试分析：${name}`,
    }, `重试分析：${name}`);
    const feedback = createElement(state.document, 'p', {
      class: 'today-retry-feedback', role: 'status', 'aria-live': 'polite',
    });
    action.addEventListener('click', () => { void state.startRetry(row, action, feedback); });
    container.append(action, feedback);
  }
  return container;
}

function setPanelRows(state, key, rows) {
  if (!rows.length) {
    setPanelEmpty(state, key);
    return;
  }
  const panel = state.panels[key];
  panel.panel.setAttribute('data-state', 'loaded');
  panel.panel.removeAttribute('aria-busy');
  panel.status.replaceChildren(`已加载 ${rows.length} 条`);
  const list = createElement(state.document, 'div', { class: 'today-list' });
  if (key === 'roster') {
    for (const row of rows) {
      list.append(createElement(state.document, 'article', { class: 'today-panel-row today-roster-row' },
        createElement(state.document, 'a', {
          class: 'today-roster-link', href: '#roster',
        }, displayName(row)),
        createElement(state.document, 'span', { class: 'today-row-tag' }, '值日')));
    }
  } else {
    for (const row of rows) list.append(queueRowView(state, key, row));
  }
  panel.body.replaceChildren(list);
}

export function createTodayRoute(dependencies) {
  const validated = validateDependencies(dependencies);
  return function todayRoute({ root, params, signal, isCurrent }) {
    void params;
    if (!isCurrent() || signal.aborted) return undefined;
    const headerDate = localDateLabel(validated.now);
    if (!isCurrent() || signal.aborted) return undefined;
    const shell = createElement(validated.document, 'div', { class: 'view active today-view' });
    const hero = createElement(validated.document, 'header', { class: 'today-header today-hero' },
      createElement(validated.document, 'p', { class: 'today-eyebrow' }, '教师工作台'),
      createElement(validated.document, 'h1', { 'aria-label': '今日任务' },
        createElement(validated.document, 'span', {
          class: 'teacher-sr-only', 'aria-hidden': 'true',
        }, '今日任务'),
        createElement(validated.document, 'span', null, '今天的工作，一眼看清')),
      createElement(validated.document, 'p', { class: 'today-date muted' }, headerDate),
      createElement(validated.document, 'p', { class: 'today-hero-description muted' }, '每个面板独立加载与恢复，不让一个失败拖住整页。'),
      createElement(validated.document, 'p', { class: 'today-auth' }, '已解锁 · 仅本次浏览器会话'));
    const roster = createPanel(
      validated.document,
      'roster',
      '今日值日生',
      '两名值日幼儿',
      '正在加载今日排班…',
      'success',
    );
    const startConversation = createElement(validated.document, 'a', {
      class: 'btn today-start-link', href: '/index.html', target: '_blank', rel: 'noopener',
    }, '开始幼儿对话');
    roster.panel.append(startConversation);
    const pending = createPanel(
      validated.document,
      'pending',
      '待审阅',
      '需要老师确认的会话',
      '正在加载待审阅会话…',
      'warning',
    );
    const processing = createPanel(
      validated.document,
      'processing',
      '分析中',
      '后台正在整理内容',
      '正在加载分析中会话…',
      'info',
    );
    const failed = createPanel(
      validated.document,
      'failed',
      '分析失败',
      '原会话仍安全保留',
      '正在加载分析失败会话…',
      'danger',
    );
    const grid = createElement(validated.document, 'div', { class: 'today-panel-grid' },
      roster.panel, pending.panel, processing.panel, failed.panel);
    const auxiliary = createElement(validated.document, 'section', { class: 'card today-panel today-auxiliary today-metrics-strip' },
      createElement(validated.document, 'h2', null, '辅助指标'),
      createElement(validated.document, 'p', { class: 'muted' }, '本周指标暂不可用'));
    shell.append(hero, grid, auxiliary);
    if (!isCurrent() || signal.aborted) return undefined;
    root.replaceChildren(shell);

    let cleaned = false;
    const generations = new Map(Object.keys(PANEL_SPECS).map(key => [key, 0]));
    const state = {
      document: validated.document,
      panels: { roster, pending, processing, failed },
      loadPanel: null,
      startRetry: null,
    };
    const isPanelCurrent = (key, generation) => !cleaned && !signal.aborted && isCurrent()
      && generations.get(key) === generation;
    const loadPanel = key => {
      const generation = (generations.get(key) || 0) + 1;
      generations.set(key, generation);
      if (!isPanelCurrent(key, generation)) return Promise.resolve();
      setPanelLoading(state, key);
      return Promise.resolve()
        .then(() => {
          if (!isPanelCurrent(key, generation)) return undefined;
          return validated.request(PANEL_SPECS[key].path, { signal });
        })
        .then(result => {
          if (!isPanelCurrent(key, generation) || result === undefined) return undefined;
          const rows = PANEL_SPECS[key].validate(result);
          if (!isPanelCurrent(key, generation)) return undefined;
          setPanelRows(state, key, rows);
          return undefined;
        })
        .catch(() => {
          if (!isPanelCurrent(key, generation)) return undefined;
          setPanelError(state, key);
          return undefined;
        });
    };
    state.loadPanel = loadPanel;
    const retryFlights = new Map();
    const routeIsCurrent = () => !cleaned && !signal.aborted && isCurrent();
    const startRetry = (row, button, feedback) => {
      const existing = retryFlights.get(row.id);
      if (existing) return existing;
      if (!routeIsCurrent()) return Promise.resolve();
      button.disabled = true;
      feedback.replaceChildren();
      let operation;
      operation = Promise.resolve()
        .then(() => {
          if (!routeIsCurrent()) return undefined;
          return validated.request(`/api/conversations/${row.id}/analysis/retry`, { method: 'POST', signal });
        })
        .then(response => {
          if (!routeIsCurrent() || response === undefined) return undefined;
          validateRetryResponse(row.id, response);
          if (!routeIsCurrent()) return undefined;
          button.disabled = true;
          return Promise.allSettled(['failed', 'processing', 'pending'].map(loadPanel));
        })
        .catch(() => {
          if (!routeIsCurrent()) return undefined;
          button.disabled = false;
          feedback.replaceChildren('暂时无法重试分析，请稍后再试。');
          return undefined;
        });
      retryFlights.set(row.id, operation);
      void operation.then(() => {
        if (retryFlights.get(row.id) === operation) retryFlights.delete(row.id);
      });
      return operation;
    };
    state.startRetry = startRetry;
    void Promise.allSettled(['roster', 'pending', 'processing', 'failed'].map(loadPanel));
    return {
      cleanup() {
        cleaned = true;
        for (const key of Object.keys(PANEL_SPECS)) generations.set(key, (generations.get(key) || 0) + 1);
        retryFlights.clear();
      },
    };
  };
}
