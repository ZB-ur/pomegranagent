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
  let cleanupThenables = 0;

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
    if (disposed || suppressing || cleanupThenables !== 0) return;
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
      cleanupStarted: false,
      cleanupFallbackStarted: false,
      stopAttempted: false,
    };
    current = run;

    let recognition;
    try {
      recognition = new Recognition();
    } catch (error) {
      if (isCurrent(run)) terminal(run, syncErrorEvent(error), { cleanupRecognition: false });
      return;
    }

    run.recognition = recognition;
    if (!isListeningRun(run)) {
      cleanupWithSuppression(run, false);
      return;
    }
    if (!assignRecognition(run, 'onresult', event => handleResult(run, event))) return;
    if (!assignRecognition(run, 'onspeechend', () => handleSpeechEnd(run))) return;
    if (!assignRecognition(run, 'onerror', event => handleError(run, event))) return;
    if (!assignRecognition(run, 'onend', () => handleEnd(run))) return;
    if (!assignRecognition(run, 'lang', 'zh-CN')) return;
    if (!assignRecognition(run, 'interimResults', true)) return;
    if (!assignRecognition(run, 'continuous', true)) return;
    if (!startRecognition(run)) return;
    if (isListeningRun(run)) arm(run);
  }

  function assignRecognition(run, property, value) {
    if (!isListeningRun(run)) return false;
    try {
      run.recognition[property] = value;
    } catch (error) {
      if (isCurrent(run)) terminal(run, syncErrorEvent(error), { cleanupRecognition: false });
      return false;
    }
    return isListeningRun(run);
  }

  function startRecognition(run) {
    let startMethod;
    try {
      startMethod = run.recognition.start;
    } catch (error) {
      if (isCurrent(run)) terminal(run, syncErrorEvent(error), { cleanupRecognition: false });
      return false;
    }
    if (!isListeningRun(run)) return false;
    if (typeof startMethod !== 'function') {
      terminal(run, errorEvent('SPEECH_FAILED', true), { cleanupRecognition: false });
      return false;
    }
    try {
      consumeThenable(startMethod.call(run.recognition), {
        onRejected(error) {
          if (isCurrent(run)) terminal(run, syncErrorEvent(error), { cleanupRecognition: false });
        },
      });
    } catch (error) {
      if (isCurrent(run)) terminal(run, syncErrorEvent(error), { cleanupRecognition: false });
      return false;
    }
    return isListeningRun(run);
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
      consumeThenable(handle, {
        onRejected() {
          if (isCurrent(run)) fail(run, true);
        },
      });
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
      consumeThenable(clearTimer(handle), {
        onRejected() {
          if (isCurrent(run)) fail(run, true);
        },
      });
    } catch {
      if (isCurrent(run)) fail(run, true);
    }
  }

  function requestStop(run) {
    if (!isListeningRun(run)) return;
    run.phase = 'stopping';
    const released = releaseTimer(run, true, false);
    if (!released && run.timerFailure) {
      stopRecognition(run, true);
      return;
    }
    if (!isCurrent(run) || run.phase !== 'stopping') return;

    stopRecognition(run, false);
  }

  function stopRecognition(run, terminalCleanup) {
    if (terminalCleanup) {
      const previous = suppressing;
      suppressing = true;
      try {
        stopRecognitionAtBoundary(run, true);
      } finally {
        suppressing = previous;
      }
      return;
    }
    stopRecognitionAtBoundary(run, false);
  }

  function stopRecognitionAtBoundary(run, terminalCleanup) {
    const recognition = run.recognition;
    let stopMethod;
    try {
      stopMethod = recognition.stop;
    } catch (error) {
      handleStopFailure(run, terminalCleanup);
      return;
    }
    if (!terminalCleanup && (!isCurrent(run) || run.phase !== 'stopping')) return;
    if (typeof stopMethod !== 'function') {
      handleStopFailure(run, terminalCleanup);
      return;
    }
    run.stopAttempted = true;
    try {
      consumeThenable(stopMethod.call(recognition), {
        onRejected() {
          handleStopFailure(run, terminalCleanup);
        },
      });
    } catch (error) {
      handleStopFailure(run, terminalCleanup);
    }
  }

  function handleStopFailure(run, terminalCleanup) {
    if (isCurrent(run)) {
      fail(run, true, run.stopAttempted);
    } else if (terminalCleanup && run.timerFailure) {
      cleanupWithSuppression(run, run.stopAttempted);
    }
  }

  function releaseTimer(run, reportFailure, cleanupRecognition) {
    const handle = run.timer;
    run.timer = null;
    if (handle === null || handle === SCHEDULING) return true;
    try {
      let rejected = false;
      consumeThenable(clearTimer(handle), {
        onRejected() {
          rejected = true;
          timerFailure(run, reportFailure, cleanupRecognition);
        },
      });
      return !rejected;
    } catch {
      timerFailure(run, reportFailure, cleanupRecognition);
      return false;
    }
  }

  function timerFailure(run, reportFailure, cleanupRecognition) {
    if (reportFailure && isCurrent(run)) {
      run.timerFailure = true;
      fail(run, cleanupRecognition);
    }
  }

  function fail(run, cleanupRecognition, stopAlreadyAttempted = false) {
    terminal(run, errorEvent('SPEECH_FAILED', true), { cleanupRecognition, stopAlreadyAttempted });
  }

  function terminal(run, event, { cleanupRecognition, stopAlreadyAttempted = false }) {
    if (!isCurrent(run)) return;
    run.phase = 'terminal';
    if (current === run) current = null;
    const previous = suppressing;
    suppressing = true;
    try {
      releaseTimer(run, false, false);
      if (cleanupRecognition) cleanup(run, stopAlreadyAttempted);
    } finally {
      suppressing = previous;
    }
    emit(event);
  }

  function suppress(run) {
    if (!isCurrent(run)) return;
    run.phase = 'terminal';
    if (current === run) current = null;
    const previous = suppressing;
    suppressing = true;
    try {
      releaseTimer(run, false, false);
      cleanup(run, false);
    } finally {
      suppressing = previous;
    }
  }

  function cleanupWithSuppression(run, stopAlreadyAttempted) {
    const previous = suppressing;
    suppressing = true;
    try {
      cleanup(run, stopAlreadyAttempted);
    } finally {
      suppressing = previous;
    }
  }

  function cleanup(run, stopAlreadyAttempted) {
    if (run.cleanupStarted) return;
    const recognition = run.recognition;
    if (recognition === null) return;
    run.cleanupStarted = true;
    let abort;
    try {
      abort = recognition.abort;
    } catch {
      cleanupFallbackStop(run, stopAlreadyAttempted);
      return;
    }
    if (typeof abort !== 'function') {
      cleanupFallbackStop(run, stopAlreadyAttempted);
      return;
    }
    try {
      consumeThenable(abort.call(recognition), {
        keepCleanupFence: true,
        onRejected() {
          cleanupFallbackStopWithSuppression(run, stopAlreadyAttempted);
        },
      });
    } catch {
      cleanupFallbackStop(run, stopAlreadyAttempted);
    }
  }

  function cleanupFallbackStopWithSuppression(run, stopAlreadyAttempted) {
    const previous = suppressing;
    suppressing = true;
    try {
      cleanupFallbackStop(run, stopAlreadyAttempted);
    } finally {
      suppressing = previous;
    }
  }

  function cleanupFallbackStop(run, stopAlreadyAttempted) {
    if (stopAlreadyAttempted || run.cleanupFallbackStarted) return;
    run.cleanupFallbackStarted = true;
    const recognition = run.recognition;
    let stop;
    try {
      stop = recognition.stop;
    } catch {
      return;
    }
    if (typeof stop !== 'function') return;
    try {
      consumeThenable(stop.call(recognition), { keepCleanupFence: true });
    } catch {}
  }

  function consumeThenable(value, { keepCleanupFence = false, onRejected = () => {} } = {}) {
    if (!value || (typeof value !== 'object' && typeof value !== 'function')) return;
    let fenceOpen = false;
    let fenceReleaseScheduled = false;
    const closeFence = () => {
      if (!fenceOpen) return;
      fenceOpen = false;
      cleanupThenables -= 1;
    };
    const releaseFenceSoon = () => {
      if (!fenceOpen || fenceReleaseScheduled) return;
      fenceReleaseScheduled = true;
      try {
        Promise.resolve().then(closeFence).catch(closeFence);
      } catch {
        closeFence();
      }
    };
    if (keepCleanupFence) {
      fenceOpen = true;
      cleanupThenables += 1;
    }
    let then;
    try {
      then = value.then;
    } catch (error) {
      try {
        onRejected(error);
      } catch {}
      releaseFenceSoon();
      return;
    }
    if (typeof then !== 'function') {
      releaseFenceSoon();
      return;
    }
    let settled = false;
    const settle = (rejected, error) => {
      if (settled) return;
      settled = true;
      try {
        if (rejected) onRejected(error);
      } catch {}
    };
    try {
      then.call(value, () => settle(false), error => settle(true, error));
    } catch (error) {
      settle(true, error);
    }
    releaseFenceSoon();
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
