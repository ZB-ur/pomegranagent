import { STATES, assertSnapshot, controlsFor } from './machine.mjs';

const ACTION_KEYS = Object.freeze([
  'onStart',
  'onSelectChild',
  'onRecordToggle',
  'onRetry',
  'onReset',
  'onOpenTeacherHelp',
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
const ACTION_TOKEN_TO_KEY = Object.freeze(Object.assign(Object.create(null), {
  start: 'onStart',
  'select-child': 'onSelectChild',
  'record-toggle': 'onRecordToggle',
  retry: 'onRetry',
  reset: 'onReset',
  'open-teacher-help': 'onOpenTeacherHelp',
}));

export function createChildView(root, actions, dom) {
  assertRoot(root);
  const actionCallbacks = validateActions(actions);
  const domAPI = validateDom(dom);

  let destroyed = false;
  let renderEpoch = 0;
  let currentState = null;
  let currentStatus = null;
  let currentActionables = new Set();
  let currentFocusTargets = new Map();

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

  function messageLog(snapshot) {
    const log = element('div', {
      role: 'log',
      'aria-live': 'polite',
      'aria-relevant': 'additions text',
      'aria-label': '对话记录',
    });
    for (const message of snapshot.messages) {
      const item = element('article', { class: `child-message child-message--${message.role}` });
      const speaker = element('p', { class: 'child-message__speaker' });
      appendText(speaker, message.role === 'child' ? childLabel(snapshot.child) : '鸭鸭日记本');
      const content = element('p', { class: 'child-message__text' });
      appendText(content, message.text);
      append(item, speaker, content);
      append(log, item);
    }
    return log;
  }

  function draftRegion(snapshot) {
    if (snapshot.draft === null) return null;
    const region = element('section', { id: 'pending-draft', 'aria-label': '待发送草稿' });
    const heading = element('h2');
    appendText(heading, '待发送草稿');
    const text = element('p');
    appendText(text, snapshot.draft.text);
    append(region, heading, text);
    return region;
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
      class: 'child-view',
      'data-state': snapshot.value,
      'aria-labelledby': 'app-title',
    });
    const heading = element('h1', { id: 'app-title', tabindex: '-1' });
    appendText(heading, titleFor(snapshot.value));
    nextFocusTargets.set('#app-title', heading);
    append(section, heading);

    const stateContent = renderState(snapshot, controls);
    for (const node of stateContent) append(section, node);

    const status = element('p', {
      id: 'child-status',
      role: 'status',
      'aria-live': 'polite',
      'aria-atomic': 'true',
      tabindex: '-1',
    });
    appendText(status, statusFor(snapshot));
    nextFocusTargets.set('#child-status', status);
    append(section, status);

    const helpIsUnavailable = actionCallbacks.onOpenTeacherHelp === null;
    const describedBy = helpIsUnavailable
      ? 'child-status teacher-help-unavailable-note'
      : 'child-status';
    const help = button({
      id: 'teacher-help-button',
      text: '老师帮忙',
      token: 'open-teacher-help',
      disabled: helpIsUnavailable,
      describedBy,
    });
    append(section, help);
    if (helpIsUnavailable) {
      const note = element('p', { id: 'teacher-help-unavailable-note' });
      appendText(note, '老师帮助功能尚未启用');
      append(section, note);
    }

    replaceChildren(root, section);
    currentStatus = status;
    currentState = snapshot.value;
    if (previousState !== snapshot.value) {
      const selector = focusTargetFor(snapshot, controls, helpIsUnavailable);
      scheduleFocus(epoch, snapshot.value, selector);
    }
    return undefined;
  }

  function renderState(snapshot, controls) {
    switch (snapshot.value) {
      case 'welcome': {
        const intro = element('p', { class: 'child-view__intro' });
        appendText(intro, '和值日小朋友一起，记录小鸭的成长故事～');
        return [intro, button({ id: 'start-button', text: '开始', token: 'start' })];
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
      case 'listening': {
        const record = button({
          id: 'record-button',
          text: snapshot.value === 'ready' ? '开始说话' : '结束说话',
          token: 'record-toggle',
          disabled: controls.recordDisabled,
        });
        return [messageLog(snapshot), record];
      }
      case 'submitting': {
        const nodes = [messageLog(snapshot)];
        const draftNode = draftRegion(snapshot);
        if (draftNode !== null) nodes.push(draftNode);
        return nodes;
      }
      case 'speaking':
      case 'saving_conversation':
        return [messageLog(snapshot)];
      case 'submission_failed':
        return renderSubmissionFailure(snapshot, controls);
      case 'completed':
        return [
          messageLog(snapshot),
          button({ id: 'reset-button', text: '换下一位小朋友', token: 'reset' }),
        ];
      case 'recovery': {
        const alert = element('p', { role: 'alert', class: 'child-view__error' });
        appendText(alert, errorCopy(snapshot.error));
        const nodes = [alert];
        if (snapshot.messages.length > 0) nodes.push(messageLog(snapshot));
        return nodes;
      }
      default:
        throw new TypeError('Unknown child view state');
    }
  }

  function renderRoster(snapshot) {
    if (snapshot.roster.length === 0) {
      const empty = element('p', { id: 'roster-empty' });
      appendText(empty, '今天还未排班，请老师帮忙');
      return [empty];
    }
    const list = element('ul', { 'aria-label': '今日值日小朋友' });
    for (const rosterChild of snapshot.roster) {
      const item = element('li');
      const card = button({
        id: `child-card-${rosterChild.id}`,
        text: childLabel(rosterChild),
        token: 'select-child',
        className: 'child-card',
      });
      setAttribute(card, 'data-child-id', String(rosterChild.id));
      append(item, card);
      append(list, item);
    }
    return [list];
  }

  function renderSubmissionFailure(snapshot, controls) {
    const completeRetryContext = snapshot.draft !== null && snapshot.child !== null && !controls.retryDisabled;
    const nodes = [messageLog(snapshot)];
    const draftNode = draftRegion(snapshot);
    if (draftNode !== null) nodes.push(draftNode);
    const alert = element('p', { role: 'alert', class: 'child-view__error' });
    appendText(alert, completeRetryContext
      ? '这句话还没有送达，原话已经保留'
      : '不存在可重发的草稿，请老师帮忙');
    nodes.push(alert);
    if (completeRetryContext) {
      nodes.push(button({ id: 'retry-button', text: '重新发送', token: 'retry' }));
    }
    return nodes;
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
    currentActionables = new Set();
    currentFocusTargets = new Map();
    try {
      root.removeEventListener('click', handleClick);
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

  return Object.freeze({ render, announce, focus, destroy });
}

function validateActions(actions) {
  const values = exactOwnDataValues(actions, ACTION_KEYS, 'actions');
  const callbacks = Object.create(null);
  for (const key of ACTION_KEYS) {
    const value = values[key];
    if (key === 'onOpenTeacherHelp') {
      if (value !== null && typeof value !== 'function') throw new TypeError('onOpenTeacherHelp must be a function or null');
    } else if (typeof value !== 'function') {
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
  return child?.nickname || child?.name || '小朋友';
}

function statusFor(snapshot) {
  switch (snapshot.value) {
    case 'welcome': return '准备好后，请按开始';
    case 'loading_roster': return '正在加载今天的值日小朋友';
    case 'selecting_child': return snapshot.roster.length === 0 ? '今天还未排班，请老师帮忙' : '请选择今天值日的小朋友';
    case 'opening': return '鸭鸭正在和你打招呼';
    case 'ready': return '点一下开始说话，也可以按空格键';
    case 'listening': return '正在听，停顿后会自动发送';
    case 'submitting': return '这句话正在送给鸭鸭';
    case 'speaking': return '鸭鸭正在回答';
    case 'submission_failed': return snapshot.draft === null || snapshot.child === null
      ? '这句话没有可重发的草稿，请老师帮忙'
      : '这句话还没有送达，原话已经保留';
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

function focusTargetFor(snapshot, controls, helpIsUnavailable) {
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
      return snapshot.draft !== null && snapshot.child !== null && !controls.retryDisabled
        ? '#retry-button'
        : helpIsUnavailable ? '#child-status' : '#teacher-help-button';
    case 'completed': return '#reset-button';
    case 'recovery': return helpIsUnavailable ? '#child-status' : '#teacher-help-button';
    default: throw new TypeError('Unknown child view state');
  }
}

function asTypeError(error) {
  return error instanceof TypeError ? error : new TypeError('child view DOM seam failed', { cause: error });
}

function freshTypeError(message, cause) {
  return new TypeError(message, { cause });
}
