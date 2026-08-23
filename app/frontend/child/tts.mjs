const COLD_START_MS = 5000;
const BROWSER_TIMEOUT_MS = 15000;
const SCHEDULING = Symbol('scheduling');
const SKIPPED = Symbol('skipped');

export function createTTSController(deps = {}) {
  const {
    loadEdgeBlob,
    Audio: makeAudio,
    createObjectURL,
    revokeObjectURL,
    browserSpeak,
    speechSynthesis,
    SpeechSynthesisUtterance,
    setTimer,
    clearTimer,
  } = deps;
  const AbortController = Object.hasOwn(deps, 'AbortController')
    ? deps.AbortController
    : globalThis.AbortController;
  let active = null;
  let disposed = false;

  function isActive(request) {
    return request !== null && active === request && !request.done;
  }

  function speak(text) {
    if (typeof text !== 'string' || !text.trim()) {
      return Promise.resolve(result('text', 'invalid-text'));
    }
    if (disposed) return Promise.resolve(result('cancelled', 'disposed'));
    cancel('superseded');

    return new Promise(resolve => {
      const edgeAborter = createAborter(AbortController);
      const request = {
        audio: null,
        browserAborter: null,
        browserCancels: [],
        browserTimer: null,
        coldTimer: null,
        done: false,
        edgeAborter,
        edgeSignal: edgeAborter?.signal ?? null,
        fallbackStarted: false,
        objectURL: null,
        resolve,
        revokedURL: null,
      };
      active = request;
      request.settle = value => settle(request, value);

      if (!edgeAborter) {
        startFallback(request, text, 'abort-controller-unavailable');
        return;
      }

      const coldTimerStarted = scheduleTimer(request, 'coldTimer', () => {
        abortEdge(request);
        if (!isActive(request)) return;
        startFallback(request, text, 'edge-timeout');
      }, COLD_START_MS);
      if (!isActive(request)) return;
      if (!coldTimerStarted) {
        startFallback(request, text, 'edge-timer-error');
        return;
      }

      run(() => loadEdgeBlob(text, request.edgeSignal))
        .then(blob => startEdgeAudio(request, blob, text))
        .catch(error => {
          if (!edgeIsCurrent(request)) return;
          startFallback(request, text, error?.name === 'AbortError' ? 'edge-timeout' : 'edge-request-error');
        });
    });
  }

  function cancel(reason = 'cancelled') {
    const request = active;
    if (!isActive(request)) return;
    abortEdge(request);
    if (!isActive(request)) return;
    stopEdge(request);
    if (!isActive(request)) return;
    stopBrowser(request);
    if (!isActive(request)) return;
    request.settle(result('cancelled', reason));
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    cancel('disposed');
  }

  function startEdgeAudio(request, blob, text) {
    if (!edgeIsCurrent(request)) return;
    run(() => createObjectURL(blob))
      .then(objectURL => {
        if (!edgeIsCurrent(request)) {
          revokeURL(request, objectURL);
          return;
        }
        request.objectURL = objectURL;
        return run(() => makeAudio(objectURL)).then(audio => {
          if (!edgeIsCurrent(request)) return;
          if (!audio || (typeof audio !== 'object' && typeof audio !== 'function')) {
            startFallback(request, text, 'edge-audio-error');
            return;
          }
          request.audio = audio;
          audio.onplaying = () => {
            if (edgeIsCurrent(request)) clearTimerOnce(request, 'coldTimer');
          };
          audio.onended = () => {
            if (edgeIsCurrent(request)) request.settle(result('edge', 'ended'));
          };
          audio.onerror = () => {
            if (edgeIsCurrent(request)) startFallback(request, text, 'edge-playback-error');
          };
          run(() => audio.play()).catch(() => {
            if (edgeIsCurrent(request)) startFallback(request, text, 'edge-play-rejected');
          });
        });
      })
      .catch(() => {
        if (edgeIsCurrent(request)) startFallback(request, text, 'edge-setup-error');
      });
  }

  function startFallback(request, text, reason) {
    if (!isActive(request) || request.fallbackStarted) return;
    if (reason !== 'edge-timeout') {
      clearTimerOnce(request, 'coldTimer');
      if (!isActive(request)) return;
    }
    request.fallbackStarted = true;
    abortEdge(request);
    if (!isActive(request)) return;
    stopEdge(request);
    if (!isActive(request)) return;

    request.browserAborter = createAborter(AbortController);
    if (!isActive(request)) return;
    const browserTimerStarted = scheduleTimer(request, 'browserTimer', () => {
      stopBrowser(request);
      if (!isActive(request)) return;
      request.settle(result('text', 'browser-timeout'));
    }, BROWSER_TIMEOUT_MS);
    if (!isActive(request)) return;
    if (!browserTimerStarted) {
      request.settle(result('text', 'browser-timer-error'));
      return;
    }

    const context = {
      clearTimer,
      onCancel(cancelBrowser) {
        if (typeof cancelBrowser !== 'function') return;
        const once = onceOnly(cancelBrowser);
        if (!browserIsCurrent(request)) {
          if (request.done || request.browserAborter?.signal?.aborted) absorbCleanup(once);
          return;
        }
        request.browserCancels.push(once);
      },
      reason,
      setTimer,
      signal: request.browserAborter?.signal ?? null,
    };
    const invokeBrowser = typeof browserSpeak === 'function'
      ? () => browserSpeak(text, context)
      : () => defaultBrowserSpeak(text, {
        ...context,
        speechSynthesis,
        SpeechSynthesisUtterance,
      });

    run(() => browserIsCurrent(request) ? invokeBrowser() : SKIPPED)
      .then(value => {
        if (!browserIsCurrent(request) || value === SKIPPED) return;
        request.settle(normalizeFallback(value, reason));
      })
      .catch(() => {
        if (browserIsCurrent(request)) request.settle(result('text', reason));
      });
  }

  function settle(request, value) {
    if (request.done) return;
    request.done = true;
    clearTimerOnce(request, 'coldTimer');
    clearTimerOnce(request, 'browserTimer');
    detachAudio(request);
    revokeURL(request);
    if (active === request) active = null;
    request.resolve(result(value.mode, value.reason));
  }

  function scheduleTimer(request, key, callback, delay) {
    if (!isActive(request)) return false;
    let timer;
    request[key] = SCHEDULING;
    const fire = () => {
      if (request[key] !== SCHEDULING && request[key] !== timer) return;
      request[key] = null;
      callback();
    };
    try {
      timer = setTimer(fire, delay);
    } catch {
      if (request[key] === SCHEDULING) request[key] = null;
      return false;
    }
    absorbThenable(timer);
    if (request[key] !== SCHEDULING || !isActive(request)) {
      absorbCleanup(() => clearTimer(timer));
      return false;
    }
    request[key] = timer;
    return true;
  }

  function clearTimerOnce(request, key) {
    const timer = request[key];
    if (timer === null) return;
    request[key] = null;
    if (timer !== SCHEDULING) absorbCleanup(() => clearTimer(timer));
  }

  function abortEdge(request) {
    const aborter = request.edgeAborter;
    request.edgeAborter = null;
    if (aborter) absorbCleanup(() => aborter.abort());
  }

  function stopEdge(request) {
    const audio = request.audio;
    request.audio = null;
    if (audio) {
      absorbCleanup(() => audio.pause?.());
      detachAudioValue(audio);
    }
    revokeURL(request);
  }

  function stopBrowser(request) {
    const aborter = request.browserAborter;
    request.browserAborter = null;
    const cancels = request.browserCancels.splice(0);
    if (aborter) absorbCleanup(() => aborter.abort());
    for (const cancelBrowser of cancels) absorbCleanup(cancelBrowser);
  }

  function detachAudio(request) {
    const audio = request.audio;
    request.audio = null;
    if (audio) detachAudioValue(audio);
  }

  function detachAudioValue(audio) {
    absorbCleanup(() => {
      audio.onplaying = null;
      audio.onended = null;
      audio.onerror = null;
    });
  }

  function revokeURL(request, explicitURL) {
    const objectURL = explicitURL === undefined ? request.objectURL : explicitURL;
    if (objectURL === null || objectURL === undefined || request.revokedURL === objectURL) return;
    request.revokedURL = objectURL;
    if (request.objectURL === objectURL) request.objectURL = null;
    absorbCleanup(() => revokeObjectURL(objectURL));
  }

  function edgeIsCurrent(request) {
    return isActive(request)
      && !request.fallbackStarted
      && request.edgeAborter !== null
      && request.edgeSignal?.aborted !== true;
  }

  function browserIsCurrent(request) {
    return isActive(request) && request.fallbackStarted;
  }

  return Object.freeze({ speak, cancel, dispose });
}

function defaultBrowserSpeak(text, {
  onCancel,
  speechSynthesis,
  SpeechSynthesisUtterance,
} = {}) {
  return new Promise(resolve => {
    let done = false;
    let utterance = null;
    const settle = value => {
      if (done) return;
      done = true;
      if (utterance) {
        utterance.onend = null;
        utterance.onerror = null;
      }
      resolve(value);
    };
    const cancelled = () => {
      absorbCleanup(() => speechSynthesis?.cancel?.());
      settle(result('cancelled', 'browser-cancelled'));
    };

    if (!speechSynthesis || typeof speechSynthesis.speak !== 'function' || typeof SpeechSynthesisUtterance !== 'function') {
      settle(result('text', 'browser-unavailable'));
      return;
    }

    try {
      utterance = new SpeechSynthesisUtterance(text);
      utterance.onend = () => settle(result('browser', 'ended'));
      utterance.onerror = () => settle(result('text', 'browser-error'));
      onCancel?.(cancelled);
      if (done) return;
      run(() => done ? undefined : speechSynthesis.speak(utterance))
        .catch(() => settle(result('text', 'browser-error')));
    } catch {
      settle(result('text', 'browser-error'));
    }
  });
}

function createAborter(AbortController) {
  if (typeof AbortController !== 'function') return null;
  try {
    const aborter = new AbortController();
    if (!aborter?.signal || typeof aborter.abort !== 'function') return null;
    return aborter;
  } catch {
    return null;
  }
}

function run(work) {
  return Promise.resolve().then(work);
}

function absorbCleanup(work) {
  try {
    absorbThenable(work());
  } catch {}
}

function absorbThenable(value) {
  try {
    if (value && typeof value.then === 'function') Promise.resolve(value).catch(() => {});
  } catch {}
}

function onceOnly(callback) {
  let called = false;
  return () => {
    if (called) return;
    called = true;
    return callback();
  };
}

function normalizeFallback(value, reason) {
  if (value?.mode === 'browser' || value?.mode === 'text') {
    return result(value.mode, typeof value.reason === 'string' ? value.reason : reason);
  }
  return result('text', reason);
}

function result(mode, reason) {
  const normalizedMode = ['edge', 'browser', 'text', 'cancelled'].includes(mode) ? mode : 'text';
  return { mode: normalizedMode, reason: typeof reason === 'string' ? reason : 'unknown' };
}
