const SILENCE_MS = 1500;
const SCHEDULING = Symbol('speech timer scheduling');

export function createSpeechController(deps) {
  if (!deps || typeof deps !== 'object') throw new TypeError('speech dependencies must be an object');

  const Recognition = deps.Recognition;
  const onEvent = deps.onEvent;
  const setTimer = deps.setTimer === undefined ? globalThis.setTimeout : deps.setTimer;
  const clearTimer = deps.clearTimer === undefined ? globalThis.clearTimeout : deps.clearTimer;
  if (typeof onEvent !== 'function' || typeof setTimer !== 'function' || typeof clearTimer !== 'function') {
    throw new TypeError('speech dependencies require functions');
  }

  let current = null;
  let disposed = false;
  let nextGeneration = 0;
  let suppressing = false;

  function isCurrent(run) {
    return current === run && run.phase !== 'terminal' && run.generation === current.generation;
  }

  function isListeningRun(run) {
    return isCurrent(run) && run.phase === 'listening';
  }

  function emit(event) {
    try {
      onEvent(event);
    } catch {}
  }

  function start() {
    if (disposed || suppressing) return;
    if (Recognition === null || Recognition === undefined) {
      emit(errorEvent('SPEECH_UNSUPPORTED', false));
      return;
    }

    if (current?.phase === 'listening') return;
    if (current?.phase === 'stopping') {
      suppress(current);
      if (disposed || suppressing || current !== null) return;
    }

    const run = {
      finalByIndex: new Map(),
      generation: ++nextGeneration,
      interimByIndex: new Map(),
      phase: 'listening',
      recognition: null,
      timer: null,
      timerFailure: false,
    };

    let recognition;
    try {
      recognition = new Recognition();
    } catch (error) {
      emit(syncErrorEvent(error));
      return;
    }

    run.recognition = recognition;
    current = run;
    try {
      recognition.onresult = event => handleResult(run, event);
      recognition.onspeechend = () => handleSpeechEnd(run);
      recognition.onerror = event => handleError(run, event);
      recognition.onend = () => handleEnd(run);
      recognition.lang = 'zh-CN';
      recognition.interimResults = true;
      recognition.continuous = true;
      recognition.start();
    } catch (error) {
      if (isCurrent(run)) terminal(run, syncErrorEvent(error), { cleanupRecognition: false });
      return;
    }

    arm(run);
  }

  function stop(reason = 'manual') {
    if (disposed) return;
    const run = current;
    if (!run || run.phase === 'terminal') return;
    if (reason === 'superseded') {
      suppress(run);
      return;
    }
    requestStop(run);
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    if (current) suppress(current);
  }

  function isListening() {
    return current !== null && current.phase !== 'terminal';
  }

  function handleResult(run, event) {
    if (!isCurrent(run)) return;
    let text;
    try {
      updateTranscript(run, event);
      text = transcript(run);
    } catch {
      fail(run, true);
      return;
    }
    if (!isCurrent(run)) return;
    emit({ type: 'partial', text });
    if (isListeningRun(run)) arm(run);
  }

  function handleSpeechEnd(run) {
    if (isListeningRun(run)) arm(run);
  }

  function handleError(run, event) {
    if (!isCurrent(run)) return;
    let eventToEmit;
    try {
      eventToEmit = recognitionErrorEvent(event);
    } catch {
      eventToEmit = errorEvent('SPEECH_FAILED', true);
    }
    terminal(run, eventToEmit, { cleanupRecognition: false });
  }

  function handleEnd(run) {
    if (!isCurrent(run)) return;
    terminal(run, terminalTranscriptEvent(run), { cleanupRecognition: false });
  }

  function updateTranscript(run, event) {
    const results = event?.results;
    const length = results.length;
    const resultIndex = event && 'resultIndex' in Object(event) ? event.resultIndex : 0;
    if (!Number.isInteger(resultIndex) || resultIndex < 0) throw new TypeError('invalid recognition result index');

    for (const index of [...run.interimByIndex.keys()]) {
      if (index >= length || results[index] === undefined) run.interimByIndex.delete(index);
    }

    for (let index = resultIndex; index < length; index += 1) {
      const result = results[index];
      if (result === undefined || result === null) {
        run.interimByIndex.delete(index);
        continue;
      }
      const text = typeof result[0]?.transcript === 'string' ? result[0].transcript : '';
      if (result.isFinal) {
        run.finalByIndex.set(index, text);
        run.interimByIndex.delete(index);
      } else if (!run.finalByIndex.has(index)) {
        run.interimByIndex.set(index, text);
      }
    }
  }

  function transcript(run) {
    const indexes = new Set([...run.finalByIndex.keys(), ...run.interimByIndex.keys()]);
    return [...indexes]
      .sort((left, right) => left - right)
      .map(index => run.finalByIndex.has(index) ? run.finalByIndex.get(index) : run.interimByIndex.get(index))
      .join('')
      .trim();
  }

  function terminalTranscriptEvent(run) {
    const text = transcript(run);
    return text ? { type: 'final', text } : { type: 'empty' };
  }

  function recognitionErrorEvent(event) {
    const code = event?.error;
    if (code === 'no-speech') return { type: 'empty' };
    if (code === 'not-allowed' || code === 'service-not-allowed') return errorEvent('MIC_PERMISSION_DENIED', false);
    if (code === 'audio-capture') return errorEvent('MIC_UNAVAILABLE', true);
    return errorEvent('SPEECH_FAILED', true);
  }

  function syncErrorEvent(error) {
    let name;
    try {
      name = error?.name;
    } catch {
      return errorEvent('SPEECH_FAILED', true);
    }
    if (name === 'NotAllowedError' || name === 'SecurityError') return errorEvent('MIC_PERMISSION_DENIED', false);
    return errorEvent('SPEECH_FAILED', true);
  }

  function arm(run) {
    if (!isListeningRun(run)) return;
    if (!releaseTimer(run, true, true) || !isListeningRun(run)) return;

    run.timer = SCHEDULING;
    let handle;
    try {
      handle = setTimer(() => timerFired(run, handle), SILENCE_MS);
      absorbThenable(handle);
    } catch {
      if (run.timer === SCHEDULING) run.timer = null;
      if (isCurrent(run)) fail(run, true);
      return;
    }

    if (!isListeningRun(run) || run.timer !== SCHEDULING) {
      clearReturnedHandle(run, handle);
      return;
    }
    run.timer = handle;
  }

  function timerFired(run, handle) {
    if (!isCurrent(run) || (run.timer !== SCHEDULING && run.timer !== handle)) return;
    run.timer = null;
    requestStop(run);
  }

  function clearReturnedHandle(run, handle) {
    try {
      absorbThenable(clearTimer(handle));
    } catch {
      if (isCurrent(run)) fail(run, true);
    }
  }

  function requestStop(run) {
    if (!isListeningRun(run)) return;
    run.phase = 'stopping';
    const released = releaseTimer(run, true, false);
    if (!released && run.timerFailure) {
      stopRecognition(run);
      return;
    }
    if (!isCurrent(run) || run.phase !== 'stopping') return;

    stopRecognition(run);
  }

  function stopRecognition(run) {
    try {
      if (typeof run.recognition.stop !== 'function') throw new TypeError('recognition stop is unavailable');
      absorbThenable(run.recognition.stop());
    } catch {
      if (isCurrent(run)) {
        fail(run, true);
      } else if (run.timerFailure) {
        suppressing = true;
        try {
          cleanup(run);
        } finally {
          suppressing = false;
        }
      }
    }
  }

  function releaseTimer(run, reportFailure, cleanupRecognition) {
    const handle = run.timer;
    run.timer = null;
    if (handle === null || handle === SCHEDULING) return true;
    try {
      absorbThenable(clearTimer(handle));
      return true;
    } catch {
      if (reportFailure && isCurrent(run)) {
        run.timerFailure = true;
        fail(run, cleanupRecognition);
      }
      return false;
    }
  }

  function fail(run, cleanupRecognition) {
    terminal(run, errorEvent('SPEECH_FAILED', true), { cleanupRecognition });
  }

  function terminal(run, event, { cleanupRecognition }) {
    if (!isCurrent(run)) return;
    run.phase = 'terminal';
    if (current === run) current = null;
    releaseTimer(run, false, false);
    if (cleanupRecognition) {
      suppressing = true;
      try {
        cleanup(run);
      } finally {
        suppressing = false;
      }
    }
    emit(event);
  }

  function suppress(run) {
    if (!isCurrent(run)) return;
    run.phase = 'terminal';
    if (current === run) current = null;
    suppressing = true;
    try {
      releaseTimer(run, false, false);
      cleanup(run);
    } finally {
      suppressing = false;
    }
  }

  function cleanup(run) {
    const recognition = run.recognition;
    try {
      const abort = recognition.abort;
      if (typeof abort === 'function') {
        try {
          absorbThenable(abort.call(recognition));
          return;
        } catch {}
      }
    } catch {}
    try {
      const stop = recognition.stop;
      if (typeof stop === 'function') absorbThenable(stop.call(recognition));
    } catch {}
  }

  return Object.freeze({
    start,
    stop,
    dispose,
    isListening,
    get recognition() {
      return current?.recognition ?? null;
    },
  });
}

function errorEvent(code, retryable) {
  return { type: 'error', error: { code, retryable } };
}

function absorbThenable(value) {
  try {
    if (value && typeof value.then === 'function') Promise.resolve(value).catch(() => {});
  } catch {}
}
