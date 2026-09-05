import { STATES, assertSnapshot, controlsFor } from './machine.mjs';
import { renderAvatarImage } from '../shared/avatar.mjs';

const ACTION_KEYS = Object.freeze([
  'onStart',
  'onSelectChild',
  'onRecordToggle',
  'onRetry',
  'onReset',
  'onOpenTeacherHelp',
  'onSubmitTeacherPin',
  'onSubmitTeacherText',
  'onSaveTeacherDraft',
  'onRetryTeacherRecovery',
  'onRetryMicrophone',
  'onEndWithTeacher',
  'onLockTeacherHelp',
]);
const DOM_KEYS = Object.freeze([
  'createElement',
  'createTextNode',
  'queueMicrotask',
  'isFocused',
]);
const FOCUS_SELECTORS = new Set([
  '#start-button',
  '#app-title',
  '#child-status',
  '#record-button',
  '#retry-button',
  '#reset-button',
  '#teacher-help-button',
]);
const ERROR_COPY = new Map([
  ['MIC_PERMISSION_DENIED', '麦克风没有开启，请老师帮忙'],
  ['MIC_UNAVAILABLE', '现在找不到麦克风，请老师帮忙'],
  ['SPEECH_UNSUPPORTED', '这个浏览器不能使用语音，请老师帮忙'],
  ['SPEECH_FAILED', '刚才没有听清，请老师帮忙'],
  ['LOCAL_STORAGE_FAILED', '浏览器没有安全保存这次对话，请老师帮忙'],
  ['IDEMPOTENCY_CONFLICT', '这句话的记录状态不一致，请老师确认'],
  ['RECOVERY_CHILD_MISMATCH', '无法安全确认是哪位小朋友的对话'],
  ['RECOVERY_CONVERSATION_MISMATCH', '无法安全确认要恢复哪一次对话'],
  ['RECOVERY_CONVERSATION_MISSING', '原来的对话暂时找不到'],
  ['RECOVERY_COMPLETION_BOUNDARY_MISSING', '结束对话所需的记录不完整'],
  ['MULTIPLE_ACTIVE_CONVERSATIONS', '发现多次未完成对话，需要老师选择'],
  ['ROSTER_CARDINALITY_INVALID', '今天的值日名单需要老师确认'],
]);
const RECOVERY_FALLBACK = '这次对话需要老师检查后再继续';
const PET_POSTER_BY_STATE = Object.freeze({
  welcome: '/assets/duck-front-512.png',
  loading_roster: '/assets/duck-front-512.png',
  selecting_child: '/assets/duck-side-512.png',
  opening: '/assets/duck-encouraging.png',
  ready: '/assets/duck-front-512.png',
  listening: '/assets/duck-listening.png',
  submitting: '/assets/duck-listening.png',
  speaking: '/assets/duck-encouraging.png',
  submission_failed: '/assets/duck-front-512.png',
  saving_conversation: '/assets/duck-listening.png',
  completed: '/assets/duck-happy.png',
  recovery: '/assets/duck-front-512.png',
});
const PET_POSTER_ALT_BY_STATE = Object.freeze({
  welcome: '',
  loading_roster: '',
  selecting_child: '',
  opening: '鸭鸭日记本正在和你打招呼',
  ready: '',
  listening: '鸭鸭日记本正在认真听',
  submitting: '',
  speaking: '鸭鸭日记本正在回答',
  submission_failed: '',
  saving_conversation: '',
  completed: '鸭鸭日记本开心地完成了记录',
  recovery: '',
});
const STATE_PRESENTATION = Object.freeze({
  welcome: Object.freeze({ lead: '准备好后，一起记录今天的小鸭故事。', pill: '准备开始' }),
  loading_roster: Object.freeze({ lead: '正在准备今天的值日名单。', pill: '正在准备' }),
  selecting_child: Object.freeze({ lead: '请选择今天值日的小朋友。', pill: '选一位小朋友' }),
  opening: Object.freeze({ lead: '日记本正在准备和你聊天。', pill: '正在打招呼' }),
  ready: Object.freeze({ lead: '想好以后，点一下开始说话。', pill: '可以说话' }),
  listening: Object.freeze({ lead: '日记本正在认真听。', pill: '正在听' }),
  submitting: Object.freeze({ lead: '正在把这句话发给日记本。', pill: '正在发送' }),
  speaking: Object.freeze({ lead: '日记本正在回答。', pill: '正在回答' }),
  submission_failed: Object.freeze({ lead: '原话已经保留，可以再试一次。', pill: '发送未完成' }),
  saving_conversation: Object.freeze({ lead: '正在安全保存今天的话。', pill: '正在保存' }),
  completed: Object.freeze({ lead: '今天的日记已经记好啦。', pill: '已经完成' }),
  recovery: Object.freeze({ lead: '请老师检查后再继续。', pill: '需要帮助' }),
});
const ACTION_TOKEN_TO_KEY = Object.freeze(Object.assign(Object.create(null), {
  start: 'onStart',
  'select-child': 'onSelectChild',
  'record-toggle': 'onRecordToggle',
  retry: 'onRetry',
  reset: 'onReset',
  'open-teacher-help': 'onOpenTeacherHelp',
}));
const TEACHER_TOKEN_TO_KEY = Object.freeze(Object.assign(Object.create(null), {
  'save-draft': 'onSaveTeacherDraft',
  'retry-recovery': 'onRetryTeacherRecovery',
  'retry-microphone': 'onRetryMicrophone',
  'end-session': 'onEndWithTeacher',
  lock: 'onLockTeacherHelp',
}));

export function createChildView(root, actions, dom) {
  assertRoot(root);
  const actionCallbacks = validateActions(actions);
  const domAPI = validateDom(dom);

  let destroyed = false;
  let renderEpoch = 0;
  let currentState = null;
  let currentStatus = null;
  let currentSnapshot = null;
  let currentControls = null;
  let currentActionables = new Set();
  let currentFocusTargets = new Map();
  let teacherUI = null;
  let teacherMode = 'locked';
  let teacherOpener = null;
  let teacherLockPending = false;

  function createElement(tag) {
    const element = invoke(domAPI.createElement, dom, [tag], 'createElement');
    assertElement(element);
    return element;
  }

  function createText(text) {
    const node = invoke(domAPI.createTextNode, dom, [String(text)], 'createTextNode');
    assertTextNode(node);
    return node;
  }

  function appendText(element, value) {
    append(element, createText(value));
    return element;
  }

  function element(tag, attributes = null, children = []) {
    const node = createElement(tag);
    if (attributes !== null) {
      for (const [name, value] of Object.entries(attributes)) {
        setAttribute(node, name, value);
      }
    }
    for (const childNode of children) append(node, childNode);
    return node;
  }

  function button({ id, text, token, disabled = false, describedBy = 'child-status', className = null }) {
    const attributes = { type: 'button', id, 'data-child-action': token, 'aria-describedby': describedBy };
    if (className !== null) attributes.class = className;
    const node = element('button', attributes);
    setDisabled(node, disabled);
    appendText(node, text);
    currentActionables.add(node);
    currentFocusTargets.set(`#${id}`, node);
    return node;
  }

  function messageRow(snapshot, message) {
    const item = element('article', { class: `child-message child-message--${message.role}` });
    const speaker = element('p', { class: 'child-message__speaker' });
    if (message.role === 'diary') {
      const diaryMark = element('img', {
        src: '/assets/diary-mark.svg',
        alt: '',
        width: '28',
        height: '28',
      });
      append(speaker, diaryMark);
      appendText(speaker, '鸭鸭日记本');
    } else {
      appendText(speaker, childLabel(snapshot.child));
    }
    const content = element('p', { class: 'child-message__text' });
    appendText(content, message.text);
    append(item, speaker, content);
    return item;
  }

  function pendingDraftRow(snapshot) {
    if (snapshot.draft === null) return null;
    const item = element('article', {
      id: 'pending-draft',
      class: 'child-message child-message--child child-message--pending',
      'aria-label': '待发送草稿',
    });
    const speaker = element('p', { class: 'child-message__speaker' });
    appendText(speaker, `${childLabel(snapshot.child)} · 待发送草稿`);
    const content = element('p', { class: 'child-message__text' });
    appendText(content, snapshot.draft.text);
    append(item, speaker, content);
    return item;
  }

  function failureRow(copy) {
    const item = element('article', {
      role: 'alert',
      class: 'child-message child-message--failure',
    });
    const label = element('p', { class: 'child-message__speaker' });
    appendText(label, '发送状态');
    const content = element('p', { class: 'child-message__text' });
    appendText(content, copy);
    append(item, label, content);
    return item;
  }

  function conversationPanel(snapshot, transcriptState) {
    const panel = element('section', {
      class: 'child-conversation-panel',
      'aria-labelledby': 'conversation-panel-title',
    });
    const header = element('header', { class: 'child-conversation-panel__header' });
    const title = element('h2', { id: 'conversation-panel-title' });
    appendText(title, '对话记录');
    const statePill = element('span', {
      class: 'child-conversation-panel__state',
      'aria-label': '当前状态',
    });
    appendText(statePill, STATE_PRESENTATION[snapshot.value].pill);
    append(header, title, statePill);

    const log = element('div', {
      class: 'child-conversation-panel__messages',
      role: 'log',
      'aria-live': 'polite',
      'aria-relevant': 'additions text',
      'aria-label': '对话记录',
    });
    for (const message of snapshot.messages) append(log, messageRow(snapshot, message));
    if (transcriptState.includeDraft) {
      const draft = pendingDraftRow(snapshot);
      if (draft !== null) append(log, draft);
    }
    if (transcriptState.failureCopy !== null) append(log, failureRow(transcriptState.failureCopy));
    append(panel, header, log);
    return panel;
  }

  function petOrb(snapshot, controls) {
    const orb = element('section', {
      class: 'child-pet-orb',
      'data-state': snapshot.value,
      'aria-label': '鸭鸭日记本伙伴',
    });
    const visual = element('div', { class: 'child-pet-orb__visual' });
    const poster = element('img', {
      class: 'child-pet-orb__poster',
      src: PET_POSTER_BY_STATE[snapshot.value],
      alt: PET_POSTER_ALT_BY_STATE[snapshot.value],
    });
    append(visual, poster);
    const stateCopy = element('p', { class: 'child-pet-orb__status' });
    appendText(stateCopy, STATE_PRESENTATION[snapshot.value].pill);
    append(orb, visual, stateCopy);

    let action = null;
    switch (snapshot.value) {
      case 'welcome':
        action = button({ id: 'start-button', text: '开始', token: 'start', className: 'child-pet-orb__action' });
        break;
      case 'ready':
      case 'listening':
        action = button({
          id: 'record-button',
          text: snapshot.value === 'ready' ? '开始说话' : '结束说话',
          token: 'record-toggle',
          disabled: controls.recordDisabled,
          className: 'child-pet-orb__action',
        });
        break;
      case 'submission_failed':
        if (submissionRetryAvailable(snapshot, controls)) {
          action = button({ id: 'retry-button', text: '重新发送', token: 'retry', className: 'child-pet-orb__action' });
        }
        break;
      case 'completed':
        action = button({ id: 'reset-button', text: '换下一位小朋友', token: 'reset', className: 'child-pet-orb__action' });
        break;
      default:
        break;
    }
    if (action !== null) append(orb, action);
    return orb;
  }

  function render(snapshot) {
    assertAlive();
    assertSnapshot(snapshot);
    if (!STATES.includes(snapshot.value)) throw new TypeError('Unknown child view state');

    const previousState = currentState;
    const epoch = ++renderEpoch;
    const controls = controlsFor(snapshot);
    const nextActionables = new Set();
    const nextFocusTargets = new Map();
    currentActionables = nextActionables;
    currentFocusTargets = nextFocusTargets;

    const section = element('section', {
      class: 'child-view child-shell',
      'data-state': snapshot.value,
      'aria-labelledby': 'app-title',
    });
    const shellHeader = element('header', { class: 'child-shell__header' });
    const brand = element('div', { class: 'child-shell__brand' });
    const brandImage = element('img', {
      src: '/assets/notebook-mark.svg',
      alt: '',
      width: '40',
      height: '40',
    });
    const brandName = element('span');
    appendText(brandName, '鸭鸭日记本');
    append(brand, brandImage, brandName);

    const help = button({
      id: 'teacher-help-button',
      text: '请老师帮忙',
      token: 'open-teacher-help',
      describedBy: 'child-status',
    });
    append(shellHeader, brand, help);

    const shellContent = element('div', { class: 'child-shell__content' });
    const state = element('section', { class: 'child-state' });
    const stateHeader = element('header', { class: 'child-state__header' });
    const heading = element('h1', { id: 'app-title', tabindex: '-1' });
    appendText(heading, titleFor(snapshot.value));
    nextFocusTargets.set('#app-title', heading);
    const lead = element('p', { class: 'child-state__lead' });
    appendText(lead, STATE_PRESENTATION[snapshot.value].lead);
    append(stateHeader, heading, lead);

    const stage = element('div', { class: 'child-stage' });
    const stateContent = renderState(snapshot, controls);
    for (const node of stateContent) append(stage, node);
    append(stage, petOrb(snapshot, controls));

    const status = element('p', {
      id: 'child-status',
      role: 'status',
      'aria-live': 'polite',
      'aria-atomic': 'true',
      tabindex: '-1',
    });
    appendText(status, statusFor(snapshot, controls));
    nextFocusTargets.set('#child-status', status);
    append(state, stateHeader, stage, status);
    append(shellContent, state);
    append(section, shellHeader, shellContent);

    if (teacherUI === null) replaceChildren(root, section);
    else replaceChildren(root, section, teacherUI.dialog);
    currentStatus = status;
    currentState = snapshot.value;
    currentSnapshot = snapshot;
    currentControls = controls;
    if (teacherUI !== null) {
      hydrateTeacherTextFromSnapshot();
      syncTeacherDialogControls();
    }
    if (previousState !== snapshot.value) {
      const selector = focusTargetFor(snapshot, controls);
      scheduleFocus(epoch, snapshot.value, selector);
    }
    return undefined;
  }

  function renderState(snapshot, controls) {
    switch (snapshot.value) {
      case 'welcome': {
        const intro = element('p', { class: 'child-view__intro' });
        appendText(intro, '和值日小朋友一起，记录小鸭的成长故事～');
        return [intro];
      }
      case 'loading_roster': {
        const busy = element('div', { 'aria-busy': 'true' });
        appendText(busy, '正在准备今天的值日名单');
        return [busy];
      }
      case 'selecting_child':
        return renderRoster(snapshot);
      case 'opening': {
        const identity = element('p', { class: 'child-view__identity' });
        appendText(identity, snapshot.child === null
          ? '正在确认小朋友信息'
          : `值日小朋友：${childLabel(snapshot.child)}`);
        return [identity];
      }
      case 'ready':
      case 'listening':
        return [conversationPanel(snapshot, { includeDraft: false, failureCopy: null })];
      case 'submitting':
        return [conversationPanel(snapshot, { includeDraft: true, failureCopy: null })];
      case 'speaking':
      case 'saving_conversation':
        return [conversationPanel(snapshot, { includeDraft: false, failureCopy: null })];
      case 'submission_failed':
        return [conversationPanel(snapshot, {
          includeDraft: true,
          failureCopy: submissionFailureCopy(snapshot, controls),
        })];
      case 'completed':
        return [conversationPanel(snapshot, { includeDraft: false, failureCopy: null })];
      case 'recovery':
        return [conversationPanel(snapshot, {
          includeDraft: false,
          failureCopy: errorCopy(snapshot.error),
        })];
      default:
        throw new TypeError('Unknown child view state');
    }
  }

  function renderRoster(snapshot) {
    const panel = element('section', { class: 'child-roster-panel' });
    if (snapshot.roster.length === 0) {
      setAttribute(panel, 'class', 'child-roster-panel child-roster-panel--empty');
      const empty = element('p', { id: 'roster-empty' });
      appendText(empty, '今天还未排班，请老师帮忙');
      append(panel, empty);
      return [panel];
    }
    const list = element('ul', { 'aria-label': '今日值日小朋友' });
    for (const rosterChild of snapshot.roster) {
      const labelGraphemes = childLabelGraphemes(rosterChild);
      const visibleLabel = labelGraphemes.join('');
      const item = element('li');
      const card = button({
        id: `child-card-${rosterChild.id}`,
        text: '',
        token: 'select-child',
        className: 'child-card',
      });
      const avatar = renderAvatarImage(dom, rosterChild.avatar, labelGraphemes[0]);
      setAttribute(avatar, 'class', 'child-card__avatar');
      setAttribute(avatar, 'aria-hidden', 'true');
      const label = element('span', { class: 'child-card__label' });
      appendText(label, visibleLabel);
      replaceChildren(card, avatar, label);
      setAttribute(card, 'data-child-id', String(rosterChild.id));
      append(item, card);
      append(list, item);
    }
    append(panel, list);
    return [panel];
  }

  function submissionFailureCopy(snapshot, controls) {
    return submissionRetryAvailable(snapshot, controls)
      ? '暂时没有收到日记本的确认，原话已经保留'
      : '不存在可重发的草稿，请老师帮忙';
  }

  function announce(text) {
    assertAlive();
    if (typeof text !== 'string') throw new TypeError('announcement must be a string');
    if (currentStatus === null) return undefined;
    replaceChildren(currentStatus, createText(text));
    return undefined;
  }

  function focus(selector) {
    if (destroyed || typeof selector !== 'string' || !FOCUS_SELECTORS.has(selector)) return false;
    const target = currentFocusTargets.get(selector);
    if (!isFocusable(target)) return false;
    try {
      target.focus();
      return domAPI.isFocused(target) === true;
    } catch {
      return false;
    }
  }

  function openTeacherHelp(options) {
    assertAlive();
    const parsed = readBooleanOptions(options, ['unlocked'], 'openTeacherHelp options');
    ensureTeacherDialog();
    teacherOpener = currentFocusTargets.get('#teacher-help-button') ?? null;
    setTeacherMode(parsed.unlocked ? 'unlocked' : 'locked');
    if (teacherUI.dialog.open !== true) invoke(teacherUI.dialog.showModal, teacherUI.dialog, [], 'dialog.showModal');
    focusTeacherField();
    return undefined;
  }

  function showTeacherHelpUnlocked() {
    assertAlive();
    ensureTeacherDialog();
    setTeacherMode('unlocked');
    focusTeacherField();
    return undefined;
  }

  function showTeacherHelpError(copy) {
    assertAlive();
    if (typeof copy !== 'string') throw new TypeError('teacher help copy must be a string');
    ensureTeacherDialog();
    teacherLockPending = false;
    syncTeacherDialogControls();
    replaceChildren(teacherUI.error, createText(copy));
    return undefined;
  }

  function clearTeacherPin() {
    assertAlive();
    if (teacherUI !== null) {
      try {
        teacherUI.pin.value = '';
        if (hasCallable(teacherUI.pin, 'setCustomValidity')) teacherUI.pin.setCustomValidity('');
      } catch (error) {
        throw asTypeError(error);
      }
    }
    return undefined;
  }

  function closeTeacherHelp(options) {
    assertAlive();
    const parsed = readBooleanOptions(options, ['clearText', 'restoreFocus'], 'closeTeacherHelp options');
    closeTeacherDialog(parsed.clearText, parsed.restoreFocus);
    return undefined;
  }

  function ensureTeacherDialog() {
    if (teacherUI !== null) return teacherUI;
    const dialog = element('dialog', {
      id: 'teacher-help-dialog',
      'aria-modal': 'true',
      'aria-labelledby': 'teacher-help-title',
      'aria-describedby': 'teacher-help-description',
    });
    const title = element('h2', { id: 'teacher-help-title', tabindex: '-1' });
    appendText(title, '老师帮忙');
    const description = element('p', { id: 'teacher-help-description' });
    appendText(description, '老师可以帮助继续这次对话。');
    const dialogHeader = element('header', { class: 'teacher-help-dialog__header' });
    append(dialogHeader, title, description);

    const unlockForm = element('form', {
      id: 'teacher-unlock-form',
      class: 'teacher-help-dialog__section teacher-help-dialog__section--locked',
      novalidate: '',
    });
    const pinLabel = element('label', { for: 'teacher-pin' });
    appendText(pinLabel, '教师 PIN');
    const pin = element('input', {
      id: 'teacher-pin',
      type: 'password',
      inputmode: 'numeric',
      pattern: '[0-9]{4,6}',
      minlength: '4',
      maxlength: '6',
      autocomplete: 'current-password',
      required: '',
    });
    const error = element('p', {
      id: 'teacher-help-error',
      role: 'alert',
      'aria-live': 'assertive',
    });
    const unlockButton = element('button', { id: 'teacher-unlock-button', type: 'submit' });
    appendText(unlockButton, '解锁老师帮助');
    append(unlockForm, pinLabel, pin, unlockButton);

    const actions = element('section', {
      id: 'teacher-actions',
      class: 'teacher-help-dialog__section teacher-help-dialog__section--unlocked',
      'aria-label': '老师帮助操作',
    });
    const textLabel = element('label', { for: 'teacher-text' });
    appendText(textLabel, '补录孩子刚才说的话');
    const text = element('textarea', { id: 'teacher-text', maxlength: '2000' });
    const actionsNote = element('p', { id: 'teacher-actions-note' });
    const submitText = teacherButton('teacher-submit-text', '发送补录', 'submit-text');
    const saveDraft = teacherButton('teacher-save-draft', '保存补录草稿', 'save-draft');
    const retryRecovery = teacherButton('teacher-retry-recovery', '重新检查这次对话', 'retry-recovery');
    const retryMicrophone = teacherButton('teacher-retry-microphone', '重试麦克风', 'retry-microphone');
    const endSession = teacherButton('teacher-end-session', '结束并安全保存会话', 'end-session');
    const lock = teacherButton('teacher-lock-button', '立即锁定', 'lock');
    append(actions, textLabel, text, actionsNote, submitText, saveDraft, retryRecovery, retryMicrophone, endSession, lock);
    const close = teacherButton('teacher-help-close', '返回孩子页面', 'close');
    const dialogFooter = element('footer', { class: 'teacher-help-dialog__footer' });
    append(dialogFooter, close);
    append(dialog, dialogHeader, error, unlockForm, actions, dialogFooter);
    teacherUI = {
      dialog,
      title,
      unlockForm,
      pin,
      error,
      unlockButton,
      actions,
      text,
      actionsNote,
      submitText,
      saveDraft,
      retryRecovery,
      retryMicrophone,
      endSession,
      lock,
      close,
    };
    try {
      unlockForm.addEventListener('submit', handleTeacherSubmit);
      dialog.addEventListener('click', handleTeacherClick);
      dialog.addEventListener('cancel', handleTeacherCancel);
      dialog.addEventListener('keydown', handleTeacherKeydown);
    } catch (error) {
      teacherUI = null;
      throw asTypeError(error);
    }
    append(root, dialog);
    hydrateTeacherTextFromSnapshot();
    syncTeacherDialogControls();
    return teacherUI;
  }

  function teacherButton(id, text, token) {
    const node = element('button', { id, type: 'button', 'data-teacher-action': token });
    appendText(node, text);
    return node;
  }

  function setTeacherMode(mode) {
    teacherMode = mode;
    setHidden(teacherUI.unlockForm, mode !== 'locked');
    setHidden(teacherUI.actions, mode !== 'unlocked');
    syncTeacherDialogControls();
  }

  function hydrateTeacherTextFromSnapshot() {
    if (teacherUI === null || currentSnapshot === null) return;
    if ((currentSnapshot.value === 'submitting' || currentSnapshot.value === 'submission_failed')
      && currentSnapshot.draft !== null) {
      try {
        teacherUI.text.value = currentSnapshot.draft.text;
      } catch (error) {
        throw asTypeError(error);
      }
    }
  }

  function syncTeacherDialogControls() {
    if (teacherUI === null) return;
    setHidden(teacherUI.unlockForm, teacherMode !== 'locked');
    setHidden(teacherUI.actions, teacherMode !== 'unlocked');
    setDisabled(teacherUI.pin, teacherLockPending);
    setDisabled(teacherUI.unlockButton, teacherLockPending);
    setDisabled(teacherUI.text, teacherLockPending);
    setDisabled(teacherUI.lock, teacherLockPending);
    setDisabled(teacherUI.close, teacherLockPending);
    if (currentSnapshot === null || currentControls === null) return;
    const retryDraft = currentSnapshot.value === 'submission_failed'
      && currentSnapshot.draft !== null
      && currentSnapshot.error?.retryable === true
      && currentControls.retryDisabled === false;
    replaceChildren(teacherUI.submitText, createText(retryDraft ? '重新发送这句话' : '发送补录'));
    setAttribute(teacherUI.submitText, 'data-teacher-action', retryDraft ? 'retry' : 'submit-text');
    setDisabled(teacherUI.submitText, teacherLockPending || (retryDraft
      ? currentControls.retryDisabled
      : currentControls.teacherTextDisabled));
    setDisabled(teacherUI.saveDraft, teacherLockPending || currentControls.teacherDraftDisabled);
    setDisabled(teacherUI.retryRecovery, teacherLockPending || currentControls.teacherRecoveryRetryDisabled);
    setDisabled(teacherUI.retryMicrophone, teacherLockPending || currentControls.teacherMicrophoneRetryDisabled);
    setDisabled(teacherUI.endSession, teacherLockPending || currentControls.teacherCompleteDisabled);
    const safe = currentControls.teacherTextDisabled === false
      || currentControls.teacherRecoveryRetryDisabled === false
      || currentControls.teacherMicrophoneRetryDisabled === false
      || currentControls.teacherCompleteDisabled === false
      || retryDraft;
    replaceChildren(teacherUI.actionsNote, createText(safe ? '' : '请先在安全恢复状态下操作'));
    setHidden(teacherUI.actionsNote, safe);
  }

  function focusTeacherField() {
    const target = teacherMode === 'unlocked' ? teacherUI.text : teacherUI.pin;
    try {
      target.focus();
    } catch (error) {
      throw asTypeError(error);
    }
  }

  function closeTeacherDialog(clearText, restoreFocus) {
    if (teacherUI === null) return;
    if (clearText === true) {
      try {
        teacherUI.pin.value = '';
        teacherUI.text.value = '';
        if (hasCallable(teacherUI.pin, 'setCustomValidity')) teacherUI.pin.setCustomValidity('');
        replaceChildren(teacherUI.error);
      } catch (error) {
        throw asTypeError(error);
      }
      teacherMode = 'locked';
      setHidden(teacherUI.unlockForm, false);
      setHidden(teacherUI.actions, true);
    }
    if (teacherUI.dialog.open === true) invoke(teacherUI.dialog.close, teacherUI.dialog, [], 'dialog.close');
    if (restoreFocus === true) {
      const opener = teacherOpener;
      if (opener !== null && contains(root, opener) && opener.disabled !== true && hasCallable(opener, 'focus')) {
        try {
          opener.focus();
        } catch {
          focus('#teacher-help-button');
        }
      } else {
        focus('#teacher-help-button');
      }
    }
    teacherOpener = null;
    teacherLockPending = false;
    syncTeacherDialogControls();
  }

  function requestTeacherLock(callback) {
    if (teacherLockPending || teacherUI === null) return;
    teacherLockPending = true;
    syncTeacherDialogControls();
    try {
      callback();
    } catch {
      teacherLockPending = false;
      syncTeacherDialogControls();
    }
  }

  function handleTeacherSubmit(event) {
    if (destroyed || teacherUI === null || teacherMode !== 'locked' || teacherLockPending) return;
    try {
      if (event !== null && typeof event === 'object' && hasCallable(event, 'preventDefault')) event.preventDefault();
      actionCallbacks.onSubmitTeacherPin(teacherUI.pin.value);
    } catch {}
  }

  function handleTeacherClick(event) {
    if (destroyed || teacherUI === null) return;
    const target = findTeacherActionElement(event);
    if (target === null || target.disabled === true || !contains(teacherUI.dialog, target)) return;
    const token = safeGetAttribute(target, 'data-teacher-action');
    try {
      if (token === 'submit-text') {
        actionCallbacks.onSubmitTeacherText(teacherUI.text.value);
        return;
      }
      if (token === 'retry') {
        actionCallbacks.onRetry();
        return;
      }
      if (token === 'close') {
        if (teacherMode === 'locked') closeTeacherDialog(true, true);
        else requestTeacherLock(actionCallbacks.onLockTeacherHelp);
        return;
      }
      if (!Object.hasOwn(TEACHER_TOKEN_TO_KEY, token)) return;
      const callback = actionCallbacks[TEACHER_TOKEN_TO_KEY[token]];
      if (typeof callback !== 'function') return;
      if (token === 'retry-microphone' || token === 'end-session' || token === 'lock') {
        requestTeacherLock(callback);
        return;
      }
      callback(token === 'save-draft' ? teacherUI.text.value : undefined);
    } catch {}
  }

  function handleTeacherCancel(event) {
    if (destroyed || teacherUI === null) return;
    try {
      if (event !== null && typeof event === 'object' && hasCallable(event, 'preventDefault')) event.preventDefault();
      if (teacherMode === 'locked') closeTeacherDialog(true, true);
      else requestTeacherLock(actionCallbacks.onLockTeacherHelp);
    } catch {}
  }

  function handleTeacherKeydown(event) {
    if (destroyed || teacherUI === null || teacherUI.dialog.open !== true) return;
    let key;
    let shiftKey;
    let target;
    try {
      key = event?.key;
      shiftKey = event?.shiftKey === true;
      target = event?.target;
    } catch {
      return;
    }
    if (key !== 'Tab') return;
    const candidates = teacherMode === 'locked'
      ? [teacherUI.pin, teacherUI.unlockButton, teacherUI.close]
      : [
        teacherUI.text,
        teacherUI.submitText,
        teacherUI.saveDraft,
        teacherUI.retryRecovery,
        teacherUI.retryMicrophone,
        teacherUI.endSession,
        teacherUI.lock,
        teacherUI.close,
      ];
    const enabled = candidates.filter(candidate => candidate.disabled !== true && contains(teacherUI.dialog, candidate));
    if (enabled.length === 0) return;
    const destination = shiftKey && target === enabled[0]
      ? enabled.at(-1)
      : !shiftKey && target === enabled.at(-1)
        ? enabled[0]
        : null;
    if (destination === null) return;
    try {
      if (hasCallable(event, 'preventDefault')) event.preventDefault();
      destination.focus();
    } catch {}
  }

  function findTeacherActionElement(event) {
    let node;
    try {
      node = event === null || typeof event !== 'object' ? null : event.target;
    } catch {
      return null;
    }
    const seen = new Set();
    while (node !== null && node !== undefined && node !== teacherUI.dialog && !seen.has(node)) {
      seen.add(node);
      if (hasCallable(node, 'getAttribute') && safeGetAttribute(node, 'data-teacher-action') !== null) return node;
      try {
        node = node.parentNode;
      } catch {
        return null;
      }
    }
    return null;
  }

  function scheduleFocus(epoch, state, selector) {
    try {
      domAPI.queueMicrotask(() => {
        if (destroyed || renderEpoch !== epoch || currentState !== state) return;
        focus(selector);
      });
    } catch (error) {
      throw asTypeError(error);
    }
  }

  function destroy() {
    if (destroyed) return undefined;
    destroyed = true;
    renderEpoch += 1;
    currentState = null;
    currentStatus = null;
    currentSnapshot = null;
    currentControls = null;
    currentActionables = new Set();
    currentFocusTargets = new Map();
    teacherLockPending = false;
    try {
      root.removeEventListener('click', handleClick);
      if (teacherUI !== null) {
        teacherUI.unlockForm.removeEventListener('submit', handleTeacherSubmit);
        teacherUI.dialog.removeEventListener('click', handleTeacherClick);
        teacherUI.dialog.removeEventListener('cancel', handleTeacherCancel);
        teacherUI.dialog.removeEventListener('keydown', handleTeacherKeydown);
      }
      if (teacherUI !== null) closeTeacherDialog(true, false);
      replaceChildren(root);
    } catch (error) {
      throw asTypeError(error);
    }
    return undefined;
  }

  function handleClick(event) {
    if (destroyed) return;
    const actionElement = findActionElement(event);
    if (actionElement === null || !currentActionables.has(actionElement)) return;
    if (!contains(root, actionElement) || !isNativeButton(actionElement) || actionElement.disabled === true) return;
    const token = safeGetAttribute(actionElement, 'data-child-action');
    if (!Object.hasOwn(ACTION_TOKEN_TO_KEY, token)) return;
    const actionKey = ACTION_TOKEN_TO_KEY[token];
    if (!Object.hasOwn(actionCallbacks, actionKey)) return;
    const callback = actionCallbacks[actionKey];
    if (typeof callback !== 'function') return;
    if (token === 'select-child') {
      const childId = canonicalChildId(safeGetAttribute(actionElement, 'data-child-id'));
      if (childId === null) return;
      callback(childId);
      return;
    }
    callback();
  }

  function findActionElement(event) {
    let node;
    try {
      node = event === null || typeof event !== 'object' ? null : event.target;
    } catch {
      return null;
    }
    const seen = new Set();
    while (node !== null && node !== undefined && node !== root && !seen.has(node)) {
      seen.add(node);
      if (hasCallable(node, 'getAttribute') && safeGetAttribute(node, 'data-child-action') !== null) {
        return node;
      }
      try {
        node = node.parentNode;
      } catch {
        return null;
      }
    }
    return null;
  }

  function assertAlive() {
    if (destroyed) throw new TypeError('child view is destroyed');
  }

  function isFocusable(target) {
    if (target === undefined || target === null || !currentFocusTargetsHas(target)) return false;
    if (!contains(root, target) || target.disabled === true || !hasCallable(target, 'focus')) return false;
    return true;
  }

  function currentFocusTargetsHas(target) {
    for (const candidate of currentFocusTargets.values()) {
      if (candidate === target) return true;
    }
    return false;
  }

  try {
    root.addEventListener('click', handleClick);
  } catch (error) {
    throw asTypeError(error);
  }

  return Object.freeze({
    render,
    announce,
    focus,
    destroy,
    openTeacherHelp,
    showTeacherHelpUnlocked,
    showTeacherHelpError,
    clearTeacherPin,
    closeTeacherHelp,
  });
}

function validateActions(actions) {
  const values = exactOwnDataValues(actions, ACTION_KEYS, 'actions');
  const callbacks = Object.create(null);
  for (const key of ACTION_KEYS) {
    const value = values[key];
    if (typeof value !== 'function') {
      throw new TypeError(`${key} must be a function`);
    }
    callbacks[key] = value;
  }
  return Object.freeze(callbacks);
}

function validateDom(dom) {
  const values = exactOwnDataValues(dom, DOM_KEYS, 'dom');
  const api = Object.create(null);
  for (const key of DOM_KEYS) {
    const value = values[key];
    if (typeof value !== 'function') throw new TypeError(`dom.${key} must be a function`);
    api[key] = value;
  }
  return Object.freeze(api);
}

function assertRoot(root) {
  if (root === null || (typeof root !== 'object' && typeof root !== 'function')) {
    throw new TypeError('root must be a DOM element');
  }
  for (const key of ['replaceChildren', 'addEventListener', 'removeEventListener', 'querySelector', 'contains']) {
    if (!hasCallable(root, key)) throw new TypeError(`root.${key} must be a function`);
  }
}

function assertElement(element) {
  if (element === null || (typeof element !== 'object' && typeof element !== 'function')) {
    throw new TypeError('createElement must return an element');
  }
  let tagName;
  try {
    tagName = element.tagName;
    void element.parentNode;
    void element.disabled;
    void element.textContent;
  } catch (error) {
    throw asTypeError(error);
  }
  if (typeof tagName !== 'string') throw new TypeError('element.tagName must be a string');
  for (const key of ['append', 'replaceChildren', 'setAttribute', 'getAttribute', 'focus']) {
    if (!hasCallable(element, key)) throw new TypeError(`element.${key} must be a function`);
  }
}

function assertTextNode(node) {
  if (node === null || (typeof node !== 'object' && typeof node !== 'function')) {
    throw new TypeError('createTextNode must return a text node');
  }
  try {
    void node.parentNode;
    void node.textContent;
  } catch (error) {
    throw asTypeError(error);
  }
}

function exactOwnDataValues(value, expectedKeys, name) {
  if (value === null || (typeof value !== 'object' && typeof value !== 'function')) {
    throw new TypeError(`${name} must be an object`);
  }
  let keys;
  try {
    keys = Reflect.ownKeys(value);
  } catch (error) {
    throw freshTypeError(`${name} own keys could not be read`, error);
  }
  if (keys.length !== expectedKeys.length || keys.some(key => typeof key !== 'string' || !expectedKeys.includes(key))) {
    throw new TypeError(`${name} must have exactly the required keys`);
  }
  const values = Object.create(null);
  for (const key of expectedKeys) {
    let descriptor;
    try {
      descriptor = Reflect.getOwnPropertyDescriptor(value, key);
    } catch (error) {
      throw freshTypeError(`${name}.${key} descriptor could not be read`, error);
    }
    if (descriptor === undefined || !Object.hasOwn(descriptor, 'value')) {
      throw new TypeError(`${name}.${key} must be an own data property`);
    }
    values[key] = descriptor.value;
  }
  return Object.freeze(values);
}

function hasCallable(object, key) {
  try {
    return typeof object[key] === 'function';
  } catch {
    return false;
  }
}

function invoke(fn, receiver, args, name) {
  try {
    return fn.apply(receiver, args);
  } catch (error) {
    throw new TypeError(`${name} failed`, { cause: error });
  }
}

function append(element, ...nodes) {
  try {
    element.append(...nodes);
  } catch (error) {
    throw asTypeError(error);
  }
}

function replaceChildren(element, ...nodes) {
  try {
    element.replaceChildren(...nodes);
  } catch (error) {
    throw asTypeError(error);
  }
}

function setAttribute(element, name, value) {
  try {
    element.setAttribute(name, String(value));
  } catch (error) {
    throw asTypeError(error);
  }
}

function setDisabled(element, disabled) {
  try {
    element.disabled = disabled === true;
    if (disabled === true) element.setAttribute('disabled', '');
  } catch (error) {
    throw asTypeError(error);
  }
}

function setHidden(element, hidden) {
  try {
    element.hidden = hidden === true;
  } catch (error) {
    throw asTypeError(error);
  }
}

function safeGetAttribute(element, name) {
  try {
    return element.getAttribute(name);
  } catch {
    return null;
  }
}

function contains(root, element) {
  try {
    return root.contains(element) === true;
  } catch {
    return false;
  }
}

function isNativeButton(element) {
  try {
    return typeof element.tagName === 'string' && element.tagName.toUpperCase() === 'BUTTON';
  } catch {
    return false;
  }
}

function canonicalChildId(value) {
  if (typeof value !== 'string' || !/^[1-9][0-9]*$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 && String(parsed) === value ? parsed : null;
}

function titleFor(state) {
  return state === 'loading_roster' || state === 'selecting_child' ? '今天轮到谁值日呀？' : '鸭鸭日记本';
}

function childLabel(child) {
  return childLabelGraphemes(child).join('');
}

function childLabelGraphemes(child) {
  for (const candidate of [child?.nickname, child?.name]) {
    if (typeof candidate !== 'string') continue;
    const graphemes = segmentGraphemes(candidate);
    let start = 0;
    let end = graphemes.length;
    while (start < end && isInvisibleEdgeGrapheme(graphemes[start])) start += 1;
    while (end > start && isInvisibleEdgeGrapheme(graphemes[end - 1])) end -= 1;
    const normalized = graphemes.slice(start, end);
    if (normalized.some(grapheme => !isInvisibleEdgeGrapheme(grapheme))) return normalized;
  }
  return ['小', '朋', '友'];
}

function segmentGraphemes(value) {
  try {
    if (typeof Intl.Segmenter === 'function') {
      const segments = new Intl.Segmenter('zh-CN', { granularity: 'grapheme' }).segment(value);
      return Array.from(segments, entry => entry.segment);
    }
  } catch {}
  return fallbackGraphemes(value);
}

function fallbackGraphemes(value) {
  const graphemes = [];
  for (const codePoint of value) {
    if (graphemes.length === 0) {
      graphemes.push(codePoint);
      continue;
    }
    const lastIndex = graphemes.length - 1;
    const previous = graphemes[lastIndex];
    if (extendsFallbackGrapheme(previous, codePoint)) {
      graphemes[lastIndex] += codePoint;
    } else {
      graphemes.push(codePoint);
    }
  }
  return graphemes;
}

function extendsFallbackGrapheme(previous, codePoint) {
  if (previous.endsWith('\r') && codePoint === '\n') return true;
  if (/^(?:\p{Grapheme_Extend}|\p{Emoji_Modifier}|\p{Mc})$/u.test(codePoint)) return true;
  if (codePoint === '\u200d') return true;
  if (
    previous.endsWith('\u200d')
    && /\p{Extended_Pictographic}(?:\p{Grapheme_Extend}|\p{Emoji_Modifier}|\p{Mc})*\u200d$/u.test(previous)
    && /^\p{Extended_Pictographic}$/u.test(codePoint)
  ) return true;
  if (/^\p{Regional_Indicator}$/u.test(codePoint)) {
    const regionalCount = Array.from(previous).filter(point => /^\p{Regional_Indicator}$/u.test(point)).length;
    return regionalCount % 2 === 1;
  }
  return false;
}

function isInvisibleEdgeGrapheme(grapheme) {
  return /^(?:\s|\p{Default_Ignorable_Code_Point})+$/u.test(grapheme);
}

function submissionRetryAvailable(snapshot, controls) {
  return snapshot.draft !== null && snapshot.child !== null && !controls.retryDisabled;
}

function statusFor(snapshot, controls) {
  switch (snapshot.value) {
    case 'welcome': return '准备好后，请按开始';
    case 'loading_roster': return '正在加载今天的值日小朋友';
    case 'selecting_child': return snapshot.roster.length === 0 ? '今天还未排班，请老师帮忙' : '请选择今天值日的小朋友';
    case 'opening': return '鸭鸭日记本正在和你打招呼';
    case 'ready': return '点一下开始说话，也可以按空格键';
    case 'listening': return '正在听，停顿后会自动发送';
    case 'submitting': return '这句话正在发给鸭鸭日记本';
    case 'speaking': return '鸭鸭日记本正在回答';
    case 'submission_failed': return submissionRetryAvailable(snapshot, controls)
      ? '暂时没有收到日记本的确认，原话已经保留'
      : '不存在可重发的草稿，请老师帮忙';
    case 'saving_conversation': return '正在安全保存今天的话';
    case 'completed': return '今天的话已经安全记下来啦';
    case 'recovery': return snapshot.error?.code === 'MIC_PERMISSION_DENIED'
      ? '麦克风没有开启，请老师帮忙'
      : '需要老师帮忙恢复这次对话';
    default: throw new TypeError('Unknown child view state');
  }
}

function errorCopy(error) {
  return ERROR_COPY.get(error?.code) ?? RECOVERY_FALLBACK;
}

function focusTargetFor(snapshot, controls) {
  switch (snapshot.value) {
    case 'welcome': return '#start-button';
    case 'loading_roster': return '#child-status';
    case 'selecting_child': return '#app-title';
    case 'opening': return '#child-status';
    case 'ready':
    case 'listening': return controls.recordDisabled ? '#child-status' : '#record-button';
    case 'submitting':
    case 'speaking':
    case 'saving_conversation': return '#child-status';
    case 'submission_failed':
      return submissionRetryAvailable(snapshot, controls)
        ? '#retry-button'
        : '#teacher-help-button';
    case 'completed': return '#reset-button';
    case 'recovery': return '#teacher-help-button';
    default: throw new TypeError('Unknown child view state');
  }
}

function readBooleanOptions(value, keys, name) {
  let ownKeys;
  try {
    ownKeys = Reflect.ownKeys(value);
  } catch {
    throw new TypeError(`${name} must be an own-data record`);
  }
  if (value === null || (typeof value !== 'object' && typeof value !== 'function')
    || ownKeys.length !== keys.length
    || ownKeys.some(key => typeof key !== 'string' || !keys.includes(key))) {
    throw new TypeError(`${name} must be an own-data record`);
  }
  const result = Object.create(null);
  for (const key of keys) {
    let descriptor;
    try {
      descriptor = Reflect.getOwnPropertyDescriptor(value, key);
    } catch {
      throw new TypeError(`${name} must be an own-data record`);
    }
    if (descriptor === undefined || !Object.hasOwn(descriptor, 'value') || typeof descriptor.value !== 'boolean') {
      throw new TypeError(`${name}.${key} must be a boolean data property`);
    }
    result[key] = descriptor.value;
  }
  return result;
}

function asTypeError(error) {
  return error instanceof TypeError ? error : new TypeError('child view DOM seam failed', { cause: error });
}

function freshTypeError(message, cause) {
  return new TypeError(message, { cause });
}
