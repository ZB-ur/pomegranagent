const APP_DEPENDENCY_KEYS = Object.freeze([
  'api',
  'machine',
  'store',
  'createDraft',
  'mergeRecovery',
  'createSpeech',
  'tts',
  'view',
  'keyboard',
  'uuid',
  'now',
  'AbortController',
]);

const API_KEYS = Object.freeze([
  'ready',
  'getTodayRoster',
  'getActiveConversation',
  'chat',
  'complete',
  'teacherStatus',
  'teacherSetup',
  'teacherUnlock',
  'teacherLock',
  'tts',
]);

const MACHINE_KEYS = Object.freeze([
  'STATES',
  'assertSnapshot',
  'controlsFor',
  'createInitialSnapshot',
  'transition',
]);

const STORE_KEYS = Object.freeze(['load', 'save', 'clear']);
const TTS_KEYS = Object.freeze(['speak', 'cancel', 'dispose']);
const VIEW_KEYS = Object.freeze(['render', 'announce', 'focus', 'destroy']);
const KEYBOARD_KEYS = Object.freeze(['isInteractiveTarget', 'isDialogActive']);
const BOOTSTRAP_DEPENDENCY_KEYS = Object.freeze([
  'bootstrapAPI',
  'onMaintenanceFailure',
  'createStore',
  'createTTS',
  'createView',
  'root',
  'dom',
  'machine',
  'createDraft',
  'mergeRecovery',
  'createSpeech',
  'keyboard',
  'uuid',
  'now',
  'AbortController',
]);
const CANCELLED = Symbol('cancelled child effect');
let bootstrapActive = false;

export function createChildApp(deps) {
  const configured = validateAppDependencies(deps);
  let speech = null;
  let speechBinding = null;
  let snapshot = null;
  let destroyed = false;
  let initializePromise = null;
  let lifecycle = 'pending';
  let criticalDepth = 0;
  let appEpoch = 0;
  let nextEffectEpoch = 0;
  let drainingSpeechEvents = false;
  let constructionReady = false;
  const effects = new Map();
  const queuedSpeechEvents = [];
  try {
    speech = withinBoundary(() => configured.createSpeech({ onEvent: receiveSpeechEvent }));
    speechBinding = validateSpeech(speech);
    snapshot = callExternal(configured.machine.values.createInitialSnapshot, configured.machine.owner);
    callExternal(configured.machine.values.assertSnapshot, configured.machine.owner, [snapshot]);
    callExternal(configured.view.values.render, configured.view.owner, [snapshot]);
    constructionReady = true;
    drainSpeechEvents();

    function withinBoundary(work) {
      criticalDepth += 1;
      try {
        return work();
      } finally {
        criticalDepth -= 1;
        if (criticalDepth === 0) drainSpeechEvents();
      }
    }

    function callExternal(fn, owner, args = []) {
      return withinBoundary(() => fn.apply(owner, args));
    }

    function publicNoop() {
      return destroyed || criticalDepth !== 0;
    }

    function receiveSpeechEvent(event) {
      const entry = effects.get('speech') ?? null;
      if (destroyed || !constructionReady) {
        if (!destroyed) queuedSpeechEvents.push({ entry, event });
        return;
      }
      queuedSpeechEvents.push({ entry, event });
      if (criticalDepth === 0) drainSpeechEvents();
    }

    function drainSpeechEvents() {
      if (destroyed || !constructionReady || criticalDepth !== 0 || drainingSpeechEvents) return;
      drainingSpeechEvents = true;
      try {
        while (!destroyed && criticalDepth === 0 && queuedSpeechEvents.length > 0) {
          const queued = queuedSpeechEvents.shift();
          handleSpeechEvent(queued.event, queued.entry);
        }
      } finally {
        drainingSpeechEvents = false;
      }
    }

    function isCurrentEffect(entry) {
      return entry !== null
        && entry !== undefined
        && !destroyed
        && entry.active === true
        && entry.appEpoch === appEpoch
        && effects.get(entry.key) === entry;
    }

    function createEffect(key) {
      cancelEffect(key);
      let controller;
      let signal;
      let abort;
      try {
        controller = withinBoundary(() => Reflect.construct(configured.AbortController, []));
        signal = withinBoundary(() => controller.signal);
        abort = withinBoundary(() => controller.abort);
      } catch {
        return null;
      }
      if (signal === null || typeof signal !== 'object' || typeof abort !== 'function') return null;
      const entry = {
        active: true,
        appEpoch,
        abort,
        controller,
        epoch: ++nextEffectEpoch,
        key,
        signal,
      };
      effects.set(key, entry);
      return entry;
    }

    function startEffect(key, work, onFulfilled, onRejected, onControllerFailure) {
      const entry = createEffect(key);
      if (entry === null) {
        try {
          return Promise.resolve(onControllerFailure?.());
        } catch {
          return Promise.resolve(undefined);
        }
      }
      const operation = consume(() => {
        if (!isCurrentEffect(entry)) return CANCELLED;
        return callExternal(work, null, [entry.signal]);
      }, withinBoundary);
      const settled = operation.then(
        packet => {
          const value = packet.value;
          if (value === CANCELLED || !isCurrentEffect(entry)) return undefined;
          return onFulfilled(value, entry);
        },
        error => {
          if (!isCurrentEffect(entry)) return undefined;
          return onRejected(error, entry);
        },
      ).catch(() => undefined).finally(() => {
        if (effects.get(key) === entry) effects.delete(key);
      });
      entry.promise = settled;
      return settled;
    }

    function cancelEffect(key) {
      const entry = effects.get(key);
      if (!entry) return;
      effects.delete(key);
      entry.active = false;
      withinBoundary(() => {
        try {
          const value = callExternal(entry.abort, entry.controller);
          absorbThenable(value);
        } catch {}
        if (key === 'tts') {
          try {
            absorbThenable(callExternal(configured.tts.values.cancel, configured.tts.owner, ['superseded']));
          } catch {}
        }
        if (key === 'speech') {
          try {
            absorbThenable(callExternal(speechBinding.values.stop, speechBinding.owner, ['superseded']));
          } catch {}
        }
      });
    }

    function invalidateEffect(key, entry) {
      if (!isCurrentEffect(entry) || effects.get(key) !== entry) return false;
      effects.delete(key);
      entry.active = false;
      return true;
    }

    function cancelAllEffects() {
      return withinBoundary(() => {
        appEpoch += 1;
        for (const key of [...effects.keys()]) cancelEffect(key);
      });
    }

    function forceRecovery(base, error) {
      try {
        const recovered = callExternal(configured.machine.values.transition, configured.machine.owner, [base, {
          type: 'BEGIN_RECOVERY',
          error,
        }]);
        callExternal(configured.machine.values.assertSnapshot, configured.machine.owner, [recovered]);
        snapshot = recovered;
        callExternal(configured.view.values.render, configured.view.owner, [recovered]);
      } catch {}
      return false;
    }

    function commit(event, { persist = true } = {}) {
      return withinBoundary(() => {
        if (destroyed) return { ok: false, reason: 'destroyed' };
        const previous = snapshot;
        let next;
        try {
          next = callExternal(configured.machine.values.transition, configured.machine.owner, [snapshot, event]);
          callExternal(configured.machine.values.assertSnapshot, configured.machine.owner, [next]);
        } catch (error) {
          return { ok: false, reason: 'transition', error };
        }
        snapshot = next;
        try {
          absorbThenable(callExternal(configured.view.values.render, configured.view.owner, [next]));
        } catch {
          cancelAllEffects();
          forceRecovery(event.type === 'RESET' ? previous : next, {
            code: 'VIEW_RENDER_FAILED', retryable: false,
          });
          return { ok: false, reason: 'render' };
        }
        if (!persist) return { ok: true, snapshot: next };
        try {
          absorbThenable(callExternal(configured.store.values.save, configured.store.owner, [next]));
        } catch {
          cancelAllEffects();
          forceRecovery(event.type === 'RESET' ? previous : next, {
            code: 'LOCAL_STORAGE_FAILED', retryable: false,
          });
          return { ok: false, reason: 'store' };
        }
        return { ok: true, snapshot: next };
      });
    }

    function beginRecovery(error, { persist = true } = {}) {
      return withinBoundary(() => {
        cancelAllEffects();
        return commit({ type: 'BEGIN_RECOVERY', error }, { persist });
      });
    }

    function startActiveRecovery(localRecord, child) {
      return startEffect(
        `active:${child.id}`,
        () => configured.api.values.getActiveConversation.call(configured.api.owner, child.id),
        active => resolveRecovery(localRecord, successRead(child, active)),
        error => resolveRecovery(localRecord, failureRead(child, normalizeError(error))),
        () => resolveRecovery(localRecord, failureRead(child, effectControllerError())),
      );
    }

    function resolveRecovery(localRecord, remoteRead) {
      if (destroyed || snapshot.value !== 'recovery') return Promise.resolve(undefined);
      let outcome;
      try {
        outcome = validateRecoveryOutcome(
          callExternal(configured.mergeRecovery, null, [localRecord, remoteRead]),
          configured.machine,
        );
      } catch {
        beginRecovery({ code: 'RECOVERY_MERGE_FAILED', retryable: false }, { persist: false });
        return Promise.resolve(undefined);
      }
      if (outcome.snapshot.value === 'loading_roster' && outcome.storageAction !== 'clear') {
        beginRecovery({ code: 'RECOVERY_RESULT_INVALID', retryable: false }, { persist: false });
        return Promise.resolve(undefined);
      }
      const finish = () => {
        const resolved = commit({ type: 'RECOVERY_RESOLVED', snapshot: outcome.snapshot });
        if (!resolved.ok) return undefined;
        if (outcome.snapshot.value === 'loading_roster') {
          return scanRoster(null);
        }
        if (outcome.snapshot.value === 'saving_conversation') return startCompletion();
        return undefined;
      };
      if (outcome.storageAction === 'keep') return Promise.resolve(finish());
      if (outcome.storageAction !== 'clear') {
        beginRecovery({ code: 'RECOVERY_RESULT_INVALID', retryable: false }, { persist: false });
        return Promise.resolve(undefined);
      }
      return Promise.resolve(withinBoundary(() => {
        try {
          absorbThenable(callExternal(configured.store.values.clear, configured.store.owner));
        } catch {
          beginRecovery({ code: 'LOCAL_STORAGE_FAILED', retryable: false }, { persist: false });
          return undefined;
        }
        return finish();
      }));
    }

    function beginLocalRecovery(localRecord) {
      const started = commit({ type: 'START' }, { persist: false });
      if (!started.ok) return undefined;
      const entered = commit({
        type: 'BEGIN_RECOVERY',
        error: { code: 'RECOVERY_BOOTSTRAPPING', retryable: true },
      }, { persist: false });
      if (!entered.ok) return undefined;
      const child = safeLocalChild(localRecord);
      return child === null ? scanRoster(localRecord) : startActiveRecovery(localRecord, child);
    }

    function safeLocalChild(localRecord) {
      try {
        if (localRecord === null || typeof localRecord !== 'object') return null;
        const descriptor = Reflect.getOwnPropertyDescriptor(localRecord, 'child');
        if (descriptor === undefined || !Object.hasOwn(descriptor, 'value') || descriptor.value === null) return null;
        const child = descriptor.value;
        if (child === null || typeof child !== 'object' || Array.isArray(child)
          || Reflect.getPrototypeOf(child) !== Object.prototype) return null;
        const values = Object.create(null);
        for (const key of ['id', 'name', 'nickname', 'avatar']) {
          const field = Reflect.getOwnPropertyDescriptor(child, key);
          if (field === undefined || !Object.hasOwn(field, 'value')) return null;
          values[key] = field.value;
        }
        if (!Number.isSafeInteger(values.id) || values.id <= 0 || typeof values.name !== 'string'
          || values.name.length === 0 || (values.nickname !== null && typeof values.nickname !== 'string')
          || (values.avatar !== null && typeof values.avatar !== 'string')) return null;
        return Object.freeze({
          id: values.id,
          name: values.name,
          nickname: values.nickname,
          avatar: values.avatar,
        });
      } catch {
        return null;
      }
    }

    function successRead(child, active) {
      return {
        kind: 'success',
        queriedChild: child,
        active,
      };
    }

    function failureRead(child, error) {
      return {
        kind: 'failure',
        queriedChild: child,
        error,
      };
    }

    function validateRecoveryOutcome(outcome, machineBinding) {
      const values = exactRecord(outcome, ['snapshot', 'storageAction']);
      if (values.storageAction !== 'keep' && values.storageAction !== 'clear') throw constructionFailure();
      callExternal(machineBinding.values.assertSnapshot, machineBinding.owner, [values.snapshot]);
      return values;
    }

    function scanRoster(localRecord) {
      return startEffect(
        'roster',
        () => configured.api.values.getTodayRoster.call(configured.api.owner),
        roster => handleRoster(localRecord, roster),
        error => handleRosterFailure(localRecord, normalizeError(error)),
        () => handleRosterFailure(localRecord, effectControllerError()),
      );
    }

    function handleRoster(localRecord, roster) {
      let children;
      try {
        children = normalizeRoster(roster);
      } catch {
        return handleRosterFailure(localRecord, { code: 'NETWORK_ERROR', retryable: false });
      }
      if (children.length > 2) {
        return handleRosterFailure(localRecord, { code: 'ROSTER_CARDINALITY_INVALID', retryable: false });
      }
      if (children.length === 0) {
        if (localRecord === null) {
          commit({ type: 'ROSTER_LOADED', children });
          return undefined;
        }
        return resolveRecovery(localRecord, successRead(null, { conversation: null }));
      }
      return scanActiveChildren(localRecord, children);
    }

    function handleRosterFailure(localRecord, error) {
      if (localRecord === null) {
        beginRecovery(error);
        return undefined;
      }
      return resolveRecovery(localRecord, failureRead(null, error));
    }

    function normalizeRoster(value) {
      if (!Array.isArray(value)) throw constructionFailure();
      const seen = new Set();
      const children = [];
      for (const rawChild of value) {
        const child = copyChild(rawChild);
        if (!seen.has(child.id)) {
          seen.add(child.id);
          children.push(child);
        }
      }
      return children;
    }

    function copyChild(rawChild) {
      if (rawChild === null || typeof rawChild !== 'object' || Array.isArray(rawChild)) throw constructionFailure();
      const values = Object.create(null);
      for (const key of ['id', 'name', 'nickname', 'avatar']) {
        const descriptor = Reflect.getOwnPropertyDescriptor(rawChild, key);
        if (descriptor === undefined || !Object.hasOwn(descriptor, 'value')) throw constructionFailure();
        values[key] = descriptor.value;
      }
      if (!Number.isSafeInteger(values.id) || values.id <= 0 || typeof values.name !== 'string' || values.name.length === 0
        || (values.nickname !== null && typeof values.nickname !== 'string')
        || (values.avatar !== null && typeof values.avatar !== 'string')) throw constructionFailure();
      return Object.freeze({
        id: values.id,
        name: values.name,
        nickname: values.nickname,
        avatar: values.avatar,
      });
    }

    function scanActiveChildren(localRecord, children) {
      let remaining = children.length;
      let firstFailure = null;
      const reads = [];
      const settle = () => {
        remaining -= 1;
        if (remaining !== 0) return undefined;
        if (firstFailure !== null) return handleRosterFailure(localRecord, firstFailure);
        return decideActiveReads(localRecord, children, reads);
      };
      const pending = children.map(child => startEffect(
        `active:${child.id}`,
        () => configured.api.values.getActiveConversation.call(configured.api.owner, child.id),
        active => {
          try {
            reads.push({ child, active, conversation: activeConversation(active) });
          } catch {
            firstFailure ??= { code: 'NETWORK_ERROR', retryable: false };
          }
          return settle();
        },
        error => {
          firstFailure ??= normalizeError(error);
          return settle();
        },
        () => {
          firstFailure ??= effectControllerError();
          return settle();
        },
      ));
      return Promise.all(pending).then(() => undefined);
    }

    function activeConversation(active) {
      if (active === null || typeof active !== 'object' || Array.isArray(active)) throw constructionFailure();
      const descriptor = Reflect.getOwnPropertyDescriptor(active, 'conversation');
      if (descriptor === undefined || !Object.hasOwn(descriptor, 'value')) throw constructionFailure();
      return descriptor.value;
    }

    function decideActiveReads(localRecord, children, reads) {
      const activeReads = reads.filter(read => read.conversation !== null);
      if (activeReads.length === 0) {
        if (localRecord === null) {
          commit({ type: 'ROSTER_LOADED', children });
          return undefined;
        }
        return resolveRecovery(localRecord, successRead(null, { conversation: null }));
      }
      if (activeReads.length === 1) {
        const selected = activeReads[0];
        if (localRecord === null) {
          const entered = commit({
            type: 'BEGIN_RECOVERY',
            error: { code: 'RECOVERY_BOOTSTRAPPING', retryable: true },
          }, { persist: false });
          if (!entered.ok) return undefined;
        }
        return resolveRecovery(localRecord, successRead(selected.child, selected.active));
      }
      return handleRosterFailure(localRecord, {
        code: 'MULTIPLE_ACTIVE_CONVERSATIONS', retryable: false,
      });
    }

    function startCompletion() {
      if (snapshot.value !== 'saving_conversation' || snapshot.conversationId === null || snapshot.lastMessageId === null) {
        return Promise.resolve(undefined);
      }
      const conversationId = snapshot.conversationId;
      const lastMessageId = snapshot.lastMessageId;
      return startEffect(
        'complete',
        signal => configured.api.values.complete.call(configured.api.owner, conversationId, lastMessageId, signal),
        result => handleCompletionSuccess(result),
        error => handleCompletionFailure(normalizeError(error)),
        () => handleCompletionFailure(effectControllerError()),
      );
    }

    function handleCompletionSuccess(result) {
      const completed = commit({ type: 'COMPLETE_SUCCEEDED', result });
      if (!completed.ok && completed.reason === 'transition') {
        beginRecovery({ code: 'COMPLETE_RESPONSE_INVALID', retryable: false });
      }
      return undefined;
    }

    function handleCompletionFailure(error) {
      if (error.code === 'CONVERSATION_CHANGED') return restartCompletionRecovery(error);
      commit({ type: 'COMPLETE_FAILED', error });
      return undefined;
    }

    function restartCompletionRecovery(error) {
      const entered = beginRecovery(error, { persist: false });
      if (!entered.ok || destroyed || snapshot.value !== 'recovery') return Promise.resolve(undefined);
      return startEffect(
        'recovery',
        () => configured.store.values.load.call(configured.store.owner),
        localRecord => {
          const child = safeLocalChild(localRecord);
          if (child === null) {
            beginRecovery({ code: 'RECOVERY_RESULT_INVALID', retryable: false }, { persist: false });
            return undefined;
          }
          return startActiveRecovery(localRecord, child);
        },
        () => {
          beginRecovery({ code: 'LOCAL_STORAGE_FAILED', retryable: false }, { persist: false });
          return undefined;
        },
        () => {
          beginRecovery(effectControllerError(), { persist: false });
          return undefined;
        },
      );
    }

    function startTTS(text) {
      return startEffect(
        'tts',
        () => configured.tts.values.speak.call(configured.tts.owner, text),
        () => settleTTS(),
        () => settleTTS(),
        () => beginRecovery(effectControllerError()),
      );
    }

    function settleTTS() {
      const settled = commit({ type: 'TTS_SETTLED' });
      if (!settled.ok) return undefined;
      if (snapshot.value === 'saving_conversation') return startCompletion();
      return undefined;
    }

    function startChat() {
      if (snapshot.value !== 'submitting' || snapshot.child === null || snapshot.draft === null) return Promise.resolve(undefined);
      const input = Object.freeze({
        request_id: snapshot.draft.request_id,
        child_id: snapshot.child.id,
        text: snapshot.draft.text,
        conversation_id: snapshot.conversationId,
        max_rounds: 3,
      });
      return startEffect(
        'chat',
        signal => configured.api.values.chat.call(configured.api.owner, input, signal),
        result => handleChatSuccess(result),
        error => handleChatFailure(normalizeError(error)),
        () => handleChatFailure(effectControllerError()),
      );
    }

    function handleChatSuccess(result) {
      const submitted = commit({ type: 'SUBMIT_SUCCEEDED', result });
      if (!submitted.ok) {
        if (submitted.reason === 'transition') {
          commit({
            type: 'SUBMIT_FAILED',
            error: { code: 'CHAT_RESPONSE_CONFLICT', retryable: false },
          });
        }
        return undefined;
      }
      return startTTS(snapshot.reply);
    }

    function handleChatFailure(error) {
      commit({ type: 'SUBMIT_FAILED', error });
      return undefined;
    }

    function handleSpeechEvent(rawEvent, entry) {
      if (!isCurrentEffect(entry) || snapshot.value !== 'listening') return;
      const event = readSpeechEvent(rawEvent);
      if (event === null) return;
      if (event.type === 'partial') {
        try {
          callExternal(configured.view.values.announce, configured.view.owner, [event.text]);
        } catch {}
        return;
      }
      if (event.type === 'empty') {
        if (!invalidateEffect('speech', entry)) return;
        commit({ type: 'SPEECH_EMPTY' });
        return;
      }
      if (event.type === 'error') {
        if (!invalidateEffect('speech', entry)) return;
        beginRecovery(normalizeError(event.error));
        return;
      }
      if (event.type === 'final') {
        if (!invalidateEffect('speech', entry)) return;
        let draft;
        try {
          draft = callExternal(configured.createDraft, null, [event.text, {
            uuid: configured.uuid,
            now: configured.now,
          }]);
        } catch {
          beginRecovery({ code: 'DRAFT_CREATION_FAILED', retryable: false });
          return;
        }
        const committed = commit({ type: 'SPEECH_FINAL', draft });
        if (!committed.ok) {
          if (committed.reason === 'transition') {
            beginRecovery({ code: 'DRAFT_CREATION_FAILED', retryable: false });
          }
          return;
        }
        startChat();
      }
    }

    function initialize() {
      if (destroyed) return Promise.resolve(undefined);
      if (initializePromise !== null) return initializePromise;
      initializePromise = consume(
        () => callExternal(configured.api.values.ready, configured.api.owner),
        withinBoundary,
      )
        .then(() => {
          if (destroyed) return undefined;
          lifecycle = 'ready';
          return consume(
            () => callExternal(configured.store.values.load, configured.store.owner),
            withinBoundary,
          )
            .then(packet => {
              const localRecord = packet.value;
              if (destroyed || localRecord === null) return undefined;
              return beginLocalRecovery(localRecord);
            }, () => {
              if (destroyed) return undefined;
              const started = commit({ type: 'START' }, { persist: false });
              if (!started.ok) return undefined;
              beginRecovery({ code: 'LOCAL_STORAGE_FAILED', retryable: false }, { persist: false });
              return undefined;
            });
        }, () => {
          if (!destroyed) lifecycle = 'gate-failed';
          return undefined;
        });
      return initializePromise;
    }

    function start() {
      if (publicNoop()) return Promise.resolve(undefined);
      return initialize().then(() => {
        if (destroyed || lifecycle !== 'ready' || snapshot.value !== 'welcome') return undefined;
        const started = commit({ type: 'START' }, { persist: false });
        if (!started.ok) return undefined;
        return scanRoster(null);
      }, () => undefined).then(() => undefined, () => undefined);
    }

    function selectChild(childId) {
      if (publicNoop()) return Promise.resolve(undefined);
      return initialize().then(() => {
        if (destroyed || lifecycle !== 'ready' || snapshot.value !== 'selecting_child'
          || !Number.isSafeInteger(childId) || childId <= 0) return undefined;
        const child = snapshot.roster.find(candidate => candidate.id === childId);
        if (!child) return undefined;
        cancelAllEffects();
        const selected = commit({ type: 'CHILD_SELECTED', childId });
        if (!selected.ok) return undefined;
        return startTTS(`你好呀，${child.nickname || child.name}！我是鸭鸭日记本，今天想听你讲讲照顾小鸭的事～`);
      }, () => undefined).then(() => undefined, () => undefined);
    }

    function recordToggle() {
      if (publicNoop()) return undefined;
      let controls;
      try {
        controls = callExternal(configured.machine.values.controlsFor, configured.machine.owner, [snapshot]);
      } catch {
        return undefined;
      }
      if (!recordControlEnabled(controls)) return undefined;
      if (snapshot.value === 'ready') {
        const started = commit({ type: 'RECORD_TOGGLE' });
        if (!started.ok) return undefined;
        startSpeech();
        return undefined;
      }
      if (snapshot.value !== 'listening' || snapshot.stopRequested === true) return undefined;
      const stopping = commit({ type: 'RECORD_TOGGLE' });
      if (!stopping.ok) return undefined;
      const entry = effects.get('speech');
      if (!isCurrentEffect(entry) || entry.manualStopRequested === true) return undefined;
      entry.manualStopRequested = true;
      try {
        absorbThenable(callExternal(speechBinding.values.stop, speechBinding.owner, ['manual']));
      } catch {
        cancelEffect('speech');
        beginRecovery({ code: 'SPEECH_FAILED', retryable: true });
      }
      return undefined;
    }

    function startSpeech() {
      const entry = createEffect('speech');
      if (entry === null) {
        beginRecovery(effectControllerError());
        return;
      }
      try {
        absorbThenable(callExternal(speechBinding.values.start, speechBinding.owner));
      } catch {
        cancelEffect('speech');
        beginRecovery({ code: 'SPEECH_FAILED', retryable: true });
      }
    }

    function retry() {
      if (publicNoop()) return Promise.resolve(undefined);
      return initialize().then(() => {
        if (destroyed || lifecycle !== 'ready' || snapshot.value !== 'submission_failed'
          || snapshot.error?.retryable !== true || snapshot.draft === null) {
          return undefined;
        }
        const retried = commit({ type: 'RETRY_SUBMIT' });
        if (!retried.ok) return undefined;
        return startChat();
      }, () => undefined).then(() => undefined, () => undefined);
    }

    function reset() {
      if (publicNoop() || (snapshot.value !== 'recovery' && snapshot.value !== 'completed')) return undefined;
      return withinBoundary(() => {
        cancelAllEffects();
        try {
          absorbThenable(callExternal(configured.store.values.clear, configured.store.owner));
        } catch {
          beginRecovery({ code: 'LOCAL_STORAGE_FAILED', retryable: false }, { persist: false });
          return undefined;
        }
        commit({ type: 'RESET' }, { persist: false });
        return undefined;
      });
    }

    function handleGlobalKeydown(event) {
      if (publicNoop()) return false;
      let keydown;
      try {
        keydown = withinBoundary(() => readKeydownEvent(event));
      } catch {
        return false;
      }
      if (keydown === null || keydown.code !== 'Space' || keydown.repeat === true || keydown.defaultPrevented === true) {
        return false;
      }
      let interactive;
      let dialogActive;
      let controls;
      try {
        interactive = callExternal(configured.keyboard.values.isInteractiveTarget, configured.keyboard.owner, [keydown.target]);
        if (interactive === true) return false;
        dialogActive = callExternal(configured.keyboard.values.isDialogActive, configured.keyboard.owner);
        if (dialogActive === true) return false;
        controls = callExternal(configured.machine.values.controlsFor, configured.machine.owner, [snapshot]);
      } catch {
        return false;
      }
      if (!recordControlEnabled(controls)) return false;
      let preventDefault;
      try {
        preventDefault = withinBoundary(() => event.preventDefault);
        if (typeof preventDefault !== 'function') return false;
        callExternal(preventDefault, event);
      } catch {
        return false;
      }
      recordToggle();
      return true;
    }

    function getSnapshot() {
      return snapshot;
    }

    function destroy() {
      if (destroyed || criticalDepth !== 0) return undefined;
      withinBoundary(() => {
        cancelAllEffects();
        destroyed = true;
        disposeSpeech(speechBinding);
        disposeBinding(configured.tts, 'dispose');
        disposeBinding(configured.view, 'destroy');
      });
      return undefined;
    }

    return Object.freeze({
      initialize,
      start,
      selectChild,
      recordToggle,
      retry,
      reset,
      handleGlobalKeydown,
      getSnapshot,
      destroy,
    });
  } catch {
    disposeSpeech(speechBinding);
    throw constructionFailure();
  }
}

export async function bootstrapBrowserChildApp(deps) {
  if (bootstrapActive) return null;
  bootstrapActive = true;
  try {
    const configured = validateBootstrapDependencies(deps);
    let api;
    let preflight;
    try {
      const sourcePacket = await consume(() => configured.values.bootstrapAPI.call(configured.owner));
      api = validateAPI(sourcePacket.value);
      const preflightPacket = consume(() => api.values.ready.call(api.owner));
      preflight = preflightPacket.then(packet => packet.value);
      await preflight;
    } catch (error) {
      reportMaintenance(configured, error);
      return null;
    }

    const facade = createPreflightAPIFacade(api, preflight);
    let store = null;
    let tts = null;
    let view = null;
    let app = null;
    let forwardingLive = true;
    try {
      store = validateStore(configured.values.createStore.call(configured.owner));
      tts = validateTTS(configured.values.createTTS.call(configured.owner, facade));
      const actions = Object.freeze({
        onStart: () => forwardingLive && app !== null ? app.start() : undefined,
        onSelectChild: childId => forwardingLive && app !== null ? app.selectChild(childId) : undefined,
        onRecordToggle: () => forwardingLive && app !== null ? app.recordToggle() : undefined,
        onRetry: () => forwardingLive && app !== null ? app.retry() : undefined,
        onReset: () => forwardingLive && app !== null ? app.reset() : undefined,
        onOpenTeacherHelp: null,
      });
      view = validateView(configured.values.createView.call(
        configured.owner,
        configured.values.root,
        actions,
        configured.values.dom,
      ));
      app = createChildApp({
        api: facade,
        machine: configured.values.machine,
        store: store.owner,
        createDraft: configured.values.createDraft,
        mergeRecovery: configured.values.mergeRecovery,
        createSpeech: configured.values.createSpeech,
        tts: tts.owner,
        view: view.owner,
        keyboard: configured.values.keyboard,
        uuid: configured.values.uuid,
        now: configured.values.now,
        AbortController: configured.values.AbortController,
      });
      await app.initialize();
      return app;
    } catch {
      forwardingLive = false;
      if (app !== null) {
        try {
          app.destroy();
        } catch {}
      } else {
        disposeBinding(view, 'destroy');
        disposeBinding(tts, 'dispose');
      }
      throw constructionFailure();
    }
  } finally {
    bootstrapActive = false;
  }
}

function validateAppDependencies(deps) {
  const values = exactRecord(deps, APP_DEPENDENCY_KEYS);
  const api = exactRecord(values.api, API_KEYS);
  const machine = exactRecord(values.machine, MACHINE_KEYS);
  const store = exactRecord(values.store, STORE_KEYS);
  const tts = exactRecord(values.tts, TTS_KEYS);
  const view = exactRecord(values.view, VIEW_KEYS);
  const keyboard = exactRecord(values.keyboard, KEYBOARD_KEYS);

  requireCallableRecord(api, API_KEYS);
  if (!Array.isArray(machine.STATES)) failValidation();
  requireCallableRecord(machine, MACHINE_KEYS.filter(key => key !== 'STATES'));
  requireCallableRecord(store, STORE_KEYS);
  requireCallableRecord(tts, TTS_KEYS);
  requireCallableRecord(view, VIEW_KEYS);
  requireCallableRecord(keyboard, KEYBOARD_KEYS);
  for (const key of ['createDraft', 'mergeRecovery', 'createSpeech', 'uuid', 'now', 'AbortController']) {
    if (typeof values[key] !== 'function') failValidation();
  }
  return Object.freeze({
    api: binding(values.api, api),
    machine: binding(values.machine, machine),
    store: binding(values.store, store),
    createDraft: values.createDraft,
    mergeRecovery: values.mergeRecovery,
    createSpeech: values.createSpeech,
    tts: binding(values.tts, tts),
    view: binding(values.view, view),
    keyboard: binding(values.keyboard, keyboard),
    uuid: values.uuid,
    now: values.now,
    AbortController: values.AbortController,
  });
}

function validateBootstrapDependencies(deps) {
  const values = exactRecord(deps, BOOTSTRAP_DEPENDENCY_KEYS);
  if (typeof values.bootstrapAPI !== 'function'
    || typeof values.onMaintenanceFailure !== 'function'
    || typeof values.createStore !== 'function'
    || typeof values.createTTS !== 'function'
    || typeof values.createView !== 'function'
    || typeof values.createDraft !== 'function'
    || typeof values.mergeRecovery !== 'function'
    || typeof values.createSpeech !== 'function'
    || typeof values.uuid !== 'function'
    || typeof values.now !== 'function'
    || typeof values.AbortController !== 'function') {
    failValidation();
  }
  const machine = exactRecord(values.machine, MACHINE_KEYS);
  if (!Array.isArray(machine.STATES)) failValidation();
  requireCallableRecord(machine, MACHINE_KEYS.filter(key => key !== 'STATES'));
  const keyboard = exactRecord(values.keyboard, KEYBOARD_KEYS);
  requireCallableRecord(keyboard, KEYBOARD_KEYS);
  return binding(deps, values);
}

function validateAPI(value) {
  const values = exactRecord(value, API_KEYS);
  requireCallableRecord(values, API_KEYS);
  return binding(value, values);
}

function validateStore(value) {
  const values = exactRecord(value, STORE_KEYS);
  requireCallableRecord(values, STORE_KEYS);
  return binding(value, values);
}

function validateTTS(value) {
  const values = exactRecord(value, TTS_KEYS);
  requireCallableRecord(values, TTS_KEYS);
  return binding(value, values);
}

function validateView(value) {
  const values = exactRecord(value, VIEW_KEYS);
  requireCallableRecord(values, VIEW_KEYS);
  return binding(value, values);
}

function createPreflightAPIFacade(api, preflight) {
  const facade = Object.create(null);
  for (const key of API_KEYS) {
    if (key === 'ready') {
      facade.ready = () => preflight;
      continue;
    }
    const sourceMethod = api.values[key];
    facade[key] = (...args) => sourceMethod.apply(api.owner, args);
  }
  return Object.freeze(facade);
}

function validateSpeech(value) {
  const expectedMethods = ['start', 'stop', 'dispose', 'isListening'];
  if (value === null || typeof value !== 'object' || Array.isArray(value)) failValidation();
  let prototype;
  let keys;
  try {
    prototype = Reflect.getPrototypeOf(value);
    keys = Reflect.ownKeys(value);
  } catch {
    failValidation();
  }
  if (prototype !== Object.prototype && prototype !== null) failValidation();
  if (keys.length !== 5 || keys.some(key => typeof key !== 'string' || ![...expectedMethods, 'recognition'].includes(key))) {
    failValidation();
  }
  const methods = Object.create(null);
  for (const key of expectedMethods) {
    let descriptor;
    try {
      descriptor = Reflect.getOwnPropertyDescriptor(value, key);
    } catch {
      failValidation();
    }
    if (descriptor === undefined || !Object.hasOwn(descriptor, 'value') || typeof descriptor.value !== 'function') {
      failValidation();
    }
    methods[key] = descriptor.value;
  }
  let recognition;
  try {
    recognition = Reflect.getOwnPropertyDescriptor(value, 'recognition');
  } catch {
    failValidation();
  }
  if (recognition === undefined || Object.hasOwn(recognition, 'value') || typeof recognition.get !== 'function') {
    failValidation();
  }
  return binding(value, Object.freeze(methods));
}

function exactRecord(value, expectedKeys) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) failValidation();
  let prototype;
  let keys;
  try {
    prototype = Reflect.getPrototypeOf(value);
    keys = Reflect.ownKeys(value);
  } catch {
    failValidation();
  }
  if (prototype !== Object.prototype && prototype !== null) failValidation();
  if (keys.length !== expectedKeys.length || keys.some(key => typeof key !== 'string' || !expectedKeys.includes(key))) {
    failValidation();
  }
  const values = Object.create(null);
  for (const key of expectedKeys) {
    let descriptor;
    try {
      descriptor = Reflect.getOwnPropertyDescriptor(value, key);
    } catch {
      failValidation();
    }
    if (descriptor === undefined || !Object.hasOwn(descriptor, 'value')) failValidation();
    values[key] = descriptor.value;
  }
  return Object.freeze(values);
}

function requireCallableRecord(record, keys) {
  for (const key of keys) {
    if (typeof record[key] !== 'function') failValidation();
  }
}

function binding(owner, values) {
  return Object.freeze({ owner, values });
}

function disposeSpeech(speech) {
  if (speech === null) return;
  try {
    absorbThenable(speech.values.dispose.call(speech.owner));
  } catch {}
}

function disposeBinding(bindingValue, key) {
  try {
    absorbThenable(bindingValue.values[key].call(bindingValue.owner));
  } catch {}
}

function constructionFailure() {
  return new TypeError('child app construction failed');
}

function consume(work, boundary = invokeDirectly) {
  return new Promise((resolve, reject) => {
    Promise.resolve().then(() => {
      let value;
      try {
        value = boundary(work);
      } catch (error) {
        reject(error);
        return;
      }
      adoptExternalValue(value, resolve, reject, boundary, new Set());
    }, reject);
  });
}

function adoptExternalValue(value, resolve, reject, boundary, seen) {
  if (value === null || (typeof value !== 'object' && typeof value !== 'function')) {
    resolve(valuePacket(value));
    return;
  }
  if (seen.has(value)) {
    reject(new TypeError('external thenable cycle'));
    return;
  }
  seen.add(value);
  let then;
  try {
    then = boundary(() => value.then);
  } catch (error) {
    reject(error);
    return;
  }
  if (typeof then !== 'function') {
    resolve(valuePacket(value));
    return;
  }
  let settled = false;
  let returned;
  try {
    returned = boundary(() => then.call(
      value,
      next => {
        if (settled) return;
        settled = true;
        adoptExternalValue(next, resolve, reject, boundary, seen);
      },
      error => {
        if (settled) return;
        settled = true;
        reject(error);
      },
    ));
  } catch (error) {
    if (!settled) reject(error);
    return;
  }
  absorbThenable(returned, boundary);
}

function valuePacket(value) {
  const packet = Object.create(null);
  packet.value = value;
  return Object.freeze(packet);
}

function invokeDirectly(work) {
  return work();
}

function absorbThenable(value, boundary = invokeDirectly) {
  try {
    if (value === null || (typeof value !== 'object' && typeof value !== 'function')) return;
    const then = boundary(() => value.then);
    if (typeof then !== 'function') return;
    const returned = boundary(() => then.call(value, () => undefined, () => undefined));
    if (returned === value || returned === null
      || (typeof returned !== 'object' && typeof returned !== 'function')) return;
    Promise.resolve(returned).catch(() => {});
  } catch {}
}

function normalizeError(value) {
  let code = 'NETWORK_ERROR';
  let retryable = false;
  if (value !== null && (typeof value === 'object' || typeof value === 'function')) {
    try {
      const codeDescriptor = Reflect.getOwnPropertyDescriptor(value, 'code');
      if (codeDescriptor !== undefined && Object.hasOwn(codeDescriptor, 'value')
        && typeof codeDescriptor.value === 'string' && codeDescriptor.value.length > 0) {
        code = codeDescriptor.value;
      }
      const retryableDescriptor = Reflect.getOwnPropertyDescriptor(value, 'retryable');
      if (retryableDescriptor !== undefined && Object.hasOwn(retryableDescriptor, 'value')
        && typeof retryableDescriptor.value === 'boolean') {
        retryable = retryableDescriptor.value;
      }
    } catch {
      code = 'NETWORK_ERROR';
      retryable = false;
    }
  }
  if (code === 'REQUEST_IN_PROGRESS') retryable = true;
  if (code === 'IDEMPOTENCY_CONFLICT' || code === 'MIC_PERMISSION_DENIED') retryable = false;
  return Object.freeze({ code, retryable });
}

function readSpeechEvent(value) {
  if (value === null || (typeof value !== 'object' && typeof value !== 'function')) return null;
  try {
    const type = Reflect.getOwnPropertyDescriptor(value, 'type');
    if (type === undefined || !Object.hasOwn(type, 'value')) return null;
    if (type.value === 'empty') return Object.freeze({ type: 'empty' });
    if (type.value === 'error') {
      const error = Reflect.getOwnPropertyDescriptor(value, 'error');
      if (error === undefined || !Object.hasOwn(error, 'value')) return null;
      return Object.freeze({ type: 'error', error: error.value });
    }
    if (type.value !== 'partial' && type.value !== 'final') return null;
    const text = Reflect.getOwnPropertyDescriptor(value, 'text');
    if (text === undefined || !Object.hasOwn(text, 'value') || typeof text.value !== 'string') return null;
    return Object.freeze({ type: type.value, text: text.value });
  } catch {
    return null;
  }
}

function readKeydownEvent(value) {
  if (value === null || (typeof value !== 'object' && typeof value !== 'function')) return null;
  try {
    return Object.freeze({
      code: value.code,
      repeat: value.repeat,
      defaultPrevented: value.defaultPrevented,
      target: value.target,
    });
  } catch {
    return null;
  }
}

function recordControlEnabled(value) {
  if (value === null || (typeof value !== 'object' && typeof value !== 'function')) return false;
  try {
    const descriptor = Reflect.getOwnPropertyDescriptor(value, 'recordDisabled');
    return descriptor !== undefined && Object.hasOwn(descriptor, 'value') && descriptor.value === false;
  } catch {
    return false;
  }
}

function effectControllerError() {
  return Object.freeze({ code: 'EFFECT_CONTROLLER_FAILED', retryable: false });
}

function reportMaintenance(configured, error) {
  try {
    configured.values.onMaintenanceFailure.call(configured.owner, maintenanceCode(error));
  } catch {}
}

function maintenanceCode(error) {
  if (error === null || (typeof error !== 'object' && typeof error !== 'function')) {
    return 'CHILD_BOOTSTRAP_FAILED';
  }
  let descriptor;
  try {
    descriptor = Reflect.getOwnPropertyDescriptor(error, 'code');
  } catch {
    return 'CHILD_BOOTSTRAP_FAILED';
  }
  const code = descriptor && Object.hasOwn(descriptor, 'value') ? descriptor.value : null;
  return code === 'VERSION_MISMATCH' || code === 'DB_MODE_MISMATCH' || code === 'HEALTH_UNAVAILABLE'
    ? code
    : 'CHILD_BOOTSTRAP_FAILED';
}

function failValidation() {
  throw new TypeError('invalid child app dependencies');
}
