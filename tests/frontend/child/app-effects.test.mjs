import test from 'node:test';
import assert from 'node:assert/strict';

import * as rawMachine from '../../../app/frontend/child/machine.mjs';
import {
  STATES,
  assertSnapshot,
  controlsFor,
  createInitialSnapshot,
  transition,
} from '../../../app/frontend/child/machine.mjs';
import { createDraft, mergeRecovery } from '../../../app/frontend/child/session-store.mjs';
import { bootstrapBrowserChildApp, createChildApp } from '../../../app/frontend/child/app.mjs';

const MACHINE_FACADE = Object.freeze({
  STATES,
  assertSnapshot,
  controlsFor,
  createInitialSnapshot,
  transition,
});

test('module exposes exactly the approved child orchestration factories', async () => {
  const module = await import('../../../app/frontend/child/app.mjs');
  assert.deepEqual(Object.keys(module).sort(), [
    'bootstrapBrowserChildApp',
    'createChildApp',
  ]);
});

function createFixture() {
  const calls = {
    api: [],
    speechFactory: 0,
    speechStart: 0,
    speechStop: 0,
    speechDispose: 0,
    store: [],
    tts: [],
    view: [],
  };
  const controllers = [];
  let recognitionReads = 0;
  let speechOnEvent = null;
  const speech = {
    start() { calls.speechStart += 1; },
    stop() { calls.speechStop += 1; },
    dispose() { calls.speechDispose += 1; },
    isListening() { return false; },
  };
  Object.defineProperty(speech, 'recognition', {
    enumerable: true,
    get() {
      recognitionReads += 1;
      return null;
    },
  });
  const api = {
    ready() { calls.api.push('ready'); return Promise.resolve(); },
    getTodayRoster() { calls.api.push('roster'); return Promise.resolve([]); },
    getActiveConversation(childId) { calls.api.push(['active', childId]); return Promise.resolve({ conversation: null }); },
    chat(input, signal) { calls.api.push(['chat', input, signal]); return Promise.resolve(null); },
    complete(conversationId, lastMessageId, signal) {
      calls.api.push(['complete', conversationId, lastMessageId, signal]);
      return Promise.resolve(null);
    },
    teacherStatus() { calls.api.push('teacherStatus'); return Promise.resolve(null); },
    teacherSetup() { calls.api.push('teacherSetup'); return Promise.resolve(null); },
    teacherUnlock() { calls.api.push('teacherUnlock'); return Promise.resolve(null); },
    teacherLock() { calls.api.push('teacherLock'); return Promise.resolve(null); },
    tts() { calls.api.push('tts'); return Promise.resolve(null); },
  };
  const store = {
    load() { calls.store.push('load'); return null; },
    save(snapshot) { calls.store.push(['save', snapshot]); },
    clear() { calls.store.push('clear'); },
  };
  const tts = {
    speak(text) { calls.tts.push(['speak', text]); return Promise.resolve({ mode: 'text', reason: 'test' }); },
    cancel(reason) { calls.tts.push(['cancel', reason]); },
    dispose() { calls.tts.push(['dispose']); },
  };
  const view = {
    render(snapshot) { calls.view.push(['render', snapshot]); },
    announce(text) { calls.view.push(['announce', text]); },
    focus(selector) { calls.view.push(['focus', selector]); return false; },
    openTeacherHelp(options) { calls.view.push(['openTeacherHelp', options]); },
    showTeacherHelpUnlocked() { calls.view.push(['showTeacherHelpUnlocked']); },
    showTeacherHelpError(copy) { calls.view.push(['showTeacherHelpError', copy]); },
    clearTeacherPin() { calls.view.push(['clearTeacherPin']); },
    closeTeacherHelp(options) { calls.view.push(['closeTeacherHelp', options]); },
    destroy() { calls.view.push(['destroy']); },
  };
  class FakeAbortController {
    constructor() {
      this.signal = {};
      this.abortCalls = 0;
      controllers.push(this);
    }

    abort() { this.abortCalls += 1; }
  }
  const deps = {
    api,
    machine: MACHINE_FACADE,
    store,
    createDraft,
    mergeRecovery,
    createSpeech({ onEvent }) {
      calls.speechFactory += 1;
      assert.equal(typeof onEvent, 'function');
      speechOnEvent = onEvent;
      return speech;
    },
    tts,
    view,
    keyboard: {
      isInteractiveTarget() { return false; },
      isDialogActive() { return false; },
    },
    uuid() { return '00000000-0000-4000-8000-000000000007'; },
    now() { return '2026-08-23T00:00:00.000Z'; },
    AbortController: FakeAbortController,
  };
  return {
    calls,
    controllers,
    deps,
    get recognitionReads() { return recognitionReads; },
    emitSpeech(event) { speechOnEvent?.(event); },
    speech,
  };
}

function createBootstrapFixture() {
  const child = createFixture();
  const calls = {
    actions: null,
    order: [],
    bootstrapAPI: 0,
    maintenance: [],
    storeFactory: 0,
    ttsFactory: 0,
    viewFactory: 0,
  };
  const deps = {
    bootstrapAPI() {
      calls.bootstrapAPI += 1;
      calls.order.push('api');
      return Promise.resolve(child.deps.api);
    },
    onMaintenanceFailure(code) {
      calls.maintenance.push(code);
    },
    createStore() {
      calls.storeFactory += 1;
      calls.order.push('store');
      return child.deps.store;
    },
    createTTS(api) {
      calls.ttsFactory += 1;
      calls.order.push('tts');
      assert.notEqual(api, child.deps.api);
      assert.deepEqual(Reflect.ownKeys(api).sort(), [
        'chat', 'complete', 'getActiveConversation', 'getTodayRoster', 'ready', 'teacherLock',
        'teacherSetup', 'teacherStatus', 'teacherUnlock', 'tts',
      ]);
      return child.deps.tts;
    },
    createView(root, actions, dom) {
      calls.viewFactory += 1;
      calls.order.push('view');
      assert.equal(root, deps.root);
      assert.equal(dom, deps.dom);
      calls.actions = actions;
      assert.deepEqual(Reflect.ownKeys(actions).sort(), [
        'onEndWithTeacher', 'onLockTeacherHelp', 'onOpenTeacherHelp', 'onRecordToggle',
        'onReset', 'onRetry', 'onRetryMicrophone', 'onRetryTeacherRecovery',
        'onSaveTeacherDraft', 'onSelectChild', 'onStart', 'onSubmitTeacherPin',
        'onSubmitTeacherText',
      ]);
      for (const callback of Object.values(actions)) assert.equal(typeof callback, 'function');
      assert.equal(actions.onOpenTeacherHelp(), undefined);
      assert.equal(actions.onSubmitTeacherPin('1234'), undefined);
      assert.equal(actions.onSubmitTeacherText('补录'), undefined);
      assert.equal(actions.onSaveTeacherDraft('草稿'), undefined);
      assert.equal(actions.onRetryTeacherRecovery(), undefined);
      assert.equal(actions.onRetryMicrophone(), undefined);
      assert.equal(actions.onEndWithTeacher(), undefined);
      assert.equal(actions.onLockTeacherHelp(), undefined);
      return child.deps.view;
    },
    root: {},
    dom: {},
    machine: MACHINE_FACADE,
    createDraft,
    mergeRecovery,
    createSpeech: child.deps.createSpeech,
    keyboard: child.deps.keyboard,
    uuid: child.deps.uuid,
    now: child.deps.now,
    AbortController: child.deps.AbortController,
  };
  return { child, calls, deps };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function destroyBeforeControllerWork(fixture, targetIndex, getApp) {
  let created = 0;
  fixture.deps.AbortController = class DestroyingAbortController {
    constructor() {
      this.signal = {};
      this.abortCalls = 0;
      fixture.controllers.push(this);
      created += 1;
      if (created === targetIndex) {
        Promise.resolve().then(() => getApp()?.destroy());
      }
    }

    abort() { this.abortCalls += 1; }
  };
  return () => created;
}

async function flushMicrotasks() {
  for (let count = 0; count < 8; count += 1) await Promise.resolve();
}

function explicitlyStopAndEmitSpeech(app, fixture, event) {
  app.recordToggle();
  fixture.emitSpeech(event);
}

function childRecord(id = 7, name = '小雨') {
  return { id, name, nickname: null, avatar: null };
}

function chatResult(overrides = {}) {
  return {
    request_id: '00000000-0000-4000-8000-000000000007',
    conversation_id: 9,
    child_message_id: 41,
    diary_message_id: 42,
    reply: '真棒！',
    round: 1,
    ended: false,
    end_reason: null,
    replayed: false,
    ...overrides,
  };
}

function completeResult(overrides = {}) {
  return {
    conversation_id: 9,
    conversation_saved: true,
    status: 'completed',
    completed_at: '2026-08-23T00:01:00.000Z',
    message_count: 2,
    last_message_id: 42,
    analysis_job_id: 3,
    analysis_status: 'pending',
    replayed: false,
    ...overrides,
  };
}

function pendingCompletionRecord() {
  return {
    version: 1,
    child: childRecord(),
    conversation_id: 9,
    revision: null,
    last_message_id: 42,
    state: 'saving_conversation',
    messages: [
      { id: 41, role: 'child', text: '我给小鸭换了水' },
      { id: 42, role: 'diary', text: '真棒！' },
    ],
    draft: null,
    should_complete: true,
    failure: null,
    updated_at: '2026-08-23T00:00:01.000Z',
  };
}

function activeConversation() {
  return {
    id: 9,
    child_id: 7,
    status: 'active',
    revision: 1,
    round: 1,
    last_message_id: 42,
    messages: [
      { id: 41, role: 'child', text: '我给小鸭换了水' },
      { id: 42, role: 'diary', text: '真棒！' },
    ],
  };
}

function localDraftRecord() {
  return {
    version: 1,
    child: childRecord(),
    conversation_id: null,
    revision: null,
    last_message_id: null,
    state: 'submission_failed',
    messages: [],
    draft: {
      text: '我给小鸭换了水',
      request_id: '00000000-0000-4000-8000-000000000007',
      created_at: '2026-08-23T00:00:00.000Z',
    },
    should_complete: false,
    failure: { code: 'LOCAL_DRAFT_NOT_CONFIRMED', retryable: true },
    updated_at: '2026-08-23T00:00:01.000Z',
  };
}

function localReadyRecord() {
  return {
    version: 1,
    child: childRecord(),
    conversation_id: null,
    revision: null,
    last_message_id: null,
    state: 'ready',
    messages: [],
    draft: null,
    should_complete: false,
    failure: null,
    updated_at: '2026-08-23T00:00:01.000Z',
  };
}

async function enterAuthorizedRecovery(
  fixture,
  teacherStatus = null,
  activeReader = null,
  rosterReader = null,
) {
  fixture.deps.api.getTodayRoster = rosterReader ?? (() => {
    fixture.calls.api.push('roster');
    return Promise.resolve([childRecord()]);
  });
  fixture.deps.api.getActiveConversation = activeReader ?? (childId => {
    fixture.calls.api.push(['active', childId]);
    return Promise.resolve({ conversation: null });
  });
  fixture.deps.api.teacherStatus = teacherStatus ?? (() => {
    fixture.calls.api.push('teacherStatus');
    return Promise.resolve({ configured: true, authenticated: true });
  });
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  app.recordToggle();
  fixture.emitSpeech({ type: 'error', error: { code: 'SPEECH_FAILED', retryable: true } });
  await app.openTeacherHelp();
  assert.equal(app.getSnapshot().value, 'recovery');
  assert.equal(app.getSnapshot().teacherUnlocked, true);
  return app;
}

test('createChildApp accepts only trap-safe exact plain dependency facades before effects', () => {
  const valid = createFixture();
  const app = createChildApp(valid.deps);
  assert.equal(typeof app.getSnapshot, 'function');

  const cases = [
    ['missing required root key', (() => {
      const fixture = createFixture();
      delete fixture.deps.now;
      return fixture;
    })()],
    ['extra nested API key', (() => {
      const fixture = createFixture();
      fixture.deps.api.extra = () => {};
      return fixture;
    })()],
    ['symbol root key', (() => {
      const fixture = createFixture();
      fixture.deps[Symbol('extra')] = true;
      return fixture;
    })()],
    ['accessor root key', (() => {
      const fixture = createFixture();
      const value = fixture.deps.api;
      Object.defineProperty(fixture.deps, 'api', { enumerable: true, get() { return value; } });
      return fixture;
    })()],
    ['ownKeys proxy fault', (() => {
      const fixture = createFixture();
      const original = fixture.deps;
      fixture.deps = new Proxy(original, { ownKeys() { throw new Error('ownKeys trap'); } });
      return fixture;
    })()],
    ['raw ESM machine namespace', (() => {
      const fixture = createFixture();
      fixture.deps.machine = rawMachine;
      return fixture;
    })()],
  ];

  for (const [name, fixture] of cases) {
    const raw = new Error(`${name} raw dependency failure`);
    let thrown = null;
    try {
      createChildApp(fixture.deps);
    } catch (error) {
      thrown = error;
    }
    assert.equal(thrown instanceof TypeError, true, name);
    assert.notEqual(thrown, raw, name);
    assert.equal(Object.hasOwn(thrown, 'cause'), false, name);
    assert.deepEqual(fixture.calls.api, [], name);
    assert.deepEqual(fixture.calls.store, [], name);
    assert.deepEqual(fixture.calls.tts, [], name);
    assert.deepEqual(fixture.calls.view, [], name);
    assert.equal(fixture.calls.speechFactory, 0, name);
  }
});

test('createChildApp constructs one speech controller then renders only fresh welcome', () => {
  const fixture = createFixture();
  const app = createChildApp(fixture.deps);

  assert.equal(fixture.calls.speechFactory, 1);
  assert.equal(fixture.recognitionReads, 0);
  assert.deepEqual(fixture.calls.api, []);
  assert.deepEqual(fixture.calls.store, []);
  assert.deepEqual(fixture.calls.tts, []);
  assert.equal(fixture.calls.view.length, 1);
  assert.equal(fixture.calls.view[0][0], 'render');
  assert.equal(fixture.calls.view[0][1].value, 'welcome');
  assert.equal(Object.isFrozen(app.getSnapshot()), true);
});

test('a synchronous speech-factory callback before lifecycle setup is queued without a TDZ construction failure', () => {
  const fixture = createFixture();
  fixture.deps.createSpeech = ({ onEvent }) => {
    fixture.calls.speechFactory += 1;
    onEvent({ type: 'final', text: 'factory-time speech must be inert' });
    return fixture.speech;
  };

  const app = createChildApp(fixture.deps);
  assert.equal(app.getSnapshot().value, 'welcome');
  assert.equal(fixture.calls.speechFactory, 1);
  assert.deepEqual(fixture.calls.api, []);
  assert.deepEqual(fixture.calls.store, []);
  assert.equal(fixture.calls.view.filter(([kind]) => kind === 'render').length, 1);
});

test('malformed speech and initial welcome rendering fail without transferring caller-owned view or TTS', () => {
  const malformed = createFixture();
  malformed.deps.createSpeech = () => ({
    start() {}, stop() {}, dispose() {}, isListening() {},
  });
  assert.throws(() => createChildApp(malformed.deps), error => {
    assert.equal(error instanceof TypeError, true);
    assert.equal(Object.hasOwn(error, 'cause'), false);
    return true;
  });
  assert.equal(malformed.calls.speechFactory, 0);
  assert.deepEqual(malformed.calls.view, []);
  assert.deepEqual(malformed.calls.tts, []);
  assert.deepEqual(malformed.calls.store, []);

  const renderFailure = createFixture();
  renderFailure.deps.view.render = () => { throw new Error('render raw'); };
  assert.throws(() => createChildApp(renderFailure.deps), error => {
    assert.equal(error instanceof TypeError, true);
    assert.equal(Object.hasOwn(error, 'cause'), false);
    return true;
  });
  assert.equal(renderFailure.calls.speechFactory, 1);
  assert.equal(renderFailure.calls.speechDispose, 1);
  assert.deepEqual(renderFailure.calls.api, []);
  assert.deepEqual(renderFailure.calls.store, []);
  assert.deepEqual(renderFailure.calls.tts, []);
});

test('child app exposes the frozen lifecycle surface and destruction is an idempotent no-op boundary', async () => {
  const fixture = createFixture();
  const app = createChildApp(fixture.deps);
  const beforeDestroy = app.getSnapshot();

  assert.deepEqual(Reflect.ownKeys(app).sort(), [
    'destroy', 'endWithTeacher', 'getSnapshot', 'handleGlobalKeydown', 'initialize',
    'lockTeacherHelp', 'openTeacherHelp', 'recordToggle', 'reset', 'retry',
    'retryMicrophone', 'retryTeacherRecovery', 'saveTeacherDraft', 'selectChild', 'start',
    'submitTeacherPin', 'submitTeacherText',
  ]);
  assert.equal(Object.isFrozen(app), true);
  assert.equal(Object.isFrozen(beforeDestroy), true);
  assert.equal(await app.initialize(), undefined);
  assert.equal(await app.selectChild(7), undefined);
  assert.equal(app.recordToggle(), undefined);
  assert.equal(await app.retry(), undefined);
  assert.equal(app.reset(), undefined);
  assert.equal(app.handleGlobalKeydown({ code: 'Space' }), false);
  assert.equal(await app.openTeacherHelp(), undefined);
  assert.equal(await app.submitTeacherPin('1234'), undefined);
  assert.equal(await app.submitTeacherText('补录'), undefined);
  assert.equal(await app.saveTeacherDraft('草稿'), undefined);
  assert.equal(await app.retryTeacherRecovery(), undefined);
  assert.equal(await app.retryMicrophone(), undefined);
  assert.equal(await app.endWithTeacher(), undefined);
  assert.equal(await app.lockTeacherHelp(), undefined);
  assert.deepEqual(fixture.calls.api, ['ready', 'teacherStatus', 'teacherStatus', 'teacherLock']);
  assert.deepEqual(fixture.calls.store, ['load']);
  const snapshotBeforeDestroy = app.getSnapshot();

  assert.equal(app.destroy(), undefined);
  assert.equal(app.destroy(), undefined);
  assert.equal(fixture.calls.speechDispose, 1);
  assert.deepEqual(fixture.calls.tts, [['dispose']]);
  assert.deepEqual(fixture.calls.view.filter(([kind]) => kind === 'destroy'), [['destroy']]);

  assert.equal(await app.initialize(), undefined);
  assert.equal(await app.start(), undefined);
  assert.equal(await app.selectChild(7), undefined);
  assert.equal(app.recordToggle(), undefined);
  assert.equal(await app.retry(), undefined);
  assert.equal(app.reset(), undefined);
  assert.equal(app.handleGlobalKeydown({ code: 'Space' }), false);
  assert.equal(await app.openTeacherHelp(), undefined);
  assert.equal(await app.submitTeacherPin('1234'), undefined);
  assert.equal(await app.submitTeacherText('补录'), undefined);
  assert.equal(await app.saveTeacherDraft('草稿'), undefined);
  assert.equal(await app.retryTeacherRecovery(), undefined);
  assert.equal(await app.retryMicrophone(), undefined);
  assert.equal(await app.endWithTeacher(), undefined);
  assert.equal(await app.lockTeacherHelp(), undefined);
  assert.equal(app.getSnapshot(), snapshotBeforeDestroy);
  assert.equal(fixture.calls.speechStart, 0);
  assert.equal(fixture.calls.speechStop, 0);
  assert.deepEqual(fixture.calls.api, ['ready', 'teacherStatus', 'teacherStatus', 'teacherLock']);
  assert.deepEqual(fixture.calls.store, ['load']);
});

test('teacher help status uses the adapter-only registry path and fixed local failure copy', async () => {
  const fixture = createFixture();
  let statusWork = () => Promise.resolve({ configured: true, authenticated: true });
  fixture.deps.api.teacherStatus = () => {
    fixture.calls.api.push('teacherStatus');
    return statusWork();
  };
  const app = createChildApp(fixture.deps);
  await app.initialize();
  fixture.calls.api.length = 0;
  fixture.calls.store.length = 0;
  fixture.calls.view.length = 0;

  assert.equal(await app.openTeacherHelp(), undefined);
  assert.equal(app.getSnapshot().teacherUnlocked, true);
  assert.deepEqual(fixture.calls.api, ['teacherStatus']);
  assert.deepEqual(fixture.calls.store, []);
  assert.deepEqual(fixture.calls.view.filter(([kind]) => kind !== 'render'), [
    ['openTeacherHelp', { unlocked: true }],
  ]);

  statusWork = () => Promise.resolve({ configured: true, authenticated: false });
  fixture.calls.api.length = 0;
  fixture.calls.store.length = 0;
  fixture.calls.view.length = 0;
  assert.equal(await app.openTeacherHelp(), undefined);
  assert.equal(app.getSnapshot().teacherUnlocked, false);
  assert.deepEqual(fixture.calls.api, ['teacherStatus']);
  assert.deepEqual(fixture.calls.store, []);
  assert.deepEqual(fixture.calls.view.filter(([kind]) => kind !== 'render'), [
    ['openTeacherHelp', { unlocked: false }],
  ]);

  statusWork = () => Promise.resolve({ configured: true, authenticated: true });
  await app.openTeacherHelp();
  assert.equal(app.getSnapshot().teacherUnlocked, true);
  const failures = [
    () => { throw { code: 'NETWORK_ERROR', message: 'private sync detail' }; },
    () => ({ get then() { throw { code: 'NETWORK_ERROR', message: 'private then detail' }; } }),
    () => Promise.reject({ code: 'NETWORK_ERROR', message: 'private reject detail' }),
  ];
  for (const failure of failures) {
    statusWork = failure;
    fixture.calls.api.length = 0;
    fixture.calls.store.length = 0;
    fixture.calls.view.length = 0;
    assert.equal(await app.openTeacherHelp(), undefined);
    assert.equal(app.getSnapshot().teacherUnlocked, false);
    assert.deepEqual(fixture.calls.api, ['teacherStatus']);
    assert.deepEqual(fixture.calls.store, []);
    assert.deepEqual(fixture.calls.view.filter(([kind]) => kind !== 'render'), [
      ['openTeacherHelp', { unlocked: false }],
      ['showTeacherHelpError', '老师帮助暂时不可用，请稍后重试'],
    ]);
    assert.equal(JSON.stringify(fixture.calls.view).includes('private'), false);
  }
});

test('teacher PIN rechecks status, uses one adapter auth call, and clears every secret reference', async () => {
  const sentinel = '4826';

  async function runSuccess({ configured, method }) {
    const fixture = createFixture();
    fixture.deps.api.teacherStatus = () => {
      fixture.calls.api.push('teacherStatus');
      return Promise.resolve({ configured, authenticated: false });
    };
    fixture.deps.api.teacherSetup = pin => {
      fixture.calls.api.push(['teacherSetup', pin]);
      return Promise.resolve({ configured: true, authenticated: true });
    };
    fixture.deps.api.teacherUnlock = pin => {
      fixture.calls.api.push(['teacherUnlock', pin]);
      return Promise.resolve({ configured: true, authenticated: true });
    };
    const app = createChildApp(fixture.deps);
    await app.initialize();
    fixture.calls.api.length = 0;
    fixture.calls.store.length = 0;
    fixture.calls.view.length = 0;

    assert.equal(await app.submitTeacherPin(sentinel), undefined);
    assert.deepEqual(fixture.calls.api, ['teacherStatus', [method, sentinel]]);
    assert.equal(app.getSnapshot().teacherUnlocked, true);
    assert.deepEqual(fixture.calls.store, []);
    assert.deepEqual(fixture.calls.view.filter(([kind]) => kind !== 'render'), [
      ['showTeacherHelpUnlocked'],
      ['clearTeacherPin'],
    ]);
    assert.equal(JSON.stringify(app.getSnapshot()).includes(sentinel), false);
    assert.equal(JSON.stringify(fixture.calls.store).includes(sentinel), false);
    assert.equal(JSON.stringify(fixture.calls.view).includes(sentinel), false);
  }

  await runSuccess({ configured: false, method: 'teacherSetup' });
  await runSuccess({ configured: true, method: 'teacherUnlock' });

  const invalid = createFixture();
  const invalidApp = createChildApp(invalid.deps);
  await invalidApp.initialize();
  invalid.calls.api.length = 0;
  invalid.calls.view.length = 0;
  assert.equal(await invalidApp.submitTeacherPin('１２34'), undefined);
  assert.deepEqual(invalid.calls.api, []);
  assert.deepEqual(invalid.calls.view, [
    ['showTeacherHelpError', '请输入 4 到 6 位数字 PIN'],
    ['clearTeacherPin'],
  ]);

  const failures = [
    () => Promise.reject({ code: 'PIN_INVALID', message: `raw-${sentinel}` }),
    () => ({ get then() { throw { code: 'PIN_ALREADY_CONFIGURED', message: `raw-${sentinel}` }; } }),
    () => Promise.reject({ code: 'NETWORK_ERROR', message: `raw-${sentinel}` }),
  ];
  const expectedCopies = [
    'PIN 不正确，请重新输入',
    '老师帮助状态已变化，请关闭后重新打开',
    '老师帮助暂时不可用，请稍后重试',
  ];
  for (let index = 0; index < failures.length; index += 1) {
    const fixture = createFixture();
    fixture.deps.api.teacherStatus = () => {
      fixture.calls.api.push('teacherStatus');
      return Promise.resolve({ configured: true, authenticated: false });
    };
    fixture.deps.api.teacherUnlock = pin => {
      fixture.calls.api.push(['teacherUnlock', pin]);
      return failures[index]();
    };
    const app = createChildApp(fixture.deps);
    await app.initialize();
    fixture.calls.api.length = 0;
    fixture.calls.store.length = 0;
    fixture.calls.view.length = 0;
    assert.equal(await app.submitTeacherPin(sentinel), undefined);
    assert.deepEqual(fixture.calls.api, ['teacherStatus', ['teacherUnlock', sentinel]]);
    assert.equal(app.getSnapshot().teacherUnlocked, false);
    assert.deepEqual(fixture.calls.store, []);
    assert.deepEqual(fixture.calls.view.filter(([kind]) => kind !== 'render'), [
      ['showTeacherHelpError', expectedCopies[index]],
      ['clearTeacherPin'],
    ]);
    assert.equal(JSON.stringify(fixture.calls.view).includes(sentinel), false);
    assert.equal(JSON.stringify(fixture.calls.store).includes(sentinel), false);
    assert.equal(JSON.stringify(app.getSnapshot()).includes(sentinel), false);
  }
});

test('teacher lock is adapter-only, clears dialog state, restores focus, and leaves child drafts intact', async () => {
  const fixture = createFixture();
  fixture.deps.store.load = () => {
    fixture.calls.store.push('load');
    return localDraftRecord();
  };
  fixture.deps.api.getActiveConversation = childId => {
    fixture.calls.api.push(['active', childId]);
    return Promise.resolve({ conversation: null });
  };
  fixture.deps.api.teacherStatus = () => {
    fixture.calls.api.push('teacherStatus');
    return Promise.resolve({ configured: true, authenticated: true });
  };
  fixture.deps.api.teacherLock = () => {
    fixture.calls.api.push('teacherLock');
    return Promise.resolve({ configured: true, authenticated: false });
  };
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.openTeacherHelp();
  const draftBeforeLock = app.getSnapshot().draft;
  fixture.calls.api.length = 0;
  fixture.calls.store.length = 0;
  fixture.calls.view.length = 0;

  assert.equal(await app.lockTeacherHelp(), undefined);
  assert.equal(app.getSnapshot().teacherUnlocked, false);
  assert.equal(app.getSnapshot().draft.request_id, draftBeforeLock.request_id);
  assert.deepEqual(fixture.calls.api, ['teacherLock']);
  assert.deepEqual(fixture.calls.store, []);
  assert.deepEqual(fixture.calls.view.filter(([kind]) => kind !== 'render'), [
    ['closeTeacherHelp', { clearText: true, restoreFocus: true }],
    ['clearTeacherPin'],
  ]);

  const rejected = createFixture();
  rejected.deps.api.teacherStatus = () => Promise.resolve({ configured: true, authenticated: true });
  rejected.deps.api.teacherLock = () => {
    rejected.calls.api.push('teacherLock');
    return Promise.reject({ code: 'NETWORK_ERROR', message: 'private lock detail' });
  };
  const rejectedApp = createChildApp(rejected.deps);
  await rejectedApp.initialize();
  await rejectedApp.openTeacherHelp();
  rejected.calls.api.length = 0;
  rejected.calls.store.length = 0;
  rejected.calls.view.length = 0;
  assert.equal(await rejectedApp.lockTeacherHelp(), undefined);
  assert.equal(rejectedApp.getSnapshot().teacherUnlocked, true);
  assert.deepEqual(rejected.calls.api, ['teacherLock']);
  assert.deepEqual(rejected.calls.store, []);
  assert.deepEqual(rejected.calls.view, [
    ['showTeacherHelpError', '老师帮助暂时不可用，请稍后重试'],
    ['clearTeacherPin'],
  ]);

  const stale = createFixture();
  const pendingLock = deferred();
  stale.deps.api.teacherStatus = () => Promise.resolve({ configured: true, authenticated: true });
  stale.deps.api.teacherLock = () => {
    stale.calls.api.push('teacherLock');
    return pendingLock.promise;
  };
  const staleApp = createChildApp(stale.deps);
  await staleApp.initialize();
  await staleApp.openTeacherHelp();
  stale.calls.view.length = 0;
  const locking = staleApp.lockTeacherHelp();
  await flushMicrotasks();
  staleApp.destroy();
  pendingLock.resolve({ configured: true, authenticated: false });
  await locking;
  assert.equal(stale.calls.view.some(([kind]) => kind === 'closeTeacherHelp'), false);
  assert.equal(stale.calls.view.filter(([kind]) => kind === 'destroy').length, 1);
});

test('microphone handoff waits for confirmed teacher relock before closing or starting speech', async () => {
  const fixture = createFixture();
  const pendingLock = deferred();
  const order = [];
  fixture.deps.api.teacherLock = () => {
    fixture.calls.api.push('teacherLock');
    order.push('teacherLock');
    return pendingLock.promise;
  };
  const createSpeech = fixture.deps.createSpeech;
  fixture.deps.createSpeech = options => {
    const speech = createSpeech(options);
    const start = speech.start;
    speech.start = () => {
      order.push('speech:start');
      return start.call(speech);
    };
    return speech;
  };
  const render = fixture.deps.view.render;
  fixture.deps.view.render = snapshot => {
    order.push(`render:${snapshot.value}:${snapshot.teacherUnlocked}`);
    return render(snapshot);
  };
  const closeTeacherHelp = fixture.deps.view.closeTeacherHelp;
  fixture.deps.view.closeTeacherHelp = options => {
    order.push('closeTeacherHelp');
    return closeTeacherHelp(options);
  };

  const app = await enterAuthorizedRecovery(fixture);
  fixture.calls.api.length = 0;
  fixture.calls.view.length = 0;
  fixture.calls.speechStart = 0;
  order.length = 0;

  const work = app.retryMicrophone();
  await flushMicrotasks();
  assert.deepEqual(fixture.calls.api, ['teacherLock']);
  assert.equal(fixture.calls.speechStart, 0);
  assert.equal(fixture.calls.view.some(([kind]) => kind === 'closeTeacherHelp'), false);
  assert.equal(app.getSnapshot().value, 'recovery');
  assert.equal(app.getSnapshot().teacherUnlocked, true);
  assert.deepEqual(order, ['teacherLock']);

  pendingLock.resolve({ configured: true, authenticated: false });
  await work;
  assert.equal(fixture.calls.speechStart, 1);
  assert.equal(app.getSnapshot().value, 'listening');
  assert.equal(app.getSnapshot().teacherUnlocked, false);
  assert.deepEqual(fixture.calls.view.filter(([kind]) => kind === 'closeTeacherHelp'), [
    ['closeTeacherHelp', { clearText: true, restoreFocus: false }],
  ]);
  assert.deepEqual(order, [
    'teacherLock',
    'render:listening:true',
    'render:listening:false',
    'closeTeacherHelp',
    'speech:start',
  ]);
});

test('completion handoff waits for confirmed teacher relock before closing or completing', async () => {
  const fixture = createFixture();
  const pendingLock = deferred();
  const order = [];
  let completeAttempt = 0;
  fixture.deps.store.load = () => {
    fixture.calls.store.push('load');
    return pendingCompletionRecord();
  };
  fixture.deps.api.getActiveConversation = childId => {
    fixture.calls.api.push(['active', childId]);
    return Promise.resolve({ conversation: activeConversation() });
  };
  fixture.deps.api.complete = (conversationId, lastMessageId, signal) => {
    fixture.calls.api.push(['complete', conversationId, lastMessageId, signal]);
    completeAttempt += 1;
    if (completeAttempt === 1) return Promise.reject({ code: 'NETWORK_ERROR', retryable: true });
    order.push('complete');
    return Promise.resolve(completeResult());
  };
  fixture.deps.api.teacherStatus = () => {
    fixture.calls.api.push('teacherStatus');
    return Promise.resolve({ configured: true, authenticated: true });
  };
  fixture.deps.api.teacherLock = () => {
    fixture.calls.api.push('teacherLock');
    order.push('teacherLock');
    return pendingLock.promise;
  };
  const render = fixture.deps.view.render;
  fixture.deps.view.render = snapshot => {
    order.push(`render:${snapshot.value}:${snapshot.teacherUnlocked}`);
    return render(snapshot);
  };
  const closeTeacherHelp = fixture.deps.view.closeTeacherHelp;
  fixture.deps.view.closeTeacherHelp = options => {
    order.push('closeTeacherHelp');
    return closeTeacherHelp(options);
  };

  const app = createChildApp(fixture.deps);
  await app.initialize();
  assert.equal(app.getSnapshot().value, 'recovery');
  await app.openTeacherHelp();
  fixture.calls.api.length = 0;
  fixture.calls.view.length = 0;
  fixture.calls.store.length = 0;
  order.length = 0;

  const work = app.endWithTeacher();
  await flushMicrotasks();
  assert.deepEqual(fixture.calls.api, ['teacherLock']);
  assert.equal(fixture.calls.api.some(call => Array.isArray(call) && call[0] === 'complete'), false);
  assert.equal(fixture.calls.view.some(([kind]) => kind === 'closeTeacherHelp'), false);
  assert.equal(app.getSnapshot().value, 'recovery');
  assert.equal(app.getSnapshot().teacherUnlocked, true);
  assert.deepEqual(order, ['teacherLock']);

  pendingLock.resolve({ configured: true, authenticated: false });
  await work;
  assert.equal(app.getSnapshot().value, 'completed');
  assert.equal(app.getSnapshot().teacherUnlocked, false);
  assert.equal(fixture.calls.api.filter(call => Array.isArray(call) && call[0] === 'complete').length, 1);
  assert.deepEqual(fixture.calls.view.filter(([kind]) => kind === 'closeTeacherHelp'), [
    ['closeTeacherHelp', { clearText: true, restoreFocus: false }],
  ]);
  assert.deepEqual(order, [
    'teacherLock',
    'render:saving_conversation:true',
    'render:saving_conversation:false',
    'closeTeacherHelp',
    'complete',
    'render:completed:false',
  ]);
});

test('failed teacher relock keeps the handoff unlocked and allows a later retry', async () => {
  const fixture = createFixture();
  let lockWork = () => Promise.reject({ code: 'NETWORK_ERROR', message: 'private lock detail' });
  fixture.deps.api.teacherLock = () => {
    fixture.calls.api.push('teacherLock');
    return lockWork();
  };
  const app = await enterAuthorizedRecovery(fixture);
  fixture.calls.api.length = 0;
  fixture.calls.view.length = 0;
  fixture.calls.speechStart = 0;

  assert.equal(await app.retryMicrophone(), undefined);
  assert.equal(fixture.calls.speechStart, 0);
  assert.equal(app.getSnapshot().value, 'recovery');
  assert.equal(app.getSnapshot().teacherUnlocked, true);
  assert.deepEqual(fixture.calls.api, ['teacherLock']);
  assert.equal(fixture.calls.view.some(([kind]) => kind === 'closeTeacherHelp'), false);
  assert.deepEqual(fixture.calls.view.filter(([kind]) => kind === 'showTeacherHelpError'), [
    ['showTeacherHelpError', '老师帮助暂时不可用，请稍后重试'],
  ]);
  assert.equal(JSON.stringify(fixture.calls.view).includes('private lock detail'), false);

  lockWork = () => Promise.resolve({ configured: true, authenticated: false });
  fixture.calls.api.length = 0;
  fixture.calls.view.length = 0;
  assert.equal(await app.retryMicrophone(), undefined);
  assert.equal(fixture.calls.speechStart, 1);
  assert.equal(app.getSnapshot().value, 'listening');
  assert.equal(app.getSnapshot().teacherUnlocked, false);
  assert.deepEqual(fixture.calls.api, ['teacherLock']);
  assert.equal(fixture.calls.view.filter(([kind]) => kind === 'closeTeacherHelp').length, 1);
});

test('confirmed relock closes without starting speech when handoff persistence fails', async () => {
  const fixture = createFixture();
  let failHandoffSave = false;
  const save = fixture.deps.store.save;
  fixture.deps.store.save = snapshot => {
    if (failHandoffSave && snapshot.value === 'listening') throw new Error('private handoff save failure');
    return save(snapshot);
  };
  fixture.deps.api.teacherLock = () => {
    fixture.calls.api.push('teacherLock');
    return Promise.resolve({ configured: true, authenticated: false });
  };
  const app = await enterAuthorizedRecovery(fixture);
  failHandoffSave = true;
  fixture.calls.api.length = 0;
  fixture.calls.view.length = 0;
  fixture.calls.store.length = 0;
  fixture.calls.speechStart = 0;

  assert.equal(await app.retryMicrophone(), undefined);
  assert.deepEqual(fixture.calls.api, ['teacherLock']);
  assert.equal(fixture.calls.speechStart, 0);
  assert.equal(app.getSnapshot().value, 'recovery');
  assert.equal(app.getSnapshot().error.code, 'LOCAL_STORAGE_FAILED');
  assert.equal(app.getSnapshot().teacherUnlocked, false);
  assert.deepEqual(fixture.calls.view.filter(([kind]) => kind === 'closeTeacherHelp'), [
    ['closeTeacherHelp', { clearText: true, restoreFocus: false }],
  ]);
  assert.equal(JSON.stringify(fixture.calls.view).includes('private handoff save failure'), false);
});

test('confirmed relock still closes without work when the locked render fails', async () => {
  const fixture = createFixture();
  let failLockedRender = false;
  const render = fixture.deps.view.render;
  fixture.deps.view.render = snapshot => {
    const result = render(snapshot);
    if (failLockedRender && snapshot.value === 'listening' && snapshot.teacherUnlocked === false) {
      throw new Error('private locked render failure');
    }
    return result;
  };
  fixture.deps.api.teacherLock = () => {
    fixture.calls.api.push('teacherLock');
    return Promise.resolve({ configured: true, authenticated: false });
  };
  const app = await enterAuthorizedRecovery(fixture);
  failLockedRender = true;
  fixture.calls.api.length = 0;
  fixture.calls.view.length = 0;
  fixture.calls.speechStart = 0;

  assert.equal(await app.retryMicrophone(), undefined);
  assert.deepEqual(fixture.calls.api, ['teacherLock']);
  assert.equal(fixture.calls.speechStart, 0);
  assert.equal(app.getSnapshot().value, 'recovery');
  assert.equal(app.getSnapshot().error.code, 'VIEW_RENDER_FAILED');
  assert.equal(app.getSnapshot().teacherUnlocked, false);
  assert.deepEqual(fixture.calls.view.filter(([kind]) => kind === 'closeTeacherHelp'), [
    ['closeTeacherHelp', { clearText: true, restoreFocus: false }],
  ]);
  assert.equal(JSON.stringify(fixture.calls.view).includes('private locked render failure'), false);
});

test('confirmed relock reports fixed error and starts no work when dialog close fails', async () => {
  const fixture = createFixture();
  let failClose = false;
  const closeTeacherHelp = fixture.deps.view.closeTeacherHelp;
  fixture.deps.view.closeTeacherHelp = options => {
    const result = closeTeacherHelp(options);
    if (failClose) throw new Error('private close failure');
    return result;
  };
  fixture.deps.api.teacherLock = () => {
    fixture.calls.api.push('teacherLock');
    return Promise.resolve({ configured: true, authenticated: false });
  };
  const app = await enterAuthorizedRecovery(fixture);
  failClose = true;
  fixture.calls.api.length = 0;
  fixture.calls.view.length = 0;
  fixture.calls.speechStart = 0;

  assert.equal(await app.retryMicrophone(), undefined);
  assert.deepEqual(fixture.calls.api, ['teacherLock']);
  assert.equal(fixture.calls.speechStart, 0);
  assert.equal(app.getSnapshot().value, 'listening');
  assert.equal(app.getSnapshot().teacherUnlocked, false);
  assert.deepEqual(fixture.calls.view.filter(([kind]) => kind === 'showTeacherHelpError'), [
    ['showTeacherHelpError', '老师帮助暂时不可用，请稍后重试'],
  ]);
  assert.equal(JSON.stringify(fixture.calls.view).includes('private close failure'), false);
});

test('teacher auth effects share epoch cancellation and cannot leak raw values or unhandled rejections', async () => {
  for (const action of ['status', 'auth', 'lock']) {
    const fixture = createFixture();
    const app = await enterAuthorizedRecovery(fixture);
    fixture.calls.api.length = 0;
    fixture.calls.store.length = 0;
    fixture.calls.view.length = 0;

    const pending = action === 'status'
      ? app.openTeacherHelp()
      : action === 'auth'
        ? app.submitTeacherPin('4826')
        : app.lockTeacherHelp();
    app.reset();
    await pending;

    assert.deepEqual(fixture.calls.api, [], `${action} must not invoke after reset wins the microtask`);
    assert.equal(app.getSnapshot().value, 'welcome');
    assert.equal(app.getSnapshot().teacherUnlocked, false);
    assert.deepEqual(fixture.calls.store, ['clear']);
    if (action === 'auth') {
      assert.equal(fixture.calls.view.some(([kind]) => kind === 'clearTeacherPin'), true);
    }
  }

  const lateStatus = createFixture();
  const statusResult = deferred();
  let statusWork = () => Promise.resolve({ configured: true, authenticated: true });
  const statusAdapter = () => {
    lateStatus.calls.api.push('teacherStatus');
    return statusWork();
  };
  const lateStatusApp = await enterAuthorizedRecovery(lateStatus, statusAdapter);
  statusWork = () => statusResult.promise;
  lateStatus.calls.store.length = 0;
  lateStatus.calls.view.length = 0;
  const opening = lateStatusApp.openTeacherHelp();
  await flushMicrotasks();
  lateStatusApp.reset();
  statusResult.resolve({ configured: true, authenticated: true });
  await opening;
  assert.equal(lateStatusApp.getSnapshot().value, 'welcome');
  assert.equal(lateStatusApp.getSnapshot().teacherUnlocked, false);
  assert.equal(lateStatus.calls.view.some(([kind]) => kind === 'openTeacherHelp'), false);

  const lateAuth = createFixture();
  const authResult = deferred();
  let authStatus = { configured: true, authenticated: true };
  lateAuth.deps.api.teacherUnlock = pin => {
    lateAuth.calls.api.push(['teacherUnlock', pin]);
    return authResult.promise;
  };
  const lateAuthApp = await enterAuthorizedRecovery(lateAuth, () => Promise.resolve(authStatus));
  authStatus = { configured: true, authenticated: false };
  lateAuth.calls.store.length = 0;
  lateAuth.calls.view.length = 0;
  const authenticating = lateAuthApp.submitTeacherPin('4826');
  await flushMicrotasks();
  lateAuthApp.reset();
  authResult.resolve({ configured: true, authenticated: true });
  await authenticating;
  assert.equal(lateAuthApp.getSnapshot().value, 'welcome');
  assert.equal(lateAuthApp.getSnapshot().teacherUnlocked, false);
  assert.equal(JSON.stringify(lateAuth.calls.view).includes('4826'), false);
  assert.equal(JSON.stringify(lateAuth.calls.store).includes('4826'), false);

  const lateLock = createFixture();
  const lockResult = deferred();
  lateLock.deps.api.teacherStatus = () => Promise.resolve({ configured: true, authenticated: true });
  lateLock.deps.api.teacherLock = () => {
    lateLock.calls.api.push('teacherLock');
    return lockResult.promise;
  };
  const lateLockApp = await enterAuthorizedRecovery(lateLock);
  lateLock.calls.view.length = 0;
  const locking = lateLockApp.lockTeacherHelp();
  await flushMicrotasks();
  lateLockApp.destroy();
  lockResult.resolve({ configured: true, authenticated: false });
  await locking;
  assert.equal(lateLock.calls.view.some(([kind]) => kind === 'closeTeacherHelp'), false);

  for (const failure of [
    () => { throw { code: 'NETWORK_ERROR', message: 'raw-sync-4826' }; },
    () => ({ get then() { throw { code: 'NETWORK_ERROR', message: 'raw-then-4826' }; } }),
  ]) {
    const fixture = createFixture();
    fixture.deps.api.teacherStatus = failure;
    const app = createChildApp(fixture.deps);
    await app.initialize();
    fixture.calls.view.length = 0;
    await app.openTeacherHelp();
    assert.equal(JSON.stringify(fixture.calls.view).includes('raw-'), false);
    assert.deepEqual(fixture.calls.view.filter(([kind]) => kind !== 'render'), [
      ['openTeacherHelp', { unlocked: false }],
      ['showTeacherHelpError', '老师帮助暂时不可用，请稍后重试'],
    ]);
  }

  const betweenCalls = createFixture();
  const delayedStatus = deferred();
  let betweenStatusWork = () => Promise.resolve({ configured: true, authenticated: true });
  betweenCalls.deps.api.teacherUnlock = pin => {
    betweenCalls.calls.api.push(['teacherUnlock', pin]);
    return Promise.resolve({ configured: true, authenticated: true });
  };
  const betweenCallsApp = await enterAuthorizedRecovery(
    betweenCalls,
    () => betweenStatusWork(),
  );
  betweenStatusWork = () => delayedStatus.promise;
  betweenCalls.calls.api.length = 0;
  betweenCalls.calls.view.length = 0;
  const cancelledAuth = betweenCallsApp.submitTeacherPin('4826');
  await flushMicrotasks();
  betweenCallsApp.reset();
  assert.equal(
    betweenCalls.calls.view.some(([kind]) => kind === 'clearTeacherPin'),
    true,
    'reset cancellation must clear the live PIN input before status settles',
  );
  delayedStatus.resolve({ configured: true, authenticated: false });
  await cancelledAuth;
  assert.equal(
    betweenCalls.calls.api.some(call => Array.isArray(call) && call[0] === 'teacherUnlock'),
    false,
    'a cancelled status result must not start unlock',
  );

  const supersedingAuth = createFixture();
  const firstSupersededStatus = deferred();
  const secondUnlock = deferred();
  let supersedingStatusWork = () => Promise.resolve({ configured: true, authenticated: true });
  supersedingAuth.deps.api.teacherUnlock = pin => {
    supersedingAuth.calls.api.push(['teacherUnlock', pin]);
    return secondUnlock.promise;
  };
  const supersedingAuthApp = await enterAuthorizedRecovery(
    supersedingAuth,
    () => supersedingStatusWork(),
  );
  supersedingAuth.calls.api.length = 0;
  supersedingAuth.calls.view.length = 0;
  supersedingStatusWork = () => firstSupersededStatus.promise;
  const oldPinRequest = supersedingAuthApp.submitTeacherPin('1111');
  await flushMicrotasks();
  supersedingStatusWork = () => Promise.resolve({ configured: true, authenticated: false });
  const currentPinRequest = supersedingAuthApp.submitTeacherPin('2222');
  await flushMicrotasks();
  assert.deepEqual(
    supersedingAuth.calls.api.filter(call => Array.isArray(call) && call[0] === 'teacherUnlock'),
    [['teacherUnlock', '2222']],
  );
  assert.equal(
    supersedingAuth.calls.view.filter(([kind]) => kind === 'clearTeacherPin').length,
    0,
    'superseding an old auth request must not clear the current DOM PIN',
  );
  secondUnlock.resolve({ configured: true, authenticated: true });
  await currentPinRequest;
  assert.equal(
    supersedingAuth.calls.view.filter(([kind]) => kind === 'clearTeacherPin').length,
    1,
    'only the current auth request clears the current DOM PIN on settlement',
  );
  firstSupersededStatus.resolve({ configured: true, authenticated: false });
  await oldPinRequest;
  assert.equal(
    supersedingAuth.calls.view.filter(([kind]) => kind === 'clearTeacherPin').length,
    1,
    'the superseded auth settlement must remain inert',
  );
});

test('teacher text and saved draft enter recovery through legal drafts and one chat registry boundary', async () => {
  const submitted = createFixture();
  const response = deferred();
  const order = [];
  const save = submitted.deps.store.save;
  submitted.deps.store.save = snapshot => {
    order.push(`save:${snapshot.value}`);
    return save(snapshot);
  };
  submitted.deps.api.chat = (input, signal) => {
    order.push('chat');
    submitted.calls.api.push(['chat', input, signal]);
    return response.promise;
  };
  const submittedApp = await enterAuthorizedRecovery(submitted);
  submitted.calls.api.length = 0;
  submitted.calls.store.length = 0;
  order.length = 0;

  const sending = submittedApp.submitTeacherText('  我补录了这句话  ');
  await flushMicrotasks();
  assert.deepEqual(order, ['save:submitting', 'chat']);
  const chatCall = submitted.calls.api.find(call => Array.isArray(call) && call[0] === 'chat');
  assert.equal(chatCall[1].text, '我补录了这句话');
  assert.equal(chatCall[1].request_id, '00000000-0000-4000-8000-000000000007');
  assert.equal(submittedApp.getSnapshot().draft.request_id, chatCall[1].request_id);
  response.resolve(chatResult({ request_id: chatCall[1].request_id }));
  assert.equal(await sending, undefined);

  const saved = createFixture();
  saved.deps.api.chat = (input, signal) => {
    saved.calls.api.push(['chat', input, signal]);
    return Promise.resolve(chatResult({ request_id: input.request_id }));
  };
  const savedApp = await enterAuthorizedRecovery(saved);
  saved.calls.api.length = 0;
  saved.calls.store.length = 0;
  assert.equal(await savedApp.saveTeacherDraft('  请稍后重发  '), undefined);
  assert.equal(savedApp.getSnapshot().value, 'submission_failed');
  assert.equal(savedApp.getSnapshot().draft.text, '请稍后重发');
  assert.deepEqual(savedApp.getSnapshot().error, { code: 'TEACHER_DRAFT_SAVED', retryable: true });
  assert.equal(saved.calls.api.some(call => Array.isArray(call) && call[0] === 'chat'), false);
  const savedRequestId = savedApp.getSnapshot().draft.request_id;
  assert.equal(await savedApp.retry(), undefined);
  const retryCall = saved.calls.api.find(call => Array.isArray(call) && call[0] === 'chat');
  assert.equal(retryCall[1].request_id, savedRequestId);
  assert.equal(retryCall[1].text, '请稍后重发');

  const doubled = createFixture();
  const doubledResponse = deferred();
  doubled.deps.api.chat = (input, signal) => {
    doubled.calls.api.push(['chat', input, signal]);
    return doubledResponse.promise;
  };
  const doubledApp = await enterAuthorizedRecovery(doubled);
  doubled.calls.api.length = 0;
  const first = doubledApp.submitTeacherText('只能发送一次');
  const second = doubledApp.submitTeacherText('不能覆盖第一次');
  await flushMicrotasks();
  const doubledCalls = doubled.calls.api.filter(call => Array.isArray(call) && call[0] === 'chat');
  assert.equal(doubledCalls.length, 1);
  assert.equal(doubledCalls[0][1].text, '只能发送一次');
  assert.equal(await second, undefined);
  doubledResponse.resolve(chatResult({ request_id: doubledCalls[0][1].request_id }));
  assert.equal(await first, undefined);

  const broken = createFixture();
  broken.deps.createDraft = () => { throw new Error('private draft failure'); };
  const brokenApp = await enterAuthorizedRecovery(broken);
  broken.calls.api.length = 0;
  assert.equal(await brokenApp.submitTeacherText('不会发送'), undefined);
  assert.equal(brokenApp.getSnapshot().value, 'recovery');
  assert.equal(brokenApp.getSnapshot().error.code, 'DRAFT_CREATION_FAILED');
  assert.equal(broken.calls.api.some(call => Array.isArray(call) && call[0] === 'chat'), false);
});

test('authorized recovery retry, microphone retry, and manual completion use only current safe effects', async () => {
  const recovered = createFixture();
  let loadCount = 0;
  recovered.deps.store.load = () => {
    recovered.calls.store.push('load');
    loadCount += 1;
    return loadCount === 1 ? null : localReadyRecord();
  };
  const recoveredApp = await enterAuthorizedRecovery(recovered);
  recovered.calls.api.length = 0;
  recovered.calls.store.length = 0;
  assert.equal(await recoveredApp.retryTeacherRecovery(), undefined);
  assert.equal(recoveredApp.getSnapshot().value, 'selecting_child');
  assert.equal(recoveredApp.getSnapshot().teacherUnlocked, true);
  assert.deepEqual(recovered.calls.api, [['active', 7], 'roster', ['active', 7]]);
  assert.equal(recovered.calls.store[0][0], 'save');
  assert.equal(recovered.calls.store[0][1].value, 'recovery');
  assert.equal(recovered.calls.store[1], 'load');

  const superseded = createFixture();
  const firstActive = deferred();
  const secondLoad = deferred();
  let loadWork = () => null;
  let activeReads = 0;
  superseded.deps.store.load = () => {
    superseded.calls.store.push('load');
    return loadWork();
  };
  const supersededApp = await enterAuthorizedRecovery(
    superseded,
    null,
    childId => {
      superseded.calls.api.push(['active', childId]);
      activeReads += 1;
      return activeReads === 1 ? Promise.resolve({ conversation: null }) : firstActive.promise;
    },
  );
  loadWork = () => localReadyRecord();
  const firstRetry = supersededApp.retryTeacherRecovery();
  await flushMicrotasks();
  assert.equal(activeReads, 2);
  loadWork = () => secondLoad.promise;
  const secondRetry = supersededApp.retryTeacherRecovery();
  await flushMicrotasks();
  const writesBeforeOldRead = superseded.calls.store.filter(call => Array.isArray(call) && call[0] === 'save').length;
  firstActive.resolve({ conversation: null });
  await flushMicrotasks();
  assert.equal(supersededApp.getSnapshot().value, 'recovery');
  assert.equal(supersededApp.getSnapshot().teacherUnlocked, true);
  assert.equal(
    superseded.calls.store.filter(call => Array.isArray(call) && call[0] === 'save').length,
    writesBeforeOldRead,
    'the first retry child read must be inert after a second retry owns recovery',
  );
  secondLoad.resolve(localReadyRecord());
  await Promise.all([firstRetry, secondRetry]);

  const supersededRoster = createFixture();
  const oldRoster = deferred();
  const currentRosterLoad = deferred();
  let rosterLoadWork = () => null;
  let rosterAPIWork = () => Promise.resolve([childRecord()]);
  let rosterReads = 0;
  supersededRoster.deps.store.load = () => {
    supersededRoster.calls.store.push('load');
    return rosterLoadWork();
  };
  const supersededRosterApp = await enterAuthorizedRecovery(
    supersededRoster,
    null,
    null,
    () => rosterAPIWork(),
  );
  rosterAPIWork = () => {
    rosterReads += 1;
    supersededRoster.calls.api.push('roster');
    return oldRoster.promise;
  };
  supersededRoster.calls.store.length = 0;
  supersededRoster.calls.api.length = 0;
  const oldRosterRetry = supersededRosterApp.retryTeacherRecovery();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(rosterReads, 1);
  rosterLoadWork = () => currentRosterLoad.promise;
  const currentRosterRetry = supersededRosterApp.retryTeacherRecovery();
  await flushMicrotasks();
  const rosterWritesBeforeLateResult = supersededRoster.calls.store.filter(
    call => Array.isArray(call) && call[0] === 'save',
  ).length;
  oldRoster.resolve([childRecord()]);
  await flushMicrotasks();
  assert.equal(supersededRosterApp.getSnapshot().value, 'recovery');
  assert.equal(
    supersededRoster.calls.api.filter(call => Array.isArray(call) && call[0] === 'active').length,
    0,
    'a superseded roster result must not start an active-conversation continuation',
  );
  assert.equal(
    supersededRoster.calls.store.filter(call => Array.isArray(call) && call[0] === 'save').length,
    rosterWritesBeforeLateResult,
  );
  currentRosterLoad.resolve(localReadyRecord());
  await Promise.all([oldRosterRetry, currentRosterRetry]);

  const supersededPair = createFixture();
  const activeSeven = deferred();
  const activeEight = deferred();
  const currentPairLoad = deferred();
  let pairLoadWork = () => null;
  let pairRosterWork = () => Promise.resolve([childRecord()]);
  let pairActiveWork = () => Promise.resolve({ conversation: null });
  supersededPair.deps.store.load = () => {
    supersededPair.calls.store.push('load');
    return pairLoadWork();
  };
  const supersededPairApp = await enterAuthorizedRecovery(
    supersededPair,
    null,
    childId => pairActiveWork(childId),
    () => pairRosterWork(),
  );
  pairRosterWork = () => Promise.resolve([
    childRecord(7, '小雨'),
    childRecord(8, '乐乐'),
  ]);
  pairActiveWork = childId => {
    supersededPair.calls.api.push(['active', childId]);
    return childId === 7 ? activeSeven.promise : activeEight.promise;
  };
  supersededPair.calls.store.length = 0;
  supersededPair.calls.api.length = 0;
  const oldPairRetry = supersededPairApp.retryTeacherRecovery();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(supersededPair.calls.api, [['active', 7], ['active', 8]]);
  pairLoadWork = () => currentPairLoad.promise;
  const currentPairRetry = supersededPairApp.retryTeacherRecovery();
  await flushMicrotasks();
  const pairWritesBeforeLateResults = supersededPair.calls.store.filter(
    call => Array.isArray(call) && call[0] === 'save',
  ).length;
  activeSeven.resolve({ conversation: { ...activeConversation(), child_id: 7 } });
  activeEight.resolve({ conversation: { ...activeConversation(), id: 10, child_id: 8 } });
  await flushMicrotasks();
  assert.equal(supersededPairApp.getSnapshot().value, 'recovery');
  assert.equal(
    supersededPair.calls.store.filter(call => Array.isArray(call) && call[0] === 'save').length,
    pairWritesBeforeLateResults,
    'superseded multi-active continuations must not merge or persist',
  );
  currentPairLoad.resolve(localReadyRecord());
  await Promise.all([oldPairRetry, currentPairRetry]);

  const microphone = createFixture();
  const microphoneOrder = [];
  const microphoneSave = microphone.deps.store.save;
  const microphoneStart = microphone.deps.createSpeech;
  microphone.deps.store.save = snapshot => {
    microphoneOrder.push(`save:${snapshot.value}`);
    return microphoneSave(snapshot);
  };
  microphone.deps.createSpeech = options => {
    const speech = microphoneStart(options);
    const start = speech.start;
    speech.start = () => {
      microphoneOrder.push('speech:start');
      return start.call(speech);
    };
    return speech;
  };
  microphone.deps.api.teacherLock = () => {
    microphone.calls.api.push('teacherLock');
    return Promise.resolve({ configured: true, authenticated: false });
  };
  const microphoneApp = await enterAuthorizedRecovery(microphone);
  microphone.calls.api.length = 0;
  microphone.calls.view.length = 0;
  microphoneOrder.length = 0;
  assert.equal(await microphoneApp.retryMicrophone(), undefined);
  assert.equal(microphoneApp.getSnapshot().value, 'listening');
  assert.equal(microphoneApp.getSnapshot().teacherUnlocked, false);
  assert.deepEqual(microphone.calls.api, ['teacherLock']);
  assert.deepEqual(microphoneOrder, ['save:listening', 'speech:start']);
  assert.deepEqual(microphone.calls.view.filter(([kind]) => kind !== 'render'), [
    ['closeTeacherHelp', { clearText: true, restoreFocus: false }],
    ['clearTeacherPin'],
  ]);

  const unsafeEnd = createFixture();
  const unsafeEndApp = await enterAuthorizedRecovery(unsafeEnd);
  unsafeEnd.calls.api.length = 0;
  assert.equal(await unsafeEndApp.endWithTeacher(), undefined);
  assert.equal(unsafeEndApp.getSnapshot().value, 'recovery');
  assert.equal(unsafeEnd.calls.api.some(call => Array.isArray(call) && call[0] === 'complete'), false);

  const completion = createFixture();
  let completeAttempt = 0;
  completion.deps.store.load = () => {
    completion.calls.store.push('load');
    return pendingCompletionRecord();
  };
  completion.deps.api.getActiveConversation = childId => {
    completion.calls.api.push(['active', childId]);
    return Promise.resolve({ conversation: activeConversation() });
  };
  completion.deps.api.complete = (conversationId, lastMessageId, signal) => {
    completion.calls.api.push(['complete', conversationId, lastMessageId, signal]);
    completeAttempt += 1;
    return completeAttempt === 1
      ? Promise.reject({ code: 'NETWORK_ERROR', retryable: true })
      : Promise.resolve(completeResult());
  };
  completion.deps.api.teacherStatus = () => {
    completion.calls.api.push('teacherStatus');
    return Promise.resolve({ configured: true, authenticated: true });
  };
  completion.deps.api.teacherLock = () => {
    completion.calls.api.push('teacherLock');
    return Promise.resolve({ configured: true, authenticated: false });
  };
  const completionApp = createChildApp(completion.deps);
  await completionApp.initialize();
  assert.equal(completionApp.getSnapshot().value, 'recovery');
  await completionApp.openTeacherHelp();
  completion.calls.api.length = 0;
  completion.calls.store.length = 0;
  completion.calls.view.length = 0;
  assert.equal(await completionApp.endWithTeacher(), undefined);
  assert.equal(completionApp.getSnapshot().value, 'completed');
  assert.equal(completionApp.getSnapshot().teacherUnlocked, false);
  assert.equal(completion.calls.api[0], 'teacherLock');
  const completeCalls = completion.calls.api.filter(call => Array.isArray(call) && call[0] === 'complete');
  assert.equal(completeCalls.length, 1);
  assert.equal(completeCalls[0][1], 9);
  assert.equal(completeCalls[0][2], 42);
  assert.equal(typeof completeCalls[0][3], 'object');
  assert.deepEqual(completion.calls.view.filter(([kind]) => kind !== 'render'), [
    ['closeTeacherHelp', { clearText: true, restoreFocus: false }],
    ['clearTeacherPin'],
  ]);
});

test('bootstrap gate rejection reports fixed maintenance copy before any child resource factory', async () => {
  const fixture = createBootstrapFixture();
  fixture.deps.bootstrapAPI = () => {
    fixture.calls.bootstrapAPI += 1;
    return Promise.reject({ code: 'VERSION_MISMATCH', message: 'do not leak' });
  };

  assert.equal(await bootstrapBrowserChildApp(fixture.deps), null);
  assert.equal(fixture.calls.bootstrapAPI, 1);
  assert.deepEqual(fixture.calls.maintenance, ['VERSION_MISMATCH']);
  assert.equal(fixture.calls.storeFactory, 0);
  assert.equal(fixture.calls.ttsFactory, 0);
  assert.equal(fixture.calls.viewFactory, 0);
  assert.equal(fixture.child.calls.speechFactory, 0);
  assert.deepEqual(fixture.child.calls.store, []);
  assert.deepEqual(fixture.child.calls.api, []);
});

test('bootstrap composes a preflight API facade in gate-first factory order', async () => {
  const fixture = createBootstrapFixture();
  fixture.child.deps.api.ready = () => {
    fixture.calls.order.push('source-ready');
    fixture.child.calls.api.push('ready');
    return Promise.resolve();
  };

  const app = await bootstrapBrowserChildApp(fixture.deps);

  assert.equal(typeof app.start, 'function');
  assert.deepEqual(fixture.calls.order, ['api', 'source-ready', 'store', 'tts', 'view']);
  assert.deepEqual(fixture.child.calls.api, ['ready']);
  assert.equal(fixture.calls.storeFactory, 1);
  assert.equal(fixture.calls.ttsFactory, 1);
  assert.equal(fixture.calls.viewFactory, 1);
  assert.equal(fixture.child.calls.speechFactory, 1);
  assert.equal(fixture.child.calls.view.filter(([kind]) => kind === 'render').length, 1);
  assert.equal(app.getSnapshot().value, 'welcome');
});

test('a post-gate speech construction failure cleans created view and TTS exactly once before rejecting fresh', async () => {
  const fixture = createBootstrapFixture();
  fixture.deps.createSpeech = () => { throw new Error('private speech failure'); };

  await assert.rejects(() => bootstrapBrowserChildApp(fixture.deps), error => {
    assert.equal(error instanceof TypeError, true);
    assert.equal(Object.hasOwn(error, 'cause'), false);
    return true;
  });
  assert.deepEqual(fixture.calls.order, ['api', 'store', 'tts', 'view']);
  assert.deepEqual(fixture.child.calls.tts, [['dispose']]);
  assert.deepEqual(fixture.child.calls.view.filter(([kind]) => kind === 'destroy'), [['destroy']]);
  assert.deepEqual(fixture.child.calls.store, []);
});

test('a reentrant bootstrap call from bootstrapAPI cannot create a second factory chain', async () => {
  const fixture = createBootstrapFixture();
  let nested = null;
  fixture.deps.bootstrapAPI = () => {
    fixture.calls.bootstrapAPI += 1;
    if (nested === null) nested = bootstrapBrowserChildApp(fixture.deps);
    return Promise.resolve(fixture.child.deps.api);
  };

  const app = await bootstrapBrowserChildApp(fixture.deps);
  assert.equal(typeof app.start, 'function');
  assert.equal(await nested, null);
  assert.equal(fixture.calls.bootstrapAPI, 1);
  assert.equal(fixture.calls.storeFactory, 1);
  assert.equal(fixture.calls.ttsFactory, 1);
  assert.equal(fixture.calls.viewFactory, 1);
});

test('initialize caches readiness, awaits it before one local load, and leaves an absent record at welcome', async () => {
  const fixture = createFixture();
  const ready = deferred();
  fixture.deps.api.ready = () => {
    fixture.calls.api.push('ready');
    return ready.promise;
  };
  fixture.deps.store.load = () => {
    fixture.calls.store.push('load');
    return null;
  };
  const app = createChildApp(fixture.deps);

  const first = app.initialize();
  const second = app.initialize();
  assert.equal(first, second);
  await flushMicrotasks();
  assert.deepEqual(fixture.calls.api, ['ready']);
  assert.deepEqual(fixture.calls.store, []);

  ready.resolve();
  assert.equal(await first, undefined);
  assert.deepEqual(fixture.calls.store, ['load']);
  assert.equal(app.getSnapshot().value, 'welcome');
  assert.deepEqual(fixture.calls.api, ['ready']);
  assert.deepEqual(fixture.calls.tts, []);
  assert.equal(fixture.calls.speechStart, 0);
});

test('a failed readiness gate leaves welcome rendered once and makes later start inert', async () => {
  const fixture = createFixture();
  fixture.deps.api.ready = () => {
    fixture.calls.api.push('ready');
    return Promise.reject({ code: 'HEALTH_UNAVAILABLE', message: 'private' });
  };
  const app = createChildApp(fixture.deps);

  assert.equal(await app.initialize(), undefined);
  assert.equal(await app.start(), undefined);
  assert.deepEqual(fixture.calls.api, ['ready']);
  assert.deepEqual(fixture.calls.store, []);
  assert.equal(fixture.calls.view.filter(([kind]) => kind === 'render').length, 1);
  assert.equal(app.getSnapshot().value, 'welcome');
});

test('a valid local child record bridges through nonpersisting recovery before its child-scoped active read', async () => {
  const fixture = createFixture();
  const local = localDraftRecord();
  const active = deferred();
  fixture.deps.store.load = () => {
    fixture.calls.store.push('load');
    return local;
  };
  fixture.deps.api.getActiveConversation = childId => {
    fixture.calls.api.push(['active', childId]);
    return active.promise;
  };
  const app = createChildApp(fixture.deps);
  const initialized = app.initialize();

  await flushMicrotasks();
  assert.deepEqual(fixture.calls.api, ['ready', ['active', 7]]);
  assert.equal(fixture.calls.api.includes('roster'), false);
  assert.deepEqual(fixture.calls.store, ['load']);
  assert.equal(app.getSnapshot().value, 'recovery');
  assert.equal(local.draft.request_id, '00000000-0000-4000-8000-000000000007');

  active.resolve({ conversation: null });
  assert.equal(await initialized, undefined);
  assert.equal(app.getSnapshot().value, 'submission_failed');
  assert.equal(app.getSnapshot().draft.request_id, local.draft.request_id);
  assert.equal(fixture.calls.store.length, 2);
  assert.equal(fixture.calls.store[1][0], 'save');
  assert.equal(fixture.calls.store[1][1].value, 'submission_failed');
});

test('start leaves no durable loading record and persists direct empty-roster selection only after the roster read', async () => {
  const fixture = createFixture();
  fixture.deps.api.getTodayRoster = () => {
    fixture.calls.api.push('roster');
    return Promise.resolve([]);
  };
  const app = createChildApp(fixture.deps);

  await app.initialize();
  assert.equal(app.getSnapshot().value, 'welcome');
  assert.equal(await app.start(), undefined);
  assert.equal(app.getSnapshot().value, 'selecting_child');
  assert.deepEqual(fixture.calls.api, ['ready', 'roster']);
  assert.deepEqual(fixture.calls.store.map(item => Array.isArray(item) ? [item[0], item[1].value] : item), [
    'load',
    ['save', 'selecting_child'],
  ]);
});

test('a one-child no-local roster waits for its active read before persisted roster selection', async () => {
  const fixture = createFixture();
  fixture.deps.api.getTodayRoster = () => {
    fixture.calls.api.push('roster');
    return Promise.resolve([childRecord()]);
  };
  fixture.deps.api.getActiveConversation = childId => {
    fixture.calls.api.push(['active', childId]);
    return Promise.resolve({ conversation: null });
  };
  const app = createChildApp(fixture.deps);

  await app.initialize();
  assert.equal(await app.start(), undefined);
  assert.equal(app.getSnapshot().value, 'selecting_child');
  assert.deepEqual(fixture.calls.api, ['ready', 'roster', ['active', 7]]);
  assert.equal(fixture.calls.store.filter(item => Array.isArray(item) && item[0] === 'save').length, 1);
});

test('selectChild persists selection before one exact greeting TTS and settles current opening to ready', async () => {
  const fixture = createFixture();
  const spoken = deferred();
  fixture.deps.api.getTodayRoster = () => {
    fixture.calls.api.push('roster');
    return Promise.resolve([childRecord()]);
  };
  fixture.deps.api.getActiveConversation = childId => {
    fixture.calls.api.push(['active', childId]);
    return Promise.resolve({ conversation: null });
  };
  fixture.deps.tts.speak = text => {
    fixture.calls.tts.push(['speak', text]);
    return spoken.promise;
  };
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();

  const selecting = app.selectChild(7);
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'opening');
  assert.equal(fixture.calls.store.at(-1)[0], 'save');
  assert.equal(fixture.calls.store.at(-1)[1].value, 'opening');
  assert.deepEqual(fixture.calls.tts, [[
    'speak',
    '你好呀，小雨！我是鸭鸭日记本，今天想听你讲讲照顾小鸭的事～',
  ]]);

  spoken.resolve({ mode: 'text', reason: 'fallback' });
  assert.equal(await selecting, undefined);
  assert.equal(app.getSnapshot().value, 'ready');
  assert.equal(fixture.calls.store.at(-1)[1].value, 'ready');
});

test('two record toggles in one tick persist listening then stop the already-registered speech run exactly once', async () => {
  const fixture = createFixture();
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  assert.equal(app.getSnapshot().value, 'ready');

  assert.equal(app.recordToggle(), undefined);
  assert.equal(app.getSnapshot().value, 'listening');
  assert.equal(fixture.calls.speechStart, 1);
  assert.equal(fixture.calls.speechStop, 0);
  assert.equal(fixture.calls.store.at(-1)[1].stopRequested, false);

  assert.equal(app.recordToggle(), undefined);
  assert.equal(app.getSnapshot().value, 'listening');
  assert.equal(app.getSnapshot().stopRequested, true);
  assert.equal(fixture.calls.speechStop, 1);
  assert.equal(fixture.calls.store.at(-1)[1].stopRequested, true);

  app.recordToggle();
  assert.equal(fixture.calls.speechStop, 1);
});

test('a synchronous final from speech.start is unauthorized and cannot launch chat', async () => {
  const fixture = createFixture();
  const chat = deferred();
  fixture.speech.start = () => {
    fixture.calls.speechStart += 1;
    fixture.emitSpeech({ type: 'final', text: '同步语音' });
  };
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  fixture.deps.api.chat = (input, signal) => {
    fixture.calls.api.push(['chat', input, signal]);
    return chat.promise;
  };
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);

  app.recordToggle();
  assert.equal(fixture.calls.speechStart, 1);
  assert.equal(app.getSnapshot().value, 'listening');
  assert.equal(app.getSnapshot().stopRequested, false);
  assert.equal(fixture.calls.api.some(call => Array.isArray(call) && call[0] === 'chat'), false);
  await flushMicrotasks();
  assert.equal(fixture.calls.api.filter(call => Array.isArray(call) && call[0] === 'chat').length, 0);
});

test('final and empty require the current recording generation explicit-stop grant', async () => {
  const fixture = createFixture();
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);

  app.recordToggle();
  fixture.emitSpeech({ type: 'final', text: '未授权最终稿' });
  fixture.emitSpeech({ type: 'empty' });
  assert.equal(app.getSnapshot().value, 'listening');
  assert.equal(app.getSnapshot().stopRequested, false);
  assert.equal(fixture.calls.speechStop, 0);
  assert.equal(fixture.calls.api.some(call => Array.isArray(call) && call[0] === 'chat'), false);

  explicitlyStopAndEmitSpeech(app, fixture, { type: 'empty' });
  assert.equal(app.getSnapshot().value, 'ready');

  app.recordToggle();
  fixture.emitSpeech({ type: 'final', text: '上一轮停止授权不可复用' });
  fixture.emitSpeech({ type: 'empty' });
  assert.equal(app.getSnapshot().value, 'listening');
  assert.equal(app.getSnapshot().stopRequested, false);
  explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '当前轮明确结束' });
  assert.equal(app.getSnapshot().value, 'submitting');
  await flushMicrotasks();
  assert.equal(fixture.calls.api.filter(call => Array.isArray(call) && call[0] === 'chat').length, 1);
});

test('current speech partials only announce, empty settles ready, and errors enter sanitized recovery', async () => {
  const fixture = createFixture();
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);

  const savesBeforePartial = fixture.calls.store.filter(item => Array.isArray(item) && item[0] === 'save').length;
  app.recordToggle();
  fixture.emitSpeech({ type: 'partial', text: '我在给小鸭换水' });
  assert.equal(app.getSnapshot().value, 'listening');
  assert.deepEqual(fixture.calls.view.at(-1), ['announce', '我在给小鸭换水']);
  assert.equal(fixture.calls.store.filter(item => Array.isArray(item) && item[0] === 'save').length, savesBeforePartial + 1);
  assert.equal(fixture.calls.api.some(call => Array.isArray(call) && call[0] === 'chat'), false);

  explicitlyStopAndEmitSpeech(app, fixture, { type: 'empty' });
  assert.equal(app.getSnapshot().value, 'ready');
  assert.equal(fixture.calls.store.at(-1)[1].value, 'ready');

  app.recordToggle();
  fixture.emitSpeech({
    type: 'error',
    error: {
      code: 'MIC_PERMISSION_DENIED',
      retryable: true,
      message: 'do not expose this',
      cause: { private: true },
    },
  });
  assert.equal(app.getSnapshot().value, 'recovery');
  assert.deepEqual(app.getSnapshot().error, {
    code: 'MIC_PERMISSION_DENIED',
    retryable: false,
  });
  assert.equal(Object.hasOwn(app.getSnapshot().error, 'message'), false);
  assert.equal(Object.hasOwn(app.getSnapshot().error, 'cause'), false);
});

test('a throwing partial announcement is absorbed without ending the current listening run', async () => {
  const fixture = createFixture();
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  fixture.deps.view.announce = () => { throw new Error('private announce failure'); };
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  app.recordToggle();

  fixture.emitSpeech({ type: 'partial', text: 'still listening' });
  assert.equal(app.getSnapshot().value, 'listening');
  assert.equal(app.getSnapshot().stopRequested, false);
  assert.equal(fixture.calls.speechStop, 0);
});

test('a current final creates one canonical draft, persists submitting, then launches one exact chat', async () => {
  const fixture = createFixture();
  const chat = deferred();
  let draftCalls = 0;
  const originalCreateDraft = fixture.deps.createDraft;
  fixture.deps.createDraft = (...args) => {
    draftCalls += 1;
    return originalCreateDraft(...args);
  };
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  fixture.deps.api.chat = (input, signal) => {
    fixture.calls.api.push(['chat', input, signal]);
    return chat.promise;
  };
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);

  app.recordToggle();
  explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '  我给小鸭换了水  ' });
  fixture.emitSpeech({ type: 'final', text: 'duplicate must be inert' });

  assert.equal(app.getSnapshot().value, 'submitting');
  assert.deepEqual(app.getSnapshot().draft, {
    text: '我给小鸭换了水',
    request_id: '00000000-0000-4000-8000-000000000007',
    created_at: '2026-08-23T00:00:00.000Z',
  });
  assert.equal(draftCalls, 1);
  assert.equal(fixture.calls.store.at(-1)[1].value, 'submitting');
  assert.equal(fixture.calls.api.some(call => Array.isArray(call) && call[0] === 'chat'), false);

  await flushMicrotasks();
  const chatCalls = fixture.calls.api.filter(call => Array.isArray(call) && call[0] === 'chat');
  assert.equal(chatCalls.length, 1);
  assert.deepEqual(chatCalls[0][1], {
    request_id: '00000000-0000-4000-8000-000000000007',
    child_id: 7,
    text: '我给小鸭换了水',
    conversation_id: null,
    max_rounds: 3,
  });
  assert.equal(chatCalls[0][2], fixture.controllers.at(-1).signal);
});

test('a malformed draft result is treated as DRAFT_CREATION_FAILED without launching chat', async () => {
  const fixture = createFixture();
  fixture.deps.createDraft = () => ({ text: '', request_id: 'bad', created_at: 'bad' });
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  app.recordToggle();

  explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '我给小鸭换了水' });
  assert.equal(app.getSnapshot().value, 'recovery');
  assert.deepEqual(app.getSnapshot().error, {
    code: 'DRAFT_CREATION_FAILED',
    retryable: false,
  });
  assert.equal(fixture.calls.api.some(call => Array.isArray(call) && call[0] === 'chat'), false);
});

test('a persisted successful chat starts one reply TTS and its settlement advances speaking to ready', async () => {
  const fixture = createFixture();
  const chat = deferred();
  const replySpeech = deferred();
  const order = [];
  const save = fixture.deps.store.save;
  fixture.deps.store.save = snapshot => {
    order.push(`save:${snapshot.value}`);
    return save(snapshot);
  };
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  fixture.deps.api.chat = (input, signal) => {
    fixture.calls.api.push(['chat', input, signal]);
    return chat.promise;
  };
  fixture.deps.tts.speak = text => {
    fixture.calls.tts.push(['speak', text]);
    order.push(`speak:${text}`);
    return text === '真棒！' ? replySpeech.promise : Promise.resolve({ mode: 'text' });
  };
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);

  app.recordToggle();
  explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '我给小鸭换了水' });
  await flushMicrotasks();
  chat.resolve(chatResult());
  await flushMicrotasks();

  assert.equal(app.getSnapshot().value, 'speaking');
  assert.equal(order.indexOf('save:speaking') < order.indexOf('speak:真棒！'), true);
  assert.equal(fixture.calls.tts.filter(([kind, text]) => kind === 'speak' && text === '真棒！').length, 1);

  replySpeech.resolve({ mode: 'text', reason: 'fallback' });
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'ready');
  assert.equal(fixture.calls.store.at(-1)[1].value, 'ready');
});

test('a speaking-state save failure starts no reply TTS and remains LOCAL_STORAGE_FAILED recovery', async () => {
  const fixture = createFixture();
  const save = fixture.deps.store.save;
  fixture.deps.store.save = snapshot => {
    if (snapshot.value === 'speaking') throw new Error('private speaking write failure');
    return save(snapshot);
  };
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  fixture.deps.api.chat = (input, signal) => {
    fixture.calls.api.push(['chat', input, signal]);
    return Promise.resolve(chatResult());
  };
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);

  app.recordToggle();
  explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '我给小鸭换了水' });
  await flushMicrotasks();

  assert.equal(app.getSnapshot().value, 'recovery');
  assert.deepEqual(app.getSnapshot().error, {
    code: 'LOCAL_STORAGE_FAILED',
    retryable: false,
  });
  assert.equal(fixture.calls.tts.some(([kind, text]) => kind === 'speak' && text === '真棒！'), false);
});

test('a retryable chat failure normalizes REQUEST_IN_PROGRESS and retries the exact persisted draft once', async () => {
  const fixture = createFixture();
  const firstChat = deferred();
  const secondChat = deferred();
  let chatAttempt = 0;
  let draftCalls = 0;
  const originalCreateDraft = fixture.deps.createDraft;
  fixture.deps.createDraft = (...args) => {
    draftCalls += 1;
    return originalCreateDraft(...args);
  };
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  fixture.deps.api.chat = (input, signal) => {
    fixture.calls.api.push(['chat', input, signal]);
    const result = chatAttempt === 0 ? firstChat.promise : secondChat.promise;
    chatAttempt += 1;
    return result;
  };
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);

  app.recordToggle();
  explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '我给小鸭换了水' });
  await flushMicrotasks();
  firstChat.reject({ code: 'REQUEST_IN_PROGRESS', retryable: false, message: 'private' });
  await flushMicrotasks();

  assert.equal(app.getSnapshot().value, 'submission_failed');
  assert.deepEqual(app.getSnapshot().error, { code: 'REQUEST_IN_PROGRESS', retryable: true });
  const preservedDraft = app.getSnapshot().draft;
  assert.equal(draftCalls, 1);

  const retried = app.retry();
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'submitting');
  assert.equal(draftCalls, 1);
  const chatCalls = fixture.calls.api.filter(call => Array.isArray(call) && call[0] === 'chat');
  assert.equal(chatCalls.length, 2);
  assert.deepEqual(chatCalls[1][1], chatCalls[0][1]);
  assert.deepEqual(app.getSnapshot().draft, preservedDraft);

  secondChat.resolve(chatResult());
  assert.equal(await retried, undefined);
});

test('chat failures force approved retryability and ignore hostile error accessors', async () => {
  let accessorReads = 0;
  const hostileAccessor = {};
  Object.defineProperties(hostileAccessor, {
    code: {
      get() {
        accessorReads += 1;
        throw new Error('private code getter');
      },
    },
    retryable: {
      get() {
        accessorReads += 1;
        return true;
      },
    },
  });
  const hostileProxy = new Proxy({}, {
    getOwnPropertyDescriptor() {
      throw new TypeError('private descriptor trap');
    },
  });
  const rows = [
    [{ code: 'IDEMPOTENCY_CONFLICT', retryable: true, message: 'private' },
      { code: 'IDEMPOTENCY_CONFLICT', retryable: false }],
    [{ code: 'MIC_PERMISSION_DENIED', retryable: true, cause: { private: true } },
      { code: 'MIC_PERMISSION_DENIED', retryable: false }],
    [hostileAccessor, { code: 'NETWORK_ERROR', retryable: false }],
    [hostileProxy, { code: 'NETWORK_ERROR', retryable: false }],
  ];

  for (const [failure, expected] of rows) {
    const fixture = createFixture();
    fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
    fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
    fixture.deps.api.chat = () => Promise.reject(failure);
    const app = createChildApp(fixture.deps);
    await app.initialize();
    await app.start();
    await app.selectChild(7);
    app.recordToggle();
    explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '我给小鸭换了水' });
    await flushMicrotasks();

    assert.equal(app.getSnapshot().value, 'recovery');
    assert.deepEqual(app.getSnapshot().error, expected);
    assert.equal(Object.hasOwn(app.getSnapshot().error, 'message'), false);
    assert.equal(Object.hasOwn(app.getSnapshot().error, 'cause'), false);
  }
  assert.equal(accessorReads, 0);
});

test('a replayed acknowledgement dedupes existing message IDs without a new UUID', async () => {
  const fixture = createFixture();
  let draftCalls = 0;
  const originalCreateDraft = fixture.deps.createDraft;
  fixture.deps.createDraft = (...args) => {
    draftCalls += 1;
    return originalCreateDraft(...args);
  };
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  fixture.deps.api.chat = () => Promise.resolve(chatResult({ replayed: draftCalls > 1 }));
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);

  for (let attempt = 0; attempt < 2; attempt += 1) {
    app.recordToggle();
    explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '我给小鸭换了水' });
    await flushMicrotasks();
    assert.equal(app.getSnapshot().value, 'ready');
  }

  assert.equal(draftCalls, 2);
  assert.deepEqual(app.getSnapshot().messages, [
    { id: 41, role: 'child', text: '我给小鸭换了水' },
    { id: 42, role: 'diary', text: '真棒！' },
  ]);
});

test('a replay conflicting with acknowledged history becomes CHAT_RESPONSE_CONFLICT without reply TTS', async () => {
  const fixture = createFixture();
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  fixture.deps.api.chat = () => Promise.resolve(chatResult({ replayed: true }));
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);

  app.recordToggle();
  explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '我给小鸭换了水' });
  await flushMicrotasks();
  const replyTTSBeforeConflict = fixture.calls.tts.filter(([kind, text]) => kind === 'speak' && text === '真棒！').length;

  app.recordToggle();
  explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '这次内容不同' });
  await flushMicrotasks();

  assert.equal(app.getSnapshot().value, 'recovery');
  assert.deepEqual(app.getSnapshot().error, {
    code: 'CHAT_RESPONSE_CONFLICT',
    retryable: false,
  });
  assert.equal(fixture.calls.tts.filter(([kind, text]) => kind === 'speak' && text === '真棒！').length,
    replyTTSBeforeConflict);
});

test('an ended reply persists saving_conversation before one exact completion request and accepts its boundary', async () => {
  const fixture = createFixture();
  const completion = deferred();
  const order = [];
  const save = fixture.deps.store.save;
  fixture.deps.store.save = snapshot => {
    order.push(`save:${snapshot.value}`);
    return save(snapshot);
  };
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  fixture.deps.api.chat = (input, signal) => {
    fixture.calls.api.push(['chat', input, signal]);
    return Promise.resolve(chatResult({ ended: true, end_reason: 'complete' }));
  };
  fixture.deps.api.complete = (conversationId, lastMessageId, signal) => {
    fixture.calls.api.push(['complete', conversationId, lastMessageId, signal]);
    order.push('complete');
    return completion.promise;
  };
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);

  app.recordToggle();
  explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '我给小鸭换了水' });
  await flushMicrotasks();

  assert.equal(app.getSnapshot().value, 'saving_conversation');
  const completionCalls = fixture.calls.api.filter(call => Array.isArray(call) && call[0] === 'complete');
  assert.equal(completionCalls.length, 1);
  assert.deepEqual(completionCalls[0].slice(0, 3), ['complete', 9, 42]);
  assert.equal(typeof completionCalls[0][3], 'object');
  assert.equal(order.indexOf('save:saving_conversation') < order.indexOf('complete'), true);

  completion.resolve(completeResult());
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'completed');
  assert.equal(fixture.calls.store.at(-1)[1].value, 'completed');
});

test('a completed-save failure remains the no-write LOCAL_STORAGE_FAILED recovery and does not relabel the response', async () => {
  const fixture = createFixture();
  const completion = deferred();
  const save = fixture.deps.store.save;
  fixture.deps.store.save = snapshot => {
    if (snapshot.value === 'completed') throw new Error('private completed write failure');
    return save(snapshot);
  };
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  fixture.deps.api.chat = (input, signal) => {
    fixture.calls.api.push(['chat', input, signal]);
    return Promise.resolve(chatResult({ ended: true, end_reason: 'complete' }));
  };
  fixture.deps.api.complete = () => completion.promise;
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  app.recordToggle();
  explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '我给小鸭换了水' });
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'saving_conversation');

  completion.resolve(completeResult());
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'recovery');
  assert.deepEqual(app.getSnapshot().error, {
    code: 'LOCAL_STORAGE_FAILED',
    retryable: false,
  });
  assert.equal(fixture.calls.store.filter(call => Array.isArray(call) && call[0] === 'save'
    && call[1].value === 'completed').length, 0);
});

test('an invalid completion response enters COMPLETE_RESPONSE_INVALID while preserving the completion boundary', async () => {
  const fixture = createFixture();
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  fixture.deps.api.chat = () => Promise.resolve(chatResult({ ended: true, end_reason: 'complete' }));
  fixture.deps.api.complete = () => Promise.resolve(completeResult({ message_count: 3 }));
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  app.recordToggle();
  explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '我给小鸭换了水' });
  await flushMicrotasks();
  await flushMicrotasks();

  assert.equal(app.getSnapshot().value, 'recovery');
  assert.deepEqual(app.getSnapshot().error, {
    code: 'COMPLETE_RESPONSE_INVALID',
    retryable: false,
  });
  assert.equal(app.getSnapshot().conversationId, 9);
  assert.equal(app.getSnapshot().lastMessageId, 42);
  assert.equal(app.getSnapshot().messages.length, 2);
  assert.equal(app.getSnapshot().shouldComplete, true);
});

test('an ordinary completion failure preserves IDs and messages with only a sanitized recovery error', async () => {
  const fixture = createFixture();
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  fixture.deps.api.chat = () => Promise.resolve(chatResult({ ended: true, end_reason: 'complete' }));
  fixture.deps.api.complete = () => Promise.reject({
    code: 'UPSTREAM_TIMEOUT',
    retryable: true,
    message: 'private completion failure',
    cause: { private: true },
  });
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  app.recordToggle();
  explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '我给小鸭换了水' });
  await flushMicrotasks();
  await flushMicrotasks();

  assert.equal(app.getSnapshot().value, 'recovery');
  assert.deepEqual(app.getSnapshot().error, {
    code: 'UPSTREAM_TIMEOUT',
    retryable: true,
  });
  assert.equal(app.getSnapshot().conversationId, 9);
  assert.equal(app.getSnapshot().lastMessageId, 42);
  assert.deepEqual(app.getSnapshot().messages, [
    { id: 41, role: 'child', text: '我给小鸭换了水' },
    { id: 42, role: 'diary', text: '真棒！' },
  ]);
  assert.equal(app.getSnapshot().shouldComplete, true);
});

test('CONVERSATION_CHANGED rereads the durable completion boundary through a fresh child recovery read', async () => {
  const fixture = createFixture();
  const completion = deferred();
  const rereadActive = deferred();
  let loadCount = 0;
  let activeCount = 0;
  let completionCount = 0;
  fixture.deps.store.load = () => {
    fixture.calls.store.push('load');
    loadCount += 1;
    return loadCount === 1 ? null : pendingCompletionRecord();
  };
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = childId => {
    fixture.calls.api.push(['active', childId]);
    activeCount += 1;
    return activeCount === 1
      ? Promise.resolve({ conversation: null })
      : rereadActive.promise;
  };
  fixture.deps.api.chat = (input, signal) => {
    fixture.calls.api.push(['chat', input, signal]);
    return Promise.resolve(chatResult({ ended: true, end_reason: 'complete' }));
  };
  fixture.deps.api.complete = (conversationId, lastMessageId, signal) => {
    fixture.calls.api.push(['complete', conversationId, lastMessageId, signal]);
    completionCount += 1;
    return completionCount === 1 ? completion.promise : Promise.resolve(completeResult());
  };
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  app.recordToggle();
  explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '我给小鸭换了水' });
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'saving_conversation');

  completion.reject({ code: 'CONVERSATION_CHANGED', retryable: true, message: 'private' });
  await flushMicrotasks();

  assert.equal(app.getSnapshot().value, 'recovery');
  assert.deepEqual(fixture.calls.store.filter(call => call === 'load'), ['load', 'load']);
  assert.deepEqual(fixture.calls.api.filter(call => Array.isArray(call) && call[0] === 'active'), [
    ['active', 7],
    ['active', 7],
  ]);
  assert.equal(fixture.calls.api.filter(call => Array.isArray(call) && call[0] === 'chat').length, 1);
  assert.equal(fixture.calls.store.filter(call => Array.isArray(call) && call[0] === 'save').at(-1)[1].value, 'saving_conversation');

  rereadActive.resolve({ conversation: activeConversation() });
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'completed');
});

test('a late changed-conversation recovery load after destruction cannot launch its active read', async () => {
  const fixture = createFixture();
  const completion = deferred();
  const recoveredLoad = deferred();
  let loadCount = 0;
  fixture.deps.store.load = () => {
    fixture.calls.store.push('load');
    loadCount += 1;
    return loadCount === 1 ? null : recoveredLoad.promise;
  };
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = childId => {
    fixture.calls.api.push(['active', childId]);
    return Promise.resolve({ conversation: null });
  };
  fixture.deps.api.chat = () => Promise.resolve(chatResult({ ended: true, end_reason: 'complete' }));
  fixture.deps.api.complete = () => completion.promise;
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  app.recordToggle();
  explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '我给小鸭换了水' });
  await flushMicrotasks();
  completion.reject({ code: 'CONVERSATION_CHANGED', retryable: true });
  await flushMicrotasks();
  assert.deepEqual(fixture.calls.store.filter(call => call === 'load'), ['load', 'load']);
  const activeCallsBeforeDestroy = fixture.calls.api.filter(call => Array.isArray(call) && call[0] === 'active').length;

  app.destroy();
  recoveredLoad.resolve(pendingCompletionRecord());
  await flushMicrotasks();
  assert.equal(fixture.calls.api.filter(call => Array.isArray(call) && call[0] === 'active').length, activeCallsBeforeDestroy);
  assert.equal(app.getSnapshot().value, 'recovery');
});

test('reset from recovery clears before the nonpersisting welcome transition', async () => {
  const fixture = createFixture();
  const order = [];
  const clear = fixture.deps.store.clear;
  const render = fixture.deps.view.render;
  fixture.deps.store.clear = () => {
    order.push('clear');
    return clear();
  };
  fixture.deps.view.render = snapshot => {
    order.push(`render:${snapshot.value}`);
    return render(snapshot);
  };
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  app.recordToggle();
  fixture.emitSpeech({ type: 'error', error: { code: 'SPEECH_FAILED', retryable: true } });
  assert.equal(app.getSnapshot().value, 'recovery');

  assert.equal(app.reset(), undefined);
  assert.equal(app.getSnapshot().value, 'welcome');
  assert.equal(order.indexOf('clear') < order.lastIndexOf('render:welcome'), true);
  assert.equal(fixture.calls.store.at(-1), 'clear');
  assert.equal(fixture.calls.store.filter(call => Array.isArray(call) && call[0] === 'save').at(-1)[1].value, 'recovery');
});

test('a valid noninteractive global Space prevents once and delegates one record start', async () => {
  const fixture = createFixture();
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  let preventCalls = 0;
  const event = {
    code: 'Space',
    repeat: false,
    defaultPrevented: false,
    target: {},
    preventDefault() { preventCalls += 1; },
  };

  assert.equal(app.handleGlobalKeydown(event), true);
  assert.equal(preventCalls, 1);
  assert.equal(app.getSnapshot().value, 'listening');
  assert.equal(fixture.calls.speechStart, 1);
});

test('the next accepted global Space requests one manual stop and rejected Space variants do nothing', async () => {
  const fixture = createFixture();
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  const accepted = () => ({
    code: 'Space', repeat: false, defaultPrevented: false, target: {}, prevented: 0,
    preventDefault() { this.prevented += 1; },
  });

  const first = accepted();
  assert.equal(app.handleGlobalKeydown(first), true);
  const second = accepted();
  assert.equal(app.handleGlobalKeydown(second), true);
  assert.equal(second.prevented, 1);
  assert.equal(fixture.calls.speechStop, 1);
  assert.equal(app.getSnapshot().stopRequested, true);

  for (const event of [
    { code: 'Enter', repeat: false, defaultPrevented: false, target: {}, preventDefault() { throw new Error('must not call'); } },
    { code: 'Space', repeat: true, defaultPrevented: false, target: {}, preventDefault() { throw new Error('must not call'); } },
    { code: 'Space', repeat: false, defaultPrevented: true, target: {}, preventDefault() { throw new Error('must not call'); } },
  ]) {
    assert.equal(app.handleGlobalKeydown(event), false);
  }
  assert.equal(fixture.calls.speechStop, 1);
});

test('a hostile controls result cannot escape or accept a global Space action', async () => {
  const fixture = createFixture();
  fixture.deps.machine = {
    ...MACHINE_FACADE,
    controlsFor() {
      return Object.defineProperty({}, 'recordDisabled', {
        enumerable: true,
        get() { throw new Error('private controls getter'); },
      });
    },
  };
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  let preventCalls = 0;
  const event = {
    code: 'Space', repeat: false, defaultPrevented: false, target: {},
    preventDefault() { preventCalls += 1; },
  };

  assert.equal(app.handleGlobalKeydown(event), false);
  assert.equal(preventCalls, 0);
  assert.equal(fixture.calls.speechStart, 0);
});

test('destroy cancels an already-registered roster entry before its invocation microtask', async () => {
  const fixture = createFixture();
  fixture.deps.api.getTodayRoster = () => {
    fixture.calls.api.push('roster');
    return Promise.resolve([]);
  };
  const app = createChildApp(fixture.deps);
  await app.initialize();

  const starting = app.start();
  await Promise.resolve();
  assert.equal(fixture.controllers.length, 1);
  assert.equal(app.destroy(), undefined);
  assert.equal(fixture.controllers[0].abortCalls, 1);
  assert.equal(await starting, undefined);
  await flushMicrotasks();

  assert.equal(fixture.calls.api.includes('roster'), false);
  assert.equal(app.getSnapshot().value, 'loading_roster');
});

test('destroy cancels a registered active read before its invocation microtask', async () => {
  const fixture = createFixture();
  let app = null;
  const controllerCount = destroyBeforeControllerWork(fixture, 2, () => app);
  fixture.deps.api.getTodayRoster = () => {
    fixture.calls.api.push('roster');
    return Promise.resolve([childRecord()]);
  };
  fixture.deps.api.getActiveConversation = childId => {
    fixture.calls.api.push(['active', childId]);
    return Promise.resolve({ conversation: null });
  };
  app = createChildApp(fixture.deps);
  await app.initialize();
  assert.equal(await app.start(), undefined);
  await flushMicrotasks();

  assert.equal(controllerCount(), 2);
  assert.equal(fixture.controllers[1].abortCalls, 1);
  assert.deepEqual(fixture.calls.api, ['ready', 'roster']);
  assert.equal(app.getSnapshot().value, 'loading_roster');
});

test('destroy cancels a registered greeting TTS before speak invocation', async () => {
  const fixture = createFixture();
  let app = null;
  const controllerCount = destroyBeforeControllerWork(fixture, 3, () => app);
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  assert.equal(await app.selectChild(7), undefined);
  await flushMicrotasks();

  assert.equal(controllerCount(), 3);
  assert.equal(fixture.controllers[2].abortCalls, 1);
  assert.equal(fixture.calls.tts.some(([kind]) => kind === 'speak'), false);
  assert.equal(app.getSnapshot().value, 'opening');
});

test('destroy cancels a registered chat before API invocation', async () => {
  const fixture = createFixture();
  let app = null;
  const controllerCount = destroyBeforeControllerWork(fixture, 5, () => app);
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  app.recordToggle();
  explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '我给小鸭换了水' });
  await flushMicrotasks();

  assert.equal(controllerCount(), 5);
  assert.equal(fixture.controllers[4].abortCalls, 1);
  assert.equal(fixture.calls.api.some(call => Array.isArray(call) && call[0] === 'chat'), false);
  assert.equal(app.getSnapshot().value, 'submitting');
});

test('destroy cancels a registered reply TTS before speak invocation', async () => {
  const fixture = createFixture();
  let app = null;
  const controllerCount = destroyBeforeControllerWork(fixture, 6, () => app);
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  fixture.deps.api.chat = (input, signal) => {
    fixture.calls.api.push(['chat', input, signal]);
    return Promise.resolve(chatResult());
  };
  app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  app.recordToggle();
  explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '我给小鸭换了水' });
  await flushMicrotasks();

  assert.equal(controllerCount(), 6);
  assert.equal(fixture.controllers[5].abortCalls, 1);
  assert.equal(fixture.calls.api.filter(call => Array.isArray(call) && call[0] === 'chat').length, 1);
  assert.equal(fixture.calls.tts.filter(([kind, text]) => kind === 'speak' && text === '真棒！').length, 0);
  assert.equal(app.getSnapshot().value, 'speaking');
});

test('destroy cancels registered completion before API invocation', async () => {
  const fixture = createFixture();
  let app = null;
  const controllerCount = destroyBeforeControllerWork(fixture, 7, () => app);
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  fixture.deps.api.chat = () => Promise.resolve(chatResult({ ended: true, end_reason: 'complete' }));
  app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  app.recordToggle();
  explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '我给小鸭换了水' });
  await flushMicrotasks();
  await flushMicrotasks();

  assert.equal(controllerCount(), 7);
  assert.equal(fixture.controllers[6].abortCalls, 1);
  assert.equal(fixture.calls.api.some(call => Array.isArray(call) && call[0] === 'complete'), false);
  assert.equal(app.getSnapshot().value, 'saving_conversation');
});

test('destroy cancels registered changed-conversation recovery before its reload invocation', async () => {
  const fixture = createFixture();
  let app = null;
  const controllerCount = destroyBeforeControllerWork(fixture, 8, () => app);
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  fixture.deps.api.chat = (input, signal) => {
    fixture.calls.api.push(['chat', input, signal]);
    return Promise.resolve(chatResult({ ended: true, end_reason: 'complete' }));
  };
  fixture.deps.api.complete = (conversationId, lastMessageId, signal) => {
    fixture.calls.api.push(['complete', conversationId, lastMessageId, signal]);
    return Promise.reject({ code: 'CONVERSATION_CHANGED', retryable: true });
  };
  app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  app.recordToggle();
  explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '我给小鸭换了水' });
  await flushMicrotasks();
  await flushMicrotasks();

  assert.equal(controllerCount(), 8);
  assert.equal(fixture.controllers[7].abortCalls, 1);
  assert.equal(fixture.calls.store.filter(call => call === 'load').length, 1);
  assert.equal(app.getSnapshot().value, 'recovery');
});

test('a late roster fulfillment after destruction is inert', async () => {
  const fixture = createFixture();
  const roster = deferred();
  fixture.deps.api.getTodayRoster = () => {
    fixture.calls.api.push('roster');
    return roster.promise;
  };
  const app = createChildApp(fixture.deps);
  await app.initialize();
  const starting = app.start();
  await flushMicrotasks();
  assert.deepEqual(fixture.calls.api, ['ready', 'roster']);
  const writesBeforeDestroy = fixture.calls.store.length;

  app.destroy();
  roster.resolve([]);
  assert.equal(await starting, undefined);
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'loading_roster');
  assert.equal(fixture.calls.store.length, writesBeforeDestroy);
});

test('a late active-conversation fulfillment after destruction is inert', async () => {
  const fixture = createFixture();
  const active = deferred();
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = childId => {
    fixture.calls.api.push(['active', childId]);
    return active.promise;
  };
  const app = createChildApp(fixture.deps);
  await app.initialize();
  const starting = app.start();
  await flushMicrotasks();
  assert.deepEqual(fixture.calls.api, ['ready', ['active', 7]]);
  const writesBeforeDestroy = fixture.calls.store.length;

  app.destroy();
  active.resolve({ conversation: null });
  assert.equal(await starting, undefined);
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'loading_roster');
  assert.equal(fixture.calls.store.length, writesBeforeDestroy);
});

test('a late chat fulfillment after destruction is inert and cannot launch reply TTS', async () => {
  const fixture = createFixture();
  const chat = deferred();
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  fixture.deps.api.chat = (input, signal) => {
    fixture.calls.api.push(['chat', input, signal]);
    return chat.promise;
  };
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  app.recordToggle();
  explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '我给小鸭换了水' });
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'submitting');
  const savesAtDestroy = fixture.calls.store.length;

  app.destroy();
  chat.resolve(chatResult());
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'submitting');
  assert.equal(fixture.calls.store.length, savesAtDestroy);
  assert.equal(fixture.calls.tts.filter(([kind, text]) => kind === 'speak' && text === '真棒！').length, 0);
});

test('a late greeting TTS settlement after destruction is inert', async () => {
  const fixture = createFixture();
  const greeting = deferred();
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  fixture.deps.tts.speak = text => {
    fixture.calls.tts.push(['speak', text]);
    return greeting.promise;
  };
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  const selecting = app.selectChild(7);
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'opening');
  const savesAtDestroy = fixture.calls.store.length;

  app.destroy();
  greeting.resolve({ mode: 'text' });
  assert.equal(await selecting, undefined);
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'opening');
  assert.equal(fixture.calls.store.length, savesAtDestroy);
});

test('a late completion fulfillment after destruction is inert', async () => {
  const fixture = createFixture();
  const completion = deferred();
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  fixture.deps.api.chat = () => Promise.resolve(chatResult({ ended: true, end_reason: 'complete' }));
  fixture.deps.api.complete = () => completion.promise;
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  app.recordToggle();
  explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '我给小鸭换了水' });
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'saving_conversation');
  const savesAtDestroy = fixture.calls.store.length;

  app.destroy();
  completion.resolve(completeResult());
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'saving_conversation');
  assert.equal(fixture.calls.store.length, savesAtDestroy);
});

test('a late speech final after destruction is inert', async () => {
  const fixture = createFixture();
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  app.recordToggle();
  assert.equal(app.getSnapshot().value, 'listening');
  const savesAtDestroy = fixture.calls.store.length;

  app.destroy();
  fixture.emitSpeech({ type: 'final', text: 'late and inert' });
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'listening');
  assert.equal(fixture.calls.store.length, savesAtDestroy);
  assert.equal(fixture.calls.api.some(call => Array.isArray(call) && call[0] === 'chat'), false);
});

test('a recovery loading-roster outcome paired with keep never resolves or persists the loading copy', async () => {
  const fixture = createFixture();
  fixture.deps.store.load = () => {
    fixture.calls.store.push('load');
    return localReadyRecord();
  };
  fixture.deps.api.getActiveConversation = childId => {
    fixture.calls.api.push(['active', childId]);
    return Promise.resolve({ conversation: null });
  };
  fixture.deps.mergeRecovery = () => Object.freeze({
    snapshot: createInitialSnapshot({ value: 'loading_roster' }),
    storageAction: 'keep',
  });
  const app = createChildApp(fixture.deps);

  await app.initialize();
  assert.equal(app.getSnapshot().value, 'recovery');
  assert.deepEqual(app.getSnapshot().error, {
    code: 'RECOVERY_RESULT_INVALID',
    retryable: false,
  });
  assert.deepEqual(fixture.calls.store, ['load']);
  assert.equal(fixture.calls.view.filter(([kind, snapshot]) => kind === 'render' && snapshot.value === 'loading_roster').length, 1);
});

test('a clear recovery outcome clears before resolving then performs one fresh no-local roster continuation', async () => {
  const fixture = createFixture();
  const order = [];
  const clear = fixture.deps.store.clear;
  const save = fixture.deps.store.save;
  fixture.deps.store.load = () => {
    fixture.calls.store.push('load');
    return localReadyRecord();
  };
  fixture.deps.store.clear = () => {
    order.push('clear');
    return clear();
  };
  fixture.deps.store.save = snapshot => {
    order.push(`save:${snapshot.value}`);
    return save(snapshot);
  };
  fixture.deps.api.getActiveConversation = childId => {
    fixture.calls.api.push(['active', childId]);
    return Promise.resolve({ conversation: null });
  };
  fixture.deps.api.getTodayRoster = () => {
    fixture.calls.api.push('roster');
    return Promise.resolve([]);
  };
  const app = createChildApp(fixture.deps);

  await app.initialize();
  assert.equal(app.getSnapshot().value, 'selecting_child');
  assert.deepEqual(fixture.calls.api, ['ready', ['active', 7], 'roster']);
  assert.equal(order.indexOf('clear') < order.indexOf('save:loading_roster'), true);
  assert.equal(order.filter(item => item === 'clear').length, 1);
});

test('a roster controller construction failure enters sanitized recovery before any roster invocation', async () => {
  const fixture = createFixture();
  fixture.deps.AbortController = class BrokenAbortController {
    constructor() { throw new Error('private controller failure'); }
  };
  fixture.deps.api.getTodayRoster = () => {
    fixture.calls.api.push('roster');
    return Promise.resolve([]);
  };
  const app = createChildApp(fixture.deps);
  await app.initialize();

  assert.equal(await app.start(), undefined);
  assert.equal(app.getSnapshot().value, 'recovery');
  assert.deepEqual(app.getSnapshot().error, {
    code: 'EFFECT_CONTROLLER_FAILED',
    retryable: false,
  });
  assert.equal(fixture.calls.api.includes('roster'), false);
});

test('hostile controller signal and abort properties fail closed before effect invocation', async () => {
  const rows = [
    class ThrowingSignalController {
      get signal() { throw new TypeError('private signal getter'); }
      abort() {}
    },
    class ThrowingAbortController {
      constructor() { this.signal = {}; }
      get abort() { throw new Error('private abort getter'); }
    },
    class NonCallableAbortController {
      constructor() {
        this.signal = {};
        this.abort = null;
      }
    },
  ];

  for (const AbortController of rows) {
    const fixture = createFixture();
    fixture.deps.AbortController = AbortController;
    fixture.deps.api.getTodayRoster = () => {
      fixture.calls.api.push('roster');
      return Promise.resolve([]);
    };
    const app = createChildApp(fixture.deps);
    await app.initialize();
    assert.equal(await app.start(), undefined);
    assert.equal(app.getSnapshot().value, 'recovery');
    assert.deepEqual(app.getSnapshot().error, {
      code: 'EFFECT_CONTROLLER_FAILED',
      retryable: false,
    });
    assert.equal(fixture.calls.api.includes('roster'), false);
  }
});

test('a hostile abort thenable is consumed once without an unhandled rejection', async () => {
  const fixture = createFixture();
  const roster = deferred();
  let abortCalls = 0;
  fixture.deps.AbortController = class HostileAbortController {
    constructor() { this.signal = {}; }
    abort() {
      abortCalls += 1;
      return Object.defineProperty({}, 'then', {
        get() { throw new Error('private abort then getter'); },
      });
    }
  };
  fixture.deps.api.getTodayRoster = () => {
    fixture.calls.api.push('roster');
    return roster.promise;
  };
  const app = createChildApp(fixture.deps);
  await app.initialize();
  const starting = app.start();
  await flushMicrotasks();
  assert.deepEqual(fixture.calls.api, ['ready', 'roster']);

  assert.doesNotThrow(() => app.destroy());
  assert.equal(abortCalls, 1);
  roster.resolve([]);
  assert.equal(await starting, undefined);
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'loading_roster');
});

test('destroy during a deferred initialize gate leaves its later continuation fully inert', async () => {
  const fixture = createFixture();
  const ready = deferred();
  fixture.deps.api.ready = () => {
    fixture.calls.api.push('ready');
    return ready.promise;
  };
  const app = createChildApp(fixture.deps);
  const initialized = app.initialize();
  await Promise.resolve();
  assert.deepEqual(fixture.calls.api, ['ready']);
  app.destroy();

  ready.resolve();
  assert.equal(await initialized, undefined);
  await flushMicrotasks();
  assert.deepEqual(fixture.calls.store, []);
  assert.equal(fixture.calls.view.filter(([kind]) => kind === 'render').length, 1);
  assert.equal(app.getSnapshot().value, 'welcome');
});

test('a reentrant store.load callback cannot start a roster while initialization is still in its call boundary', async () => {
  const fixture = createFixture();
  let app = null;
  fixture.deps.store.load = () => {
    fixture.calls.store.push('load');
    app.start();
    return null;
  };
  fixture.deps.api.getTodayRoster = () => {
    fixture.calls.api.push('roster');
    return Promise.resolve([]);
  };
  app = createChildApp(fixture.deps);

  await app.initialize();
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'welcome');
  assert.equal(fixture.calls.api.includes('roster'), false);
});

test('a reentrant destroy during an external callback is deferred as a no-op until the boundary releases', async () => {
  const fixture = createFixture();
  let app = null;
  fixture.deps.store.load = () => {
    fixture.calls.store.push('load');
    app.destroy();
    return null;
  };
  app = createChildApp(fixture.deps);

  await app.initialize();
  assert.equal(app.getSnapshot().value, 'welcome');
  assert.equal(fixture.calls.speechDispose, 0);
  assert.equal(fixture.calls.tts.some(([kind]) => kind === 'dispose'), false);
  assert.equal(await app.start(), undefined);
  assert.equal(fixture.calls.api.includes('roster'), true);
});

test('a save-failure cancellation keeps an abort callback from reentering a new speech run', async () => {
  const fixture = createFixture();
  const greeting = deferred();
  let app = null;
  let failReadyOnce = true;
  let abortCalls = 0;
  const save = fixture.deps.store.save;
  fixture.deps.store.save = snapshot => {
    if (snapshot.value === 'ready' && failReadyOnce) {
      failReadyOnce = false;
      throw new Error('private save failure');
    }
    return save(snapshot);
  };
  fixture.deps.AbortController = class ReentrantAbortController {
    constructor() { this.signal = {}; }
    abort() { abortCalls += 1; app?.recordToggle(); }
  };
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  fixture.deps.tts.speak = text => {
    fixture.calls.tts.push(['speak', text]);
    return greeting.promise;
  };
  app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  const selecting = app.selectChild(7);
  await flushMicrotasks();

  greeting.resolve({ mode: 'text' });
  assert.equal(await selecting, undefined);
  assert.equal(app.getSnapshot().value, 'recovery');
  assert.equal(abortCalls, 1);
  assert.equal(fixture.calls.speechStart, 0);
  assert.equal(fixture.calls.store.filter(call => Array.isArray(call) && call[0] === 'save'
    && call[1].value === 'listening').length, 0);
});

test('a render callback cannot reentrantly select a child from the selecting transition', async () => {
  const fixture = createFixture();
  let app = null;
  const render = fixture.deps.view.render;
  fixture.deps.view.render = snapshot => {
    render(snapshot);
    if (snapshot.value === 'selecting_child') app?.selectChild(7);
  };
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  app = createChildApp(fixture.deps);

  await app.initialize();
  await app.start();
  await flushMicrotasks();

  assert.equal(app.getSnapshot().value, 'selecting_child');
  assert.equal(fixture.calls.tts.filter(([kind]) => kind === 'speak').length, 0);
  assert.equal(fixture.calls.store.filter(call => Array.isArray(call) && call[0] === 'save'
    && call[1].value === 'selecting_child').length, 1);
});

test('an ordinary render failure enters no-write VIEW_RENDER_FAILED recovery before roster work', async () => {
  const fixture = createFixture();
  const render = fixture.deps.view.render;
  fixture.deps.view.render = snapshot => {
    if (snapshot.value === 'loading_roster') throw new Error('private render failure');
    render(snapshot);
  };
  fixture.deps.api.getTodayRoster = () => {
    fixture.calls.api.push('roster');
    return Promise.resolve([]);
  };
  const app = createChildApp(fixture.deps);

  await app.initialize();
  await app.start();

  assert.equal(app.getSnapshot().value, 'recovery');
  assert.deepEqual(app.getSnapshot().error, { code: 'VIEW_RENDER_FAILED', retryable: false });
  assert.equal(fixture.calls.api.includes('roster'), false);
  assert.equal(fixture.calls.store.filter(call => Array.isArray(call) && call[0] === 'save').length, 0);
});

test('a RESET welcome render failure restores the prior recovery snapshot before no-write recovery', async () => {
  const fixture = createFixture();
  let failWelcome = false;
  const render = fixture.deps.view.render;
  fixture.deps.view.render = snapshot => {
    if (failWelcome && snapshot.value === 'welcome') throw new Error('private reset render failure');
    render(snapshot);
  };
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  app.recordToggle();
  fixture.emitSpeech({ type: 'error', error: { code: 'SPEECH_FAILED', retryable: true } });
  assert.equal(app.getSnapshot().value, 'recovery');
  const savesBeforeReset = fixture.calls.store.filter(call => Array.isArray(call) && call[0] === 'save').length;
  failWelcome = true;

  assert.equal(app.reset(), undefined);

  assert.equal(app.getSnapshot().value, 'recovery');
  assert.deepEqual(app.getSnapshot().error, { code: 'VIEW_RENDER_FAILED', retryable: false });
  assert.equal(fixture.calls.store.filter(call => call === 'clear').length, 1);
  assert.equal(fixture.calls.store.filter(call => Array.isArray(call) && call[0] === 'save').length, savesBeforeReset);
});

test('failure to save TTS_SETTLED into saving_conversation invokes complete zero times', async () => {
  const fixture = createFixture();
  const reply = deferred();
  const save = fixture.deps.store.save;
  fixture.deps.store.save = snapshot => {
    if (snapshot.value === 'saving_conversation') throw new Error('private saving transition failure');
    return save(snapshot);
  };
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  fixture.deps.api.chat = () => Promise.resolve(chatResult({ ended: true, end_reason: 'complete' }));
  fixture.deps.tts.speak = text => {
    fixture.calls.tts.push(['speak', text]);
    return text === '真棒！' ? reply.promise : Promise.resolve({ mode: 'text' });
  };
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  app.recordToggle();
  explicitlyStopAndEmitSpeech(app, fixture, { type: 'final', text: '我给小鸭换了水' });
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'speaking');

  reply.resolve({ mode: 'audio' });
  await flushMicrotasks();

  assert.equal(app.getSnapshot().value, 'recovery');
  assert.deepEqual(app.getSnapshot().error, { code: 'LOCAL_STORAGE_FAILED', retryable: false });
  assert.equal(fixture.calls.api.some(call => Array.isArray(call) && call[0] === 'complete'), false);
});

test('a pending completion reload starts exactly one replay-safe complete and no chat or TTS', async () => {
  const fixture = createFixture();
  fixture.deps.store.load = () => {
    fixture.calls.store.push('load');
    return pendingCompletionRecord();
  };
  fixture.deps.api.getActiveConversation = childId => {
    fixture.calls.api.push(['active', childId]);
    return Promise.resolve({ conversation: activeConversation() });
  };
  fixture.deps.api.complete = (conversationId, lastMessageId, signal) => {
    fixture.calls.api.push(['complete', conversationId, lastMessageId, signal]);
    return Promise.resolve(completeResult({ replayed: true }));
  };
  const app = createChildApp(fixture.deps);

  await app.initialize();
  await flushMicrotasks();

  const completions = fixture.calls.api.filter(call => Array.isArray(call) && call[0] === 'complete');
  assert.equal(completions.length, 1);
  assert.equal(completions[0][1], 9);
  assert.equal(completions[0][2], 42);
  assert.equal(fixture.calls.api.some(call => Array.isArray(call) && call[0] === 'chat'), false);
  assert.equal(fixture.calls.tts.filter(([kind]) => kind === 'speak').length, 0);
  assert.equal(app.getSnapshot().value, 'completed');
});

test('an active-controller failure merges a valid local draft without an empty bridge write', async () => {
  const fixture = createFixture();
  const local = localDraftRecord();
  const before = JSON.stringify(local);
  let remoteRead = null;
  fixture.deps.store.load = () => {
    fixture.calls.store.push('load');
    return local;
  };
  fixture.deps.mergeRecovery = (localRecord, remote) => {
    remoteRead = remote;
    return mergeRecovery(localRecord, remote);
  };
  fixture.deps.AbortController = class BrokenAbortController {
    constructor() { throw new Error('private active controller failure'); }
  };
  fixture.deps.api.getActiveConversation = () => {
    fixture.calls.api.push(['active', 7]);
    return Promise.resolve({ conversation: null });
  };
  const app = createChildApp(fixture.deps);

  await app.initialize();

  assert.equal(JSON.stringify(local), before);
  assert.equal(fixture.calls.api.some(call => Array.isArray(call) && call[0] === 'active'), false);
  assert.deepEqual(remoteRead, {
    kind: 'failure',
    queriedChild: childRecord(),
    error: { code: 'EFFECT_CONTROLLER_FAILED', retryable: false },
  });
  const saves = fixture.calls.store.filter(call => Array.isArray(call) && call[0] === 'save');
  assert.equal(saves.length, 1);
  assert.equal(saves[0][1].draft.request_id, local.draft.request_id);
  assert.equal(app.getSnapshot().draft.request_id, local.draft.request_id);
});

test('a roster-controller failure merges valid childless local data without clearing or empty overwrite', async () => {
  const fixture = createFixture();
  const local = { ...localReadyRecord(), child: null };
  const before = JSON.stringify(local);
  let remoteRead = null;
  fixture.deps.store.load = () => {
    fixture.calls.store.push('load');
    return local;
  };
  fixture.deps.mergeRecovery = (localRecord, remote) => {
    remoteRead = remote;
    return mergeRecovery(localRecord, remote);
  };
  fixture.deps.AbortController = class BrokenAbortController {
    constructor() { throw new Error('private roster controller failure'); }
  };
  fixture.deps.api.getTodayRoster = () => {
    fixture.calls.api.push('roster');
    return Promise.resolve([]);
  };
  const app = createChildApp(fixture.deps);

  await app.initialize();

  assert.equal(JSON.stringify(local), before);
  assert.equal(fixture.calls.api.includes('roster'), false);
  assert.deepEqual(remoteRead, {
    kind: 'failure',
    queriedChild: null,
    error: { code: 'EFFECT_CONTROLLER_FAILED', retryable: false },
  });
  assert.equal(fixture.calls.store.filter(call => call === 'clear').length, 0);
  const saves = fixture.calls.store.filter(call => Array.isArray(call) && call[0] === 'save');
  assert.equal(saves.length, 1);
  assert.equal(saves[0][1].value, 'recovery');
  assert.equal(app.getSnapshot().value, 'recovery');
});

test('save and announce callbacks cannot reentrantly toggle recording', async () => {
  const fixture = createFixture();
  let app = null;
  const save = fixture.deps.store.save;
  fixture.deps.store.save = snapshot => {
    app?.recordToggle();
    return save(snapshot);
  };
  fixture.deps.view.announce = text => {
    fixture.calls.view.push(['announce', text]);
    app?.recordToggle();
  };
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);

  assert.equal(fixture.calls.speechStart, 0);
  app.recordToggle();
  assert.equal(fixture.calls.speechStart, 1);
  fixture.emitSpeech({ type: 'partial', text: '我正在说' });

  assert.equal(app.getSnapshot().value, 'listening');
  assert.equal(app.getSnapshot().stopRequested, false);
  assert.equal(fixture.calls.speechStop, 0);
  assert.deepEqual(fixture.calls.view.at(-1), ['announce', '我正在说']);
});

test('a reset clear callback cannot recurse into reset or start another roster effect', async () => {
  const fixture = createFixture();
  let app = null;
  const clear = fixture.deps.store.clear;
  fixture.deps.store.clear = () => {
    app?.reset();
    app?.start();
    return clear();
  };
  fixture.deps.api.getTodayRoster = () => {
    fixture.calls.api.push('roster');
    return Promise.resolve([childRecord()]);
  };
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  app.recordToggle();
  fixture.emitSpeech({ type: 'error', error: { code: 'SPEECH_FAILED', retryable: true } });
  const rosterCalls = fixture.calls.api.filter(call => call === 'roster').length;

  app.reset();
  await flushMicrotasks();

  assert.equal(fixture.calls.store.filter(call => call === 'clear').length, 1);
  assert.equal(fixture.calls.api.filter(call => call === 'roster').length, rosterCalls);
  assert.equal(app.getSnapshot().value, 'welcome');
});

test('a recovery clear callback cannot recurse before its fresh roster continuation', async () => {
  const fixture = createFixture();
  let app = null;
  const clear = fixture.deps.store.clear;
  fixture.deps.store.load = () => {
    fixture.calls.store.push('load');
    return localReadyRecord();
  };
  fixture.deps.store.clear = () => {
    app?.reset();
    app?.start();
    return clear();
  };
  fixture.deps.api.getActiveConversation = childId => {
    fixture.calls.api.push(['active', childId]);
    return Promise.resolve({ conversation: null });
  };
  fixture.deps.api.getTodayRoster = () => {
    fixture.calls.api.push('roster');
    return Promise.resolve([]);
  };
  app = createChildApp(fixture.deps);

  await app.initialize();

  assert.equal(fixture.calls.store.filter(call => call === 'clear').length, 1);
  assert.equal(fixture.calls.api.filter(call => call === 'roster').length, 1);
  assert.deepEqual(fixture.calls.api, ['ready', ['active', 7], 'roster']);
  assert.equal(app.getSnapshot().value, 'selecting_child');
});

test('speech start and manual stop callbacks cannot reentrantly toggle the current generation', async () => {
  const fixture = createFixture();
  let app = null;
  fixture.speech.start = () => {
    fixture.calls.speechStart += 1;
    app?.recordToggle();
  };
  fixture.speech.stop = () => {
    fixture.calls.speechStop += 1;
    app?.recordToggle();
  };
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);

  app.recordToggle();
  assert.equal(app.getSnapshot().value, 'listening');
  assert.equal(app.getSnapshot().stopRequested, false);
  assert.equal(fixture.calls.speechStart, 1);
  assert.equal(fixture.calls.speechStop, 0);

  app.recordToggle();
  assert.equal(app.getSnapshot().stopRequested, true);
  assert.equal(fixture.calls.speechStop, 1);
});

test('destroy-time speech and view callbacks cannot reenter or launch another effect', async () => {
  const fixture = createFixture();
  let app = null;
  fixture.speech.stop = () => {
    fixture.calls.speechStop += 1;
    app?.recordToggle();
  };
  fixture.speech.dispose = () => {
    fixture.calls.speechDispose += 1;
    app?.start();
  };
  fixture.deps.tts.dispose = () => {
    fixture.calls.tts.push(['dispose']);
    app?.start();
  };
  fixture.deps.view.destroy = () => {
    fixture.calls.view.push(['destroy']);
    app?.start();
  };
  fixture.deps.api.getTodayRoster = () => {
    fixture.calls.api.push('roster');
    return Promise.resolve([childRecord()]);
  };
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  app.recordToggle();
  const rosterCalls = fixture.calls.api.filter(call => call === 'roster').length;

  app.destroy();
  await flushMicrotasks();

  assert.equal(fixture.calls.speechStop, 1);
  assert.equal(fixture.calls.speechDispose, 1);
  assert.equal(fixture.calls.tts.filter(([kind]) => kind === 'dispose').length, 1);
  assert.equal(fixture.calls.view.filter(([kind]) => kind === 'destroy').length, 1);
  assert.equal(fixture.calls.api.filter(call => call === 'roster').length, rosterCalls);
  assert.equal(fixture.calls.api.some(call => Array.isArray(call) && call[0] === 'chat'), false);
});

test('destroy-time TTS cancel and dispose callbacks cannot reenter the pending greeting', async () => {
  const fixture = createFixture();
  const greeting = deferred();
  let app = null;
  fixture.deps.tts.speak = text => {
    fixture.calls.tts.push(['speak', text]);
    return greeting.promise;
  };
  fixture.deps.tts.cancel = reason => {
    fixture.calls.tts.push(['cancel', reason]);
    app?.recordToggle();
  };
  fixture.deps.tts.dispose = () => {
    fixture.calls.tts.push(['dispose']);
    app?.start();
  };
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  const selecting = app.selectChild(7);
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'opening');

  app.destroy();
  greeting.resolve({ mode: 'text' });
  await selecting;
  await flushMicrotasks();

  assert.equal(fixture.calls.tts.filter(([kind]) => kind === 'cancel').length, 1);
  assert.equal(fixture.calls.tts.filter(([kind]) => kind === 'dispose').length, 1);
  assert.equal(fixture.calls.speechStart, 0);
  assert.equal(app.getSnapshot().value, 'opening');
});

test('destroy consumes rejecting cleanup thenables from speech, TTS, and view exactly once', async () => {
  const fixture = createFixture();
  const thenCalls = { speech: 0, tts: 0, view: 0 };
  const rejectingThenable = key => ({
    then(resolve, reject) {
      thenCalls[key] += 1;
      reject(new Error(`private ${key} cleanup rejection`));
    },
  });
  fixture.speech.dispose = () => rejectingThenable('speech');
  fixture.deps.tts.dispose = () => rejectingThenable('tts');
  fixture.deps.view.destroy = () => rejectingThenable('view');
  const app = createChildApp(fixture.deps);
  await app.initialize();

  assert.doesNotThrow(() => app.destroy());
  await flushMicrotasks();

  assert.deepEqual(thenCalls, { speech: 1, tts: 1, view: 1 });
});

test('global Space is inert in welcome, loading, and recovery without preventing default', async () => {
  const fixture = createFixture();
  const roster = deferred();
  fixture.deps.api.getTodayRoster = () => roster.promise;
  const app = createChildApp(fixture.deps);
  const makeSpace = () => ({
    code: 'Space', repeat: false, defaultPrevented: false, target: {}, prevented: 0,
    preventDefault() { this.prevented += 1; },
  });

  const welcomeSpace = makeSpace();
  assert.equal(app.handleGlobalKeydown(welcomeSpace), false);
  assert.equal(welcomeSpace.prevented, 0);

  await app.initialize();
  const starting = app.start();
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'loading_roster');
  const loadingSpace = makeSpace();
  assert.equal(app.handleGlobalKeydown(loadingSpace), false);
  assert.equal(loadingSpace.prevented, 0);

  roster.reject({ code: 'NETWORK_ERROR', retryable: true });
  await starting;
  await flushMicrotasks();
  assert.equal(app.getSnapshot().value, 'recovery');
  const recoverySpace = makeSpace();
  assert.equal(app.handleGlobalKeydown(recoverySpace), false);
  assert.equal(recoverySpace.prevented, 0);
  assert.equal(fixture.calls.speechStart, 0);
});

test('global Space behind an interactive target or active dialog is never accepted', async () => {
  for (const blockedBy of ['interactive', 'dialog']) {
    const fixture = createFixture();
    fixture.deps.keyboard.isInteractiveTarget = () => blockedBy === 'interactive';
    fixture.deps.keyboard.isDialogActive = () => blockedBy === 'dialog';
    fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
    fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
    const app = createChildApp(fixture.deps);
    await app.initialize();
    await app.start();
    await app.selectChild(7);
    const event = {
      code: 'Space', repeat: false, defaultPrevented: false, target: {}, prevented: 0,
      preventDefault() { this.prevented += 1; },
    };

    assert.equal(app.handleGlobalKeydown(event), false, blockedBy);
    assert.equal(event.prevented, 0, blockedBy);
    assert.equal(fixture.calls.speechStart, 0, blockedBy);
  }
});

test('destroy after store.load invocation makes its deferred local continuation fully inert', async () => {
  const fixture = createFixture();
  const loaded = deferred();
  fixture.deps.store.load = () => {
    fixture.calls.store.push('load');
    return loaded.promise;
  };
  const app = createChildApp(fixture.deps);
  const initialized = app.initialize();
  await flushMicrotasks();
  assert.deepEqual(fixture.calls.api, ['ready']);
  assert.deepEqual(fixture.calls.store, ['load']);
  const rendersBeforeDestroy = fixture.calls.view.filter(([kind]) => kind === 'render').length;

  app.destroy();
  loaded.resolve(localDraftRecord());
  await initialized;
  await flushMicrotasks();

  assert.deepEqual(fixture.calls.store, ['load']);
  assert.equal(fixture.calls.api.some(call => Array.isArray(call) && call[0] === 'active'), false);
  assert.equal(fixture.calls.view.filter(([kind]) => kind === 'render').length, rendersBeforeDestroy);
  assert.equal(app.getSnapshot().value, 'welcome');
});

test('roster scan dedupes children and resolves the zero, one, and multiple-active boundaries', async () => {
  const secondChild = childRecord(8, '小云');

  {
    const fixture = createFixture();
    fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord(), childRecord(), secondChild]);
    fixture.deps.api.getActiveConversation = childId => {
      fixture.calls.api.push(['active', childId]);
      return Promise.resolve({ conversation: null });
    };
    const app = createChildApp(fixture.deps);
    await app.initialize();
    await app.start();
    assert.equal(app.getSnapshot().value, 'selecting_child');
    assert.deepEqual(app.getSnapshot().roster.map(child => child.id), [7, 8]);
    assert.deepEqual(fixture.calls.api.filter(call => Array.isArray(call) && call[0] === 'active')
      .map(call => call[1]).sort(), [7, 8]);
  }

  {
    const fixture = createFixture();
    fixture.deps.api.getTodayRoster = () => Promise.resolve([
      childRecord(), secondChild, childRecord(9, '小岚'),
    ]);
    fixture.deps.api.getActiveConversation = childId => {
      fixture.calls.api.push(['active', childId]);
      return Promise.resolve({ conversation: null });
    };
    const app = createChildApp(fixture.deps);
    await app.initialize();
    await app.start();
    assert.equal(app.getSnapshot().value, 'recovery');
    assert.deepEqual(app.getSnapshot().error, { code: 'ROSTER_CARDINALITY_INVALID', retryable: false });
    assert.equal(fixture.calls.api.some(call => Array.isArray(call) && call[0] === 'active'), false);
  }

  {
    const fixture = createFixture();
    fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord(), secondChild]);
    fixture.deps.api.getActiveConversation = childId => Promise.resolve({
      conversation: { ...activeConversation(), id: childId + 2, child_id: childId },
    });
    const app = createChildApp(fixture.deps);
    await app.initialize();
    await app.start();
    assert.equal(app.getSnapshot().value, 'recovery');
    assert.deepEqual(app.getSnapshot().error, { code: 'MULTIPLE_ACTIVE_CONVERSATIONS', retryable: false });
  }

  {
    const fixture = createFixture();
    fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord(), secondChild]);
    fixture.deps.api.getActiveConversation = childId => Promise.resolve({
      conversation: childId === 8
        ? { ...activeConversation(), id: 10, child_id: 8 }
        : null,
    });
    const app = createChildApp(fixture.deps);
    await app.initialize();
    await app.start();
    assert.equal(app.getSnapshot().value, 'ready');
    assert.equal(app.getSnapshot().child.id, 8);
    assert.equal(app.getSnapshot().conversationId, 10);
    assert.equal(fixture.calls.tts.filter(([kind]) => kind === 'speak').length, 0);
  }
});

test('rejected key event getters cannot reentrantly start speech before policy rejection', async () => {
  const fixture = createFixture();
  fixture.deps.api.getTodayRoster = () => Promise.resolve([childRecord()]);
  fixture.deps.api.getActiveConversation = () => Promise.resolve({ conversation: null });
  const app = createChildApp(fixture.deps);
  await app.initialize();
  await app.start();
  await app.selectChild(7);
  const event = {
    get code() {
      app.recordToggle();
      return 'KeyA';
    },
    repeat: false,
    defaultPrevented: false,
    target: {},
    preventDefault() { throw new Error('must not prevent rejected key'); },
  };

  assert.equal(app.handleGlobalKeydown(event), false);
  assert.equal(fixture.calls.speechStart, 0);
  assert.equal(app.getSnapshot().value, 'ready');
});

test('effect then getter and call execute inside the public-action critical section', async () => {
  const fixture = createFixture();
  let app = null;
  let getterCalls = 0;
  let thenCalls = 0;
  fixture.deps.api.getTodayRoster = () => Object.defineProperty({}, 'then', {
    get() {
      getterCalls += 1;
      app?.destroy();
      return resolve => {
        thenCalls += 1;
        app?.destroy();
        resolve([]);
      };
    },
  });
  app = createChildApp(fixture.deps);
  await app.initialize();

  await app.start();
  await flushMicrotasks();

  assert.equal(getterCalls, 1);
  assert.equal(thenCalls, 1);
  assert.equal(fixture.calls.speechDispose, 0);
  assert.equal(fixture.calls.tts.some(([kind]) => kind === 'dispose'), false);
  assert.equal(fixture.calls.view.some(([kind]) => kind === 'destroy'), false);
  assert.equal(app.getSnapshot().value, 'selecting_child');
});

test('cleanup thenable return chains are consumed without leaking a nested rejection', async () => {
  const fixture = createFixture();
  const nestedCalls = { speech: 0, tts: 0, view: 0 };
  const cleanupThenable = key => ({
    then(resolve) {
      resolve();
      return {
        then(_resolve, reject) {
          nestedCalls[key] += 1;
          reject(new Error(`private nested ${key} rejection`));
        },
      };
    },
  });
  fixture.speech.dispose = () => cleanupThenable('speech');
  fixture.deps.tts.dispose = () => cleanupThenable('tts');
  fixture.deps.view.destroy = () => cleanupThenable('view');
  const app = createChildApp(fixture.deps);
  await app.initialize();

  app.destroy();
  await flushMicrotasks();

  assert.deepEqual(nestedCalls, { speech: 1, tts: 1, view: 1 });
});

test('a bootstrap callback cannot reenter a second factory chain through different dependencies', async () => {
  const outer = createBootstrapFixture();
  const inner = createBootstrapFixture();
  let nested = null;
  outer.deps.bootstrapAPI = () => {
    outer.calls.bootstrapAPI += 1;
    outer.calls.order.push('api');
    nested = bootstrapBrowserChildApp(inner.deps);
    return Promise.resolve(outer.child.deps.api);
  };

  const outerApp = await bootstrapBrowserChildApp(outer.deps);
  const innerApp = await nested;

  assert.notEqual(outerApp, null);
  assert.equal(innerApp, null);
  assert.equal(outer.calls.storeFactory, 1);
  assert.equal(inner.calls.storeFactory, 0);
  outerApp.destroy();
});
