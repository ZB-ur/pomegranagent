(function (global) {
  'use strict';

  class APIError extends Error {
    constructor({ status = 0, code, message, fieldErrors = {}, retryable = false, requestId = null, cause = null }) {
      super(message);
      this.name = 'APIError';
      this.status = status;
      this.code = code;
      this.fieldErrors = fieldErrors;
      this.retryable = retryable;
      this.requestId = requestId;
      this.cause = cause;
    }
  }

  async function parseSuccess(response, responseType) {
    const contentType = response.headers.get('content-type') || '';
    if (responseType === 'blob') {
      if (!contentType || contentType.includes('json')) {
        throw new APIError({ status: response.status, code: 'INVALID_RESPONSE', message: '服务返回了无效媒体内容' });
      }
      return response.blob();
    }
    if (responseType === 'text') return response.text();
    if (!contentType.includes('application/json')) {
      throw new APIError({ status: response.status, code: 'INVALID_RESPONSE', message: '服务返回了非 JSON 数据' });
    }
    return response.json();
  }

  const inFlightBySequence = new Map();
  const sendFetch = fetch;

  async function request(path, options = {}) {
    const method = options.method || 'GET';
    const responseType = options.responseType || 'json';
    const timeoutMs = options.timeoutMs === undefined ? 10000 : options.timeoutMs;
    const controller = new AbortController();
    const sequenceKey = options.sequenceKey || null;
    let timedOut = false;
    if (sequenceKey) {
      inFlightBySequence.get(sequenceKey)?.abort('superseded');
      inFlightBySequence.set(sequenceKey, controller);
    }
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort('timeout');
    }, timeoutMs);
    const cancelFromCaller = () => controller.abort('caller');
    if (options.signal) {
      if (options.signal.aborted) cancelFromCaller();
      else options.signal.addEventListener('abort', cancelFromCaller, { once: true });
    }
    const headers = new Headers(options.headers || {});
    if (options.requestId) headers.set('X-Request-ID', options.requestId);
    let body = options.body;
    if (body !== undefined && body !== null && typeof body !== 'string' && !(body instanceof FormData)) {
      headers.set('Content-Type', 'application/json');
      body = JSON.stringify(body);
    }
    try {
      const response = await sendFetch(path, {
        method,
        headers,
        body,
        signal: controller.signal,
        credentials: 'same-origin',
        cache: options.cache || 'default',
      });
      if (!response.ok) {
        const payload = (response.headers.get('content-type') || '').includes('application/json') ? await response.json() : null;
        const detail = payload && payload.error;
        throw new APIError({
          status: response.status,
          code: detail ? detail.code : 'INVALID_ERROR_RESPONSE',
          message: detail ? detail.message : `请求失败（HTTP ${response.status}）`,
          fieldErrors: detail ? detail.field_errors : {},
          retryable: detail ? detail.retryable : response.status >= 500,
          requestId: detail ? detail.request_id : response.headers.get('x-request-id'),
        });
      }
      return await parseSuccess(response, responseType);
    } catch (error) {
      if (error instanceof APIError) throw error;
      if (controller.signal.aborted && !timedOut) {
        throw new DOMException('Request cancelled', 'AbortError');
      }
      throw new APIError({
        code: timedOut ? 'REQUEST_TIMEOUT' : 'NETWORK_ERROR',
        message: timedOut ? '请求超时，请重试' : '网络连接失败，请检查服务是否正在运行',
        retryable: true,
        cause: error,
      });
    } finally {
      clearTimeout(timer);
      options.signal?.removeEventListener('abort', cancelFromCaller);
      if (sequenceKey && inFlightBySequence.get(sequenceKey) === controller) {
        inFlightBySequence.delete(sequenceKey);
      }
    }
  }

  let readyPromise = null;

  function setGateState(state, detail) {
    document.documentElement.dataset.appState = state;
    global.dispatchEvent(new CustomEvent(state === 'ready' ? 'duck:runtime-ready' : 'duck:runtime-blocked', { detail }));
  }

  async function performVersionGate() {
    try {
      const [disk, health] = await Promise.all([
        request(`/version.json?ts=${Date.now()}`, { cache: 'no-store' }),
        request('/api/health', { cache: 'no-store' }),
      ]);
      const matches = ['release_id', 'api_version', 'schema_version'].every((key) => disk[key] === health[key]);
      if (!matches) throw new APIError({ code: 'VERSION_MISMATCH', message: '应用正在更新，请重启服务后刷新页面' });
      if (health.db_mode !== 'app') throw new APIError({ code: 'DB_MODE_MISMATCH', message: '服务连接了测试数据库，业务页面已停用' });
      setGateState('ready', health);
      return health;
    } catch (error) {
      const normalized = error instanceof APIError ? error : new APIError({ code: 'HEALTH_UNAVAILABLE', message: '无法验证应用版本' });
      setGateState('maintenance', normalized);
      renderMaintenance(normalized.message);
      throw normalized;
    }
  }

  function bootstrapVersionGate() {
    if (!readyPromise) readyPromise = performVersionGate();
    return readyPromise;
  }

  function ready() {
    return bootstrapVersionGate();
  }

  function renderMaintenance(message) {
    const existing = document.getElementById('runtime-maintenance');
    if (existing) return;
    const panel = document.createElement('main');
    panel.id = 'runtime-maintenance';
    panel.setAttribute('role', 'alert');
    panel.innerHTML = `<h1>应用暂不可用</h1><p>${String(message).replace(/[<>&]/g, '')}</p><p>请老师重启服务后刷新页面。</p>`;
    document.body.replaceChildren(panel);
  }

  global.DuckAPI = Object.freeze({ request, bootstrapVersionGate, ready, APIError });
})(window);
