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
    coldStartMs = 5000,
    browserTimeoutMs = 15000,
  } = deps;
  let active = null;
  let disposed = false;

  function speak(text) {
    if (disposed) return Promise.resolve(result('cancelled', 'disposed'));
    cancel('superseded');

    return new Promise(resolve => {
      const request = {
        audio: null,
        browserAborter: null,
        browserCancels: [],
        browserTimer: null,
        coldTimer: null,
        done: false,
        edgeAborter: createAborter(),
        fallbackStarted: false,
        objectURL: null,
        resolve,
        revokedURL: null,
      };
      active = request;
      request.settle = value => settle(request, value);

      try {
        request.coldTimer = setTimer(() => {
          request.coldTimer = null;
          request.edgeAborter.abort();
          startFallback(request, text, 'edge-timeout');
        }, coldStartMs);
      } catch {
        startFallback(request, text, 'edge-timer-error');
      }

      run(() => loadEdgeBlob(text, request.edgeAborter.signal))
        .then(blob => startEdgeAudio(request, blob, text))
        .catch(error => {
          if (!edgeIsCurrent(request)) return;
          startFallback(request, text, error?.name === 'AbortError' ? 'edge-timeout' : 'edge-request-error');
        });
    });
  }

  function cancel(reason = 'cancelled') {
    const request = active;
    if (!request || request.done) return;
    request.edgeAborter.abort();
    stopEdge(request);
    stopBrowser(request);
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
            if (edgeIsCurrent(request)) clearColdTimer(request);
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
    if (request.done || request.fallbackStarted || active !== request) return;
    if (reason !== 'edge-timeout') clearColdTimer(request);
    request.fallbackStarted = true;
    request.edgeAborter.abort();
    stopEdge(request);
    request.browserAborter = createAborter();

    try {
      request.browserTimer = setTimer(() => {
        request.browserTimer = null;
        stopBrowser(request);
        request.settle(result('text', 'browser-timeout'));
      }, browserTimeoutMs);
    } catch {
      request.settle(result('text', 'browser-timer-error'));
      return;
    }

    const context = {
      clearTimer,
      onCancel(cancelBrowser) {
        if (typeof cancelBrowser !== 'function') return;
        if (request.browserAborter.signal.aborted) {
          safely(cancelBrowser);
        } else {
          request.browserCancels.push(cancelBrowser);
        }
      },
      reason,
      setTimer,
      signal: request.browserAborter.signal,
    };
    const invokeBrowser = typeof browserSpeak === 'function'
      ? () => browserSpeak(text, context)
      : () => defaultBrowserSpeak(text, {
        ...context,
        speechSynthesis,
        SpeechSynthesisUtterance,
      });

    run(invokeBrowser)
      .then(value => request.settle(normalizeFallback(value, reason)))
      .catch(() => request.settle(result('text', reason)));
  }

  function settle(request, value) {
    if (request.done) return;
    request.done = true;
    clearColdTimer(request);
    clearBrowserTimer(request);
    detachAudio(request);
    revokeURL(request);
    if (active === request) active = null;
    request.resolve(result(value.mode, value.reason));
  }

  function clearColdTimer(request) {
    clearTimerOnce(request, 'coldTimer');
  }

  function clearBrowserTimer(request) {
    clearTimerOnce(request, 'browserTimer');
  }

  function clearTimerOnce(request, key) {
    if (request[key] === null) return;
    const timer = request[key];
    request[key] = null;
    safely(() => clearTimer(timer));
  }

  function stopEdge(request) {
    const audio = request.audio;
    request.audio = null;
    if (audio) {
      safely(() => audio.pause?.());
      detachAudioValue(audio);
    }
    revokeURL(request);
  }

  function stopBrowser(request) {
    if (!request.browserAborter) return;
    request.browserAborter.abort();
    for (const cancelBrowser of request.browserCancels.splice(0)) safely(cancelBrowser);
  }

  function detachAudio(request) {
    const audio = request.audio;
    request.audio = null;
    if (audio) detachAudioValue(audio);
  }

  function detachAudioValue(audio) {
    safely(() => {
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
    safely(() => revokeObjectURL(objectURL));
  }

  function edgeIsCurrent(request) {
    return active === request
      && !request.done
      && !request.fallbackStarted
      && !request.edgeAborter.signal.aborted;
  }

  return Object.freeze({ speak, cancel, dispose });
}

function defaultBrowserSpeak(text, {
  signal,
  speechSynthesis,
  SpeechSynthesisUtterance,
} = {}) {
  return new Promise(resolve => {
    let done = false;
    let utterance = null;
    const settle = value => {
      if (done) return;
      done = true;
      safely(() => signal?.removeEventListener?.('abort', cancelled));
      if (utterance) {
        utterance.onend = null;
        utterance.onerror = null;
      }
      resolve(value);
    };
    const cancelled = () => {
      safely(() => speechSynthesis?.cancel?.());
      settle(result('cancelled', 'browser-cancelled'));
    };

    if (!speechSynthesis || typeof speechSynthesis.speak !== 'function' || typeof SpeechSynthesisUtterance !== 'function') {
      settle(result('text', 'browser-unavailable'));
      return;
    }
    if (signal?.aborted) {
      cancelled();
      return;
    }

    try {
      utterance = new SpeechSynthesisUtterance(text);
      utterance.onend = () => settle(result('browser', 'ended'));
      utterance.onerror = () => settle(result('text', 'browser-error'));
      signal?.addEventListener?.('abort', cancelled);
      speechSynthesis.speak(utterance);
    } catch {
      settle(result('text', 'browser-error'));
    }
  });
}

function createAborter() {
  const listeners = new Set();
  const signal = {
    aborted: false,
    addEventListener(type, listener) {
      if (type === 'abort') listeners.add(listener);
    },
    removeEventListener(type, listener) {
      if (type === 'abort') listeners.delete(listener);
    },
  };
  return {
    signal,
    abort() {
      if (signal.aborted) return;
      signal.aborted = true;
      for (const listener of [...listeners]) safely(listener);
      listeners.clear();
    },
  };
}

function run(work) {
  return Promise.resolve().then(work);
}

function safely(work) {
  try { work(); } catch {}
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
