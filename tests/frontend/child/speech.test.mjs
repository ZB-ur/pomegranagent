import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

import { createSpeechController } from '../../../app/frontend/child/speech.mjs';

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

async function settleMicrotasks() {
  for (let turn = 0; turn < 6; turn += 1) await Promise.resolve();
}

test('exports only the controller factory and returns the exact frozen surface', async () => {
  const module = await import('../../../app/frontend/child/speech.mjs');
  assert.deepEqual(Object.keys(module), ['createSpeechController']);
  const { Recognition, instances } = recognitionClass();
  const events = [];
  const controller = createSpeechController({
    Recognition,
    onEvent: event => events.push(event),
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
  assert.equal(controller.start(), undefined);
  assert.equal(instances.length, 1);
  assert.equal(controller.stop(), undefined);
  assert.equal(controller.isListening(), true);
  assert.equal(controller.dispose(), undefined);
  assert.deepEqual(events, []);
});

test('validates the injected construction boundary and keeps unsupported recognition nonthrowing', () => {
  const onEvent = () => {};
  assert.throws(() => createSpeechController(), TypeError);
  assert.throws(() => createSpeechController(null), TypeError);
  assert.throws(() => createSpeechController('speech'), TypeError);
  assert.throws(() => createSpeechController({ Recognition: null, onEvent: null }), TypeError);

  const events = [];
  const controller = createSpeechController({ Recognition: null, onEvent: event => events.push(event) });
  assert.equal(controller.start(), undefined);
  assert.equal(controller.stop(), undefined);
  assert.equal(controller.recognition, null);
  assert.equal(controller.isListening(), false);
  assert.deepEqual(events, [errorEvent('SPEECH_UNSUPPORTED', false)]);
});

test('explicit stop stays pending without an onend and only onend settles the transcript', async () => {
  const { Recognition, instances } = recognitionClass();
  const events = [];
  const controller = createSpeechController({
    Recognition,
    onEvent: event => events.push(event),
  });
  controller.start();
  const recognition = instances[0];
  assert.deepEqual(events, []);

  recognition.onresult({ resultIndex: 0, results: [result('我喂菜', false)] });
  controller.stop();
  assert.equal(recognition.stopCount, 1);
  await settleMicrotasks();
  assert.equal(controller.isListening(), true);
  assert.deepEqual(events, [{ type: 'partial', text: '我喂菜' }]);
  recognition.onend();
  assert.deepEqual(events, [
    { type: 'partial', text: '我喂菜' },
    { type: 'final', text: '我喂菜' },
  ]);
});

test('assembles indexed final and interim transcripts without duplicates, spaces, or vanished interim text', () => {
  const { Recognition, instances } = recognitionClass();
  const events = [];
  const controller = createSpeechController({
    Recognition,
    onEvent: event => events.push(event),
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
  ]);
  assert.equal(recognition.startCount, 2);
  assert.equal(controller.isListening(), true);
  recognition.onresult({ resultIndex: 0, results: [result('C', true)] });
  assert.deepEqual(events.at(-1), { type: 'partial', text: 'ABC' });
  controller.stop();
  assert.deepEqual(events.at(-1), { type: 'partial', text: 'ABC' });
  recognition.onend();
  assert.deepEqual(events.at(-1), { type: 'final', text: 'ABC' });

  controller.start();
  const second = instances[1];
  second.onresult({ resultIndex: 0, results: [result('甲', false), result('乙', false)] });
  second.onresult({ resultIndex: 0, results: [result('甲', false)] });
  assert.deepEqual(events.slice(-2), [
    { type: 'partial', text: '甲乙' },
    { type: 'partial', text: '甲' },
  ]);
  second.onend();
  assert.deepEqual(events.at(-1), { type: 'partial', text: '甲' });
  assert.equal(second.startCount, 2);
  assert.equal(controller.isListening(), true);
  second.onresult({ resultIndex: 0, results: [result('丙', false)] });
  assert.deepEqual(events.at(-1), { type: 'partial', text: '甲丙' });
  controller.stop();
  second.onend();
  assert.deepEqual(events.at(-1), { type: 'final', text: '甲丙' });
});

test('natural end and no-speech restart the recognizer and only explicit stop settles the accumulated transcript', () => {
  const scenarios = [
    {
      name: 'final segments',
      beforeEnd: recognition => recognition.onresult({ results: [result('  完成  ', true)] }),
      afterRestart: recognition => recognition.onresult({ results: [result('继续', false)] }),
      expectedEvents: [
        { type: 'partial', text: '完成' },
        { type: 'partial', text: '完成继续' },
        { type: 'final', text: '完成继续' },
      ],
    },
    {
      name: 'blank final',
      beforeEnd: recognition => recognition.onresult({ results: [result('   ', true)] }),
      afterRestart: () => {},
      expectedEvents: [{ type: 'partial', text: '' }, { type: 'empty' }],
    },
    {
      name: 'early end',
      beforeEnd: () => {},
      afterRestart: () => {},
      expectedEvents: [{ type: 'empty' }],
    },
    {
      name: 'no speech',
      beforeEnd: recognition => recognition.onerror({ error: 'no-speech' }),
      afterRestart: recognition => recognition.onresult({ results: [result('补充', false)] }),
      expectedEvents: [{ type: 'partial', text: '补充' }, { type: 'final', text: '补充' }],
    },
  ];
  for (const scenario of scenarios) {
    const { Recognition, instances } = recognitionClass();
    const events = [];
    const controller = createSpeechController({
      Recognition, onEvent: event => events.push(event),
    });
    controller.start();
    const recognition = instances[0];
    scenario.beforeEnd(recognition);
    recognition.onend();
    assert.equal(controller.recognition, recognition, scenario.name);
    assert.equal(recognition.startCount, 2, scenario.name);
    assert.equal(controller.isListening(), true, scenario.name);
    assert.equal(events.some(event => event.type === 'final' || event.type === 'empty'), false, scenario.name);
    scenario.afterRestart(recognition);
    controller.stop();
    assert.equal(recognition.stopCount, 1, scenario.name);
    assert.equal(events.some(event => event.type === 'final' || event.type === 'empty'), false, scenario.name);
    recognition.onend();
    assert.deepEqual(events, scenario.expectedEvents, scenario.name);
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
    const { Recognition, instances } = recognitionClass();
    const events = [];
    const controller = createSpeechController({
      Recognition, onEvent: event => events.push(event),
    });
    controller.start();
    instances[0].onerror({ error: input });
    instances[0].onend();
    assert.deepEqual(events, [errorEvent(code, retryable)], input);
    assert.equal(controller.recognition, null, input);
  }
});

test('maps constructor, configuration, and synchronous start failures without leaking recognition', () => {
  const permission = Object.assign(new Error('denied'), { name: 'NotAllowedError' });
  const security = Object.assign(new Error('blocked'), { name: 'SecurityError' });
  const cases = [
    { name: 'constructor permission', Recognition: class { constructor() { throw permission; } }, expected: errorEvent('MIC_PERMISSION_DENIED', false) },
    { name: 'configuration security', Recognition: class { set lang(_) { throw security; } }, expected: errorEvent('MIC_PERMISSION_DENIED', false) },
    { name: 'start generic', Recognition: class { start() { throw new Error('start'); } }, expected: errorEvent('SPEECH_FAILED', true) },
  ];
  for (const item of cases) {
    const events = [];
    const controller = createSpeechController({
      Recognition: item.Recognition, onEvent: event => events.push(event),
    });
    assert.doesNotThrow(() => controller.start(), item.name);
    assert.deepEqual(events, [item.expected], item.name);
    assert.equal(controller.recognition, null, item.name);
    assert.equal(controller.isListening(), false, item.name);
  }
});

test('manual stop keeps its generation for a late final and settles once on end', () => {
  const { Recognition, instances } = recognitionClass();
  const events = [];
  const controller = createSpeechController({
    Recognition, onEvent: event => events.push(event),
  });
  controller.start();
  const recognition = instances[0];
  controller.stop('manual');
  controller.stop('manual');
  assert.equal(recognition.stopCount, 1);
  assert.equal(controller.isListening(), true);
  recognition.onresult({ results: [result('晚到最终稿', true)] });
  assert.deepEqual(events, [{ type: 'partial', text: '晚到最终稿' }]);
  recognition.onend();
  recognition.onend();
  assert.deepEqual(events, [
    { type: 'partial', text: '晚到最终稿' },
    { type: 'final', text: '晚到最终稿' },
  ]);
  assert.equal(controller.isListening(), false);
  assert.equal(controller.recognition, null);
});

test('manual stop without recognition end remains pending indefinitely without emitting', async () => {
  const { Recognition, instances } = recognitionClass();
  const events = [];
  const controller = createSpeechController({
    Recognition, onEvent: event => events.push(event),
  });
  controller.start();
  controller.stop();
  assert.equal(instances[0].stopCount, 1);
  assert.equal(controller.isListening(), true);
  await settleMicrotasks();
  await settleMicrotasks();
  assert.deepEqual(events, []);
  assert.equal(instances[0].abortCount ?? 0, 0);
  assert.equal(controller.recognition, instances[0]);
  assert.equal(controller.isListening(), true);
});

test('manual stop after no-speech waits for native end', () => {
  const { Recognition, instances } = recognitionClass();
  const events = [];
  const controller = createSpeechController({
    Recognition, onEvent: event => events.push(event),
  });

  controller.start();
  const recognition = instances[0];
  recognition.onerror({ error: 'no-speech' });
  controller.stop();

  assert.equal(recognition.stopCount ?? 0, 0);
  assert.equal(controller.isListening(), true);
  assert.deepEqual(events, []);

  recognition.onend();
  assert.deepEqual(events, [{ type: 'empty' }]);
  assert.equal(controller.isListening(), false);
  assert.equal(controller.recognition, null);
});

test('no-speech after manual stop preserves text captured before a natural restart', () => {
  const { Recognition, instances } = recognitionClass();
  const events = [];
  const controller = createSpeechController({
    Recognition, onEvent: event => events.push(event),
  });

  controller.start();
  const recognition = instances[0];
  recognition.onresult({ results: [result('前半句话', true)] });
  recognition.onend();
  assert.equal(recognition.startCount, 2);

  controller.stop();
  recognition.onerror({ error: 'no-speech' });
  assert.deepEqual(events, [{ type: 'partial', text: '前半句话' }]);

  recognition.onend();
  assert.deepEqual(events.at(-1), { type: 'final', text: '前半句话' });
  assert.equal(controller.isListening(), false);
});

test('duplicate listening start is inert while a stopping generation is superseded and stale callbacks are ignored', () => {
  const { Recognition, instances } = recognitionClass();
  const events = [];
  const controller = createSpeechController({
    Recognition, onEvent: event => events.push(event),
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
  assert.deepEqual(events, []);
  assert.equal(controller.recognition, fresh);
  assert.equal(fresh.startCount, 2);
  controller.stop();
  assert.deepEqual(events, []);
  fresh.onend();
  assert.deepEqual(events, [{ type: 'empty' }]);
  assert.equal(controller.recognition, null);
  controller.start();
  assert.equal(controller.recognition, instances[2]);
});

test('dispose suppresses every current and late event and permanently makes public calls inert', () => {
  const { Recognition, instances } = recognitionClass();
  const events = [];
  const controller = createSpeechController({
    Recognition, onEvent: event => events.push(event),
  });
  controller.dispose();
  controller.start();
  assert.equal(instances.length, 0);

  const second = createSpeechController({
    Recognition, onEvent: event => events.push(event),
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
  assert.deepEqual(events, []);
});

test('superseded cleanup falls back to recognition.stop when abort is unavailable', () => {
  const { Recognition, instances } = recognitionClass({ construct() { this.abort = undefined; } });
  const events = [];
  const controller = createSpeechController({
    Recognition, onEvent: event => events.push(event),
  });
  controller.start();
  controller.stop('superseded');
  instances[0].onresult({ results: [result('不可见', true)] });
  instances[0].onend();
  assert.equal(instances[0].stopCount, 1);
  assert.equal(controller.recognition, null);
  assert.deepEqual(events, []);
});

test('synchronous recognition callbacks and onEvent reentry cannot arm an obsolete run', async () => {
  const errorFactory = recognitionClass({ start() { this.onerror({ error: 'audio-capture' }); } });
  const errorEvents = [];
  const errorController = createSpeechController({
    Recognition: errorFactory.Recognition, onEvent: event => errorEvents.push(event),
  });
  assert.doesNotThrow(() => errorController.start());
  assert.deepEqual(errorEvents, [errorEvent('MIC_UNAVAILABLE', true)]);
  assert.equal(errorController.recognition, null);
  const endFactory = recognitionClass({
    start() {
      if (this.startCount === 1) this.onend();
    },
  });
  const endEvents = [];
  const endController = createSpeechController({
    Recognition: endFactory.Recognition, onEvent: event => endEvents.push(event),
  });
  endController.start();
  assert.deepEqual(endEvents, []);
  assert.equal(endController.isListening(), true);
  await settleMicrotasks();
  assert.equal(endFactory.instances[0].startCount, 2);
  assert.deepEqual(endEvents, []);
  assert.equal(endController.recognition, endFactory.instances[0]);

  const stuckFactory = recognitionClass({ start() { this.onend(); } });
  const stuckEvents = [];
  const stuckController = createSpeechController({
    Recognition: stuckFactory.Recognition,
    onEvent: event => stuckEvents.push(event),
  });
  stuckController.start();
  assert.deepEqual(stuckEvents, []);
  assert.equal(stuckController.isListening(), true);
  await settleMicrotasks();
  assert.deepEqual(stuckEvents, [errorEvent('SPEECH_FAILED', true)]);
  assert.equal(stuckController.isListening(), false);
  assert.equal(stuckController.recognition, null);
  assert.equal(stuckFactory.instances[0].abortCount, 1);
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
  });
  reentryController.start();
  assert.equal(reentryFactory.instances.length, 2);
  assert.equal(reentryController.recognition, reentryFactory.instances[1]);
  assert.deepEqual(reentryEvents, [errorEvent('SPEECH_FAILED', true)]);
  const disposeFactory = recognitionClass();
  let disposeController;
  disposeController = createSpeechController({
    Recognition: disposeFactory.Recognition,
    onEvent: () => disposeController.dispose(),
  });
  disposeController.start();
  disposeFactory.instances[0].onresult({ results: [result('局部', false)] });
  assert.equal(disposeController.recognition, null);
});

test('recognition-stop dependency failures emit once and stale callbacks stay inert', () => {
  const stopFactory = recognitionClass({ stop() { throw new Error('stop'); } });
  const stopEvents = [];
  const stopFailure = createSpeechController({
    Recognition: stopFactory.Recognition,
    onEvent: event => stopEvents.push(event),
  });
  stopFailure.start();
  assert.doesNotThrow(() => stopFailure.stop());
  assert.deepEqual(stopEvents, [errorEvent('SPEECH_FAILED', true)]);
  assert.equal(stopFailure.recognition, null);
});

test('suppressed cleanup failures during supersede, dispose, error, and natural end never add SPEECH_FAILED', () => {
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
    onEvent: event => supersedeEvents.push(event),
  });
  supersede.start();
  supersede.stop();
  supersede.start();
  assert.deepEqual(supersedeEvents, []);
  assert.equal(supersedeFactory.instances.length, 2);
  assert.equal(supersedeFactory.instances[0].abortCount, 1);
  assert.equal(supersede.recognition, supersedeFactory.instances[1]);
  const disposeFactory = recognitionClass({ abort() { throw new Error('abort'); } });
  const disposeEvents = [];
  const dispose = createSpeechController({
    Recognition: disposeFactory.Recognition,
    onEvent: event => disposeEvents.push(event),
  });
  dispose.start();
  dispose.dispose();
  assert.deepEqual(disposeEvents, []);
  const terminalFactory = recognitionClass();
  const terminalEvents = [];
  const terminal = createSpeechController({
    Recognition: terminalFactory.Recognition,
    onEvent: event => terminalEvents.push(event),
  });
  terminal.start();
  terminalFactory.instances[0].onerror({ error: 'network' });
  assert.deepEqual(terminalEvents, [errorEvent('SPEECH_FAILED', true)]);

  const endFactory = recognitionClass();
  const endEvents = [];
  const naturalEnd = createSpeechController({
    Recognition: endFactory.Recognition,
    onEvent: event => endEvents.push(event),
  });
  naturalEnd.start();
  endFactory.instances[0].onend();
  assert.deepEqual(endEvents, []);
  assert.equal(naturalEnd.isListening(), true);
  assert.equal(endFactory.instances[0].startCount, 2);
  naturalEnd.stop();
  endFactory.instances[0].onend();
  assert.deepEqual(endEvents, [{ type: 'empty' }]);
});

test('an onEvent exception is contained without terminating a listening partial run', () => {
  const { Recognition, instances } = recognitionClass();
  const controller = createSpeechController({
    Recognition,
    onEvent() { throw new Error('observer'); },
  });
  controller.start();
  assert.doesNotThrow(() => instances[0].onresult({ results: [result('仍在听', false)] }));
  assert.equal(controller.isListening(), true);
  assert.doesNotThrow(() => instances[0].onend());
  assert.equal(controller.isListening(), true);
  assert.equal(instances[0].startCount, 2);
  assert.doesNotThrow(() => controller.stop());
  assert.equal(controller.isListening(), true);
  assert.doesNotThrow(() => instances[0].onend());
  assert.equal(controller.isListening(), false);
});

test('supersede abort disposal leaves the controller permanently terminal without a replacement run', () => {
  const events = [];
  let controller;
  const { Recognition, instances } = recognitionClass({
    abort() { controller.dispose(); },
  });
  controller = createSpeechController({
    Recognition, onEvent: event => events.push(event),
  });
  controller.start();
  controller.stop();
  controller.start();

  assert.equal(instances.length, 1);
  assert.equal(instances[0].abortCount, 1);
  assert.equal(controller.recognition, null);
  assert.equal(controller.isListening(), false);
  assert.deepEqual(events, []);
  controller.start();
  assert.equal(instances.length, 1);
});

test('throwing name accessors in constructor, configuration, and start failures never escape start', () => {
  const trappedError = () => Object.defineProperty({}, 'name', {
    get() { throw new Error('name trap'); },
  });
  const cases = [
    { name: 'constructor', Recognition: class { constructor() { throw trappedError(); } } },
    { name: 'configuration', Recognition: class { set lang(_) { throw trappedError(); } } },
    { name: 'start', Recognition: class { start() { throw trappedError(); } } },
  ];
  for (const item of cases) {
    const events = [];
    const controller = createSpeechController({
      Recognition: item.Recognition,
      onEvent: event => events.push(event),
    });
    assert.doesNotThrow(() => controller.start(), item.name);
    assert.deepEqual(events, [errorEvent('SPEECH_FAILED', true)], item.name);
    assert.equal(controller.recognition, null, item.name);
    assert.equal(controller.isListening(), false, item.name);
  }
});

test('manual stop failures abort best-effort without a second terminal event', () => {
  const calls = [];
  const events = [];
  const { Recognition } = recognitionClass({
    abort() { calls.push('abort'); throw new Error('abort failure'); },
    stop() { calls.push('stop'); throw new Error('stop failure'); },
  });
  const controller = createSpeechController({
    Recognition, onEvent: event => events.push(event),
  });
  controller.start();
  controller.stop();
  assert.deepEqual(calls, ['stop', 'abort']);
  assert.deepEqual(events, [errorEvent('SPEECH_FAILED', true)]);
  assert.equal(controller.recognition, null);
  const cleanupCalls = [];
  const cleanupEvents = [];
  const { Recognition: CleanupRecognition } = recognitionClass({
    abort() { cleanupCalls.push('abort'); },
    stop() { cleanupCalls.push('stop'); throw new Error('stop failure'); },
  });
  const cleanupController = createSpeechController({
    Recognition: CleanupRecognition,
    onEvent: event => cleanupEvents.push(event),
  });
  cleanupController.start();
  cleanupController.stop();
  assert.deepEqual(cleanupCalls, ['stop', 'abort']);
  assert.deepEqual(cleanupEvents, [errorEvent('SPEECH_FAILED', true)]);
  assert.equal(cleanupController.recognition, null);
});

test('constructor and every recognition configuration setter stop invalidated generations before later setup', () => {
  const properties = ['lang', 'interimResults', 'continuous'];

  function makeScenario(trigger) {
    const events = [];
    const instances = [];
    let controller;
    class Recognition {
      constructor() {
        instances.push(this);
        if (trigger === 'constructor-dispose') controller.dispose();
      }

      set lang(value) {
        this.writes = [...(this.writes ?? []), ['lang', value]];
        if (trigger === 'lang-dispose') controller.dispose();
        if (trigger === 'lang-replace' && instances[0] === this) replace();
      }

      set interimResults(value) {
        this.writes = [...(this.writes ?? []), ['interimResults', value]];
        if (trigger === 'interimResults-dispose') controller.dispose();
        if (trigger === 'interimResults-replace' && instances[0] === this) replace();
      }

      set continuous(value) {
        this.writes = [...(this.writes ?? []), ['continuous', value]];
        if (trigger === 'continuous-dispose') controller.dispose();
        if (trigger === 'continuous-replace' && instances[0] === this) replace();
      }

      start() { this.startCount = (this.startCount ?? 0) + 1; }
      stop() { this.stopCount = (this.stopCount ?? 0) + 1; }
      abort() { this.abortCount = (this.abortCount ?? 0) + 1; }
    }
    const replace = () => {
      controller.stop();
      controller.start();
    };
    controller = createSpeechController({
      Recognition, onEvent: event => events.push(event),
    });
    return { controller, events, instances };
  }

  const constructed = makeScenario('constructor-dispose');
  constructed.controller.start();
  assert.equal(constructed.instances.length, 1);
  assert.deepEqual(constructed.instances[0].writes ?? [], []);
  assert.equal(constructed.instances[0].startCount ?? 0, 0);
  assert.equal(constructed.controller.recognition, null);
  assert.deepEqual(constructed.events, []);

  for (const property of properties) {
    const disposed = makeScenario(`${property}-dispose`);
    disposed.controller.start();
    assert.deepEqual(disposed.instances[0].writes.map(([key]) => key), properties.slice(0, properties.indexOf(property) + 1), property);
    assert.equal(disposed.instances[0].startCount ?? 0, 0, property);
    assert.equal(disposed.controller.recognition, null, property);
    assert.deepEqual(disposed.events, [], property);

    const replaced = makeScenario(`${property}-replace`);
    replaced.controller.start();
    assert.equal(replaced.instances.length, 2, property);
    assert.deepEqual(replaced.instances[0].writes.map(([key]) => key), properties.slice(0, properties.indexOf(property) + 1), property);
    assert.equal(replaced.instances[0].startCount ?? 0, 0, property);
    assert.equal(replaced.controller.recognition, replaced.instances[1], property);
    assert.equal(replaced.instances[1].startCount, 1, property);
    assert.deepEqual(replaced.events, [], property);
  }
});

test('a hostile stop getter may replace the run but is read once and never invokes the old stop', () => {
  const events = [];
  const instances = [];
  let controller;
  class Recognition {
    constructor() { instances.push(this); }
    start() { this.startCount = (this.startCount ?? 0) + 1; }
    abort() { this.abortCount = (this.abortCount ?? 0) + 1; }
    get stop() {
      this.stopGetterCount = (this.stopGetterCount ?? 0) + 1;
      controller.start();
      return () => { this.stopCallCount = (this.stopCallCount ?? 0) + 1; };
    }
  }
  controller = createSpeechController({
    Recognition, onEvent: event => events.push(event),
  });
  controller.start();
  const old = instances[0];
  controller.stop();

  assert.equal(old.stopGetterCount, 1);
  assert.equal(old.stopCallCount ?? 0, 0);
  assert.equal(old.abortCount, 1);
  assert.equal(instances.length, 2);
  assert.equal(controller.recognition, instances[1]);
  assert.equal(instances[1].startCount, 1);
  assert.deepEqual(events, []);
});

test('then getter failures in abort and stop execute cleanup fallback or one terminal failure', () => {
  const thenTrap = () => Object.defineProperty({}, 'then', {
    get() { throw new Error('then trap'); },
  });
  const disposeEvents = [];
  const { Recognition: DisposeRecognition, instances: disposeInstances } = recognitionClass({
    abort() { return thenTrap(); },
    stop() { this.fallbackStopCount = (this.fallbackStopCount ?? 0) + 1; },
  });
  const disposeController = createSpeechController({
    Recognition: DisposeRecognition,
    onEvent: event => disposeEvents.push(event),
  });
  disposeController.start();
  disposeController.dispose();
  assert.equal(disposeInstances[0].abortCount, 1);
  assert.equal(disposeInstances[0].fallbackStopCount, 1);
  assert.deepEqual(disposeEvents, []);
  assert.equal(disposeController.recognition, null);
  const stopEvents = [];
  const { Recognition: StopRecognition, instances: stopInstances } = recognitionClass({
    abort() { this.abortCleanupCount = (this.abortCleanupCount ?? 0) + 1; },
    stop() { return thenTrap(); },
  });
  const stopController = createSpeechController({
    Recognition: StopRecognition,
    onEvent: event => stopEvents.push(event),
  });
  stopController.start();
  stopController.stop();
  assert.equal(stopInstances[0].stopCount, 1);
  assert.equal(stopInstances[0].abortCleanupCount, 1);
  assert.deepEqual(stopEvents, [errorEvent('SPEECH_FAILED', true)]);
  assert.equal(stopController.recognition, null);
});

test('cleanup thenables keep a terminal generation suppressed through synchronous and asynchronous reentry', async () => {
  const cases = [
    {
      name: 'synchronous start',
      then(resolve) {
        this.controller.start();
        resolve();
      },
    },
    {
      name: 'asynchronous start',
      then(resolve) {
        queueMicrotask(() => {
          this.controller.start();
          resolve();
        });
      },
    },
    {
      name: 'asynchronous dispose',
      then(resolve) {
        queueMicrotask(() => {
          this.controller.dispose();
          resolve();
        });
      },
    },
    {
      name: 'resolved direct microtask start',
      then(resolve) {
        resolve();
        queueMicrotask(() => this.controller.start());
      },
    },
    {
      name: 'rejected direct microtask start',
      then(_resolve, reject) {
        reject(new Error('cleanup rejected'));
        queueMicrotask(() => this.controller.start());
      },
    },
  ];
  for (const scenario of cases) {
    const events = [];
    const instances = [];
    let controller;
    class Recognition {
      constructor() { instances.push(this); }
      start() { this.startCount = (this.startCount ?? 0) + 1; }
      stop() { throw new Error('stop failure'); }
      abort() {
        const thenable = { controller };
        thenable.then = scenario.then;
        return thenable;
      }
    }
    controller = createSpeechController({
      Recognition, onEvent: event => events.push(event),
    });
    controller.start();
    controller.stop();
    for (let tick = 0; tick < 6; tick += 1) await Promise.resolve();

    assert.equal(instances.length, 1, scenario.name);
    assert.equal(instances[0].startCount, 1, scenario.name);
    assert.equal(controller.recognition, null, scenario.name);
    assert.equal(controller.isListening(), false, scenario.name);
    assert.deepEqual(events, [errorEvent('SPEECH_FAILED', true)], scenario.name);
  }
});

test('a raw recognizer returned after constructor disposal is aborted exactly once without setup', () => {
  const events = [];
  const instances = [];
  let controller;
  class Recognition {
    constructor() {
      instances.push(this);
      controller.dispose();
    }

    set lang(value) { this.configuration = [...(this.configuration ?? []), ['lang', value]]; }
    set interimResults(value) { this.configuration = [...(this.configuration ?? []), ['interimResults', value]]; }
    set continuous(value) { this.configuration = [...(this.configuration ?? []), ['continuous', value]]; }
    start() { this.startCount = (this.startCount ?? 0) + 1; }
    stop() { this.stopCount = (this.stopCount ?? 0) + 1; }
    abort() { this.abortCount = (this.abortCount ?? 0) + 1; }
  }
  controller = createSpeechController({
    Recognition, onEvent: event => events.push(event),
  });

  assert.doesNotThrow(() => controller.start());
  assert.equal(instances.length, 1);
  assert.equal(instances[0].abortCount, 1);
  assert.equal(instances[0].stopCount ?? 0, 0);
  assert.equal(instances[0].startCount ?? 0, 0);
  assert.deepEqual(instances[0].configuration ?? [], []);
  assert.equal(controller.recognition, null);
  assert.equal(controller.isListening(), false);
  assert.deepEqual(events, []);
  controller.start();
  assert.equal(instances.length, 1);
});

test('a rejected recognition-start thenable terminalizes the captured run', async () => {
  const events = [];
  const { Recognition, instances } = recognitionClass({
    start() { return Promise.reject(new Error('start rejected')); },
  });
  const controller = createSpeechController({
    Recognition, onEvent: event => events.push(event),
  });

  assert.doesNotThrow(() => controller.start());
  await settleMicrotasks();
  assert.equal(instances[0].startCount, 1);
  assert.deepEqual(events, [errorEvent('SPEECH_FAILED', true)]);
  assert.equal(controller.recognition, null);
  assert.equal(controller.isListening(), false);
});

test('a rejected recognition-stop thenable terminalizes the captured stopping run', async () => {
  const events = [];
  const { Recognition, instances } = recognitionClass({
    stop() { return Promise.reject(new Error('stop rejected')); },
  });
  const controller = createSpeechController({
    Recognition, onEvent: event => events.push(event),
  });
  controller.start();
  assert.doesNotThrow(() => controller.stop());
  await settleMicrotasks();

  assert.equal(instances[0].stopCount, 1);
  assert.equal(instances[0].abortCount, 1);
  assert.deepEqual(events, [errorEvent('SPEECH_FAILED', true)]);
  assert.equal(controller.recognition, null);
  assert.equal(controller.isListening(), false);
});

test('a rejected recognition-abort thenable falls back to exactly one cleanup stop', async () => {
  const events = [];
  const { Recognition, instances } = recognitionClass({
    abort() { return Promise.reject(new Error('abort rejected')); },
  });
  const controller = createSpeechController({
    Recognition, onEvent: event => events.push(event),
  });
  controller.start();
  assert.doesNotThrow(() => controller.dispose());
  await settleMicrotasks();

  assert.equal(instances[0].abortCount, 1);
  assert.equal(instances[0].stopCount, 1);
  assert.deepEqual(events, []);
  assert.equal(controller.recognition, null);
  assert.equal(controller.isListening(), false);
});

test('a never-settling cleanup thenable fences only its consuming microtask', async () => {
  const events = [];
  const { Recognition, instances } = recognitionClass({
    abort() { return { then() {} }; },
  });
  const controller = createSpeechController({
    Recognition, onEvent: event => events.push(event),
  });
  controller.start();
  const old = instances[0];
  controller.stop('superseded');
  await Promise.resolve();
  controller.start();

  assert.equal(old.abortCount, 1);
  assert.equal(instances.length, 2);
  assert.equal(controller.recognition, instances[1]);
  assert.equal(controller.isListening(), true);
  assert.deepEqual(events, []);
});

test('a cleanup then getter trap fences its directly queued reentry before falling back', async () => {
  const events = [];
  const { Recognition, instances } = recognitionClass({
    abort() {
      return Object.defineProperty({}, 'then', {
        get() {
          queueMicrotask(() => controller.start());
          throw new Error('then getter trap');
        },
      });
    },
  });
  const controller = createSpeechController({
    Recognition, onEvent: event => events.push(event),
  });
  controller.start();
  controller.stop('superseded');
  await settleMicrotasks();

  assert.equal(instances.length, 1);
  assert.equal(instances[0].abortCount, 1);
  assert.equal(instances[0].stopCount, 1);
  assert.equal(controller.recognition, null);
  assert.equal(controller.isListening(), false);
  assert.deepEqual(events, []);
  controller.start();
  assert.equal(instances.length, 2);
});

test('natural end restarts in place and only explicit stop plus end settles', () => {
  const events = [];
  const { Recognition, instances } = recognitionClass();
  const controller = createSpeechController({
    Recognition,
    onEvent: event => events.push(event),
  });

  controller.start();
  instances[0].onend();
  controller.start();

  assert.equal(instances.length, 1);
  assert.equal(controller.recognition, instances[0]);
  assert.equal(controller.isListening(), true);
  assert.equal(instances[0].startCount, 2);
  assert.deepEqual(events, []);

  controller.stop();
  assert.equal(instances[0].stopCount, 1);
  assert.deepEqual(events, []);
  instances[0].onend();
  assert.deepEqual(events, [{ type: 'empty' }]);
});

test('an abort then call return rejection is consumed and falls back exactly once without an unhandled rejection', () => {
  const moduleUrl = new URL('../../../app/frontend/child/speech.mjs', import.meta.url).href;
  const script = `
    import { createSpeechController } from ${JSON.stringify(moduleUrl)};
    const instances = [];
    class Recognition {
      constructor() { instances.push(this); }
      start() {}
      abort() {
        return {
          then() { return Promise.reject(new Error('nested abort rejection')); },
        };
      }
      stop() { this.stopCount = (this.stopCount ?? 0) + 1; }
    }
    const controller = createSpeechController({
      Recognition,
      onEvent() {},
    });
    controller.start();
    controller.dispose();
    for (let turn = 0; turn < 8; turn += 1) await Promise.resolve();
    if (instances.length !== 1) {
      console.error('unexpected replacement run');
      process.exitCode = 1;
    }
    if (instances[0].stopCount !== 1) {
      console.error('fallback stop was not exact');
      process.exitCode = 1;
    }
  `;
  const result = spawnSync(process.execPath, [
    '--unhandled-rejections=strict',
    '--input-type=module',
    '--eval',
    script,
  ], { encoding: 'utf8' });

  assert.equal(result.status, 0, result.stderr || result.stdout);
});
