function fromCookie() {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : '';
}

export function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta && meta.getAttribute('content')) {
    return meta.getAttribute('content');
  }

  const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
  if (input && input.value) {
    return input.value;
  }

  return fromCookie();
}

export function csrfHeaders(extra = {}) {
  return {
    'X-CSRFToken': getCsrfToken(),
    ...extra,
  };
}
