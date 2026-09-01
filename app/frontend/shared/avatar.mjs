const CANONICAL_AVATAR = /^\/api\/media\/avatars\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function element(document, tag) {
  if (document === null || (typeof document !== 'object' && typeof document !== 'function') ||
      typeof document.createElement !== 'function') throw new TypeError('Invalid avatar document.');
  const node = document.createElement(tag);
  if (node === null || (typeof node !== 'object' && typeof node !== 'function') ||
      typeof node.setAttribute !== 'function' || typeof node.append !== 'function' ||
      typeof node.replaceChildren !== 'function' || typeof node.addEventListener !== 'function') {
    throw new TypeError('Invalid avatar element.');
  }
  return node;
}

export function renderAvatarImage(document, avatar, fallbackText) {
  const wrapper = element(document, 'span');
  const fallback = element(document, 'span');
  fallback.setAttribute('class', 'avatar-fallback');
  fallback.textContent = typeof fallbackText === 'string' && fallbackText !== '' ? fallbackText : '?';

  if (typeof avatar !== 'string' || !CANONICAL_AVATAR.test(avatar)) {
    wrapper.append(fallback);
    return wrapper;
  }

  const image = element(document, 'img');
  image.setAttribute('src', avatar);
  image.setAttribute('alt', '');
  image.setAttribute('decoding', 'async');
  image.setAttribute('draggable', 'false');
  fallback.hidden = true;
  let failed = false;
  image.addEventListener('error', () => {
    if (failed) return;
    failed = true;
    fallback.hidden = false;
    wrapper.replaceChildren(fallback);
  }, { once: true });
  wrapper.append(image, fallback);
  return wrapper;
}
