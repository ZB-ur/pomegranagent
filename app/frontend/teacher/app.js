import { createTeacherRouter } from './router.mjs';
import { createLegacyTeacherRoutes } from './legacy-routes.mjs';
import { createTodayRoute } from './views/today.mjs';

const main = document.getElementById('main');
const nav = document.getElementById('nav');
const teacherRouteManifest = [
  { route: 'today' },
  { route: 'children' },
  { route: 'ducks' },
  { route: 'roster' },
  { route: 'review' },
  { route: 'growth' },
  { route: 'search' },
];
let runtimeReady = false;
let teacherAuthenticated = false;
let teacherRouter = null;
let lockButton = null;
let lockFeedback = null;
let currentPinInput = null;

nav.setAttribute('aria-busy', 'true');
nav.querySelectorAll('button').forEach(button => { button.disabled = true; });

function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  if (attrs) for (const key in attrs) {
    if (key === 'onclick') node.addEventListener('click', attrs[key]);
    else if (key === 'oninput') node.addEventListener('input', attrs[key]);
    else if (key === 'onchange') node.addEventListener('change', attrs[key]);
    else node.setAttribute(key, attrs[key]);
  }
  for (const child of children) node.append(child);
  return node;
}

function clearTeacherPin() {
  if (currentPinInput) currentPinInput.value = '';
  currentPinInput = null;
}

function updateTeacherNavigation() {
  const enabled = runtimeReady && teacherAuthenticated;
  if (!enabled) {
    nav.setAttribute('aria-busy', 'true');
    nav.querySelectorAll('button').forEach(button => { button.disabled = true; });
    return;
  }
  nav.removeAttribute('aria-busy');
  nav.querySelectorAll('button').forEach(button => { button.disabled = false; });
}

function renderTeacherLocked(message) {
  main.replaceChildren();
  const card = h('section', { class: 'card', role: 'status' });
  card.append(h('h2', null, '教师端已锁定'), h('p', { class: 'muted' }, message));
  main.append(card);
}

function setLockFeedback(message) {
  if (!lockFeedback) {
    lockFeedback = h('p', {
      id: 'teacher-lock-feedback',
      class: 'teacher-lock-feedback',
      role: 'alert',
      'aria-live': 'assertive',
    });
    document.querySelector('aside').append(lockFeedback);
  }
  lockFeedback.textContent = message;
}

function ensureLockButton() {
  if (lockButton) return;
  lockButton = h('button', { class: 'btn gray teacher-lock-button', type: 'button' }, '立即锁定');
  lockButton.addEventListener('click', lockTeacherPage);
  document.querySelector('aside').append(lockButton);
}

function authenticationErrorCopy(error) {
  return error && error.code === 'PIN_INVALID' ? 'PIN 不正确' : '暂时无法完成教师验证，请稍后重试。';
}

function startTeacherRouter() {
  if (!runtimeReady || !teacherAuthenticated) return;
  migrateOverviewHash();
  if (!teacherRouter) {
    const legacyRoutes = createLegacyTeacherRoutes({
      request: (path, options) => window.DuckAPI.request(path, options),
      document,
      alert: (...args) => window.alert(...args),
    });
    const today = createTodayRoute({
      request: (path, options) => window.DuckAPI.request(path, options),
      document,
    });
    const routes = Object.fromEntries(teacherRouteManifest.map(({ route }) => [
      route,
      route === 'today' ? today : legacyRoutes[route],
    ]));
    teacherRouter = createTeacherRouter({
      window,
      root: main,
      nav,
      routes,
      defaultRoute: 'today',
      onError: () => {},
    });
  }
  return teacherRouter.start();
}

function migrateOverviewHash() {
  const raw = String(window.location.hash || '');
  if (raw !== '#overview' && !raw.startsWith('#overview?')) return;
  window.history.replaceState(null, '', `#today${raw.slice('#overview'.length)}`);
}

async function bootstrapTeacherPage() {
  await window.DuckAPI.ready();
  runtimeReady = true;
  updateTeacherNavigation();
  await unlockTeacherPage();
  await startTeacherRouter();
}

async function unlockTeacherPage() {
  const auth = await window.DuckAuth.status();
  if (auth.authenticated) {
    teacherAuthenticated = true;
    updateTeacherNavigation();
    ensureLockButton();
    lockButton.disabled = false;
    return true;
  }

  teacherAuthenticated = false;
  updateTeacherNavigation();
  return new Promise(resolve => {
    main.replaceChildren();
    const form = h('form', { class: 'card' });
    const inputId = 'teacher-pin';
    const label = h('label', { for: inputId }, auth.configured ? '教师 PIN' : '设置教师 PIN');
    const input = h('input', {
      id: inputId,
      type: 'password',
      inputmode: 'numeric',
      pattern: '[0-9]{4,6}',
      minlength: '4',
      maxlength: '6',
      autocomplete: 'off',
      required: 'required',
    });
    currentPinInput = input;
    const feedback = h('p', { role: 'alert', 'aria-live': 'assertive' });
    const submit = h('button', { class: 'btn', type: 'submit' }, auth.configured ? '解锁' : '设置并解锁');
    form.append(
      h('h2', null, auth.configured ? '教师端已锁定' : '首次设置教师 PIN'),
      label,
      input,
      submit,
      feedback,
    );
    form.addEventListener('submit', async event => {
      event.preventDefault();
      submit.disabled = true;
      feedback.textContent = '';
      try {
        if (auth.configured) await window.DuckAuth.unlock(input.value);
        else await window.DuckAuth.setup(input.value);
        clearTeacherPin();
        form.remove();
        teacherAuthenticated = true;
        updateTeacherNavigation();
        ensureLockButton();
        lockButton.disabled = false;
        resolve(true);
      } catch (error) {
        feedback.textContent = authenticationErrorCopy(error);
        submit.disabled = false;
        input.focus();
      }
    });
    main.append(form);
    input.focus();
  });
}

function handleTeacherBootstrapFailure(_error) {
  if (document.getElementById('runtime-maintenance')) return;
  if (teacherRouter) teacherRouter.stop();
  teacherRouter = null;
  teacherAuthenticated = false;
  updateTeacherNavigation();
  renderTeacherLocked('教师端暂不可用，请稍后重试。');
}

async function lockTeacherPage() {
  const button = lockButton;
  if (!button) return;
  button.disabled = true;
  setLockFeedback('');
  try {
    await window.DuckAuth.lock();
  } catch (_error) {
    button.disabled = false;
    setLockFeedback('暂时无法锁定，请稍后重试。');
    return;
  }

  clearTeacherPin();
  if (teacherRouter) teacherRouter.stop();
  teacherRouter = null;
  teacherAuthenticated = false;
  updateTeacherNavigation();
  button.remove();
  if (lockButton === button) lockButton = null;
  renderTeacherLocked('教师端已锁定，重新输入 PIN 后可继续。');
  try {
    await unlockTeacherPage();
    await startTeacherRouter();
  } catch (error) {
    handleTeacherBootstrapFailure(error);
  }
}

window.addEventListener('pagehide', clearTeacherPin, { once: false });
bootstrapTeacherPage().catch(handleTeacherBootstrapFailure);
