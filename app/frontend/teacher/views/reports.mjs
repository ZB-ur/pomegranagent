import { parseChildren } from './management.mjs';


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
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() === month - 1 && parsed.getUTCDate() === day;
}
function timestamp(value) { return typeof value === 'string' && value.trim() && Number.isFinite(Date.parse(value)); }

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

export function parseHistoryPage(value) {
  const page = record(value, ['items', 'next_before_id']);
  const items = array(page.items).map(item => {
    const row = record(item, ['id', 'child', 'date', 'completed_at', 'status', 'end_reason', 'message_count', 'round', 'analysis_status', 'review_status', 'revision']);
    const child = record(row.child, ['id', 'name', 'nickname', 'avatar']);
    if (!positive(row.id) || !positive(child.id) || typeof child.name !== 'string' || !child.name.trim() ||
        !(child.nickname === null || typeof child.nickname === 'string') || !(child.avatar === null || typeof child.avatar === 'string') ||
        !dateString(row.date) || !timestamp(row.completed_at) || row.status !== 'ended' ||
        !['max_rounds', 'complete', 'manual'].includes(row.end_reason) || !positive(row.message_count) || !nonnegative(row.round) ||
        !['pending', 'processing', 'succeeded', 'failed'].includes(row.analysis_status) ||
        !['pending', 'draft', 'confirmed', 'unavailable'].includes(row.review_status) || !nonnegative(row.revision)) throw invalid();
    if ((row.analysis_status === 'succeeded') !== ['pending', 'draft', 'confirmed'].includes(row.review_status)) throw invalid();
    return { ...row, child };
  });
  if (!(page.next_before_id === null || positive(page.next_before_id)) ||
      (page.next_before_id !== null && (!items.length || page.next_before_id !== items.at(-1).id))) throw invalid();
  return { ...page, items };
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
    const maximumDateTicks = 6;
    const dateTicks = result.dates.length <= maximumDateTicks
      ? result.dates
      : Array.from({ length: maximumDateTicks }, (_item, index) => (
        result.dates[Math.round(index * (result.dates.length - 1) / (maximumDateTicks - 1))]
      ));
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
    const view = h('section', { class: 'reports-view' });
    const controls = h('div', { class: 'card' });
    const status = h('p', { role: 'status', 'aria-live': 'polite', text: '正在加载历史记录…' });
    const results = h('div', { class: 'report-history' });
    view.append(h('h1', { text: '明细检索' }), controls, status, results);
    context.root.replaceChildren(view);
    const raw = context.params.get('child_id');
    const selectedId = raw && /^\d+$/.test(raw) && Number(raw) > 0 ? Number(raw) : null;
    let nextBeforeId = null;
    let loadingMore = false;
    const showRetry = () => {
      const retry = h('button', { type: 'button', class: 'btn gray', text: '重试历史记录' });
      retry.addEventListener('click', () => void load());
      status.setAttribute('role', 'alert');
      status.replaceChildren('历史记录加载失败，请重试。', retry);
    };

    const appendPage = (page, append) => {
      if (!append) results.replaceChildren();
      for (const item of page.items) {
        const row = h('article', { class: 'card report-history-row' });
        row.append(
          h('h2', { text: displayName(item.child) }),
          h('p', { text: `${item.date} · ${item.round} 轮 · ${item.analysis_status} · ${item.review_status}` }),
          h('a', { href: `#review?conversation_id=${item.id}`, text: `查看会话 #${item.id}` }),
        );
        results.append(row);
      }
      nextBeforeId = page.next_before_id;
      const old = view.querySelector('.report-load-more');
      if (old) old.remove();
      if (nextBeforeId !== null) {
        const button = h('button', { type: 'button', class: 'btn report-load-more', text: '加载更多' });
        button.addEventListener('click', () => void loadHistory(true, button));
        view.append(button);
      }
      if (!results.children.length) results.append(h('p', { class: 'card muted', text: '暂无历史记录' }));
    };
    const loadHistory = async (append = false, button = null) => {
      if (loadingMore) return;
      loadingMore = true;
      if (button) button.disabled = true;
      const token = scope.next();
      try {
        const query = new URLSearchParams({ limit: '20' });
        if (selectedId !== null) query.set('child_id', String(selectedId));
        if (append && nextBeforeId !== null) query.set('before_id', String(nextBeforeId));
        const response = await scope.run(`/api/conversations/history?${query}`, {}, token);
        if (!response.current) return;
        appendPage(parseHistoryPage(response.result), append);
        status.setAttribute('role', 'status');
        status.textContent = '历史记录已加载';
      } catch (_error) {
        if (scope.alive(token)) {
          if (button) {
            status.setAttribute('role', 'alert');
            status.textContent = '历史记录加载失败，请重试。';
            button.disabled = false;
          } else showRetry();
        }
      } finally { loadingMore = false; }
    };
    const load = async () => {
      const token = scope.next();
      status.setAttribute('role', 'status');
      status.textContent = '正在加载历史记录…';
      try {
        const childResponse = await scope.run('/api/children?include_inactive=true', {}, token);
        if (!childResponse.current) return;
        const children = parseChildren(childResponse.result);
        const selector = selectorFor(children, selectedId, '筛选幼儿', '全部幼儿', event => {
          const id = Number(event.target.value);
          navigate(id ? `#search?child_id=${id}` : '#search');
        });
        controls.replaceChildren(selector.field);
        if (selectedId !== null && !children.some(child => child.id === selectedId)) {
          status.setAttribute('role', 'alert'); status.textContent = '所选幼儿不存在，请重新选择。'; return;
        }
        await loadHistory(false);
      } catch (_error) {
        if (scope.alive(token)) showRetry();
      }
    };
    void load();
    return { cleanup: scope.cleanup };
  };
  return { growth, search };
}
