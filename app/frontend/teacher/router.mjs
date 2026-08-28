function isAbortError(error) {
  return error && error.name === 'AbortError';
}

function readFragment(window, routes, defaultRoute) {
  const raw = String(window.location.hash || '');
  const fragment = raw.startsWith('#') ? raw.slice(1) : raw;
  const queryIndex = fragment.indexOf('?');
  const route = queryIndex < 0 ? fragment : fragment.slice(0, queryIndex);
  const query = queryIndex < 0 ? '' : fragment.slice(queryIndex + 1);
  const valid = Object.prototype.hasOwnProperty.call(routes, route);
  const acceptedRoute = valid ? route : defaultRoute;
  const full = valid ? `#${route}${queryIndex < 0 ? '' : `?${query}`}` : `#${defaultRoute}`;
  return {
    route: acceptedRoute,
    params: new URLSearchParams(valid ? query : ''),
    full,
    canonical: raw !== full,
  };
}

function safeInvoke(callback, argument) {
  try {
    const result = callback(argument);
    Promise.resolve(result).catch(() => {});
  } catch (_error) {
    // An error reporter must not turn a route transition into an unhandled error.
  }
}

export function createTeacherRouter({
  window,
  root,
  nav,
  routes,
  defaultRoute = 'overview',
  confirmLeave = async () => true,
  onError = () => {},
}) {
  if (!window?.addEventListener || !window?.removeEventListener || !window?.history?.replaceState
      || !window?.location || !root?.replaceChildren || !root?.querySelector
      || !nav?.addEventListener || !nav?.removeEventListener || !nav?.querySelectorAll
      || !routes || typeof routes !== 'object' || typeof routes[defaultRoute] !== 'function') {
    throw new TypeError('Teacher router requires window, root, nav, and route dependencies.');
  }

  let started = false;
  let active = null;
  let epoch = 0;
  let intent = 0;

  const report = error => {
    if (!isAbortError(error)) safeInvoke(onError, error);
  };

  const buttons = () => Array.from(nav.querySelectorAll('button'));

  const clearNavigation = () => {
    for (const button of buttons()) {
      button.classList?.remove('active');
      button.removeAttribute?.('aria-current');
    }
  };

  const setNavigation = route => {
    clearNavigation();
    for (const button of buttons()) {
      if (button.dataset?.v !== route) continue;
      button.classList?.add('active');
      button.setAttribute?.('aria-current', 'page');
      break;
    }
  };

  const clearRoot = () => {
    try {
      root.replaceChildren();
    } catch (error) {
      report(error);
    }
  };

  const runCleanup = state => {
    if (!state || state.cleaned) return;
    state.cleaned = true;
    const cleanup = state.cleanup;
    state.cleanup = null;
    if (typeof cleanup !== 'function') return;
    try {
      Promise.resolve(cleanup()).catch(report);
    } catch (error) {
      report(error);
    }
  };

  const dispose = state => {
    if (!state || state.disposed) return;
    state.disposed = true;
    try {
      state.controller.abort();
    } catch (error) {
      report(error);
    }
    runCleanup(state);
  };

  const isLive = state => started && active === state && !state.disposed && !state.controller.signal.aborted;

  const useCleanup = (state, result) => {
    if (!result || (typeof result !== 'object' && typeof result !== 'function')) return;
    let cleanup;
    try {
      cleanup = result.cleanup;
    } catch (error) {
      if (isLive(state)) report(error);
      return;
    }
    if (typeof cleanup !== 'function') return;
    if (isLive(state)) {
      state.cleanup = cleanup;
      return;
    }
    try {
      Promise.resolve(cleanup()).catch(report);
    } catch (error) {
      report(error);
    }
  };

  const focusRouteHeading = state => {
    if (!isLive(state)) return;
    try {
      const title = root.querySelector('h1, h2');
      if (!title || !isLive(state)) return;
      title.setAttribute?.('tabindex', '-1');
      if (isLive(state)) title.focus?.();
    } catch (error) {
      if (isLive(state)) report(error);
    }
  };

  const runLoader = state => {
    let result;
    try {
      result = state.loader({
        root,
        route: state.route,
        params: new URLSearchParams(state.params.toString()),
        signal: state.controller.signal,
        epoch: state.epoch,
        isCurrent: () => isLive(state),
      });
    } catch (error) {
      if (isLive(state)) report(error);
      return Promise.resolve(false);
    }

    return Promise.resolve(result).then(
      value => {
        useCleanup(state, value);
        if (!isLive(state)) return false;
        focusRouteHeading(state);
        return true;
      },
      error => {
        if (isLive(state)) report(error);
        return false;
      },
    );
  };

  const accept = descriptor => {
    const previous = active;
    dispose(previous);
    if (active === previous) active = null;
    clearRoot();

    const loader = routes[descriptor.route];
    if (typeof loader !== 'function') {
      report(new TypeError(`Teacher route is unavailable: ${descriptor.route}`));
      return Promise.resolve(false);
    }

    const state = {
      route: descriptor.route,
      params: new URLSearchParams(descriptor.params.toString()),
      full: descriptor.full,
      epoch: ++epoch,
      controller: new AbortController(),
      loader,
      cleanup: null,
      cleaned: false,
      disposed: false,
    };
    active = state;
    setNavigation(state.route);
    return runLoader(state);
  };

  const replaceHash = full => {
    try {
      window.history.replaceState(null, '', full);
      return true;
    } catch (error) {
      report(error);
      return false;
    }
  };

  const restoreActiveHash = () => {
    if (active) replaceHash(active.full);
  };

  const transitionFromLocation = async () => {
    const descriptor = readFragment(window, routes, defaultRoute);
    if (descriptor.canonical && !replaceHash(descriptor.full)) return false;
    if (!started) return false;
    if (active?.full === descriptor.full) {
      intent += 1;
      return false;
    }

    const thisIntent = ++intent;
    if (active) {
      let allowed = false;
      try {
        allowed = await confirmLeave(current(), {
          route: descriptor.route,
          params: new URLSearchParams(descriptor.params.toString()),
        });
      } catch (error) {
        report(error);
      }
      if (!started || thisIntent !== intent) return false;
      if (!allowed) {
        restoreActiveHash();
        return false;
      }
    }
    if (!started || thisIntent !== intent) return false;
    return accept(descriptor);
  };

  const onHashChange = () => {
    void transitionFromLocation().catch(report);
  };

  const onNavigationClick = event => {
    const button = event.target?.closest?.('button');
    const route = button?.dataset?.v;
    if (!started || button?.disabled || typeof routes[route] !== 'function') return;
    if (active?.route === route) {
      if (window.location.hash !== active.full && !replaceHash(active.full)) return;
      void refresh().catch(report);
      return;
    }
    window.location.hash = `#${route}`;
  };

  const current = () => {
    if (!active) return null;
    return {
      route: active.route,
      params: new URLSearchParams(active.params.toString()),
      epoch: active.epoch,
    };
  };

  const start = () => {
    if (started) return Promise.resolve(Boolean(active));
    started = true;
    window.addEventListener('hashchange', onHashChange);
    nav.addEventListener('click', onNavigationClick);
    return transitionFromLocation();
  };

  const refresh = () => {
    if (!started || !active) return Promise.resolve(false);
    intent += 1;
    return accept({
      route: active.route,
      params: new URLSearchParams(active.params.toString()),
      full: active.full,
      canonical: false,
    });
  };

  const stop = () => {
    if (!started && !active) return;
    started = false;
    intent += 1;
    window.removeEventListener('hashchange', onHashChange);
    nav.removeEventListener('click', onNavigationClick);
    dispose(active);
    active = null;
    clearNavigation();
    clearRoot();
  };

  return { start, refresh, stop, current };
}
