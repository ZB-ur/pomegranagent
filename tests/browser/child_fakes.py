from __future__ import annotations


CONTROLLED_CHILD_FAKE_SCRIPT = r"""
(() => {
  const latest = values => values.length === 0 ? null : values[values.length - 1];
  const call = (target, key, event) => {
    const callback = target && target[key];
    if (typeof callback === 'function') callback.call(target, event);
  };

  const test = {
    recognition: {
      instances: [],
      starts: 0,
      stops: 0,
      aborts: 0,
      emitResult(index, text, isFinal) {
        const instance = latest(this.instances);
        if (!instance || !Number.isInteger(index) || index < 0) return;
        instance.results[index] = {
          0: { transcript: typeof text === 'string' ? text : '' },
          isFinal: isFinal === true,
        };
        call(instance, 'onresult', {
          resultIndex: index,
          results: instance.results.slice(),
        });
      },
      emitEnd() {
        call(latest(this.instances), 'onend', {});
      },
      emitError(code) {
        call(latest(this.instances), 'onerror', { error: code });
      },
    },
    tts: {
      utterances: [],
      cancels: 0,
      emitEnd(index) {
        call(this.utterances[index], 'onend', {});
      },
      emitError(index) {
        call(this.utterances[index], 'onerror', {});
      },
    },
    audio: {
      instances: [],
      rejectNextPlay: false,
      emitPlaying(index) {
        call(this.instances[index], 'onplaying', {});
      },
      emitEnded(index) {
        call(this.instances[index], 'onended', {});
      },
      emitError(index) {
        call(this.instances[index], 'onerror', {});
      },
      rejectNextPlayOnce() {
        this.rejectNextPlay = true;
      },
    },
  };

  class ControlledRecognition {
    constructor() {
      this.results = [];
      test.recognition.instances.push(this);
    }

    start() {
      test.recognition.starts += 1;
    }

    stop() {
      test.recognition.stops += 1;
    }

    abort() {
      test.recognition.aborts += 1;
    }
  }

  class ControlledAudio {
    constructor(url) {
      this.url = url;
      this.playCalls = 0;
      this.pauseCalls = 0;
      test.audio.instances.push(this);
    }

    play() {
      this.playCalls += 1;
      if (test.audio.rejectNextPlay) {
        test.audio.rejectNextPlay = false;
        return Promise.reject(new Error('synthetic audio play rejection'));
      }
      return Promise.resolve();
    }

    pause() {
      this.pauseCalls += 1;
    }
  }

  class ControlledUtterance {
    constructor(text) {
      this.text = text;
    }
  }

  Object.defineProperties(globalThis, {
    SpeechRecognition: { configurable: true, value: ControlledRecognition, writable: true },
    webkitSpeechRecognition: { configurable: true, value: ControlledRecognition, writable: true },
    Audio: { configurable: true, value: ControlledAudio, writable: true },
    speechSynthesis: {
      configurable: true,
      value: {
        speak(utterance) {
          test.tts.utterances.push(utterance);
        },
        cancel() {
          test.tts.cancels += 1;
        },
      },
      writable: true,
    },
    SpeechSynthesisUtterance: { configurable: true, value: ControlledUtterance, writable: true },
    __childTest: { configurable: true, value: test, writable: false },
  });
})();
"""


def install_controlled_child_fakes(page) -> None:
    page.add_init_script(CONTROLLED_CHILD_FAKE_SCRIPT)
