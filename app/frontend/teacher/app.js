import { createTeacherRouter } from './router.mjs';
import { createTodayRoute } from './views/today.mjs';
import { createReviewRoute } from './views/review.mjs';
import { createManagementRoutes } from './views/management.mjs';
import { createReportRoutes } from './views/reports.mjs';
import { createDirtyGuard } from './dirty-guard.mjs';

const main = document.getElementById('main');
const nav = document.getElementById('nav');
const topbarTitle = document.querySelector('.teacher-topbar-title');
const topbarActions = document.querySelector('.teacher-topbar-actions');
const reviewDirtyGuard = createDirtyGuard({ window, document });
const teacherRouteManifest = [
  { route: 'today', title: '今日任务' },
  { route: 'children', title: '幼儿管理' },
  { route: 'ducks', title: '小鸭管理' },
  { route: 'roster', title: '值日排班' },
  { route: 'review', title: '值日审阅' },
  { route: 'growth', title: '能力成长曲线' },
  { route: 'search', title: '明细检索' },
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

function setTeacherTopbarTitle(title = '安全设置') {
  topbarTitle.textContent = title;
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
  setTeacherTopbarTitle();
  main.replaceChildren();
  const view = h('section', { class: 'teacher-auth-view' });
  const card = h('section', { class: 'card teacher-auth-card', role: 'status' });
  card.append(h('h2', null, '教师端已锁定'), h('p', { class: 'muted' }, message));
  view.append(card);
  main.append(view);
}

function setLockFeedback(message) {
  if (!message) {
    if (lockFeedback) lockFeedback.remove();
    lockFeedback = null;
    return;
  }
  if (!lockFeedback) {
    lockFeedback = h('p', {
      id: 'teacher-lock-feedback',
      class: 'teacher-lock-feedback',
      role: 'alert',
      'aria-live': 'assertive',
    });
    topbarActions.prepend(lockFeedback);
  }
  lockFeedback.textContent = message;
}

function ensureLockButton() {
  if (lockButton) return;
  lockButton = h('button', { class: 'btn gray teacher-lock-button', type: 'button' }, '立即锁定');
  lockButton.addEventListener('click', lockTeacherPage);
  topbarActions.append(lockButton);
}

function removeLockButton() {
  if (!lockButton) return;
  lockButton.remove();
  lockButton = null;
}

function authenticationErrorCopy(error) {
  return error && error.code === 'PIN_INVALID' ? 'PIN 不正确' : '暂时无法完成教师验证，请稍后重试。';
}

function withTeacherRouteTitle(title, loader) {
  if (typeof loader !== 'function') return loader;
  return context => {
    setTeacherTopbarTitle(title);
    return loader(context);
  };
}

function startTeacherRouter() {
  if (!runtimeReady || !teacherAuthenticated) return;
  migrateOverviewHash();
  if (!teacherRouter) {
    const managementRoutes = createManagementRoutes({
      request: (path, options) => window.DuckAPI.request(path, options),
      document,
      createAbortController: () => new AbortController(),
      createRequestId: () => window.crypto.randomUUID(),
    });
    const reportRoutes = createReportRoutes({
      request: (path, options) => window.DuckAPI.request(path, options),
      document,
      createAbortController: () => new AbortController(),
      navigate: fragment => { window.location.hash = fragment; },
    });
    const today = createTodayRoute({
      request: (path, options) => window.DuckAPI.request(path, options),
      document,
    });
    const review = createReviewRoute({
      request: (path, options) => window.DuckAPI.request(path, options),
      document,
      createAbortController: () => new AbortController(),
      dirtyGuard: reviewDirtyGuard,
    });
    const routes = Object.fromEntries(teacherRouteManifest.map(({ route, title }) => [
      route,
      withTeacherRouteTitle(title, route === 'today' ? today
        : route === 'review' ? review
          : managementRoutes[route] || reportRoutes[route]),
    ]));
    teacherRouter = createTeacherRouter({
      window,
      root: main,
      nav,
      routes,
      defaultRoute: 'today',
      confirmLeave: () => reviewDirtyGuard.confirmLeave(),
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
  removeLockButton();
  setLockFeedback('');
  setTeacherTopbarTitle();
  return new Promise(resolve => {
    main.replaceChildren();
    const view = h('section', {
      class: 'teacher-auth-view',
      'aria-labelledby': 'teacher-auth-title',
    });
    const intro = h('div', { class: 'teacher-auth-intro' });
    intro.append(
      h('p', { class: 'teacher-auth-eyebrow' }, auth.configured ? '教师端安全验证' : '首次使用 · 教师端安全设置'),
      h('h2', { id: 'teacher-auth-title' }, auth.configured ? '教师端已锁定' : '首次设置教师 PIN'),
      h(
        'p',
        { class: 'teacher-auth-description' },
        auth.configured
          ? '输入教师 PIN 后继续。验证只在本机当前浏览器会话生效。'
          : '这个 PIN 只用于保护教师端。幼儿端不会看到，也不会保存到页面内容中。',
      ),
    );
    const form = h('form', { class: 'card teacher-auth-card' });
    const formHeader = h('div', { class: 'teacher-auth-card-header' });
    formHeader.append(
      h('p', { class: 'teacher-auth-card-title' }, auth.configured ? '输入 4–6 位数字 PIN' : '设置 4–6 位数字 PIN'),
      h('span', { class: 'teacher-auth-local-badge' }, '仅本机验证'),
    );
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
    const field = h('div', { class: 'teacher-auth-field' });
    field.append(
      label,
      input,
      h('p', { class: 'teacher-auth-hint' }, '使用容易记住、但不易被幼儿猜到的数字'),
    );
    const privacy = h('div', { class: 'teacher-auth-privacy' });
    privacy.append(
      h('span', { class: 'teacher-auth-privacy-icon', 'aria-hidden': 'true' }, 'i'),
      h('p', null, '系统不会在界面、注释或演示数据中显示真实 PIN。'),
    );
    const feedback = h('p', { class: 'teacher-auth-feedback', role: 'alert', 'aria-live': 'assertive' });
    const submit = h('button', { class: 'btn', type: 'submit' }, auth.configured ? '解锁' : '设置并解锁');
    form.append(
      formHeader,
      field,
      privacy,
      feedback,
      submit,
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
    view.append(
      intro,
      form,
      h(
        'p',
        { class: 'teacher-auth-footer' },
        auth.configured
          ? '解锁后将返回当前任务；关闭浏览器后需要重新验证。'
          : '设置完成后将进入今日任务；所有业务导航会在解锁后可用。',
      ),
    );
    main.append(view);
    input.focus();
  });
}

function handleTeacherBootstrapFailure(_error) {
  if (document.getElementById('runtime-maintenance')) return;
  if (teacherRouter) teacherRouter.stop();
  teacherRouter = null;
  teacherAuthenticated = false;
  updateTeacherNavigation();
  removeLockButton();
  setLockFeedback('');
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
  removeLockButton();
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
