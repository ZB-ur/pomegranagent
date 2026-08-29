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

  const selectorFor = (children, selectedId, labelText, onChange) => {
    const id = labelText === '选择幼儿' ? 'growth-child-select' : 'search-child-select';
    const select = h('select', { id });
    select.append(h('option', { value: '', text: '全部幼儿' }));
    for (const child of children) select.append(h('option', { value: String(child.id), text: displayName(child) }));
    select.value = selectedId ? String(selectedId) : '';
    select.addEventListener('change', onChange);
    return h('div', { class: 'teacher-field' }, h('label', { for: id, text: labelText }), select);
  };

  const renderChart = (container, result) => {
    container.replaceChildren();
    if (!result.dimensions.some(item => item.points.length)) {
      container.append(h('p', { class: 'muted', text: '暂无已确认的成长数据' }));
      return;
    }
    const namespace = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(namespace, 'svg');
    svg.setAttribute('viewBox', '0 0 760 320');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', '能力成长曲线');
    const colors = ['#2f80ed', '#16a34a', '#f59e0b', '#8b5cf6', '#ef4444'];
    result.dimensions.forEach((dimension, dimensionIndex) => {
      const label = h('p', { class: 'report-legend', text: dimension.name });
      container.append(label);
      const points = dimension.points.map((point, index) => ({
        x: 60 + index * Math.max(1, 640 / Math.max(1, dimension.points.length - 1)),
        y: 270 - (point.score - 1) * 55,
      }));
      if (points.length) {
        const path = document.createElementNS(namespace, 'path');
        path.setAttribute('d', points.map((point, index) => `${index ? 'L' : 'M'}${point.x},${point.y}`).join(' '));
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke', colors[dimensionIndex % colors.length]);
        path.setAttribute('stroke-width', '3');
        svg.append(path);
      }
      points.forEach((point, index) => {
        const circle = document.createElementNS(namespace, 'circle');
        circle.setAttribute('cx', String(point.x)); circle.setAttribute('cy', String(point.y)); circle.setAttribute('r', '5');
        circle.setAttribute('fill', colors[dimensionIndex % colors.length]);
        const title = document.createElementNS(namespace, 'title');
        title.textContent = `${dimension.points[index].date}：${dimension.points[index].score}分`;
        circle.append(title); svg.append(circle);
      });
    });
    container.prepend(svg);
  };

  const growth = context => {
    const scope = scopeFor(context);
    const view = h('section', { class: 'reports-view' });
    const controls = h('div', { class: 'card' });
    const status = h('p', { role: 'status', 'aria-live': 'polite', text: '正在加载幼儿…' });
    const chart = h('div', { class: 'card report-chart' });
    view.append(h('h1', { text: '能力成长曲线' }), controls, status, chart);
    context.root.replaceChildren(view);
    const raw = context.params.get('child_id');
    const selectedId = raw && /^\d+$/.test(raw) && Number(raw) > 0 ? Number(raw) : null;
    const showRetry = () => {
      const retry = h('button', { type: 'button', class: 'btn gray', text: '重试成长数据' });
      retry.addEventListener('click', () => void load());
      status.setAttribute('role', 'alert');
      status.replaceChildren('成长数据加载失败，请重试。', retry);
    };
    const load = async () => {
      const token = scope.next();
      status.setAttribute('role', 'status');
      status.textContent = '正在加载幼儿…';
      try {
        const childResponse = await scope.run('/api/children?include_inactive=true', {}, token);
        if (!childResponse.current) return;
        const children = parseChildren(childResponse.result);
        controls.replaceChildren(selectorFor(children, selectedId, '选择幼儿', event => {
          const id = Number(event.target.value);
          navigate(id ? `#growth?child_id=${id}` : '#growth');
        }));
        if (selectedId === null) { status.textContent = '请选择一名幼儿查看成长曲线。'; return; }
        if (!children.some(child => child.id === selectedId)) { status.setAttribute('role', 'alert'); status.textContent = '所选幼儿不存在，请重新选择。'; return; }
        status.textContent = '正在加载成长数据…';
        const response = await scope.run(`/api/analysis/growth?child_id=${selectedId}`, {}, token);
        if (!response.current) return;
        const result = parseGrowth(response.result, selectedId);
        renderChart(chart, result);
        status.setAttribute('role', 'status');
        status.textContent = '成长数据已加载';
      } catch (_error) {
        if (scope.alive(token)) showRetry();
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
        controls.replaceChildren(selectorFor(children, selectedId, '筛选幼儿', event => {
          const id = Number(event.target.value);
          navigate(id ? `#search?child_id=${id}` : '#search');
        }));
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
