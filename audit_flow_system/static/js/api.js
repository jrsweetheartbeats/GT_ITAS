import { clearToken, getToken } from './state.js?v=20260630a';

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
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return await res.json();
}

export async function publicJson(path, payload) {
  const res = await fetch(api + path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  if (!res.ok) {
    let detail = await res.text();
    try { detail = JSON.parse(detail).detail || detail; } catch {}
    if (Array.isArray(detail)) detail = detail.map(item => item.msg || item).join('；');
    throw new Error(detail || '请求失败');
  }
  if (res.status === 204) return null;
  return res.json();
}

export async function login(payload) {
  return publicJson('/api/login', payload);
}
