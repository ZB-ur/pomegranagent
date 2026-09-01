import { renderAvatarImage } from '../../shared/avatar.mjs';

const CHILD_KEYS = ['id', 'name', 'nickname', 'avatar', 'active', 'deactivated_at', 'future_roster_entries', 'has_active_conversation'];
const DUCK_KEYS = ['id', 'name', 'avatar', 'status', 'note', 'active', 'deactivated_at', 'historical_feeding_log_count'];
const CANONICAL_AVATAR = /^\/api\/media\/avatars\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const CANONICAL_V4_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

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

function optionalAvatar(value) {
  return value === null || (typeof value === 'string' && CANONICAL_AVATAR.test(value));
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
        !optionalString(row.nickname, 64) || !optionalAvatar(row.avatar) || typeof row.active !== 'boolean' ||
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
        !optionalAvatar(row.avatar) || !optionalString(row.status, 255) || !optionalString(row.note, 2000) ||
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

export function validateAvatarMediaAck(value) {
  const row = record(value, ['id', 'url', 'mime_type', 'width', 'height', 'size_bytes', 'sha256']);
  if (typeof row.id !== 'string' || !CANONICAL_V4_UUID.test(row.id) ||
      row.url !== `/api/media/avatars/${row.id}` || !CANONICAL_AVATAR.test(row.url) ||
      row.mime_type !== 'image/webp' || !positive(row.width) || row.width > 1024 ||
      !positive(row.height) || row.height > 1024 || !positive(row.size_bytes) ||
      row.size_bytes > 5 * 1024 * 1024 || typeof row.sha256 !== 'string' ||
      !/^[0-9a-f]{64}$/.test(row.sha256)) throw invalid();
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
  const avatarFallback = item => Array.from(displayName(item).trim())[0] || '?';
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
    const noun = isChild ? '幼儿' : '小鸭';
    const title = `${noun}管理`;
    const collectionPath = isChild ? '/api/children?include_inactive=true' : '/api/ducks?include_inactive=true';
    const scope = scopeFor(context);
    let rows = [];
    let mutation = null;
    let undoState = null;
    let disposed = false;
    const dialogs = new Set();
    const dialogCleanups = new Map();
    const view = h('section', { class: `management-view${isChild ? '' : ' ducks-workspace'}` });
    const hero = h('header', { class: 'management-hero' });
    const heroCopy = h('div', { class: 'management-copy' },
      h('p', { class: 'management-eyebrow', text: isChild ? '班级成员' : '陪伴伙伴' }),
      h('h1', { text: title }),
      h('p', {
        class: 'management-description',
        text: isChild ? '查看班级幼儿状态，并在独立窗口中完成新增或修改。' : '管理小鸭资料、状态与成长档案。',
      }),
    );
    const add = h('button', { type: 'button', class: 'btn', text: `添加${noun}` });
    hero.append(heroCopy, h('div', { class: 'management-toolbar' }, add));
    const feedback = h('p', { role: 'status', 'aria-live': 'polite', class: 'management-status' });
    const listCard = h('section', { class: `card management-list-card${isChild ? '' : ' duck-list-panel'}` });
    const count = h('span', { class: 'management-count', text: '0 项' });
    listCard.append(
      h('header', { class: 'management-list-header' }, h('h2', { text: `${noun}列表` }), count),
    );
    const list = h('div', { class: 'management-list' });
    listCard.append(list);
    view.append(hero, feedback, listCard);
    const archivePanel = isChild ? null : h('section', {
      class: 'card duck-archive', 'aria-label': '小鸭成长档案',
    },
    h('h2', { text: '小鸭成长档案' }),
    h('p', { text: '选择一只小鸭查看档案，或生成最新摘要。' }),
    );
    if (archivePanel) view.append(archivePanel);
    context.root.replaceChildren(view);

    const showFailure = copy => {
      feedback.setAttribute('role', 'alert');
      feedback.textContent = copy || fixedFailure;
    };
    const showSuccess = copy => {
      feedback.setAttribute('role', 'status');
      feedback.textContent = copy;
    };

    const forgetDialog = dialog => {
      dialogs.delete(dialog);
      const cleanup = dialogCleanups.get(dialog);
      dialogCleanups.delete(dialog);
      if (cleanup) cleanup();
      if (dialog.isConnected) dialog.remove();
    };
    const closeDialog = (dialog, focusTarget = null) => {
      if (dialog.open) dialog.close();
      forgetDialog(dialog);
      if (!disposed && focusTarget?.isConnected) focusTarget.focus();
    };
    const mountDialog = (dialog, launcher) => {
      dialogs.add(dialog);
      view.append(dialog);
      dialog.addEventListener('cancel', event => {
        event.preventDefault();
        if (!mutation) closeDialog(dialog, launcher);
      });
      dialog.showModal();
    };

    const renderAvatar = item => {
      const avatar = renderAvatarImage(document, item.avatar, avatarFallback(item));
      avatar.setAttribute('class', 'management-avatar');
      avatar.setAttribute('aria-hidden', 'true');
      return avatar;
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
      const dialog = h('dialog', { 'aria-label': `停用${name}`, class: 'management-dialog' });
      const copy = isChild
        ? `停用后不再参与值日展示；${item.future_roster_entries} 条未来排班保留为历史数据，历史记录不会删除。`
        : `停用后仍保留 ${item.historical_feeding_log_count} 条喂养记录和档案，不会删除历史。`;
      const cancel = h('button', { type: 'button', class: 'btn gray', text: '取消' });
      const confirm = h('button', { type: 'button', class: 'btn', text: '确认停用' });
      dialog.append(
        h('header', { class: 'management-dialog-header' }, h('h2', { text: `停用${name}` })),
        h('div', { class: 'management-dialog-body' }, h('p', { text: copy })),
        h('footer', { class: 'management-dialog-actions' }, cancel, confirm),
      );
      cancel.addEventListener('click', () => closeDialog(dialog, launcher));
      confirm.addEventListener('click', () => {
        closeDialog(dialog);
        void changeState(item, false, launcher);
      });
      mountDialog(dialog, launcher);
    };

    const openArchive = async (item, summarize = false, action = null) => {
      if (mutation) return;
      mutation = `archive-${item.id}`;
      if (action) action.disabled = true;
      try {
        const response = await scope.run(`/api/ducks/${item.id}/${summarize ? 'summarize' : 'archive'}`, summarize ? { method: 'POST' } : {});
        if (!response.current) return;
        const ack = validateArchive(response.result, item.id, { requireSummary: summarize });
        archivePanel.setAttribute('aria-label', `小鸭档案：${item.name}`);
        archivePanel.replaceChildren(
          h('h2', { text: `小鸭档案：${item.name}` }),
          h('p', { text: ack.summary?.trim() || '暂无档案内容' }),
        );
      } catch (_error) {
        if (scope.alive()) showFailure();
      } finally {
        mutation = null;
        if (action && scope.alive()) action.disabled = false;
      }
    };

    const openEditor = (item, launcher) => {
      if (mutation) return;
      const editing = item !== null;
      const visibleName = editing ? displayName(item) : '';
      const dialogName = editing ? `修改${noun}：${visibleName}` : `新增${noun}`;
      const dialog = h('dialog', { 'aria-label': dialogName, class: 'management-dialog' });
      const formId = `management-${kind}-${editing ? item.id : 'new'}-form`;
      const form = h('form', { class: 'management-form', id: formId });
      const nameInput = h('input', {
        required: '', maxlength: '64', autocomplete: 'off', value: editing ? item.name : '',
      });
      const secondInput = h('input', {
        maxlength: isChild ? '64' : '255', autocomplete: 'off',
        value: editing ? (isChild ? item.nickname || '' : item.status || '') : '',
      });
      const noteInput = isChild ? null : h('textarea', { maxlength: '2000' });
      if (noteInput && editing) noteInput.value = item.note || '';
      const previewItem = editing ? item : { name: noun, nickname: null, avatar: null };
      const preview = h('div', {
        class: 'management-avatar-preview', 'data-avatar-preview': '', 'aria-hidden': 'true',
      });
      const fileInput = h('input', {
        type: 'file', accept: 'image/jpeg,image/png,image/webp',
      });
      const removeAvatar = h('button', {
        type: 'button', class: 'btn gray', text: '移除头像',
      });
      const avatarNote = h('p', {
        class: 'management-capability-note',
        text: '支持 JPEG、PNG、WebP；将安全转换为最长边 1024 像素的 WebP。',
      });
      const avatarControls = h('div', { class: 'management-avatar-controls' },
        field('头像图片', fileInput),
        removeAvatar,
      );
      const avatarField = h('section', { class: 'management-avatar-field', 'aria-label': '头像设置' },
        preview,
        avatarControls,
        avatarNote,
      );
      const dialogStatus = h('p', {
        role: 'status', 'aria-live': 'polite', class: 'management-dialog-status',
      });
      const cancel = h('button', { type: 'button', class: 'btn gray', text: '取消' });
      const submit = h('button', {
        type: 'submit', form: formId, class: 'btn', text: editing ? `保存${noun}` : `添加${noun}`,
      });
      form.append(
        field(isChild ? '幼儿姓名' : '小鸭名字', nameInput),
        field(isChild ? '小名' : '状态', secondInput),
        avatarField,
      );
      if (noteInput) form.append(field('备注', noteInput));
      form.append(dialogStatus);
      dialog.append(
        h('header', { class: 'management-dialog-header' },
          h('p', { class: 'management-eyebrow', text: editing ? '编辑资料' : '添加资料' }),
          h('h2', { text: dialogName }),
        ),
        h('div', { class: 'management-dialog-body' }, form),
        h('footer', { class: 'management-dialog-actions' }, cancel, submit),
      );

      const setFormBusy = busy => {
        for (const control of dialog.querySelectorAll('input, textarea, button')) control.disabled = busy;
        if (!busy && !editing && !fileInput.files?.length) removeAvatar.disabled = true;
      };
      const fail = copy => {
        dialogStatus.setAttribute('role', 'alert');
        dialogStatus.textContent = copy || fixedFailure;
      };
      let selectedFile = null;
      let shouldRemoveAvatar = false;
      let previewURL = null;
      let retainedSubmission = null;
      const releasePreviewURL = () => {
        if (previewURL === null) return;
        try { globalThis.URL.revokeObjectURL(previewURL); } catch (_error) {}
        previewURL = null;
      };
      const localPreview = url => {
        const shell = h('span', { class: 'management-avatar', 'aria-hidden': 'true' });
        const fallback = h('span', { class: 'avatar-fallback', text: avatarFallback(previewItem) });
        const image = h('img', { src: url, alt: '', decoding: 'async', draggable: 'false' });
        fallback.hidden = true;
        let failed = false;
        image.addEventListener('error', () => {
          if (failed) return;
          failed = true;
          fallback.hidden = false;
          shell.replaceChildren(fallback);
        }, { once: true });
        shell.append(image, fallback);
        return shell;
      };
      const renderPreview = () => {
        if (previewURL !== null) preview.replaceChildren(localPreview(previewURL));
        else if (shouldRemoveAvatar) preview.replaceChildren(renderAvatar({ ...previewItem, avatar: null }));
        else preview.replaceChildren(renderAvatar(previewItem));
      };
      const invalidateSubmission = () => { retainedSubmission = null; };
      dialogCleanups.set(dialog, releasePreviewURL);
      renderPreview();
      removeAvatar.disabled = !editing;
      fileInput.addEventListener('change', () => {
        invalidateSubmission();
        releasePreviewURL();
        const next = fileInput.files?.[0] || null;
        selectedFile = next;
        shouldRemoveAvatar = false;
        avatarNote.textContent = '支持 JPEG、PNG、WebP；将安全转换为最长边 1024 像素的 WebP。';
        if (next !== null) {
          try {
            previewURL = globalThis.URL.createObjectURL(next);
          } catch (_error) {
            selectedFile = null;
            fileInput.value = '';
            fail('无法预览所选图片，请重新选择。');
          }
        }
        removeAvatar.disabled = selectedFile === null && !editing;
        renderPreview();
      });
      removeAvatar.addEventListener('click', () => {
        invalidateSubmission();
        releasePreviewURL();
        selectedFile = null;
        fileInput.value = '';
        shouldRemoveAvatar = true;
        removeAvatar.disabled = true;
        avatarNote.textContent = '已选择移除头像，保存后生效。';
        renderPreview();
      });
      form.addEventListener('input', event => {
        if (event.target !== fileInput) invalidateSubmission();
      });
      form.addEventListener('change', event => {
        if (event.target !== fileInput) invalidateSubmission();
      });
      cancel.addEventListener('click', () => closeDialog(dialog, launcher));
      form.addEventListener('submit', event => {
        event.preventDefault();
        if (mutation || !form.reportValidity()) return;
        const fields = isChild ? {
          name: nameInput.value.trim(),
          nickname: secondInput.value.trim() || null,
        } : {
          name: nameInput.value.trim(),
          status: secondInput.value.trim() || null,
          note: noteInput.value.trim() || null,
        };
        if (!fields.name) {
          nameInput.setAttribute('aria-invalid', 'true');
          nameInput.focus();
          return;
        }
        nameInput.removeAttribute('aria-invalid');
        const signature = JSON.stringify({
          fields,
          avatarMode: shouldRemoveAvatar ? 'remove' : selectedFile === null ? 'keep' : 'upload',
          originalAvatar: editing ? item.avatar : null,
        });
        const snapshot = retainedSubmission !== null && retainedSubmission.signature === signature &&
          retainedSubmission.file === selectedFile
          ? retainedSubmission
          : {
            signature,
            fields,
            file: selectedFile,
            removeAvatar: shouldRemoveAvatar,
            requestId: createRequestId(),
            uploadedAvatar: null,
          };
        if (!uuid(snapshot.requestId)) throw invalid();
        retainedSubmission = snapshot;
        mutation = 'form';
        setFormBusy(true);
        void (async () => {
          let restoreFocus = false;
          let phase = snapshot.file !== null && snapshot.uploadedAvatar === null ? 'upload' : 'resource';
          try {
            if (snapshot.file !== null && snapshot.uploadedAvatar === null) {
              const uploadBody = new FormData();
              uploadBody.append('file', snapshot.file, snapshot.file.name);
              const upload = await scope.run('/api/media/avatars', {
                method: 'POST', body: uploadBody, requestId: snapshot.requestId,
              });
              if (!upload.current) return;
              snapshot.uploadedAvatar = validateAvatarMediaAck(upload.result).url;
            }
            phase = 'resource';
            const normalized = {
              ...snapshot.fields,
              avatar: snapshot.removeAvatar
                ? null
                : snapshot.uploadedAvatar || (editing ? item.avatar : null),
            };
            const response = await scope.run(`/api/${isChild ? 'children' : 'ducks'}${editing ? `/${item.id}` : ''}`, {
              method: editing ? 'PUT' : 'POST', body: normalized, requestId: snapshot.requestId,
            });
            if (!response.current) return;
            const ack = isChild
              ? validateChildAck(response.result, {
                expectedId: editing ? item.id : null,
                active: editing ? item.active : true,
                ...normalized,
              })
              : validateDuckAck(response.result, { expectedId: editing ? item.id : null, ...normalized });
            await reload();
            if (!scope.alive()) return;
            retainedSubmission = null;
            showSuccess('已保存');
            const nextEdit = list.querySelector(`[data-edit-id="${ack.id}"]`);
            closeDialog(dialog, nextEdit || add);
          } catch (_error) {
            if (scope.alive()) {
              fail(phase === 'upload'
                ? '头像上传失败，表单内容已保留，请重试。'
                : '保存失败，表单内容已保留，请重试。');
              restoreFocus = true;
            }
          } finally {
            mutation = null;
            if (scope.alive()) {
              setFormBusy(false);
              if (restoreFocus && submit.isConnected) submit.focus();
            }
          }
        })();
      });
      mountDialog(dialog, launcher);
      nameInput.focus();
    };

    const render = () => {
      list.replaceChildren();
      count.textContent = `${rows.length} 项`;
      if (!rows.length) { list.append(h('p', { class: 'muted', text: `暂无${noun}` })); return; }
      for (const item of rows) {
        const card = h('article', { class: 'management-row' });
        const rowCopy = h('div', { class: 'management-row-copy' },
          h('h3', { text: displayName(item) }),
          h('p', {
            class: 'management-row-meta',
            text: isChild
              ? `${item.nickname ? `姓名：${item.name} · ` : ''}未来排班 ${item.future_roster_entries} 条`
              : `${item.status?.trim() || '状态待补充'} · 喂养记录 ${item.historical_feeding_log_count} 条`,
          }),
        );
        const badge = h('span', {
          class: `management-badge ${item.active ? 'is-active' : 'is-inactive'}`,
          text: item.active ? '启用中' : '已停用',
        });
        card.append(h('div', { class: 'management-row-main' }, renderAvatar(item), rowCopy, badge));
        const actions = h('div', { class: 'management-row-actions' });
        const edit = h('button', {
          type: 'button', class: 'btn gray', text: '编辑',
          'aria-label': `编辑：${displayName(item)}`, 'data-edit-id': String(item.id),
        });
        edit.addEventListener('click', () => openEditor(item, edit));
        const stateButton = h('button', {
          type: 'button', class: 'btn gray', text: item.active ? '停用' : '恢复',
          'aria-label': item.active ? `停用：${displayName(item)}` : `恢复：${displayName(item)}`,
        });
        if (isChild && item.has_active_conversation) {
          stateButton.disabled = true;
          rowCopy.append(h('p', { class: 'muted', text: '当前有进行中的会话，暂不能停用。' }));
        }
        stateButton.addEventListener('click', () => item.active ? openStateDialog(item, stateButton) : void changeState(item, true, stateButton));
        actions.append(edit, stateButton);
        if (!isChild) {
          const archive = h('button', {
            type: 'button', class: 'btn gray', text: '查看档案', 'aria-label': `查看档案：${item.name}`,
          });
          const summarize = h('button', {
            type: 'button', class: 'btn gray', text: '生成档案', 'aria-label': `生成档案：${item.name}`,
          });
          archive.addEventListener('click', () => void openArchive(item, false, archive));
          summarize.addEventListener('click', () => void openArchive(item, true, summarize));
          actions.append(archive, summarize);
        }
        card.append(actions);
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

    add.addEventListener('click', () => openEditor(null, add));
    void reload();
    return { cleanup: () => {
      disposed = true;
      dismissUndo(undoState);
      scope.cleanup();
      for (const dialog of dialogs) {
        const cleanup = dialogCleanups.get(dialog);
        if (cleanup) cleanup();
        if (dialog.open) dialog.close();
        if (dialog.isConnected) dialog.remove();
      }
      dialogs.clear();
      dialogCleanups.clear();
    } };
  };

  const roster = context => {
    const scope = scopeFor(context);
    const view = h('section', { class: 'management-view roster-view' });
    let children = [];
    let rows = [];
    let busy = false;
    let retained = null;
    let disposed = false;
    const dialogs = new Set();
    const hero = h('header', { class: 'management-hero' });
    const heroCopy = h('div', { class: 'management-copy' },
      h('p', { class: 'management-eyebrow', text: '班级值日' }),
      h('h1', { text: '值日排班' }),
      h('p', { class: 'management-description', text: '先查看排班，再按需安排当日搭档或自动生成工作日排班。' }),
    );
    const monthlyLauncher = h('button', {
      type: 'button', class: 'btn gray', text: '录入本月名单', disabled: '',
      'aria-describedby': 'roster-monthly-capability',
    });
    const manualLauncher = h('button', { type: 'button', class: 'btn', text: '安排当日' });
    const automaticLauncher = h('button', { type: 'button', class: 'btn gray', text: '自动生成' });
    hero.append(heroCopy, h('div', { class: 'management-toolbar' }, monthlyLauncher));
    const capability = h('p', {
      id: 'roster-monthly-capability', class: 'roster-capability',
      text: '按多日期录入本月名单待批量 API 开放后启用；当前可安排单日或自动生成连续工作日。',
    });
    const status = h('p', { role: 'status', 'aria-live': 'polite', class: 'management-status' });
    const rosterCard = h('section', { class: 'card management-list-card roster-preview' });
    const rosterCount = h('span', { class: 'management-count', text: '0 天' });
    const rosterList = h('div', { class: 'management-list' });
    const rosterPanelFooter = h('footer', { class: 'roster-panel-footer' },
      h('div', { class: 'management-copy' },
        h('h3', { text: '临时调班与兜底' }),
        h('p', { text: '病假等情况可安排当日；没有报名名单时使用自动生成。' }),
      ),
      h('div', { class: 'roster-actions' }, manualLauncher, automaticLauncher),
    );
    rosterCard.append(
      h('header', { class: 'management-list-header' }, h('h2', { text: '排班预览' }), rosterCount),
      rosterList,
      rosterPanelFooter,
    );
    view.append(hero, capability, status, rosterCard);
    context.root.replaceChildren(view);

    const forgetDialog = dialog => {
      dialogs.delete(dialog);
      if (dialog.isConnected) dialog.remove();
    };
    const closeDialog = (dialog, launcher, { discardRetry = false } = {}) => {
      if (discardRetry) retained = null;
      if (dialog.open) dialog.close();
      forgetDialog(dialog);
      if (!disposed && launcher?.isConnected) launcher.focus();
    };
    const mountDialog = (dialog, launcher) => {
      dialogs.add(dialog);
      view.append(dialog);
      dialog.addEventListener('cancel', event => {
        event.preventDefault();
        if (!busy) closeDialog(dialog, launcher, { discardRetry: true });
      });
      dialog.showModal();
    };

    const setBusy = value => {
      busy = value;
      for (const control of view.querySelectorAll('input, select, textarea, button')) control.disabled = value;
      if (!value) monthlyLauncher.disabled = true;
    };
    const render = () => {
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
      rosterCount.textContent = `${grouped.size} 天`;
      if (!grouped.size) rosterList.append(h('p', { class: 'muted', text: '暂无排班' }));
      for (const [date, item] of [...grouped].sort(([left], [right]) => left.localeCompare(right))) {
        const projection = `${date} · ${item.cycle} · ${item.names.join('、')}`;
        rosterList.append(h('article', { class: 'management-row roster-row', 'aria-label': projection },
          h('div', { class: 'roster-date', text: date }),
          h('div', { class: 'roster-people' }, ...item.names.map(name => h('span', { class: 'roster-person', text: name }))),
          h('footer', { class: 'roster-footer' },
            h('span', { class: 'management-badge is-active', text: item.cycle }),
            h('p', { class: 'management-row-copy', text: projection }),
          ),
        ));
      }
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
          rosterList.replaceChildren();
          rosterCount.textContent = '0 天';
          status.setAttribute('role', 'alert');
          status.textContent = '排班加载失败，请重试。';
        }
      }
    };

    const submitMutation = async (kind, snapshot, ui) => {
      if (busy) return;
      let succeeded = false;
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
        succeeded = scope.alive();
      } catch (_error) {
        if (scope.alive()) {
          ui.dialogStatus.setAttribute('role', 'alert');
          ui.dialogStatus.textContent = '排班保存失败，请使用相同内容重试。';
        }
      } finally {
        if (scope.alive()) {
          setBusy(false);
          if (succeeded) closeDialog(ui.dialog, ui.launcher);
          else if (ui.submit.isConnected) ui.submit.focus();
        }
      }
    };

    const option = (value, copy, selected = false) => h('option', {
      value, text: copy, ...(selected ? { selected: '' } : {}),
    });
    const activeChildren = () => children.filter(item => item.active);
    const addActiveOptions = select => {
      select.append(option('', '请选择', true));
      for (const child of activeChildren()) select.append(option(String(child.id), displayName(child)));
    };

    const openManual = () => {
      if (busy) return;
      retained = null;
      const dialog = h('dialog', { 'aria-label': '安排当日值日', class: 'management-dialog' });
      const formId = 'management-roster-daily-form';
      const form = h('form', { id: formId, class: 'management-form' });
      const manualDate = h('input', { type: 'date', required: '' });
      const manualCycle = h('input', { required: '', maxlength: '64', autocomplete: 'off' });
      const first = h('select', { required: '', 'aria-label': '值日幼儿 1' });
      const second = h('select', { required: '', 'aria-label': '值日幼儿 2' });
      addActiveOptions(first);
      addActiveOptions(second);
      const dialogStatus = h('p', { role: 'status', 'aria-live': 'polite', class: 'management-dialog-status' });
      const cancel = h('button', { type: 'button', class: 'btn gray', text: '取消' });
      const submit = h('button', { type: 'submit', form: formId, class: 'btn', text: '保存当日排班' });
      form.append(
        field('排班日期', manualDate),
        field('手动排班周期', manualCycle),
        field('值日幼儿 1', first),
        field('值日幼儿 2', second),
        dialogStatus,
      );
      dialog.append(
        h('header', { class: 'management-dialog-header' }, h('h2', { text: '安排当日值日' })),
        h('div', { class: 'management-dialog-body' }, form),
        h('footer', { class: 'management-dialog-actions' }, cancel, submit),
      );
      const invalidate = () => { retained = null; };
      form.addEventListener('input', invalidate);
      form.addEventListener('change', invalidate);
      cancel.addEventListener('click', () => closeDialog(dialog, manualLauncher, { discardRetry: true }));
      form.addEventListener('submit', event => {
        event.preventDefault();
        if (busy || !form.reportValidity()) return;
        const normalized = {
          date: manualDate.value,
          cycle: manualCycle.value.trim(),
          childIds: [Number(first.value), Number(second.value)].sort((left, right) => left - right),
        };
        if (!dateString(normalized.date) || !normalized.cycle ||
            normalized.childIds.some(id => !positive(id)) || normalized.childIds[0] === normalized.childIds[1]) {
          dialogStatus.setAttribute('role', 'alert');
          dialogStatus.textContent = '请选择有效日期、周期和两名不同幼儿。';
          if (normalized.childIds[0] === normalized.childIds[1]) second.focus();
          else submit.focus();
          return;
        }
        const snapshot = retained && retained.kind === 'daily' && JSON.stringify(retained.normalized) === JSON.stringify(normalized)
          ? retained : { kind: 'daily', normalized, requestId: createRequestId(), ...normalized };
        void submitMutation('daily', snapshot, { dialog, launcher: manualLauncher, submit, dialogStatus });
      });
      mountDialog(dialog, manualLauncher);
      manualDate.focus();
    };

    const openAutomatic = () => {
      if (busy) return;
      retained = null;
      const dialog = h('dialog', { 'aria-label': '自动生成排班', class: 'management-dialog' });
      const formId = 'management-roster-auto-form';
      const form = h('form', { id: formId, class: 'management-form' });
      const startDate = h('input', { type: 'date', required: '' });
      const days = h('input', { type: 'number', required: '', min: '1', max: '31', value: '5' });
      const autoCycle = h('input', { required: '', maxlength: '64', autocomplete: 'off' });
      const replace = h('input', { type: 'checkbox' });
      const dialogStatus = h('p', { role: 'status', 'aria-live': 'polite', class: 'management-dialog-status' });
      const cancel = h('button', { type: 'button', class: 'btn gray', text: '取消' });
      const submit = h('button', { type: 'submit', form: formId, class: 'btn', text: '生成排班' });
      form.append(
        field('自动排班开始日期', startDate),
        field('自动排班天数', days),
        field('自动排班周期', autoCycle),
        field('替换已有排班', replace),
        dialogStatus,
      );
      dialog.append(
        h('header', { class: 'management-dialog-header' }, h('h2', { text: '自动生成排班' })),
        h('div', { class: 'management-dialog-body' }, form),
        h('footer', { class: 'management-dialog-actions' }, cancel, submit),
      );
      const invalidate = () => { retained = null; };
      form.addEventListener('input', invalidate);
      form.addEventListener('change', invalidate);
      cancel.addEventListener('click', () => closeDialog(dialog, automaticLauncher, { discardRetry: true }));
      form.addEventListener('submit', event => {
        event.preventDefault();
        if (busy || !form.reportValidity()) return;
        const normalized = {
          startDate: startDate.value,
          days: Number(days.value),
          cycle: autoCycle.value.trim(),
          replaceExisting: replace.checked,
          activeChildIds: activeChildren().map(item => item.id).sort((a, b) => a - b),
        };
        if (!dateString(normalized.startDate) || !Number.isInteger(normalized.days) ||
            normalized.days < 1 || normalized.days > 31 || !normalized.cycle || normalized.activeChildIds.length < 2) {
          dialogStatus.setAttribute('role', 'alert');
          dialogStatus.textContent = '请输入有效的自动排班参数，并确保至少有两名启用中的幼儿。';
          submit.focus();
          return;
        }
        const snapshot = retained && retained.kind === 'auto' && JSON.stringify(retained.normalized) === JSON.stringify(normalized)
          ? retained : { kind: 'auto', normalized, requestId: createRequestId(), ...normalized };
        void submitMutation('auto', snapshot, { dialog, launcher: automaticLauncher, submit, dialogStatus });
      });
      mountDialog(dialog, automaticLauncher);
      startDate.focus();
    };

    manualLauncher.addEventListener('click', openManual);
    automaticLauncher.addEventListener('click', openAutomatic);
    void reload();
    return { cleanup: () => {
      disposed = true;
      scope.cleanup();
      for (const dialog of dialogs) {
        if (dialog.open) dialog.close();
        if (dialog.isConnected) dialog.remove();
      }
      dialogs.clear();
    } };
  };

  return {
    children: createResourceRoute('child'),
    ducks: createResourceRoute('duck'),
    roster,
  };
}
