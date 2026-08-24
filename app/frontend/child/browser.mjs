import { bootstrapBrowserChildApp } from './app.mjs';
import { bootstrapBrowserChildAPI } from './api.mjs';
import { createChildView } from './view.mjs';
import { createSessionStore, createDraft, mergeRecovery } from './session-store.mjs';
import { createSpeechController } from './speech.mjs';
import { createTTSController } from './tts.mjs';
import {
  STATES,
  assertSnapshot,
  controlsFor,
  createInitialSnapshot,
  transition,
} from './machine.mjs';

const machine = Object.freeze({
  STATES,
  assertSnapshot,
  controlsFor,
  createInitialSnapshot,
  transition,
});

const root = document.getElementById('child-app');
let app = null;
let cleaned = false;

function isInteractiveTarget(target) {
  if (!(target instanceof Element)) return false;
  if (target.isContentEditable) return true;
  return target.closest(
    'a[href],button,input,textarea,select,option,summary,[contenteditable],'
    + '[role="button"],[role="link"],[role="textbox"],[role="checkbox"],'
    + '[role="combobox"],[role="menuitem"],[role="option"],[tabindex]:not([tabindex="-1"])',
  ) !== null;
}

function isDialogActive() {
  return document.querySelector('[role="dialog"][aria-modal="true"],dialog[open]') !== null;
}

function forwardGlobalKeydown(event) {
  app.handleGlobalKeydown(event);
}

function renderChildMaintenance(_code) {
  try {
    if (document.getElementById('runtime-maintenance') !== null) return;
    const main = document.createElement('main');
    main.id = 'child-maintenance';
    main.setAttribute('role', 'alert');
    main.setAttribute('aria-labelledby', 'child-maintenance-title');
    const heading = document.createElement('h1');
    heading.id = 'child-maintenance-title';
    heading.textContent = '幼儿端暂不可用';
    const copy = document.createElement('p');
    copy.textContent = '当前服务状态无法安全确认，请老师检查服务后刷新页面。';
    main.append(heading, copy);
    document.body.replaceChildren(main);
  } catch {}
}

function validUniqueRoot() {
  return root !== null
    && root.tagName === 'MAIN'
    && document.querySelectorAll('main').length === 1
    && document.querySelector('main') === root;
}

async function installChildApp() {
  if (!validUniqueRoot()) {
    renderChildMaintenance('CHILD_BOOTSTRAP_FAILED');
    return;
  }

  const dom = Object.freeze({
    createElement: tag => document.createElement(tag),
    createTextNode: text => document.createTextNode(text),
    queueMicrotask: callback => globalThis.queueMicrotask(callback),
    isFocused: element => document.activeElement === element,
  });
  const keyboard = Object.freeze({
    isInteractiveTarget,
    isDialogActive,
  });
  const dependencies = Object.freeze({
    bootstrapAPI: () => bootstrapBrowserChildAPI(globalThis),
    onMaintenanceFailure: renderChildMaintenance,
    createStore: () => createSessionStore(sessionStorage, { now: () => new Date().toISOString() }),
    createTTS: api => createTTSController({
      loadEdgeBlob: (text, signal) => api.tts(text, signal),
      Audio: url => new globalThis.Audio(url),
      createObjectURL: URL.createObjectURL.bind(URL),
      revokeObjectURL: URL.revokeObjectURL.bind(URL),
      speechSynthesis: globalThis.speechSynthesis,
      SpeechSynthesisUtterance: globalThis.SpeechSynthesisUtterance,
      setTimer: globalThis.setTimeout.bind(globalThis),
      clearTimer: globalThis.clearTimeout.bind(globalThis),
      AbortController: globalThis.AbortController,
    }),
    createView: (viewRoot, actions, viewDom) => createChildView(viewRoot, actions, viewDom),
    root,
    dom,
    machine,
    createDraft,
    mergeRecovery,
    createSpeech: ({ onEvent }) => createSpeechController({
      Recognition: globalThis.SpeechRecognition ?? globalThis.webkitSpeechRecognition ?? null,
      onEvent,
      setTimer: globalThis.setTimeout.bind(globalThis),
      clearTimer: globalThis.clearTimeout.bind(globalThis),
    }),
    keyboard,
    uuid: () => globalThis.crypto.randomUUID(),
    now: () => new Date().toISOString(),
    AbortController: globalThis.AbortController,
  });

  try {
    app = await bootstrapBrowserChildApp(dependencies);
  } catch {
    renderChildMaintenance('CHILD_BOOTSTRAP_FAILED');
    return;
  }
  if (app === null) return;
  root.setAttribute('aria-labelledby', 'app-title');
  root.removeAttribute('aria-busy');
  document.addEventListener('keydown', forwardGlobalKeydown);
}

function cleanupInstalledApp() {
  if (cleaned || app === null) return;
  cleaned = true;
  document.removeEventListener('keydown', forwardGlobalKeydown);
  try {
    app.destroy();
  } catch {}
}

globalThis.addEventListener('pagehide', cleanupInstalledApp);
void installChildApp().catch(() => renderChildMaintenance('CHILD_BOOTSTRAP_FAILED'));
