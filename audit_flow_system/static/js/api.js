import { clearToken, getToken } from './state.js?v=20260920-state12';

export const api = location.origin;

let unauthorizedHandler = () => {};

export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler || (() => {});
}

export function authHeaders() {
  const token = getToken();
  return token ? {Authorization: `Bearer ${token}`} : {};
}

export async function request(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const headers = isFormData
    ? {...authHeaders(), ...(options.headers || {})}
    : {'Content-Type': 'application/json', ...authHeaders(), ...(options.headers || {})};
  const res = await fetch(api + path, {
    headers,
    ...options
  });
  if (!res.ok) {
    if (res.status === 401) {
      clearToken();
      unauthorizedHandler();
    }
    let detail = await res.text();
    try { detail = JSON.parse(detail).detail || detail; } catch {}
    const message = detail && typeof detail === 'object' ? (detail.message || JSON.stringify(detail)) : detail;
    const error = new Error(message);
    error.detail = detail;
    throw error;
  }
  if (res.status === 204) return null;
  return await res.json();
}

export async function login(payload) {
  return postPublic('/api/login', payload);
}

export async function postPublic(path, payload) {
  const res = await fetch(api + path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error((await res.json()).detail || '请求失败');
  return res.json();
}
