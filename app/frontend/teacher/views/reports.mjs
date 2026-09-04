import { parseChildren } from './management.mjs';
import { renderAvatarImage } from '../../shared/avatar.mjs';


const CANONICAL_AVATAR = /^\/api\/media\/avatars\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const OPAQUE_CURSOR = /^[A-Za-z0-9_-]{1,1024}$/;
const SEARCH_ANALYSIS_STATUSES = Object.freeze(['pending', 'processing', 'succeeded', 'failed']);
const SEARCH_REVIEW_STATUSES = Object.freeze(['pending', 'draft', 'confirmed', 'unavailable']);
const SEARCH_END_REASONS = Object.freeze(['max_rounds', 'complete', 'manual']);
const SEARCH_PAGE_LIMIT = 5;


function invalid(cause) {
  return new TypeError('Invalid teacher report data.', cause === undefined ? undefined : { cause });
}

function descriptors(value) {
  if (value === null || typeof value !== 'object') throw invalid();
  try { return Object.getOwnPropertyDescriptors(value); }
  catch (error) { throw invalid(error); }
}

function record(value, keys) {
  if (Array.isArray(value)) throw invalid();
  const table = descriptors(value);
  const actual = Object.keys(table).filter(key => table[key].enumerable).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) throw invalid();
  const result = {};
  for (const key of keys) {
    const entry = table[key];
    if (!entry || !('value' in entry)) throw invalid();
    result[key] = entry.value;
  }
  return result;
}

function array(value) {
  if (!Array.isArray(value)) throw invalid();
  const table = descriptors(value);
  const length = table.length?.value;
  if (!Number.isSafeInteger(length) || length < 0) throw invalid();
  const result = [];
  for (let index = 0; index < length; index += 1) {
    const entry = table[String(index)];
    if (!entry || !('value' in entry)) throw invalid();
    result.push(entry.value);
  }
  if (Object.keys(table).filter(key => table[key].enumerable).length !== length) throw invalid();
  return result;
}

function positive(value) { return Number.isSafeInteger(value) && value > 0; }
function nonnegative(value) { return Number.isSafeInteger(value) && value >= 0; }
function dateString(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split('-').map(Number);
  if (year < 1) return false;
  const parsed = new Date(0);
  parsed.setUTCHours(0, 0, 0, 0);
  parsed.setUTCFullYear(year, month - 1, day);
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() === month - 1 && parsed.getUTCDate() === day;
}
function timestamp(value) { return typeof value === 'string' && value.trim() && Number.isFinite(Date.parse(value)); }
function utcTimestamp(value) {
  if (typeof value !== 'string') return false;
  const match = /^(\d{4}-\d{2}-\d{2})T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.exec(value);
  return match !== null && dateString(match[1]);
}

function dependencies(value) {
  const data = record(value, ['request', 'document', 'createAbortController', 'navigate']);
  if (typeof data.request !== 'function' || typeof data.document?.createElement !== 'function' ||
      typeof data.document?.createElementNS !== 'function' || typeof data.createAbortController !== 'function' ||
      typeof data.navigate !== 'function') throw invalid();
  return data;
}

export function parseGrowth(value, expectedChildId) {
  const result = record(value, ['child_id', 'dimensions']);
  if (!positive(result.child_id) || result.child_id !== expectedChildId) throw invalid();
  const dimensions = array(result.dimensions).map(item => {
    const dimension = record(item, ['key', 'name', 'points']);
    if (typeof dimension.key !== 'string' || !dimension.key.trim() || typeof dimension.name !== 'string' || !dimension.name.trim()) throw invalid();
    const points = array(dimension.points).map(itemPoint => {
      const point = record(itemPoint, ['date', 'score']);
      if (!dateString(point.date) || !Number.isInteger(point.score) || point.score < 1 || point.score > 5) throw invalid();
      return point;
    });
    return { ...dimension, points };
  });
  return { ...result, dimensions };
}

export function buildGrowthPresentation(result) {
  const series = result.dimensions.map(dimension => {
    const points = [...dimension.points].sort((left, right) => left.date.localeCompare(right.date));
    const latest = points.at(-1) || null;
    const recent = points.slice(-5);
    return {
      ...dimension, points, latest,
      recentMean: recent.length ? Number((recent.reduce((sum, point) => sum + point.score, 0) / recent.length).toFixed(1)) : null,
      differenceFromEarliest: latest ? latest.score - points[0].score : null,
      chronologicalText: points.length ? points.map(point => `${point.date} ${point.score} 分`).join('；') : '暂无已确认数据',
    };
  });
  const dates = [...new Set(series.flatMap(item => item.points.map(point => point.date)))].sort();
  return { dates, hasData: series.some(item => item.points.length), series };
}

export function setReportStatus(node, text, role) {
  node.textContent = text;
  if (role === null) {
    node.removeAttribute('role');
    node.removeAttribute('aria-live');
    return;
  }
  node.setAttribute('role', role);
  if (role === 'status') node.setAttribute('aria-live', 'polite');
  else node.removeAttribute('aria-live');
}

const REPORT_STATUS_COPY = Object.freeze({
  analysis: Object.freeze({ pending: '等待分析', processing: '分析中', succeeded: '分析完成', failed: '分析失败' }),
  review: Object.freeze({ pending: '等待审阅', draft: '审阅草稿', confirmed: '审阅完成', unavailable: '暂不可审阅' }),
});

export function reportStatusCopy(kind, value) {
  if (typeof kind !== 'string' || !Object.prototype.hasOwnProperty.call(REPORT_STATUS_COPY, kind)) throw invalid();
  const table = REPORT_STATUS_COPY[kind];
  if (!table || !Object.prototype.hasOwnProperty.call(table, value)) throw invalid();
  return table[value];
}

function parseHistoryItem(item, canonicalAvatar) {
    const row = record(item, ['id', 'child', 'date', 'completed_at', 'status', 'end_reason', 'message_count', 'round', 'analysis_status', 'review_status', 'revision']);
    const child = record(row.child, ['id', 'name', 'nickname', 'avatar']);
    if (!positive(row.id) || !positive(child.id) || typeof child.name !== 'string' || !child.name.trim() ||
        !(child.nickname === null || typeof child.nickname === 'string') ||
        !(child.avatar === null || (typeof child.avatar === 'string' && (!canonicalAvatar || CANONICAL_AVATAR.test(child.avatar)))) ||
        !dateString(row.date) || !timestamp(row.completed_at) || row.status !== 'ended' ||
        !['max_rounds', 'complete', 'manual'].includes(row.end_reason) || !positive(row.message_count) || !nonnegative(row.round) ||
        !['pending', 'processing', 'succeeded', 'failed'].includes(row.analysis_status) ||
        !['pending', 'draft', 'confirmed', 'unavailable'].includes(row.review_status) || !nonnegative(row.revision)) throw invalid();
    if ((row.analysis_status === 'succeeded') !== ['pending', 'draft', 'confirmed'].includes(row.review_status)) throw invalid();
    return { ...row, child };
}

export function parseHistoryPage(value) {
  const page = record(value, ['items', 'next_before_id']);
  const items = array(page.items).map(item => parseHistoryItem(item, false));
  if (!(page.next_before_id === null || positive(page.next_before_id)) ||
      (page.next_before_id !== null && (!items.length || page.next_before_id !== items.at(-1).id))) throw invalid();
  return { ...page, items };
}

export function parseSearchPage(value) {
  const page = record(value, ['items', 'next_cursor']);
  const items = array(page.items).map(item => parseHistoryItem(item, true));
  if (items.some(item => !utcTimestamp(item.completed_at)) ||
      new Set(items.map(item => item.id)).size !== items.length ||
      !(page.next_cursor === null || (typeof page.next_cursor === 'string' && OPAQUE_CURSOR.test(page.next_cursor))) ||
      (page.next_cursor !== null && items.length === 0)) throw invalid();
  return { ...page, items };
}

function canonicalFilterArray(value, allowed) {
  const result = array(value);
  if (result.some(item => typeof item !== 'string' || !allowed.includes(item)) ||
      new Set(result).size !== result.length) throw invalid();
  return result;
}

export function buildSearchRequest(value) {
  const form = record(value, [
    'child_id', 'date_from', 'date_to', 'analysis_status', 'review_status',
    'end_reason', 'keyword', 'sort',
  ]);
  let childId = null;
  if (form.child_id !== '') {
    if (typeof form.child_id !== 'string' || !/^[1-9][0-9]*$/.test(form.child_id)) throw invalid();
    childId = Number(form.child_id);
    if (!positive(childId) || String(childId) !== form.child_id) throw invalid();
  }
  if (typeof form.date_from !== 'string' || typeof form.date_to !== 'string') throw invalid();
  const dateFrom = form.date_from === '' ? null : form.date_from;
  const dateTo = form.date_to === '' ? null : form.date_to;
  if ((dateFrom !== null && !dateString(dateFrom)) || (dateTo !== null && !dateString(dateTo))) throw invalid();
  if (dateFrom !== null && dateTo !== null) {
    const from = Date.parse(`${dateFrom}T00:00:00Z`);
    const to = Date.parse(`${dateTo}T00:00:00Z`);
    if (from > to || (to - from) / 86_400_000 > 365) throw invalid();
  }
  if (typeof form.keyword !== 'string') throw invalid();
  const keyword = form.keyword.trim();
  if (Array.from(keyword).length > 100) throw invalid();
  if (!['completed_desc', 'completed_asc'].includes(form.sort)) throw invalid();
  return {
    child_id: childId,
    date_from: dateFrom,
    date_to: dateTo,
    analysis_status: canonicalFilterArray(form.analysis_status, SEARCH_ANALYSIS_STATUSES),
    review_status: canonicalFilterArray(form.review_status, SEARCH_REVIEW_STATUSES),
    end_reason: canonicalFilterArray(form.end_reason, SEARCH_END_REASONS),
    keyword: keyword || null,
    sort: form.sort,
    limit: SEARCH_PAGE_LIMIT,
  };
}

export function createReportRoutes(value) {
  const deps = dependencies(value);
  const { document, request, createAbortController, navigate } = deps;
  const h = (tag, attributes = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [key, item] of Object.entries(attributes)) {
      if (key.startsWith('on') && typeof item === 'function') node.addEventListener(key.slice(2), item);
      else if (key === 'text') node.textContent = item;
      else if (key === 'value') node.value = item;
      else node.setAttribute(key, item);
    }
    for (const child of children) node.append(child);
    return node;
  };
  const field = (text, control) => h('label', { class: 'teacher-field' }, h('span', { text }), control);
  const displayName = child => child.nickname || child.name;
  const scopeFor = context => {
    let disposed = false;
    let sequence = 0;
    const controllers = new Set();
    const alive = token => !disposed && context.isCurrent() && !context.signal.aborted && (token === undefined || token === sequence);
    const run = async (path, options = {}, token = ++sequence) => {
      const controller = createAbortController();
      if (!controller?.signal || typeof controller.abort !== 'function') throw invalid();
      const abort = () => { try { controller.abort(); } catch (_error) {} };
      context.signal.addEventListener('abort', abort, { once: true });
      controllers.add(controller);
      try {
        const result = await Promise.resolve().then(() => request(path, { ...options, signal: controller.signal }));
        if (!alive(token)) return { current: false };
        return { current: true, result };
      } finally {
        context.signal.removeEventListener('abort', abort);
        controllers.delete(controller);
      }
    };
    return {
      run,
      alive,
      next: () => ++sequence,
      cleanup() {
        if (disposed) return;
        disposed = true;
        sequence += 1;
        for (const controller of controllers) { try { controller.abort(); } catch (_error) {} }
        controllers.clear();
      },
    };
  };

  const selectorFor = (children, selectedId, labelText, emptyLabel, onChange) => {
    const id = labelText === '选择幼儿' ? 'growth-child-select' : 'search-child-select';
    const select = h('select', { id });
    select.append(h('option', { value: '', text: emptyLabel }));
    for (const child of children) select.append(h('option', { value: String(child.id), text: displayName(child) }));
    select.value = selectedId ? String(selectedId) : '';
    select.addEventListener('change', onChange);
    return {
      field: h('div', { class: 'teacher-field' }, h('label', { for: id, text: labelText }), select),
      select,
    };
  };

  const renderGrowth = (summaryStack, workspace, chart, dataPanel, result) => {
    summaryStack.replaceChildren();
    chart.replaceChildren();
    dataPanel.replaceChildren();
    if (!result.hasData) {
      summaryStack.hidden = true;
      workspace.hidden = true;
      return;
    }
    summaryStack.hidden = false;
    workspace.hidden = false;

    for (const series of result.series.filter(item => item.latest !== null)) {
      const difference = series.differenceFromEarliest > 0
        ? `+${series.differenceFromEarliest}`
        : String(series.differenceFromEarliest);
      const metric = (label, value, detail = null) => {
        const node = h('div', { class: 'growth-summary-metric' },
          h('span', { class: 'growth-summary-label', text: label }),
          h('strong', { text: value }));
        if (detail !== null) node.append(h('small', { text: detail }));
        return node;
      };
      const grid = h('div', { class: 'growth-summary-grid' },
        metric('最新评分', `${series.latest.score} 分`, series.latest.date),
        metric('最近 5 次均值', `${series.recentMean} 分`),
        metric('与最早记录差值', difference, '仅表示数值差，不代表结论'));
      summaryStack.append(h('article', { class: 'card growth-summary-card' },
        h('h2', { text: series.name }), grid));
    }

    const namespace = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(namespace, 'svg');
    svg.setAttribute('viewBox', '0 0 760 320');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-labelledby', 'growth-chart-title growth-chart-description');
    const svgTitle = document.createElementNS(namespace, 'title');
    svgTitle.setAttribute('id', 'growth-chart-title');
    svgTitle.textContent = '能力成长曲线';
    const svgDescription = document.createElementNS(namespace, 'desc');
    svgDescription.setAttribute('id', 'growth-chart-description');
    svgDescription.textContent = '按日期展示各能力维度已确认的 1 到 5 分评分。';
    svg.append(svgTitle, svgDescription);

    const colors = ['#2f80ed', '#16a34a', '#f59e0b', '#8b5cf6', '#ef4444'];
    const left = 72;
    const right = 72;
    const top = 28;
    const bottom = 266;
    const plotWidth = 760 - left - right;
    const pointX = date => {
      const index = result.dates.indexOf(date);
      return result.dates.length === 1 ? left + (plotWidth / 2) : left + (index * plotWidth / (result.dates.length - 1));
    };
    const pointY = score => bottom - ((score - 1) * (bottom - top) / 4);
    for (const score of [5, 4, 3, 2, 1]) {
      const y = pointY(score);
      const gridLine = document.createElementNS(namespace, 'line');
      gridLine.setAttribute('x1', String(left));
      gridLine.setAttribute('x2', String(left + plotWidth));
      gridLine.setAttribute('y1', String(y));
      gridLine.setAttribute('y2', String(y));
      gridLine.setAttribute('class', 'report-chart-grid-line');
      const label = document.createElementNS(namespace, 'text');
      label.setAttribute('x', '42');
      label.setAttribute('y', String(y + 5));
      label.setAttribute('data-axis-score', String(score));
      label.textContent = String(score);
      svg.append(gridLine, label);
    }
    const minimumDateTickSpacing = 96;
    const dateTicks = [];
    if (result.dates.length) {
      const firstDate = result.dates[0];
      const lastDate = result.dates.at(-1);
      const lastX = pointX(lastDate);
      let previousX = pointX(firstDate);
      dateTicks.push(firstDate);
      for (const date of result.dates.slice(1, -1)) {
        const x = pointX(date);
        if (x - previousX < minimumDateTickSpacing || lastX - x < minimumDateTickSpacing) continue;
        dateTicks.push(date);
        previousX = x;
      }
      if (lastDate !== firstDate) dateTicks.push(lastDate);
    }
    for (const date of dateTicks) {
      const label = document.createElementNS(namespace, 'text');
      label.setAttribute('x', String(pointX(date)));
      label.setAttribute('y', '298');
      label.setAttribute('class', 'report-chart-date');
      label.textContent = date;
      svg.append(label);
    }

    const legend = h('div', { class: 'report-chart-legend', 'aria-label': '图例' });
    result.series.forEach((series, seriesIndex) => {
      if (!series.points.length) return;
      const color = colors[seriesIndex % colors.length];
      legend.append(h('span', { class: 'report-legend' },
        h('span', { class: 'report-legend-swatch', 'aria-hidden': 'true', style: `background:${color}` }),
        h('span', { text: `图例 · ${series.name}` })));
      const points = series.points.map(point => ({
        ...point,
        x: pointX(point.date),
        y: pointY(point.score),
      }));
      if (points.length) {
        const path = document.createElementNS(namespace, 'path');
        path.setAttribute('d', points.map((point, index) => `${index ? 'L' : 'M'}${point.x},${point.y}`).join(' '));
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke', color);
        path.setAttribute('stroke-width', '3');
        svg.append(path);
      }
      points.forEach(point => {
        const circle = document.createElementNS(namespace, 'circle');
        circle.setAttribute('cx', String(point.x)); circle.setAttribute('cy', String(point.y)); circle.setAttribute('r', '5');
        circle.setAttribute('fill', color);
        const title = document.createElementNS(namespace, 'title');
        title.textContent = `${series.name}，${point.date}，${point.score} 分`;
        circle.append(title); svg.append(circle);
      });
    });
    chart.append(h('h2', { text: '成长曲线' }), legend, svg);
    dataPanel.append(h('h2', { text: '数据点说明' }));
    for (const series of result.series) {
      dataPanel.append(h('section', { class: 'growth-data-series' },
        h('h3', { text: `${series.name} · 已确认记录` }),
        h('p', { text: series.chronologicalText })));
    }
  };

  const growth = context => {
    const scope = scopeFor(context);
    const view = h('section', { class: 'reports-view growth-view', 'aria-busy': 'true' });
    const controls = h('div', { class: 'report-hero-selector' });
    const hero = h('header', { class: 'card report-hero' },
      h('div', { class: 'report-hero-copy' },
        h('h1', { text: '能力成长曲线' }),
        h('p', { class: 'report-hero-lead', text: '看见变化，不替孩子下结论' }),
        h('p', { class: 'muted', text: '评分固定为 1–5 分，只呈现已确认的记录。' })),
      controls);
    const status = h('p', { class: 'report-status' });
    const summaryStack = h('div', { class: 'growth-summary-stack' });
    summaryStack.hidden = true;
    const chart = h('section', { class: 'card report-chart' });
    const dataPanel = h('aside', { class: 'card growth-data-panel' });
    const workspace = h('div', { class: 'growth-workspace' }, chart, dataPanel);
    workspace.hidden = true;
    setReportStatus(status, '正在加载幼儿…', 'status');
    view.append(hero, status, summaryStack, workspace);
    context.root.replaceChildren(view);
    const raw = context.params.get('child_id');
    const selectedId = raw && /^\d+$/.test(raw) && Number(raw) > 0 ? Number(raw) : null;
    const showRetry = token => {
      if (!scope.alive(token)) return;
      const retry = h('button', { type: 'button', class: 'btn gray', text: '重试成长数据' });
      retry.addEventListener('click', () => void load());
      setReportStatus(status, '成长数据加载失败，请重试。', 'alert');
      status.append(' ', retry);
      retry.focus();
    };
    const load = async () => {
      const token = scope.next();
      view.setAttribute('aria-busy', 'true');
      setReportStatus(status, '正在加载幼儿…', 'status');
      try {
        const childResponse = await scope.run('/api/children?include_inactive=true', {}, token);
        if (!childResponse.current) return;
        const children = parseChildren(childResponse.result);
        const selector = selectorFor(children, selectedId, '选择幼儿', '请选择幼儿', event => {
          const id = Number(event.target.value);
          navigate(id ? `#growth?child_id=${id}` : '#growth');
        });
        controls.replaceChildren(selector.field);
        if (selectedId === null) {
          setReportStatus(status, '请选择一名幼儿查看成长曲线。', null);
          return;
        }
        if (!children.some(child => child.id === selectedId)) {
          setReportStatus(status, '所选幼儿不存在，请重新选择。', 'alert');
          selector.select.focus();
          return;
        }
        setReportStatus(status, '正在加载成长数据…', 'status');
        const response = await scope.run(`/api/analysis/growth?child_id=${selectedId}`, {}, token);
        if (!response.current) return;
        const result = buildGrowthPresentation(parseGrowth(response.result, selectedId));
        renderGrowth(summaryStack, workspace, chart, dataPanel, result);
        if (result.hasData) setReportStatus(status, '', null);
        else setReportStatus(status, '暂无已确认的成长数据', 'status');
      } catch (_error) {
        showRetry(token);
      } finally {
        if (scope.alive(token)) view.removeAttribute('aria-busy');
      }
    };
    void load();
    return { cleanup: scope.cleanup };
  };

  const search = context => {
    const scope = scopeFor(context);
    const view = h('section', { class: 'reports-view search-view', 'aria-busy': 'true' });
    const hero = h('header', { class: 'search-hero' },
      h('p', { class: 'search-hero-eyebrow', text: '多条件私密筛选' }),
      h('h1', { text: '查找历史日记' }),
      h('p', { class: 'muted search-hero-description', text: '筛选条件只用于本次教师查询，不会写入地址栏。' }));
    const filter = h('form', { class: 'card search-filter', novalidate: '' });
    const status = h('p', { class: 'report-status' });
    const results = h('div', { class: 'report-history', 'aria-label': '历史日记结果' });
    const pagination = h('div', { class: 'report-pagination' });
    const pageBadge = h('span', { class: 'report-page-number' });
    pageBadge.hidden = true;
    const panelHeader = h('header', { class: 'report-history-panel-header' },
      h('h2', { id: 'report-history-title', text: '历史记录' }), pageBadge);
    const columns = h('div', { class: 'report-history-columns', 'aria-hidden': 'true' },
      h('span', { text: '会话' }),
      h('span', { text: '日期' }),
      h('span', { text: '幼儿 / 轮数' }),
      h('div', { class: 'report-history-column-statuses' },
        h('span', { text: '分析状态' }), h('span', { text: '审阅状态' })),
      h('span'));
    const historyPanel = h('section', {
      class: 'card report-history-panel', 'aria-labelledby': 'report-history-title', 'aria-busy': 'true',
    }, panelHeader, columns, results, pagination);
    setReportStatus(status, '正在加载幼儿…', 'status');
    view.append(hero, filter, status, historyPanel);
    context.root.replaceChildren(view);
    let controls = null;
    let nextCursor = null;
    let submittedSnapshot = null;
    let loadedPageCount = 0;
    let renderedItemCount = 0;
    let renderedIds = new Set();
    let appendInFlight = false;

    const checkboxGroup = (legendText, name, choices) => {
      const inputs = [];
      const choicesNode = h('div', { class: 'search-choice-list' });
      for (const [value, text] of choices) {
        const input = h('input', { type: 'checkbox', name, value });
        inputs.push(input);
        choicesNode.append(h('label', { class: 'search-choice' }, input, h('span', { text })));
      }
      return {
        node: h('fieldset', { class: 'search-choice-group' }, h('legend', { text: legendText }), choicesNode),
        inputs,
      };
    };

    const renderFilters = children => {
      const labeledField = (id, text, control) => h('div', { class: 'teacher-field' },
        h('label', { for: id, text }), control);
      const selector = selectorFor(children, null, '筛选幼儿', '全部幼儿', () => {});
      const dateFrom = h('input', { id: 'search-date-from', type: 'date' });
      const dateTo = h('input', { id: 'search-date-to', type: 'date' });
      const keyword = h('input', {
        id: 'search-keyword', type: 'text', maxlength: '200', autocomplete: 'off',
        placeholder: '搜索幼儿或日记对话中的词语',
      });
      keyword.addEventListener('input', () => {
        const characters = Array.from(keyword.value);
        if (characters.length > 100) keyword.value = characters.slice(0, 100).join('');
      });
      const sort = h('select', { id: 'search-sort' },
        h('option', { value: 'completed_desc', text: '最近完成优先' }),
        h('option', { value: 'completed_asc', text: '最早完成优先' }));
      const analysis = checkboxGroup('分析状态', 'search-analysis', [
        ['pending', '等待分析'], ['processing', '分析中'],
        ['succeeded', '分析完成'], ['failed', '分析失败'],
      ]);
      const review = checkboxGroup('审阅状态', 'search-review', [
        ['pending', '等待审阅'], ['draft', '审阅草稿'],
        ['confirmed', '审阅完成'], ['unavailable', '暂不可审阅'],
      ]);
      const endReason = checkboxGroup('结束原因', 'search-end-reason', [
        ['max_rounds', '达到轮数上限'], ['complete', '自然完成'], ['manual', '手动结束'],
      ]);
      const primary = h('div', { class: 'search-filter-grid' },
        selector.field,
        labeledField('search-date-from', '开始日期', dateFrom),
        labeledField('search-date-to', '结束日期', dateTo),
        labeledField('search-keyword', '关键词', keyword),
        labeledField('search-sort', '排序', sort));
      const groups = h('div', { class: 'search-filter-groups' }, analysis.node, review.node, endReason.node);
      const actions = h('div', { class: 'search-filter-actions' },
        h('p', { class: 'muted', text: '同组可多选；不同筛选条件会同时生效。' }),
        h('button', { type: 'submit', class: 'btn', text: '搜索历史' }));
      filter.replaceChildren(primary, groups, actions);
      controls = {
        child: selector.select,
        dateFrom,
        dateTo,
        keyword,
        sort,
        analysis: analysis.inputs,
        review: review.inputs,
        endReason: endReason.inputs,
      };
    };

    const formSnapshot = () => buildSearchRequest({
      child_id: controls.child.value,
      date_from: controls.dateFrom.value,
      date_to: controls.dateTo.value,
      analysis_status: controls.analysis.filter(input => input.checked).map(input => input.value),
      review_status: controls.review.filter(input => input.checked).map(input => input.value),
      end_reason: controls.endReason.filter(input => input.checked).map(input => input.value),
      keyword: controls.keyword.value,
      sort: controls.sort.value,
    });

    const cloneSnapshot = snapshot => ({
      ...snapshot,
      analysis_status: [...snapshot.analysis_status],
      review_status: [...snapshot.review_status],
      end_reason: [...snapshot.end_reason],
    });

    filter.addEventListener('submit', event => {
      event.preventDefault();
      if (!controls) return;
      try {
        void startSearch(formSnapshot());
      } catch (_error) {
        setReportStatus(status, '日期范围无效，请检查后重试。', 'alert');
        controls.dateFrom.focus();
      }
    });

    const showRetry = (token, snapshot) => {
      if (!scope.alive(token)) return;
      const retry = h('button', { type: 'button', class: 'btn gray', text: '重试历史记录' });
      retry.addEventListener('click', () => void startSearch(snapshot));
      setReportStatus(status, '历史记录加载失败，请重试。', 'alert');
      status.append(' ', retry);
      retry.focus();
    };

    const rowFor = item => {
      const fallback = Array.from(displayName(item.child).trim())[0] || '?';
      const avatar = renderAvatarImage(document, item.child.avatar, fallback);
      avatar.setAttribute('class', 'report-history-avatar');
      avatar.setAttribute('aria-hidden', 'true');
      return h('article', { class: 'report-history-row' },
        h('h3', { class: 'report-history-id', text: `会话 #${item.id}` }),
        h('time', { class: 'report-history-date', datetime: item.date, text: item.date }),
        h('div', { class: 'report-history-child-identity' }, avatar,
          h('div', { class: 'report-history-child-meta' },
            h('p', { class: 'report-history-child', text: displayName(item.child) }),
            h('p', { class: 'report-history-rounds', text: `${item.round} 轮` }))),
        h('div', { class: 'report-history-statuses' },
          h('span', {
            class: 'report-status-tag', 'data-status-kind': 'analysis', 'data-status-value': item.analysis_status,
            text: reportStatusCopy('analysis', item.analysis_status),
          }),
          h('span', {
            class: 'report-status-tag', 'data-status-kind': 'review', 'data-status-value': item.review_status,
            text: reportStatusCopy('review', item.review_status),
          })),
        h('a', {
          class: 'report-review-link', href: `#review?conversation_id=${item.id}`,
          'aria-label': `打开会话 #${item.id} 的审阅`, text: '打开审阅 →',
        }));
    };

    const renderPagination = () => {
      pageBadge.hidden = false;
      pageBadge.textContent = `第 ${loadedPageCount} 页`;
      pagination.replaceChildren(
        h('p', {
          class: 'report-results-summary',
          text: `已显示 ${renderedItemCount} 条 · ${nextCursor === null ? '已全部加载' : '还有更多'}`,
        }),
      );
      if (nextCursor !== null) {
        const button = h('button', { type: 'button', class: 'btn report-load-more', text: '加载更多' });
        button.addEventListener('click', () => void loadMore(button));
        pagination.append(button);
      }
    };

    const commitPage = (page, append, requestCursor) => {
      if (append && (page.items.some(item => renderedIds.has(item.id)) || page.next_cursor === requestCursor)) throw invalid();
      const nodes = page.items.map(rowFor);
      if (!append) {
        results.replaceChildren(...nodes);
        renderedIds = new Set(page.items.map(item => item.id));
      } else {
        results.append(...nodes);
        page.items.forEach(item => renderedIds.add(item.id));
      }
      if (append) {
        loadedPageCount += 1;
        renderedItemCount += page.items.length;
      } else {
        loadedPageCount = 1;
        renderedItemCount = page.items.length;
      }
      nextCursor = page.next_cursor;
      renderPagination();
      if (renderedItemCount === 0) setReportStatus(status, '暂无历史记录', 'status');
      else setReportStatus(status, '', null);
    };

    const loadPage = async ({ append, body, token, button = null }) => {
      const requestCursor = append ? body.cursor : null;
      view.setAttribute('aria-busy', 'true');
      historyPanel.setAttribute('aria-busy', 'true');
      if (button) button.disabled = true;
      setReportStatus(status, append ? '正在加载更多历史记录…' : '正在加载历史记录…', 'status');
      try {
        const response = await scope.run('/api/conversations/search', {
          method: 'POST', body, sequenceKey: 'teacher-history-search',
        }, token);
        if (!response.current) return;
        const page = parseSearchPage(response.result);
        if (!scope.alive(token)) return;
        commitPage(page, append, requestCursor);
      } catch (_error) {
        if (scope.alive(token)) {
          if (button) {
            setReportStatus(status, '更多历史记录加载失败，已保留当前结果。请重试。', 'alert');
            button.disabled = false;
            button.focus();
          } else showRetry(token, body);
        }
      } finally {
        if (scope.alive(token)) {
          appendInFlight = false;
          view.removeAttribute('aria-busy');
          historyPanel.removeAttribute('aria-busy');
        }
      }
    };

    async function startSearch(snapshot) {
      const token = scope.next();
      submittedSnapshot = cloneSnapshot(snapshot);
      nextCursor = null;
      loadedPageCount = 0;
      renderedItemCount = 0;
      renderedIds = new Set();
      appendInFlight = false;
      results.replaceChildren();
      pagination.replaceChildren();
      pageBadge.hidden = true;
      await loadPage({ append: false, body: cloneSnapshot(submittedSnapshot), token });
    }

    async function loadMore(button) {
      if (appendInFlight || nextCursor === null || submittedSnapshot === null) return;
      const token = scope.next();
      appendInFlight = true;
      const body = { ...cloneSnapshot(submittedSnapshot), cursor: nextCursor };
      await loadPage({ append: true, body, token, button });
    }

    const load = async () => {
      const token = scope.next();
      view.setAttribute('aria-busy', 'true');
      historyPanel.setAttribute('aria-busy', 'true');
      setReportStatus(status, '正在加载幼儿…', 'status');
      try {
        const childResponse = await scope.run('/api/children?include_inactive=true', {}, token);
        if (!childResponse.current) return;
        const children = parseChildren(childResponse.result);
        renderFilters(children);
        await startSearch(formSnapshot());
      } catch (_error) {
        if (scope.alive(token)) {
          const retry = h('button', { type: 'button', class: 'btn gray', text: '重试筛选条件' });
          retry.addEventListener('click', () => void load());
          setReportStatus(status, '筛选条件加载失败，请重试。', 'alert');
          status.append(' ', retry);
          retry.focus();
        }
      } finally {
        if (scope.alive(token)) {
          view.removeAttribute('aria-busy');
          historyPanel.removeAttribute('aria-busy');
        }
      }
    };
    void load();
    return { cleanup: scope.cleanup };
  };
  return { growth, search };
}
