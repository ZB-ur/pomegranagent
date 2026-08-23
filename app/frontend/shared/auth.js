(function (global) {
  'use strict';
  const request = global.DuckAPI.request;

  function status() {
    return request('/api/auth/status');
  }

  function setup(pin) {
    return request('/api/auth/setup', { method: 'POST', body: { pin } });
  }

  function unlock(pin) {
    return request('/api/auth/unlock', { method: 'POST', body: { pin } });
  }

  function lock() {
    return request('/api/auth/lock', { method: 'POST' });
  }

  global.DuckAuth = Object.freeze({ status, setup, unlock, lock });
})(window);
