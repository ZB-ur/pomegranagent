import test from 'node:test';
import assert from 'node:assert/strict';

import { createTTSController } from '../../../app/frontend/child/tts.mjs';

test('module exposes only the approved controller factory', async () => {
  const module = await import('../../../app/frontend/child/tts.mjs');
  assert.deepEqual(Object.keys(module), ['createTTSController']);
});

function fakeClock() {
  let now = 0;
  let sequence = 0;
  const timers = new Map();

  return {
    setTimer(callback, delay) {
      const id = ++sequence;
      timers.set(id, { callback, at: now + delay, sequence: id });
      return id;
    },
    clearTimer(id) {
      timers.delete(id);
    },
    advance(milliseconds) {
      const target = now + milliseconds;
      while (true) {
        const next = [...timers.entries()]
          .filter(([, timer]) => timer.at <= target)
          .sort(([, left], [, right]) => left.at - right.at || left.sequence - right.sequence)[0];
        if (!next) break;
        const [id, timer] = next;
        timers.delete(id);
        now = timer.at;
        timer.callback();
      }
      now = target;
    },
    pending() {
      return timers.size;
    },
  };
}

function fakeAudio() {
  return {
    onplaying: null,
    onended: null,
    onerror: null,
    pauseCount: 0,
    play() {
      return Promise.resolve();
    },
    pause() {
      this.pauseCount += 1;
    },
  };
}

function fakeSynthesis() {
  return {
    cancelCount: 0,
    spoken: [],
    cancel() {
      this.cancelCount += 1;
    },
    speak(utterance) {
      this.spoken.push(utterance);
    },
  };
}

class FakeUtterance {
  constructor(text) {
    this.text = text;
    this.onend = null;
    this.onerror = null;
  }
}

async function tickMicrotasks() {
  for (let count = 0; count < 8; count += 1) await Promise.resolve();
}

test('edge audio settles after playback ends', async () => {
  const audio = fakeAudio();
  const clock = fakeClock();
  const tts = createTTSController({
    loadEdgeBlob: async () => ({ bytes: 'mp3' }),
    Audio: () => audio,
    createObjectURL: () => 'blob:edge',
    revokeObjectURL: () => {},
    browserSpeak: async () => ({ mode: 'browser', reason: 'fallback' }),
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
  });

  const resultPromise = tts.speak('你好');
  await tickMicrotasks();
  audio.onplaying();
  audio.onended();

  assert.deepEqual(await resultPromise, { mode: 'edge', reason: 'ended' });
  assert.equal(clock.pending(), 0);
});

test('audio not playing at 5000 ms is aborted and falls back', async () => {
  const clock = fakeClock();
  let aborted = false;
  const tts = createTTSController({
    loadEdgeBlob: (_text, signal) => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => {
        aborted = true;
        reject(Object.assign(new Error('aborted'), { name: 'AbortError' }));
      });
    }),
    browserSpeak: async () => ({ mode: 'browser', reason: 'edge-timeout' }),
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
  });

  const resultPromise = tts.speak('冷启动');
  await tickMicrotasks();
  clock.advance(4999);
  assert.equal(aborted, false);
  clock.advance(1);
  assert.equal(aborted, true);

  assert.deepEqual(await resultPromise, { mode: 'browser', reason: 'edge-timeout' });
  assert.equal(clock.pending(), 0);
});

test('browser synthesis ends successfully after an Edge request failure', async () => {
  const clock = fakeClock();
  const synthesis = fakeSynthesis();
  const tts = createTTSController({
    loadEdgeBlob: async () => { throw new Error('server unavailable'); },
    speechSynthesis: synthesis,
    SpeechSynthesisUtterance: FakeUtterance,
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
  });

  const resultPromise = tts.speak('继续说');
  await tickMicrotasks();
  assert.equal(synthesis.spoken.length, 1);
  assert.equal(synthesis.spoken[0].text, '继续说');
  synthesis.spoken[0].onend();

  assert.deepEqual(await resultPromise, { mode: 'browser', reason: 'ended' });
  assert.equal(clock.pending(), 0);
});

test('browser synthesis error and 15000 ms timeout resolve to text mode', async () => {
  const errorClock = fakeClock();
  const errorSynthesis = fakeSynthesis();
  const errorTTS = createTTSController({
    loadEdgeBlob: async () => { throw new Error('server unavailable'); },
    speechSynthesis: errorSynthesis,
    SpeechSynthesisUtterance: FakeUtterance,
    setTimer: errorClock.setTimer,
    clearTimer: errorClock.clearTimer,
  });
  const errorResult = errorTTS.speak('出错');
  await tickMicrotasks();
  errorSynthesis.spoken[0].onerror();
  assert.deepEqual(await errorResult, { mode: 'text', reason: 'browser-error' });
  assert.equal(errorClock.pending(), 0);

  const timeoutClock = fakeClock();
  const timeoutSynthesis = fakeSynthesis();
  const timeoutTTS = createTTSController({
    loadEdgeBlob: async () => { throw new Error('server unavailable'); },
    speechSynthesis: timeoutSynthesis,
    SpeechSynthesisUtterance: FakeUtterance,
    setTimer: timeoutClock.setTimer,
    clearTimer: timeoutClock.clearTimer,
  });
  const timeoutResult = timeoutTTS.speak('超时');
  await tickMicrotasks();
  timeoutClock.advance(14999);
  assert.equal(timeoutSynthesis.cancelCount, 0);
  timeoutClock.advance(1);
  assert.deepEqual(await timeoutResult, { mode: 'text', reason: 'browser-timeout' });
  assert.equal(timeoutSynthesis.cancelCount, 1);
  assert.equal(timeoutClock.pending(), 0);
});

test('cancelling browser synthesis settles immediately and calls its cancellation boundary once', async () => {
  const clock = fakeClock();
  const synthesis = fakeSynthesis();
  const tts = createTTSController({
    loadEdgeBlob: async () => { throw new Error('server unavailable'); },
    speechSynthesis: synthesis,
    SpeechSynthesisUtterance: FakeUtterance,
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
  });

  const resultPromise = tts.speak('停止');
  await tickMicrotasks();
  tts.cancel('manual-stop');

  assert.deepEqual(await resultPromise, { mode: 'cancelled', reason: 'manual-stop' });
  assert.equal(synthesis.cancelCount, 1);
  assert.equal(clock.pending(), 0);
});

test('onplaying before the 5000 ms timer wins the deterministic boundary race', async () => {
  const clock = fakeClock();
  const audio = fakeAudio();
  let browserStarts = 0;
  const tts = createTTSController({
    loadEdgeBlob: async () => ({ bytes: 'mp3' }),
    Audio: () => audio,
    createObjectURL: () => 'blob:edge',
    revokeObjectURL: () => {},
    browserSpeak: async () => {
      browserStarts += 1;
      return { mode: 'browser', reason: 'unexpected' };
    },
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
  });

  const resultPromise = tts.speak('刚好开始');
  await tickMicrotasks();
  audio.onplaying();
  clock.advance(5000);
  audio.onended();

  assert.deepEqual(await resultPromise, { mode: 'edge', reason: 'ended' });
  assert.equal(browserStarts, 0);
});

test('timer first at 5000 ms aborts, pauses, revokes, and ignores captured late edge callbacks', async () => {
  const clock = fakeClock();
  const audio = fakeAudio();
  const revoked = [];
  let edgeAborted = false;
  let browserSignal = null;
  const tts = createTTSController({
    loadEdgeBlob: (_text, signal) => new Promise(resolve => {
      signal.addEventListener('abort', () => { edgeAborted = true; });
      resolve({ bytes: 'mp3' });
    }),
    Audio: () => audio,
    createObjectURL: () => 'blob:edge',
    revokeObjectURL: url => revoked.push(url),
    browserSpeak: async (_text, context) => {
      browserSignal = context.signal;
      return { mode: 'browser', reason: 'edge-timeout' };
    },
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
  });

  const resultPromise = tts.speak('超时优先');
  await tickMicrotasks();
  const latePlaying = audio.onplaying;
  const lateEnded = audio.onended;
  clock.advance(5000);
  await tickMicrotasks();
  latePlaying();
  lateEnded();

  assert.deepEqual(await resultPromise, { mode: 'browser', reason: 'edge-timeout' });
  assert.equal(edgeAborted, true);
  assert.equal(browserSignal.aborted, false);
  assert.equal(audio.pauseCount, 1);
  assert.deepEqual(revoked, ['blob:edge']);
  assert.equal(clock.pending(), 0);
});

test('a timeout before deferred loader invocation falls back safely and ignores its late blob', async () => {
  const clock = fakeClock();
  let deferredLoaderSignal = null;
  let resolveLateBlob;
  let madeURL = 0;
  let madeAudio = 0;
  const tts = createTTSController({
    loadEdgeBlob: (_text, signal) => {
      deferredLoaderSignal = signal;
      return new Promise(resolve => { resolveLateBlob = resolve; });
    },
    Audio: () => { madeAudio += 1; return fakeAudio(); },
    createObjectURL: () => { madeURL += 1; return 'blob:late'; },
    revokeObjectURL: () => {},
    browserSpeak: async () => ({ mode: 'browser', reason: 'edge-timeout' }),
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
  });

  const resultPromise = tts.speak('不刷新微任务');
  clock.advance(5000);
  await tickMicrotasks();
  assert.equal(deferredLoaderSignal.aborted, true);
  resolveLateBlob({ bytes: 'late' });
  await tickMicrotasks();

  assert.deepEqual(await resultPromise, { mode: 'browser', reason: 'edge-timeout' });
  assert.equal(madeURL, 0);
  assert.equal(madeAudio, 0);
  assert.equal(clock.pending(), 0);
});

test('synchronous and rejected Edge setup failures resolve through browser fallback', async () => {
  const cases = [
    {
      name: 'loader throw',
      deps: { loadEdgeBlob: () => { throw new Error('loader'); } },
      reason: 'edge-request-error',
    },
    {
      name: 'loader rejection',
      deps: { loadEdgeBlob: async () => { throw new Error('loader'); } },
      reason: 'edge-request-error',
    },
    {
      name: 'URL throw',
      deps: {
        loadEdgeBlob: async () => ({ bytes: 'mp3' }),
        createObjectURL: () => { throw new Error('url'); },
      },
      reason: 'edge-setup-error',
    },
    {
      name: 'Audio factory throw',
      deps: {
        loadEdgeBlob: async () => ({ bytes: 'mp3' }),
        createObjectURL: () => 'blob:edge',
        Audio: () => { throw new Error('audio'); },
      },
      reason: 'edge-setup-error',
    },
  ];

  for (const item of cases) {
    const clock = fakeClock();
    const tts = createTTSController({
      ...item.deps,
      browserSpeak: async (_text, context) => ({ mode: 'browser', reason: context.reason }),
      setTimer: clock.setTimer,
      clearTimer: clock.clearTimer,
      revokeObjectURL: () => {},
    });
    assert.deepEqual(await tts.speak(item.name), { mode: 'browser', reason: item.reason }, item.name);
    assert.equal(clock.pending(), 0, item.name);
  }
});

test('play throws, rejects, and errors without leaving the child speech promise pending', async () => {
  const scenarios = [
    {
      name: 'play throw',
      audio: { ...fakeAudio(), play() { throw new Error('play'); } },
      event: null,
      reason: 'edge-play-rejected',
    },
    {
      name: 'play rejection',
      audio: { ...fakeAudio(), play() { return Promise.reject(new Error('play')); } },
      event: null,
      reason: 'edge-play-rejected',
    },
    {
      name: 'audio error',
      audio: fakeAudio(),
      event: 'onerror',
      reason: 'edge-playback-error',
    },
  ];

  for (const scenario of scenarios) {
    const clock = fakeClock();
    const tts = createTTSController({
      loadEdgeBlob: async () => ({ bytes: 'mp3' }),
      Audio: () => scenario.audio,
      createObjectURL: () => 'blob:edge',
      revokeObjectURL: () => {},
      browserSpeak: async (_text, context) => ({ mode: 'browser', reason: context.reason }),
      setTimer: clock.setTimer,
      clearTimer: clock.clearTimer,
    });
    const resultPromise = tts.speak(scenario.name);
    await tickMicrotasks();
    if (scenario.event) scenario.audio[scenario.event]();
    assert.deepEqual(await resultPromise, { mode: 'browser', reason: scenario.reason }, scenario.name);
    assert.equal(clock.pending(), 0, scenario.name);
  }
});

test('cancelling during an Edge request aborts it, settles once, and absorbs its late rejection', async () => {
  const clock = fakeClock();
  let rejectLoader;
  let aborted = false;
  const tts = createTTSController({
    loadEdgeBlob: (_text, signal) => new Promise((_resolve, reject) => {
      rejectLoader = reject;
      signal.addEventListener('abort', () => { aborted = true; });
    }),
    browserSpeak: async () => ({ mode: 'browser', reason: 'unexpected' }),
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
  });

  const resultPromise = tts.speak('请求中');
  await tickMicrotasks();
  tts.cancel('manual-stop');
  rejectLoader(new Error('late request failure'));
  await tickMicrotasks();

  assert.deepEqual(await resultPromise, { mode: 'cancelled', reason: 'manual-stop' });
  assert.equal(aborted, true);
  assert.equal(clock.pending(), 0);
});

test('cancelling Edge audio pauses it and revokes its object URL exactly once', async () => {
  const clock = fakeClock();
  const audio = fakeAudio();
  const revoked = [];
  const tts = createTTSController({
    loadEdgeBlob: async () => ({ bytes: 'mp3' }),
    Audio: () => audio,
    createObjectURL: () => 'blob:cleanup',
    revokeObjectURL: url => revoked.push(url),
    browserSpeak: async () => ({ mode: 'browser', reason: 'unexpected' }),
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
  });

  const resultPromise = tts.speak('音频中');
  await tickMicrotasks();
  tts.cancel('manual-stop');
  tts.cancel('ignored-second-cancel');

  assert.deepEqual(await resultPromise, { mode: 'cancelled', reason: 'manual-stop' });
  assert.equal(audio.pauseCount, 1);
  assert.deepEqual(revoked, ['blob:cleanup']);
  assert.equal(audio.onplaying, null);
  assert.equal(audio.onended, null);
  assert.equal(audio.onerror, null);
  assert.equal(clock.pending(), 0);
});

test('superseding settles the first request before the next loader starts', async () => {
  const clock = fakeClock();
  let firstSettled = false;
  const secondLoaderObservedFirstSettlement = [];
  const tts = createTTSController({
    loadEdgeBlob: text => {
      if (text === '第二句') secondLoaderObservedFirstSettlement.push(firstSettled);
      return new Promise(() => {});
    },
    browserSpeak: async () => ({ mode: 'browser', reason: 'unexpected' }),
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
  });

  const first = tts.speak('第一句');
  first.then(() => { firstSettled = true; });
  const second = tts.speak('第二句');
  await tickMicrotasks();

  assert.deepEqual(await first, { mode: 'cancelled', reason: 'superseded' });
  assert.deepEqual(secondLoaderObservedFirstSettlement, [true]);
  tts.cancel('test-end');
  assert.deepEqual(await second, { mode: 'cancelled', reason: 'test-end' });
  assert.equal(clock.pending(), 0);
});

test('dispose settles active work and later speak is a safe terminal cancellation', async () => {
  const clock = fakeClock();
  const tts = createTTSController({
    loadEdgeBlob: () => new Promise(() => {}),
    browserSpeak: async () => ({ mode: 'browser', reason: 'unexpected' }),
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
  });

  const active = tts.speak('正在说');
  tts.dispose();
  tts.dispose();

  assert.deepEqual(await active, { mode: 'cancelled', reason: 'disposed' });
  assert.deepEqual(await tts.speak('以后'), { mode: 'cancelled', reason: 'disposed' });
  assert.equal(clock.pending(), 0);
});

test('unavailable, throwing, and rejecting browser fallbacks always resolve text mode', async () => {
  const unavailableClock = fakeClock();
  const unavailable = createTTSController({
    loadEdgeBlob: async () => { throw new Error('edge'); },
    setTimer: unavailableClock.setTimer,
    clearTimer: unavailableClock.clearTimer,
  });
  assert.deepEqual(await unavailable.speak('没有浏览器语音'), { mode: 'text', reason: 'browser-unavailable' });

  const throwClock = fakeClock();
  const throws = createTTSController({
    loadEdgeBlob: async () => { throw new Error('edge'); },
    browserSpeak: () => { throw new Error('browser'); },
    setTimer: throwClock.setTimer,
    clearTimer: throwClock.clearTimer,
  });
  assert.deepEqual(await throws.speak('浏览器抛错'), { mode: 'text', reason: 'edge-request-error' });

  const rejectClock = fakeClock();
  const rejects = createTTSController({
    loadEdgeBlob: async () => { throw new Error('edge'); },
    browserSpeak: async () => { throw new Error('browser'); },
    setTimer: rejectClock.setTimer,
    clearTimer: rejectClock.clearTimer,
  });
  assert.deepEqual(await rejects.speak('浏览器拒绝'), { mode: 'text', reason: 'edge-request-error' });
  assert.equal(unavailableClock.pending() + throwClock.pending() + rejectClock.pending(), 0);
});

test('a non-timeout Edge failure clears its cold timer before browser fallback runs', async () => {
  const clock = fakeClock();
  let browserSignal = null;
  let settleBrowser;
  const tts = createTTSController({
    loadEdgeBlob: async () => { throw new Error('edge'); },
    browserSpeak: (_text, context) => {
      browserSignal = context.signal;
      return new Promise(resolve => { settleBrowser = resolve; });
    },
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
  });

  const resultPromise = tts.speak('请求错误');
  await tickMicrotasks();
  clock.advance(5000);
  assert.equal(browserSignal.aborted, false);
  settleBrowser({ mode: 'browser', reason: 'edge-request-error' });

  assert.deepEqual(await resultPromise, { mode: 'browser', reason: 'edge-request-error' });
  assert.equal(clock.pending(), 0);
});

test('late injected browser settlement after cancellation cannot overwrite the cancelled result', async () => {
  const clock = fakeClock();
  let resolveBrowser;
  let rejectBrowser;
  const tts = createTTSController({
    loadEdgeBlob: async () => { throw new Error('edge'); },
    browserSpeak: () => new Promise((resolve, reject) => {
      resolveBrowser = resolve;
      rejectBrowser = reject;
    }),
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
  });

  const resultPromise = tts.speak('晚到浏览器结果');
  await tickMicrotasks();
  tts.cancel('manual-stop');
  resolveBrowser({ mode: 'browser', reason: 'late-success' });
  rejectBrowser(new Error('late rejection'));
  await tickMicrotasks();

  assert.deepEqual(await resultPromise, { mode: 'cancelled', reason: 'manual-stop' });
  assert.equal(clock.pending(), 0);
});

test('late injected browser rejection after cancellation is absorbed under strict unhandled-rejection mode', async () => {
  const clock = fakeClock();
  let rejectBrowser;
  const tts = createTTSController({
    loadEdgeBlob: async () => { throw new Error('edge'); },
    browserSpeak: () => new Promise((_resolve, reject) => { rejectBrowser = reject; }),
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
  });

  const resultPromise = tts.speak('晚到浏览器拒绝');
  await tickMicrotasks();
  tts.cancel('manual-stop');
  rejectBrowser(new Error('late browser failure'));
  await tickMicrotasks();

  assert.deepEqual(await resultPromise, { mode: 'cancelled', reason: 'manual-stop' });
  assert.equal(clock.pending(), 0);
});
