import test from 'node:test';
import assert from 'node:assert/strict';

import { createSpeechController } from '../../../app/frontend/child/speech.mjs';

function fakeClock() {
  let now = 0;
  let next = 0;
  const timers = new Map();
  const delays = [];
  const clears = [];

  return {
    setTimer(callback, delay) {
      const id = ++next;
      delays.push(delay);
      timers.set(id, { callback, at: now + delay, id });
      return id;
    },
    clearTimer(id) {
      clears.push(id);
      timers.delete(id);
    },
    advance(milliseconds) {
      const target = now + milliseconds;
      while (true) {
        const due = [...timers.values()]
          .filter(timer => timer.at <= target)
          .sort((left, right) => left.at - right.at || left.id - right.id)[0];
        if (!due) break;
        timers.delete(due.id);
        now = due.at;
        due.callback();
      }
      now = target;
    },
    fire(id) {
      const timer = timers.get(id);
      if (!timer) return;
      timers.delete(id);
      timer.callback();
    },
    handles() {
      return [...timers.keys()];
    },
    pending() {
      return timers.size;
    },
    delays,
    clears,
  };
}

function recognitionClass(hooks = {}) {
  const instances = [];
  class FakeRecognition {
    constructor() {
      instances.push(this);
      hooks.construct?.call(this);
    }

    start() {
      this.startCount = (this.startCount ?? 0) + 1;
      return hooks.start?.call(this);
    }

    stop() {
      this.stopCount = (this.stopCount ?? 0) + 1;
      return hooks.stop?.call(this);
    }

    abort() {
      this.abortCount = (this.abortCount ?? 0) + 1;
      return hooks.abort?.call(this);
    }
  }
  return { Recognition: FakeRecognition, instances };
}

function result(text, isFinal = false) {
  const value = [{ transcript: text }];
  value.isFinal = isFinal;
  return value;
}

function errorEvent(code, retryable) {
  return { type: 'error', error: { code, retryable } };
}

test('exports only the controller factory and returns the exact frozen surface', async () => {
  const module = await import('../../../app/frontend/child/speech.mjs');
  assert.deepEqual(Object.keys(module), ['createSpeechController']);

  const clock = fakeClock();
  const { Recognition, instances } = recognitionClass();
  const events = [];
  const controller = createSpeechController({
    Recognition,
    onEvent: event => events.push(event),
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
    silenceMs: 0,
    unknownTimingOverride: 1,
  });

  assert.equal(Object.isFrozen(controller), true);
  assert.deepEqual(Object.keys(controller).sort(), [
    'dispose', 'isListening', 'recognition', 'start', 'stop',
  ]);
  assert.equal(controller.recognition, null);
  assert.equal(controller.isListening(), false);
  assert.equal(controller.start(), undefined);
  assert.equal(controller.isListening(), true);
  assert.equal(controller.recognition, instances[0]);
  assert.equal(instances[0].lang, 'zh-CN');
  assert.equal(instances[0].interimResults, true);
  assert.equal(instances[0].continuous, true);
  assert.equal(instances[0].startCount, 1);
  assert.deepEqual(clock.delays, [1500]);
  assert.equal(controller.start(), undefined);
  assert.equal(instances.length, 1);
  assert.equal(controller.stop(), undefined);
  assert.equal(controller.dispose(), undefined);
  assert.deepEqual(events, []);
});

test('validates the injected construction boundary and keeps unsupported recognition nonthrowing', () => {
  const onEvent = () => {};
  assert.throws(() => createSpeechController(), TypeError);
  assert.throws(() => createSpeechController(null), TypeError);
  assert.throws(() => createSpeechController('speech'), TypeError);
  assert.throws(() => createSpeechController({ Recognition: null, onEvent: null }), TypeError);
  assert.throws(() => createSpeechController({ Recognition: null, onEvent, setTimer: null }), TypeError);
  assert.throws(() => createSpeechController({ Recognition: null, onEvent, clearTimer: null }), TypeError);

  const events = [];
  const controller = createSpeechController({ Recognition: null, onEvent: event => events.push(event) });
  assert.equal(controller.start(), undefined);
  assert.equal(controller.stop(), undefined);
  assert.equal(controller.recognition, null);
  assert.equal(controller.isListening(), false);
  assert.deepEqual(events, [errorEvent('SPEECH_UNSUPPORTED', false)]);
});

test('uses the exact 1500 ms silence boundary and replaces one live timer on results and speech end', () => {
  const clock = fakeClock();
  const { Recognition, instances } = recognitionClass();
  const events = [];
  const controller = createSpeechController({
    Recognition,
    onEvent: event => events.push(event),
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
    silenceMs: 1,
  });
  controller.start();
  const recognition = instances[0];
  const initial = clock.handles()[0];

  clock.advance(1499);
  assert.equal(recognition.stopCount ?? 0, 0);
  clock.advance(1);
  assert.equal(recognition.stopCount, 1);
  assert.equal(clock.pending(), 0);
  recognition.onend();
  assert.deepEqual(events, [{ type: 'empty' }]);

  controller.start();
  const next = instances[1];
  const secondInitial = clock.handles()[0];
  next.onresult({ resultIndex: 0, results: [result('我喂菜', false)] });
  assert.equal(clock.pending(), 1);
  assert.equal(clock.clears.includes(secondInitial), true);
  next.onspeechend();
  assert.equal(clock.pending(), 1);
  assert.deepEqual(clock.delays, [1500, 1500, 1500, 1500]);
  next.onend();
  assert.equal(clock.pending(), 0);
});

test('assembles indexed final and interim transcripts without duplicates, spaces, or vanished interim text', () => {
  const clock = fakeClock();
  const { Recognition, instances } = recognitionClass();
  const events = [];
  const controller = createSpeechController({
    Recognition,
    onEvent: event => events.push(event),
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
  });
  controller.start();
  const recognition = instances[0];

  recognition.onresult({ resultIndex: 0, results: [result('A', false)] });
  recognition.onresult({ resultIndex: 1, results: [result('A', false), result('B', false)] });
  recognition.onresult({ resultIndex: 0, results: [result('A', true), result('B', false)] });
  recognition.onresult({ resultIndex: 1, results: [result('A', true), result('B', true)] });
  recognition.onend();
  assert.deepEqual(events, [
    { type: 'partial', text: 'A' },
    { type: 'partial', text: 'AB' },
    { type: 'partial', text: 'AB' },
    { type: 'partial', text: 'AB' },
    { type: 'final', text: 'AB' },
  ]);

  controller.start();
  const second = instances[1];
  second.onresult({ resultIndex: 0, results: [result('甲', false), result('乙', false)] });
  second.onresult({ resultIndex: 0, results: [result('甲', false)] });
  assert.deepEqual(events.slice(-2), [
    { type: 'partial', text: '甲乙' },
    { type: 'partial', text: '甲' },
  ]);
  second.onend();
  assert.equal(clock.pending(), 0);
});

test('natural final, blank final, early end, and no-speech each settle once with the approved empty semantics', () => {
  const scenarios = [
    { name: 'final', beforeEnd: recognition => recognition.onresult({ results: [result('  完成  ', true)] }), expected: { type: 'final', text: '完成' } },
    { name: 'blank final', beforeEnd: recognition => recognition.onresult({ results: [result('   ', true)] }), expected: { type: 'empty' } },
    { name: 'early end', beforeEnd: () => {}, expected: { type: 'empty' } },
    { name: 'no speech', beforeEnd: recognition => recognition.onerror({ error: 'no-speech' }), expected: { type: 'empty' } },
  ];
  for (const scenario of scenarios) {
    const clock = fakeClock();
    const { Recognition, instances } = recognitionClass();
    const events = [];
    const controller = createSpeechController({
      Recognition, onEvent: event => events.push(event), setTimer: clock.setTimer, clearTimer: clock.clearTimer,
    });
    controller.start();
    scenario.beforeEnd(instances[0]);
    instances[0].onend();
    assert.deepEqual(events.at(-1), scenario.expected, scenario.name);
    assert.equal(events.length, scenario.name === 'no speech' ? 1 : scenario.name === 'early end' ? 1 : 2, scenario.name);
    assert.equal(clock.pending(), 0, scenario.name);
    assert.equal(controller.recognition, null, scenario.name);
  }
});

test('normalizes recognition errors and suppresses the following end', () => {
  const cases = [
    ['not-allowed', 'MIC_PERMISSION_DENIED', false],
    ['service-not-allowed', 'MIC_PERMISSION_DENIED', false],
    ['audio-capture', 'MIC_UNAVAILABLE', true],
    ['network', 'SPEECH_FAILED', true],
  ];
  for (const [input, code, retryable] of cases) {
    const clock = fakeClock();
    const { Recognition, instances } = recognitionClass();
    const events = [];
    const controller = createSpeechController({
      Recognition, onEvent: event => events.push(event), setTimer: clock.setTimer, clearTimer: clock.clearTimer,
    });
    controller.start();
    instances[0].onerror({ error: input });
    instances[0].onend();
    assert.deepEqual(events, [errorEvent(code, retryable)], input);
    assert.equal(clock.pending(), 0, input);
    assert.equal(controller.recognition, null, input);
  }
});

test('maps constructor, configuration, and synchronous start failures without leaking recognition or a timer', () => {
  const permission = Object.assign(new Error('denied'), { name: 'NotAllowedError' });
  const security = Object.assign(new Error('blocked'), { name: 'SecurityError' });
  const cases = [
    { name: 'constructor permission', Recognition: class { constructor() { throw permission; } }, expected: errorEvent('MIC_PERMISSION_DENIED', false) },
    { name: 'configuration security', Recognition: class { set lang(_) { throw security; } }, expected: errorEvent('MIC_PERMISSION_DENIED', false) },
    { name: 'start generic', Recognition: class { start() { throw new Error('start'); } }, expected: errorEvent('SPEECH_FAILED', true) },
  ];
  for (const item of cases) {
    const clock = fakeClock();
    const events = [];
    const controller = createSpeechController({
      Recognition: item.Recognition, onEvent: event => events.push(event), setTimer: clock.setTimer, clearTimer: clock.clearTimer,
    });
    assert.doesNotThrow(() => controller.start(), item.name);
    assert.deepEqual(events, [item.expected], item.name);
    assert.equal(controller.recognition, null, item.name);
    assert.equal(controller.isListening(), false, item.name);
    assert.equal(clock.pending(), 0, item.name);
  }
});

test('manual stop keeps its generation for a late final, leaves no timer, and stops once', () => {
  const clock = fakeClock();
  const { Recognition, instances } = recognitionClass();
  const events = [];
  const controller = createSpeechController({
    Recognition, onEvent: event => events.push(event), setTimer: clock.setTimer, clearTimer: clock.clearTimer,
  });
  controller.start();
  const recognition = instances[0];
  controller.stop('manual');
  controller.stop('manual');
  assert.equal(recognition.stopCount, 1);
  assert.equal(controller.isListening(), true);
  assert.equal(clock.pending(), 0);
  recognition.onresult({ results: [result('晚到最终稿', true)] });
  assert.deepEqual(events, [{ type: 'partial', text: '晚到最终稿' }]);
  assert.equal(clock.pending(), 0);
  recognition.onend();
  recognition.onend();
  assert.deepEqual(events, [
    { type: 'partial', text: '晚到最终稿' },
    { type: 'final', text: '晚到最终稿' },
  ]);
  assert.equal(controller.isListening(), false);
  assert.equal(controller.recognition, null);
});

test('duplicate listening start is inert while a stopping generation is superseded and stale callbacks are ignored', () => {
  const clock = fakeClock();
  const { Recognition, instances } = recognitionClass();
  const events = [];
  const controller = createSpeechController({
    Recognition, onEvent: event => events.push(event), setTimer: clock.setTimer, clearTimer: clock.clearTimer,
  });
  controller.start();
  const old = instances[0];
  controller.start();
  assert.equal(instances.length, 1);
  controller.stop();
  controller.start();
  const fresh = instances[1];
  assert.equal(old.abortCount, 1);
  assert.equal(controller.recognition, fresh);
  old.onresult({ results: [result('过期', true)] });
  old.onerror({ error: 'network' });
  old.onend();
  assert.deepEqual(events, []);
  fresh.onend();
  assert.deepEqual(events, [{ type: 'empty' }]);
  assert.equal(controller.recognition, null);
  controller.start();
  assert.equal(controller.recognition, instances[2]);
});

test('dispose suppresses every current and late event and permanently makes public calls inert', () => {
  const clock = fakeClock();
  const { Recognition, instances } = recognitionClass();
  const events = [];
  const controller = createSpeechController({
    Recognition, onEvent: event => events.push(event), setTimer: clock.setTimer, clearTimer: clock.clearTimer,
  });
  controller.dispose();
  controller.start();
  assert.equal(instances.length, 0);

  const second = createSpeechController({
    Recognition, onEvent: event => events.push(event), setTimer: clock.setTimer, clearTimer: clock.clearTimer,
  });
  second.start();
  const recognition = instances[0];
  second.dispose();
  second.dispose();
  recognition.onresult({ results: [result('过期', true)] });
  recognition.onerror({ error: 'network' });
  recognition.onend();
  second.start();
  second.stop();
  assert.equal(recognition.abortCount, 1);
  assert.equal(second.recognition, null);
  assert.equal(second.isListening(), false);
  assert.equal(clock.pending(), 0);
  assert.deepEqual(events, []);
});

test('superseded cleanup falls back to recognition.stop when abort is unavailable', () => {
  const clock = fakeClock();
  const { Recognition, instances } = recognitionClass({ construct() { this.abort = undefined; } });
  const events = [];
  const controller = createSpeechController({
    Recognition, onEvent: event => events.push(event), setTimer: clock.setTimer, clearTimer: clock.clearTimer,
  });
  controller.start();
  controller.stop('superseded');
  instances[0].onresult({ results: [result('不可见', true)] });
  instances[0].onend();
  assert.equal(instances[0].stopCount, 1);
  assert.equal(controller.recognition, null);
  assert.equal(clock.pending(), 0);
  assert.deepEqual(events, []);
});

test('synchronous recognition callbacks and onEvent reentry cannot arm an obsolete run', () => {
  const errorClock = fakeClock();
  const errorFactory = recognitionClass({ start() { this.onerror({ error: 'audio-capture' }); } });
  const errorEvents = [];
  const errorController = createSpeechController({
    Recognition: errorFactory.Recognition, onEvent: event => errorEvents.push(event),
    setTimer: errorClock.setTimer, clearTimer: errorClock.clearTimer,
  });
  assert.doesNotThrow(() => errorController.start());
  assert.deepEqual(errorEvents, [errorEvent('MIC_UNAVAILABLE', true)]);
  assert.equal(errorClock.pending(), 0);
  assert.equal(errorController.recognition, null);

  const endClock = fakeClock();
  const endFactory = recognitionClass({ start() { this.onend(); } });
  const endEvents = [];
  const endController = createSpeechController({
    Recognition: endFactory.Recognition, onEvent: event => endEvents.push(event),
    setTimer: endClock.setTimer, clearTimer: endClock.clearTimer,
  });
  endController.start();
  assert.deepEqual(endEvents, [{ type: 'empty' }]);
  assert.equal(endClock.pending(), 0);

  const reentryClock = fakeClock();
  const reentryEvents = [];
  let reentryController;
  let reentered = false;
  const reentryFactory = recognitionClass({
    start() {
      if (!reentered) this.onerror({ error: 'network' });
    },
  });
  reentryController = createSpeechController({
    Recognition: reentryFactory.Recognition,
    onEvent: event => {
      reentryEvents.push(event);
      if (!reentered) {
        reentered = true;
        reentryController.start();
      }
    },
    setTimer: reentryClock.setTimer,
    clearTimer: reentryClock.clearTimer,
  });
  reentryController.start();
  assert.equal(reentryFactory.instances.length, 2);
  assert.equal(reentryClock.pending(), 1);
  assert.equal(reentryController.recognition, reentryFactory.instances[1]);
  assert.deepEqual(reentryEvents, [errorEvent('SPEECH_FAILED', true)]);

  const disposeClock = fakeClock();
  const disposeFactory = recognitionClass();
  let disposeController;
  disposeController = createSpeechController({
    Recognition: disposeFactory.Recognition,
    onEvent: () => disposeController.dispose(),
    setTimer: disposeClock.setTimer,
    clearTimer: disposeClock.clearTimer,
  });
  disposeController.start();
  disposeFactory.instances[0].onresult({ results: [result('局部', false)] });
  assert.equal(disposeClock.pending(), 0);
  assert.equal(disposeController.recognition, null);
});

test('a synchronously firing timer is cleared after its handle returns and does not leave ownership behind', () => {
  const { Recognition, instances } = recognitionClass({ stop() { this.onend(); } });
  const events = [];
  const clears = [];
  const controller = createSpeechController({
    Recognition,
    onEvent: event => events.push(event),
    setTimer(callback, delay) {
      assert.equal(delay, 1500);
      callback();
      return 91;
    },
    clearTimer(handle) { clears.push(handle); },
  });
  assert.doesNotThrow(() => controller.start());
  assert.equal(instances[0].stopCount, 1);
  assert.deepEqual(clears, [91]);
  assert.deepEqual(events, [{ type: 'empty' }]);
  assert.equal(controller.recognition, null);
});

test('current timer and manual-stop dependency failures emit one SPEECH_FAILED and stale callbacks stay inert', () => {
  const initialClock = fakeClock();
  const initialFactory = recognitionClass();
  const initialEvents = [];
  const initial = createSpeechController({
    Recognition: initialFactory.Recognition,
    onEvent: event => initialEvents.push(event),
    setTimer() { throw new Error('timer'); },
    clearTimer: initialClock.clearTimer,
  });
  assert.doesNotThrow(() => initial.start());
  assert.deepEqual(initialEvents, [errorEvent('SPEECH_FAILED', true)]);
  assert.equal(initial.recognition, null);

  const resultClock = fakeClock();
  const resultFactory = recognitionClass();
  const resultEvents = [];
  let sets = 0;
  const rearm = createSpeechController({
    Recognition: resultFactory.Recognition,
    onEvent: event => resultEvents.push(event),
    setTimer(callback, delay) {
      sets += 1;
      if (sets > 1) throw new Error('rearm');
      return resultClock.setTimer(callback, delay);
    },
    clearTimer: resultClock.clearTimer,
  });
  rearm.start();
  const lateInitialTimer = resultClock.handles()[0];
  assert.doesNotThrow(() => resultFactory.instances[0].onresult({ results: [result('内容', false)] }));
  assert.deepEqual(resultEvents, [
    { type: 'partial', text: '内容' },
    errorEvent('SPEECH_FAILED', true),
  ]);
  assert.equal(rearm.recognition, null);
  resultClock.fire(lateInitialTimer);
  assert.equal(resultFactory.instances[0].stopCount ?? 0, 0);

  const clearFactory = recognitionClass();
  const clearEvents = [];
  let throwClear = false;
  const clearFailure = createSpeechController({
    Recognition: clearFactory.Recognition,
    onEvent: event => clearEvents.push(event),
    setTimer: () => 11,
    clearTimer() { if (throwClear) throw new Error('clear'); },
  });
  clearFailure.start();
  throwClear = true;
  assert.doesNotThrow(() => clearFactory.instances[0].onresult({ results: [result('重置', false)] }));
  assert.deepEqual(clearEvents, [
    { type: 'partial', text: '重置' },
    errorEvent('SPEECH_FAILED', true),
  ]);

  const manualClearFactory = recognitionClass();
  const manualClearEvents = [];
  const manualClear = createSpeechController({
    Recognition: manualClearFactory.Recognition,
    onEvent: event => manualClearEvents.push(event),
    setTimer: () => 12,
    clearTimer() { throw new Error('manual clear'); },
  });
  manualClear.start();
  assert.doesNotThrow(() => manualClear.stop());
  assert.equal(manualClearFactory.instances[0].stopCount, 1);
  assert.deepEqual(manualClearEvents, [errorEvent('SPEECH_FAILED', true)]);
  assert.equal(manualClear.recognition, null);

  const stopClock = fakeClock();
  const stopFactory = recognitionClass({ stop() { throw new Error('stop'); } });
  const stopEvents = [];
  const stopFailure = createSpeechController({
    Recognition: stopFactory.Recognition,
    onEvent: event => stopEvents.push(event), setTimer: stopClock.setTimer, clearTimer: stopClock.clearTimer,
  });
  stopFailure.start();
  assert.doesNotThrow(() => stopFailure.stop());
  assert.deepEqual(stopEvents, [errorEvent('SPEECH_FAILED', true)]);
  assert.equal(stopFailure.recognition, null);
  assert.equal(stopClock.pending(), 0);

  const silenceClock = fakeClock();
  const silenceFactory = recognitionClass({ stop() { throw new Error('silence stop'); } });
  const silenceEvents = [];
  const silenceFailure = createSpeechController({
    Recognition: silenceFactory.Recognition,
    onEvent: event => silenceEvents.push(event), setTimer: silenceClock.setTimer, clearTimer: silenceClock.clearTimer,
  });
  silenceFailure.start();
  assert.doesNotThrow(() => silenceClock.advance(1500));
  assert.equal(silenceFactory.instances[0].stopCount, 1);
  assert.deepEqual(silenceEvents, [errorEvent('SPEECH_FAILED', true)]);
  assert.equal(silenceFailure.recognition, null);
  assert.equal(silenceClock.pending(), 0);
});

test('suppressed cleanup failures during supersede, dispose, error, and natural end never add SPEECH_FAILED', () => {
  const supersedeClock = fakeClock();
  const supersedeEvents = [];
  let supersede;
  const supersedeFactory = recognitionClass({
    abort() {
      this.onresult({ results: [result('过期清理', true)] });
      this.onerror({ error: 'network' });
      this.onend();
      supersede.start();
      throw new Error('abort');
    },
  });
  supersede = createSpeechController({
    Recognition: supersedeFactory.Recognition,
    onEvent: event => supersedeEvents.push(event), setTimer: supersedeClock.setTimer, clearTimer: supersedeClock.clearTimer,
  });
  supersede.start();
  supersede.stop();
  supersede.start();
  assert.deepEqual(supersedeEvents, []);
  assert.equal(supersedeFactory.instances.length, 2);
  assert.equal(supersedeFactory.instances[0].abortCount, 1);
  assert.equal(supersede.recognition, supersedeFactory.instances[1]);

  const disposeClock = fakeClock();
  const disposeFactory = recognitionClass({ abort() { throw new Error('abort'); } });
  const disposeEvents = [];
  const dispose = createSpeechController({
    Recognition: disposeFactory.Recognition,
    onEvent: event => disposeEvents.push(event), setTimer: disposeClock.setTimer,
    clearTimer() { throw new Error('clear'); },
  });
  dispose.start();
  dispose.dispose();
  assert.deepEqual(disposeEvents, []);

  const terminalClock = fakeClock();
  const terminalFactory = recognitionClass();
  const terminalEvents = [];
  const terminal = createSpeechController({
    Recognition: terminalFactory.Recognition,
    onEvent: event => terminalEvents.push(event), setTimer: terminalClock.setTimer,
    clearTimer() { throw new Error('clear'); },
  });
  terminal.start();
  terminalFactory.instances[0].onerror({ error: 'network' });
  assert.deepEqual(terminalEvents, [errorEvent('SPEECH_FAILED', true)]);

  const endFactory = recognitionClass();
  const endEvents = [];
  const naturalEnd = createSpeechController({
    Recognition: endFactory.Recognition,
    onEvent: event => endEvents.push(event), setTimer: () => 3,
    clearTimer() { throw new Error('clear'); },
  });
  naturalEnd.start();
  endFactory.instances[0].onend();
  assert.deepEqual(endEvents, [{ type: 'empty' }]);
});

test('an onEvent exception is contained without terminating a listening partial run', () => {
  const clock = fakeClock();
  const { Recognition, instances } = recognitionClass();
  const controller = createSpeechController({
    Recognition,
    onEvent() { throw new Error('observer'); },
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
  });
  controller.start();
  assert.doesNotThrow(() => instances[0].onresult({ results: [result('仍在听', false)] }));
  assert.equal(controller.isListening(), true);
  assert.equal(clock.pending(), 1);
  assert.doesNotThrow(() => instances[0].onend());
  assert.equal(controller.isListening(), false);
  assert.equal(clock.pending(), 0);
});
