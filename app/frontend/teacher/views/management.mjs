const CHILD_KEYS = ['id', 'name', 'nickname', 'avatar', 'active', 'deactivated_at', 'future_roster_entries', 'has_active_conversation'];
const DUCK_KEYS = ['id', 'name', 'avatar', 'status', 'note', 'active', 'deactivated_at', 'historical_feeding_log_count'];

function invalid(cause) {
  return new TypeError('Invalid teacher management data.', cause === undefined ? undefined : { cause });
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
  const enumerable = Object.keys(table).filter(key => table[key].enumerable);
  if (enumerable.length !== length) throw invalid();
  return result;
}

function positive(value) {
  return Number.isSafeInteger(value) && value > 0;
}

function nonnegative(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

function optionalString(value, maximum) {
  return value === null || (typeof value === 'string' && value.length <= maximum);
}

function dateString(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split('-').map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() === month - 1 && parsed.getUTCDate() === day;
}

function timestamp(value) {
  return typeof value === 'string' && value.trim() !== '' && Number.isFinite(Date.parse(value));
}

function uuid(value) {
  return typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function errorCode(value) {
  if (value === null || (typeof value !== 'object' && typeof value !== 'function')) return null;
  try {
    const descriptor = Object.getOwnPropertyDescriptor(value, 'code');
    return descriptor && 'value' in descriptor && typeof descriptor.value === 'string'
      ? descriptor.value : null;
  } catch (_error) {
    return null;
  }
}

function strictDependencies(value) {
  const data = record(value, ['request', 'document', 'createAbortController', 'createRequestId']);
  if (typeof data.request !== 'function' || typeof data.document?.createElement !== 'function' ||
      typeof data.createAbortController !== 'function' || typeof data.createRequestId !== 'function') throw invalid();
  return data;
}

export function parseChildren(value) {
  const rows = array(value).map(item => {
    const row = record(item, CHILD_KEYS);
    if (!positive(row.id) || typeof row.name !== 'string' || !row.name.trim() || row.name.length > 64 ||
        !optionalString(row.nickname, 64) || !optionalString(row.avatar, 255) || typeof row.active !== 'boolean' ||
        !(row.deactivated_at === null || timestamp(row.deactivated_at)) || !nonnegative(row.future_roster_entries) ||
        typeof row.has_active_conversation !== 'boolean') throw invalid();
    return row;
  });
  if (new Set(rows.map(row => row.id)).size !== rows.length) throw invalid();
  return rows;
}

export function parseDucks(value) {
  const rows = array(value).map(item => {
    const row = record(item, DUCK_KEYS);
    if (!positive(row.id) || typeof row.name !== 'string' || !row.name.trim() || row.name.length > 64 ||
        !optionalString(row.avatar, 255) || !optionalString(row.status, 255) || !optionalString(row.note, 2000) ||
        typeof row.active !== 'boolean' || !(row.deactivated_at === null || timestamp(row.deactivated_at)) ||
        !nonnegative(row.historical_feeding_log_count)) throw invalid();
    return row;
  });
  if (new Set(rows.map(row => row.id)).size !== rows.length) throw invalid();
  return rows;
}

export function validateChildAck(value, expected) {
  const row = record(value, ['id', 'name', 'nickname', 'avatar', 'active']);
  if (!positive(row.id) || (expected.expectedId !== null && row.id !== expected.expectedId) || row.name !== expected.name ||
      row.nickname !== expected.nickname || row.avatar !== expected.avatar || row.active !== expected.active) throw invalid();
  return row;
}

export function validateDuckAck(value, expected) {
  const row = record(value, ['id', 'name', 'avatar', 'status', 'note']);
  if (!positive(row.id) || (expected.expectedId !== null && row.id !== expected.expectedId) || row.name !== expected.name || row.avatar !== expected.avatar ||
      row.status !== expected.status || row.note !== expected.note) throw invalid();
  return row;
}

export function validateDeactivationAck(value, expected) {
  const row = record(value, ['id', 'kind', 'name', 'active', 'deactivated_at', 'affected_future_roster_entries', 'changed']);
  if (!positive(row.id) || row.id !== expected.id || row.kind !== expected.kind || row.name !== expected.name ||
      row.active !== expected.active || !nonnegative(row.affected_future_roster_entries) || typeof row.changed !== 'boolean' ||
      (row.active ? row.deactivated_at !== null : !timestamp(row.deactivated_at))) throw invalid();
  return row;
}

export function validateArchive(value, expectedDuckId, { requireSummary = false } = {}) {
  const row = record(value, ['duck_id', 'summary']);
  if (row.duck_id !== expectedDuckId || !positive(row.duck_id) || !optionalString(row.summary, 20_000) ||
      (requireSummary && (typeof row.summary !== 'string' || !row.summary.trim()))) throw invalid();
  return row;
}

export function parseRosterRows(value) {
  return array(value).map(item => {
    const row = record(item, ['id', 'cycle', 'date', 'child_id']);
    if (!positive(row.id) || typeof row.cycle !== 'string' || !row.cycle.trim() || row.cycle.length > 64 ||
        !dateString(row.date) || !positive(row.child_id)) throw invalid();
    return row;
  });
}

export function validateDailyRosterAck(value, expected) {
  const row = record(value, ['request_id', 'date', 'cycle', 'child_ids', 'replayed']);
  const ids = array(row.child_ids);
  if (!uuid(row.request_id) || row.request_id !== expected.requestId || row.date !== expected.date || row.cycle !== expected.cycle ||
      !dateString(row.date) || ids.length !== 2 || ids.some((id, index) => !positive(id) || id !== expected.childIds[index]) ||
      typeof row.replayed !== 'boolean') throw invalid();
  return { ...row, child_ids: ids };
}

export function validateAutoRosterAck(value, expected) {
  const row = record(value, ['request_id', 'schedule', 'replayed']);
  const schedule = array(row.schedule).map(item => {
    const entry = record(item, ['date', 'child_ids']);
    const ids = array(entry.child_ids);
    if (!dateString(entry.date) || ids.length !== 2 || ids[0] === ids[1] || ids.some(id => !positive(id)) || new Date(`${entry.date}T00:00:00Z`).getUTCDay() % 6 === 0) throw invalid();
    return { ...entry, child_ids: ids };
  });
  const expectedDates = [];
  const cursor = new Date(`${expected.startDate}T00:00:00Z`);
  while (expectedDates.length < expected.days) {
    if (cursor.getUTCDay() !== 0 && cursor.getUTCDay() !== 6) expectedDates.push(cursor.toISOString().slice(0, 10));
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  const activeIds = new Set(expected.activeChildIds);
  if (!uuid(row.request_id) || row.request_id !== expected.requestId || typeof row.replayed !== 'boolean' ||
      schedule.length !== expected.days || schedule.some((entry, index) => entry.date !== expectedDates[index] ||
        entry.child_ids.some(id => !activeIds.has(id)))) throw invalid();
  return { ...row, schedule };
}

export function createManagementRoutes(dependencies) {
  const deps = strictDependencies(dependencies);
  const { document, request, createAbortController, createRequestId } = deps;

  const h = (tag, attributes = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes)) {
      if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
      else if (key === 'text') node.textContent = value;
      else if (key === 'checked') node.checked = value;
      else if (key === 'value') node.value = value;
      else node.setAttribute(key, value);
    }
    for (const child of children) node.append(child);
    return node;
  };
  const field = (labelText, input) => h('label', { class: 'teacher-field' }, h('span', { text: labelText }), input);
  const displayName = item => item.nickname || item.name;
  const fixedFailure = '操作失败，请稍后重试。';

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
    const cleanup = () => {
      if (disposed) return;
      disposed = true;
      sequence += 1;
      for (const controller of controllers) {
        try { controller.abort(); } catch (_error) {}
      }
      controllers.clear();
    };
    return { run, alive, cleanup, next: () => ++sequence };
  };

  const createResourceRoute = kind => context => {
    const isChild = kind === 'child';
    const title = isChild ? '幼儿管理' : '小鸭管理';
    const collectionPath = isChild ? '/api/children?include_inactive=true' : '/api/ducks?include_inactive=true';
    const scope = scopeFor(context);
    let rows = [];
    let mutation = null;
    let undoState = null;
    const view = h('section', { class: 'management-view' });
    const heading = h('h1', { text: title });
    const feedback = h('p', { role: 'status', 'aria-live': 'polite', class: 'management-status' });
    const list = h('div', { class: 'management-list' });
    const form = h('form', { class: 'card management-form' });
    view.append(heading, form, feedback, list);
    context.root.replaceChildren(view);

    const nameInput = h('input', { required: '', maxlength: '64', autocomplete: 'off' });
    const secondInput = h(isChild ? 'input' : 'input', { maxlength: isChild ? '64' : '255', autocomplete: 'off' });
    const avatarInput = h('input', { maxlength: '255', autocomplete: 'off' });
    const noteInput = isChild ? null : h('textarea', { maxlength: '2000' });
    const submit = h('button', { type: 'submit', class: 'btn', text: isChild ? '添加幼儿' : '添加小鸭' });
    let editingId = null;
    form.append(
      field(isChild ? '幼儿姓名' : '小鸭名字', nameInput),
      field(isChild ? '小名' : '状态', secondInput),
      field('头像', avatarInput),
    );
    if (noteInput) form.append(field('备注', noteInput));
    form.append(submit);

    const setBusy = busy => {
      for (const control of form.querySelectorAll('input, textarea, button')) control.disabled = busy;
    };
    const showFailure = copy => {
      feedback.setAttribute('role', 'alert');
      feedback.textContent = copy || fixedFailure;
    };
    const showSuccess = copy => {
      feedback.setAttribute('role', 'status');
      feedback.textContent = copy;
    };

    const dismissUndo = state => {
      if (!state) return;
      if (state.timer !== null) clearTimeout(state.timer);
      state.toast.remove();
      if (undoState === state) undoState = null;
    };
    const showUndo = (item, acknowledgement) => {
      dismissUndo(undoState);
      const toast = h('div', { class: 'management-undo', 'data-undo-toast': '', role: 'status' });
      const undo = h('button', { type: 'button', class: 'btn gray', text: `撤销停用：${displayName(item)}` });
      const state = { toast, timer: null };
      undoState = state;
      toast.append(h('span', { text: '已停用，可在 10 秒内撤销。' }), undo);
      view.append(toast);
      undo.addEventListener('click', async () => {
        if (mutation || undoState !== state) return;
        mutation = `${kind}-${item.id}`;
        undo.disabled = true;
        try {
          const response = await scope.run(`/api/${isChild ? 'children' : 'ducks'}/${item.id}/reactivate`, { method: 'POST' });
          if (!response.current) return;
          validateDeactivationAck(response.result, { id: item.id, kind, name: item.name, active: true });
          dismissUndo(state);
          await reload();
        } catch (_error) {
          if (scope.alive()) showFailure();
        } finally {
          mutation = null;
          if (scope.alive() && undoState === state) undo.disabled = false;
        }
      });
      state.timer = setTimeout(() => dismissUndo(state), 10_000);
    };

    const changeState = async (item, active, action) => {
      const key = `${kind}-${item.id}`;
      if (mutation) return;
      mutation = key;
      let restoreFocus = false;
      if (action) action.disabled = true;
      try {
        const response = await scope.run(`/api/${isChild ? 'children' : 'ducks'}/${item.id}/${active ? 'reactivate' : 'deactivate'}`, { method: 'POST' });
        if (!response.current) return;
        const ack = validateDeactivationAck(response.result, { id: item.id, kind, name: item.name, active });
        await reload();
        if (!active && ack.changed && scope.alive()) showUndo(item, ack);
      } catch (error) {
        if (scope.alive() && !active && isChild && errorCode(error) === 'ACTIVE_CONVERSATION_EXISTS') {
          await reload();
          if (scope.alive()) {
            showFailure('当前会话状态已变化，已刷新幼儿列表。');
            restoreFocus = true;
          }
        } else if (scope.alive()) {
          showFailure(!active && isChild ? '暂时无法停用该幼儿，请刷新后重试。' : fixedFailure);
          restoreFocus = true;
        }
      } finally {
        mutation = null;
        if (action && scope.alive()) {
          action.disabled = false;
          if (restoreFocus && action.isConnected) action.focus();
        }
      }
    };

    const openStateDialog = (item, launcher) => {
      const name = displayName(item);
      const dialog = h('dialog', { 'aria-label': `停用${name}` });
      const copy = isChild
        ? `停用后不再参与值日展示；${item.future_roster_entries} 条未来排班保留为历史数据，历史记录不会删除。`
        : `停用后仍保留 ${item.historical_feeding_log_count} 条喂养记录和档案，不会删除历史。`;
      const cancel = h('button', { type: 'button', class: 'btn gray', text: '取消' });
      const confirm = h('button', { type: 'button', class: 'btn', text: '确认停用' });
      dialog.append(h('p', { text: copy }), cancel, confirm);
      view.append(dialog);
      const cancelDialog = () => { dialog.close(); dialog.remove(); launcher.focus(); };
      cancel.addEventListener('click', cancelDialog);
      dialog.addEventListener('cancel', event => { event.preventDefault(); cancelDialog(); });
      confirm.addEventListener('click', () => { dialog.close(); dialog.remove(); void changeState(item, false, launcher); });
      dialog.showModal();
    };

    const openArchive = async (item, summarize = false, action = null) => {
      if (mutation) return;
      mutation = `archive-${item.id}`;
      if (action) action.disabled = true;
      try {
        const response = await scope.run(`/api/ducks/${item.id}/${summarize ? 'summarize' : 'archive'}`, summarize ? { method: 'POST' } : {});
        if (!response.current) return;
        const ack = validateArchive(response.result, item.id, { requireSummary: summarize });
        const panel = h('section', { class: 'card duck-archive', 'aria-label': `小鸭档案：${item.name}` });
        panel.append(h('h2', { text: `小鸭档案：${item.name}` }), h('p', { text: ack.summary?.trim() || '暂无档案内容' }));
        const previous = view.querySelector('.duck-archive');
        if (previous) previous.remove();
        view.append(panel);
      } catch (_error) {
        if (scope.alive()) showFailure();
      } finally {
        mutation = null;
        if (action && scope.alive()) action.disabled = false;
      }
    };

    const render = () => {
      list.replaceChildren();
      if (!rows.length) { list.append(h('p', { class: 'card muted', text: isChild ? '暂无幼儿' : '暂无小鸭' })); return; }
      for (const item of rows) {
        const card = h('article', { class: 'card management-card' });
        card.append(h('h2', { text: displayName(item) }), h('p', { text: item.active ? '启用中' : '已停用' }));
        const edit = h('button', { type: 'button', class: 'btn gray', text: `编辑：${displayName(item)}` });
        edit.addEventListener('click', () => {
          editingId = item.id;
          nameInput.value = item.name;
          secondInput.value = isChild ? item.nickname || '' : item.status || '';
          avatarInput.value = item.avatar || '';
          if (noteInput) noteInput.value = item.note || '';
          submit.textContent = isChild ? '保存幼儿' : '保存小鸭';
          nameInput.focus();
        });
        const stateButton = h('button', {
          type: 'button', class: 'btn gray',
          text: item.active ? `停用：${displayName(item)}` : `恢复：${displayName(item)}`,
        });
        if (isChild && item.has_active_conversation) {
          stateButton.disabled = true;
          card.append(h('p', { class: 'muted', text: '当前有进行中的会话，暂不能停用。' }));
        }
        stateButton.addEventListener('click', () => item.active ? openStateDialog(item, stateButton) : void changeState(item, true, stateButton));
        card.append(edit, stateButton);
        if (!isChild) {
          const archive = h('button', { type: 'button', class: 'btn gray', text: `查看档案：${item.name}` });
          const summarize = h('button', { type: 'button', class: 'btn gray', text: `生成档案：${item.name}` });
          archive.addEventListener('click', () => void openArchive(item, false, archive));
          summarize.addEventListener('click', () => void openArchive(item, true, summarize));
          card.append(archive, summarize);
        }
        list.append(card);
      }
    };

    const reload = async () => {
      const token = scope.next();
      try {
        const response = await scope.run(collectionPath, {}, token);
        if (!response.current) return;
        rows = isChild ? parseChildren(response.result) : parseDucks(response.result);
        render();
      } catch (_error) { if (scope.alive(token)) showFailure('列表加载失败，请重试。'); }
    };

    form.addEventListener('submit', event => {
      event.preventDefault();
      if (mutation || !form.reportValidity()) return;
      const normalized = isChild ? {
        name: nameInput.value.trim(), nickname: secondInput.value.trim() || null, avatar: avatarInput.value.trim() || null,
      } : {
        name: nameInput.value.trim(), avatar: avatarInput.value.trim() || null,
        status: secondInput.value.trim() || null, note: noteInput.value.trim() || null,
      };
      if (!normalized.name) { nameInput.setAttribute('aria-invalid', 'true'); nameInput.focus(); return; }
      mutation = 'form';
      setBusy(true);
      void (async () => {
        try {
          const response = await scope.run(`/${isChild ? 'api/children' : 'api/ducks'}${editingId ? `/${editingId}` : ''}`, {
            method: editingId ? 'PUT' : 'POST', body: normalized,
          });
          if (!response.current) return;
          if (isChild) {
            const existing = editingId === null ? null : rows.find(item => item.id === editingId);
            if (editingId !== null && !existing) throw invalid();
            validateChildAck(response.result, {
              expectedId: editingId,
              active: existing ? existing.active : true,
              ...normalized,
            });
          }
          else validateDuckAck(response.result, { expectedId: editingId, ...normalized });
          editingId = null;
          form.reset();
          submit.textContent = isChild ? '添加幼儿' : '添加小鸭';
          await reload();
          if (scope.alive()) showSuccess('已保存');
        } catch (_error) { if (scope.alive()) showFailure(); }
        finally { mutation = null; if (scope.alive()) setBusy(false); }
      })();
    });
    void reload();
    return { cleanup: () => { dismissUndo(undoState); scope.cleanup(); } };
  };

  const roster = context => {
    const scope = scopeFor(context);
    const view = h('section', { class: 'management-view roster-view' });
    const status = h('p', { role: 'status', 'aria-live': 'polite' });
    const manual = h('form', { class: 'card management-form' });
    const automatic = h('form', { class: 'card management-form' });
    const rosterList = h('div', { class: 'card management-list' });
    view.append(h('h1', { text: '值日排班' }), manual, automatic, status, rosterList);
    context.root.replaceChildren(view);
    let children = [];
    let rows = [];
    let busy = false;
    let retained = null;

    const manualDate = h('input', { type: 'date', required: '' });
    const manualCycle = h('input', { required: '', maxlength: '64' });
    const choices = h('fieldset', {}, h('legend', { text: '选择两名值日幼儿' }));
    const manualButton = h('button', { type: 'submit', class: 'btn', text: '保存当日排班' });
    manual.append(field('排班日期', manualDate), field('手动排班周期', manualCycle), choices, manualButton);

    const startDate = h('input', { type: 'date', required: '' });
    const days = h('input', { type: 'number', required: '', min: '1', max: '31', value: '5' });
    const autoCycle = h('input', { required: '', maxlength: '64' });
    const replace = h('input', { type: 'checkbox' });
    const autoButton = h('button', { type: 'submit', class: 'btn', text: '生成排班' });
    automatic.append(field('自动排班开始日期', startDate), field('自动排班天数', days), field('自动排班周期', autoCycle), field('替换已有排班', replace), autoButton);

    const invalidate = () => { retained = null; };
    for (const form of [manual, automatic]) form.addEventListener('input', invalidate);
    const setBusy = value => {
      busy = value;
      for (const control of view.querySelectorAll('input, button')) control.disabled = value;
    };
    const render = () => {
      choices.querySelectorAll('label').forEach(node => node.remove());
      for (const child of children.filter(item => item.active)) {
        const checkbox = h('input', { type: 'checkbox', value: String(child.id) });
        choices.append(field(`选择${displayName(child)}`, checkbox));
      }
      rosterList.replaceChildren();
      const names = new Map(children.map(child => [child.id, displayName(child)]));
      const grouped = new Map();
      for (const row of rows) {
        if (!names.has(row.child_id)) throw invalid();
        const item = grouped.get(row.date) || { cycle: row.cycle, names: [] };
        if (item.cycle !== row.cycle) throw invalid();
        item.names.push(names.get(row.child_id));
        grouped.set(row.date, item);
      }
      if (!grouped.size) rosterList.append(h('p', { class: 'muted', text: '暂无排班' }));
      for (const [date, item] of grouped) rosterList.append(h('p', { text: `${date} · ${item.cycle} · ${item.names.join('、')}` }));
    };
    const reload = async () => {
      const token = scope.next();
      try {
        const [rosterResponse, childResponse] = await Promise.all([
          scope.run('/api/roster', {}, token),
          scope.run('/api/children?include_inactive=true', {}, token),
        ]);
        if (!rosterResponse.current || !childResponse.current) return;
        rows = parseRosterRows(rosterResponse.result);
        children = parseChildren(childResponse.result);
        render();
      } catch (_error) {
        if (scope.alive(token)) {
          rows = [];
          children = [];
          choices.querySelectorAll('label').forEach(node => node.remove());
          rosterList.replaceChildren();
          status.setAttribute('role', 'alert');
          status.textContent = '排班加载失败，请重试。';
        }
      }
    };

    const submitMutation = async (kind, snapshot) => {
      if (busy) return;
      const action = kind === 'daily' ? manualButton : autoButton;
      let restoreFocus = false;
      setBusy(true);
      retained = snapshot;
      try {
        const path = kind === 'daily' ? `/api/roster/${snapshot.date}` : '/api/roster/auto';
        const body = kind === 'daily'
          ? { request_id: snapshot.requestId, cycle: snapshot.cycle, child_ids: snapshot.childIds }
          : { request_id: snapshot.requestId, start_date: snapshot.startDate, days: snapshot.days, cycle: snapshot.cycle, replace_existing: snapshot.replaceExisting };
        const response = await scope.run(path, { method: kind === 'daily' ? 'PUT' : 'POST', body, requestId: snapshot.requestId });
        if (!response.current) return;
        if (kind === 'daily') validateDailyRosterAck(response.result, snapshot);
        else validateAutoRosterAck(response.result, snapshot);
        retained = null;
        status.setAttribute('role', 'status');
        status.textContent = '排班已保存';
        await reload();
      } catch (_error) {
        if (scope.alive()) {
          status.setAttribute('role', 'alert');
          status.textContent = '排班保存失败，请使用相同内容重试。';
          restoreFocus = true;
        }
      } finally {
        if (scope.alive()) {
          setBusy(false);
          if (restoreFocus && action.isConnected) action.focus();
        }
      }
    };
    manual.addEventListener('submit', event => {
      event.preventDefault();
      if (!manual.reportValidity()) return;
      const selected = [...choices.querySelectorAll('input:checked')].map(input => Number(input.value)).sort((a, b) => a - b);
      const date = manualDate.value;
      const cycle = manualCycle.value.trim();
      if (!dateString(date) || !cycle || selected.length !== 2 || selected[0] === selected[1]) {
        status.setAttribute('role', 'alert'); status.textContent = '请选择有效日期、周期和两名不同幼儿。'; return;
      }
      const normalized = { date, cycle, childIds: selected };
      const snapshot = retained && retained.kind === 'daily' && JSON.stringify(retained.normalized) === JSON.stringify(normalized)
        ? retained : { kind: 'daily', normalized, requestId: createRequestId(), ...normalized };
      void submitMutation('daily', snapshot);
    });
    automatic.addEventListener('submit', event => {
      event.preventDefault();
      if (!automatic.reportValidity()) return;
      const normalized = {
        startDate: startDate.value,
        days: Number(days.value),
        cycle: autoCycle.value.trim(),
        replaceExisting: replace.checked,
        activeChildIds: children.filter(item => item.active).map(item => item.id).sort((a, b) => a - b),
      };
      if (!dateString(normalized.startDate) || !Number.isInteger(normalized.days) || normalized.days < 1 || normalized.days > 31 || !normalized.cycle) {
        status.setAttribute('role', 'alert'); status.textContent = '请输入有效的自动排班参数。'; return;
      }
      const snapshot = retained && retained.kind === 'auto' && JSON.stringify(retained.normalized) === JSON.stringify(normalized)
        ? retained : { kind: 'auto', normalized, requestId: createRequestId(), ...normalized };
      void submitMutation('auto', snapshot);
    });
    void reload();
    return { cleanup: scope.cleanup };
  };

  return {
    children: createResourceRoute('child'),
    ducks: createResourceRoute('duck'),
    roster,
  };
}
