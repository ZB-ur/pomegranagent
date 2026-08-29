const DEPENDENCY_KEYS = ['window', 'document'];

function invalidDirtyGuardContract() {
  return new TypeError('Review dirty guard contract is invalid.');
}

function readOwnDataRecord(value, keys) {
  try {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) throw invalidDirtyGuardContract();
    const descriptors = Object.getOwnPropertyDescriptors(value);
    const actualKeys = Reflect.ownKeys(descriptors);
    if (actualKeys.length !== keys.length || !keys.every(key => actualKeys.includes(key))) {
      throw invalidDirtyGuardContract();
    }
    const record = {};
    for (const key of keys) {
      const descriptor = descriptors[key];
      if (!descriptor || !Object.prototype.hasOwnProperty.call(descriptor, 'value')) throw invalidDirtyGuardContract();
      record[key] = descriptor.value;
    }
    return record;
  } catch (_error) {
    throw invalidDirtyGuardContract();
  }
}

function validateDependencies(dependencies) {
  const record = readOwnDataRecord(dependencies, DEPENDENCY_KEYS);
  try {
    const { window: windowApi, document: documentApi } = record;
    if (!windowApi || !documentApi
        || typeof windowApi.addEventListener !== 'function'
        || typeof windowApi.removeEventListener !== 'function'
        || typeof documentApi.createElement !== 'function'
        || !documentApi.body || typeof documentApi.body.append !== 'function') {
      throw invalidDirtyGuardContract();
    }
  } catch (_error) {
    throw invalidDirtyGuardContract();
  }
  return record;
}

function assertSnapshot(snapshot) {
  if (typeof snapshot !== 'string') throw invalidDirtyGuardContract();
  return snapshot;
}

function safeCall(callback, ...args) {
  try {
    return callback(...args);
  } catch (_error) {
    return undefined;
  }
}

export function createDirtyGuard(dependencies) {
  const validated = validateDependencies(dependencies);
  const windowApi = validated.window;
  const documentApi = validated.document;
  let active = false;
  let cleanSnapshot = null;
  let currentSnapshot = null;
  let dialog = null;
  let pendingConfirmation = null;
  let resolveConfirmation = null;
  let confirmationTrigger = null;

  const isDirty = () => active && cleanSnapshot !== currentSnapshot;

  const disposeDialog = () => {
    const currentDialog = dialog;
    dialog = null;
    if (!currentDialog) return;
    safeCall(() => currentDialog.close());
    safeCall(() => currentDialog.remove());
  };

  const finishConfirmation = (allowed, discard) => {
    const resolve = resolveConfirmation;
    const pending = pendingConfirmation;
    const trigger = confirmationTrigger;
    resolveConfirmation = null;
    pendingConfirmation = null;
    confirmationTrigger = null;
    disposeDialog();
    if (discard) {
      cleanSnapshot = currentSnapshot;
    }
    if (!allowed && trigger?.isConnected) safeCall(() => trigger.focus());
    if (pending && resolve) resolve(allowed);
  };

  const onBeforeUnload = event => {
    if (!isDirty()) return;
    safeCall(() => event.preventDefault());
    try { event.returnValue = ''; } catch (_error) {}
  };

  const activate = snapshot => {
    const clean = assertSnapshot(snapshot);
    if (!active) {
      try {
        windowApi.addEventListener('beforeunload', onBeforeUnload);
      } catch (_error) {
        throw invalidDirtyGuardContract();
      }
    }
    active = true;
    finishConfirmation(false, false);
    cleanSnapshot = clean;
    currentSnapshot = clean;
  };

  const update = snapshot => {
    if (!active) return;
    currentSnapshot = assertSnapshot(snapshot);
  };

  const markClean = snapshot => {
    if (!active) return;
    const clean = assertSnapshot(snapshot);
    cleanSnapshot = clean;
    currentSnapshot = clean;
  };

  const confirmLeave = () => {
    if (!isDirty()) return Promise.resolve(true);
    if (pendingConfirmation) return pendingConfirmation;
    pendingConfirmation = new Promise(resolve => {
      resolveConfirmation = resolve;
    });
    try {
      confirmationTrigger = documentApi.activeElement;
      const nextDialog = documentApi.createElement('dialog');
      const heading = documentApi.createElement('h2');
      heading.setAttribute('id', 'teacher-dirty-dialog-heading');
      heading.append('有未保存的修改');
      nextDialog.setAttribute('aria-labelledby', 'teacher-dirty-dialog-heading');
      const continueButton = documentApi.createElement('button');
      continueButton.setAttribute('type', 'button');
      continueButton.append('继续编辑');
      const discardButton = documentApi.createElement('button');
      discardButton.setAttribute('type', 'button');
      discardButton.append('放弃修改');
      continueButton.addEventListener('click', () => finishConfirmation(false, false));
      discardButton.addEventListener('click', () => finishConfirmation(true, true));
      nextDialog.addEventListener('cancel', event => {
        safeCall(() => event.preventDefault());
        finishConfirmation(false, false);
      });
      nextDialog.append(heading, continueButton, discardButton);
      documentApi.body.append(nextDialog);
      dialog = nextDialog;
      if (typeof nextDialog.showModal === 'function') nextDialog.showModal();
      safeCall(() => continueButton.focus());
    } catch (_error) {
      finishConfirmation(false, false);
    }
    return pendingConfirmation || Promise.resolve(false);
  };

  const release = () => {
    finishConfirmation(false, false);
    if (active) safeCall(() => windowApi.removeEventListener('beforeunload', onBeforeUnload));
    active = false;
    cleanSnapshot = null;
    currentSnapshot = null;
  };

  return { activate, update, markClean, isDirty, confirmLeave, release };
}
