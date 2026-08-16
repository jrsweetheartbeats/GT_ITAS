export const $ = (id) => document.getElementById(id);

export const esc = (v) => String(v ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));

export const tag = (text, cls = '') => `<span class="tag ${cls}">${esc(text)}</span>`;

export const PROJECT_STATUS_OPTIONS = [
  ['in_progress', '正在执行'],
  ['planning', '计划中'],
  ['paused', '暂停'],
  ['completed', '已完成'],
  ['archived', '已归档'],
];

export const ACTIVE_PROJECT_STATUSES = new Set(['in_progress', 'active', 'running', '进行中', '正在执行']);

export function projectStatusLabel(status) {
  const value = String(status || '').trim();
  return Object.fromEntries(PROJECT_STATUS_OPTIONS)[value] || value || '未维护';
}

export function isActiveProjectStatus(status) {
  return ACTIVE_PROJECT_STATUSES.has(String(status || '').trim());
}

export function statusClass(s) {
  const value = String(s || '').toLowerCase();
  if (['completed', 'approved', 'resolved', 'uploaded', 'done', '已完成', '已解决'].includes(value)) return 'state-done';
  if (['closed', 'archived', '已关闭', '已归档'].includes(value)) return 'state-closed';
  if (['failed', 'returned', 'blocked', 'open', 'retained', 'revised', 'paused', '待处理', '保留', '已修订', '有问题', '暂停'].includes(value)) return 'state-risk';
  if (['assigned', 'submitted', 'running', 'in_progress', 'active', '进行中', '正在执行', '已分派'].includes(value)) return 'state-running';
  return 'state-not-started';
}

export const planRowClass = (s) => s === 'blocked' ? 'blocked-row' : s === 'changed' ? 'changed-row' : s === 'skipped' ? 'skipped-row' : '';

export function openModal(id) {
  const el = $(id);
  if (!el) return;
  el.classList.add('open');
  el.setAttribute('aria-hidden', 'false');
}

export function closeModal(id) {
  const el = $(id);
  if (!el) return;
  el.classList.remove('open');
  el.setAttribute('aria-hidden', 'true');
}

export function setStatus(text) {
  $('status').textContent = text;
}

export function formData(form) {
  const data = Object.fromEntries(new FormData(form).entries());
  for (const key of Object.keys(data)) {
    if (data[key] === '') data[key] = null;
  }
  for (const key of ['audit_year', 'prior_project_id', 'role_id', 'preparer_user_id', 'workpaper_id', 'client_id', 'project_id', 'project_leader_user_id', 'manager_user_id', 'quality_reviewer_user_id', 'field_leader_user_id', 'owner_user_id', 'assignee_user_id', 'user_id', 'request_id', 'run_id']) {
    if (key in data) data[key] = data[key] === null ? null : Number(data[key]);
  }
  return data;
}

export function activeProjectId() {
  const value = $('activeProject').value;
  return value ? Number(value) : null;
}

export function fillSelect(el, rows, label, includeBlank = true) {
  el.innerHTML = includeBlank ? '<option value="">未选择</option>' : '';
  rows.forEach(row => {
    const option = document.createElement('option');
    option.value = row.id;
    option.textContent = label(row);
    el.appendChild(option);
  });
}

export function defaultAuditScope() {
  const now = new Date();
  const year = now.getMonth() + 1 >= 10 ? now.getFullYear() : now.getFullYear() - 1;
  return [`${year}-01-01`, `${year}-12-31`];
}

export function cleanClientDescription(value) {
  const text = String(value || '').trim();
  if (!text) return '';
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === 'object') {
      const readableKeys = ['description', 'name', 'label', 'industry', 'type', 'title'];
      for (const key of readableKeys) {
        const readable = parsed[key];
        if (typeof readable === 'string' && readable.trim()) return readable.trim();
      }
      return '';
    }
  } catch {}
  return text;
}
