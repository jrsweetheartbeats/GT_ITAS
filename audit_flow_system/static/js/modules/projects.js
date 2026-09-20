import { request } from '../api.js?v=20260920-state12';
import { state } from '../state.js?v=20260920-state12';
import { $, PROJECT_STATUS_OPTIONS, activeProjectId, closeModal, defaultAuditScope, esc, fillSelect, formData, isActiveProjectStatus, openModal, projectStatusLabel, setStatus, statusClass, tag } from '../utils.js?v=20260630b';

export const projectMembersExtension = {
  onProjectSelected(_project, _members) {}
};

let refreshAll = async () => {};
let refreshProjectScoped = async () => {};
let renderWorkpaperTemplateTree = () => {};
const projectClientIssueCache = new Map();

const projectStatusFilterDefault = 'active';

function activeProjectRows() {
  // 顶部项目选择器展示当前账号可见的全部项目，不再按项目状态过滤。
  const seen = new Set();
  return (state.projects || []).filter(project => {
    const key = String(project.id);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function canFeature(module, level = 'view') {
  if (state.me?.is_admin) return true;
  const permission = state.me?.permissions?.[module];
  if (!permission) return false;
  if (level === 'manage') return Boolean(permission.manage);
  if (level === 'edit') return Boolean(permission.edit || permission.manage);
  return Boolean(permission.view || permission.edit || permission.manage);
}

function projectPickerRows(projectId = state.selectedProjectId || activeProjectId()) {
  const rows = activeProjectRows();
  const selected = projectById(projectId);
  if (
    selected
    && Number(state.selectedProjectId || 0) === Number(selected.id)
    && !rows.some(project => Number(project.id) === Number(selected.id))
  ) {
    return [selected, ...rows];
  }
  return rows;
}

function statusOptionsHtml(selected = '') {
  return PROJECT_STATUS_OPTIONS.map(([value, label]) => `<option value="${esc(value)}" ${value === selected ? 'selected' : ''}>${esc(label)}</option>`).join('');
}

function projectListRows() {
  const statusFilter = $('projectStatusFilter') ? $('projectStatusFilter').value : projectStatusFilterDefault;
  const keyword = String($('projectSearchInput')?.value || '').trim().toLowerCase();
  return (state.projects || []).filter(project => {
    if (statusFilter === 'active' && !isActiveProjectStatus(project.status)) return false;
    if (statusFilter && statusFilter !== 'active' && String(project.status || '') !== statusFilter) return false;
    const text = [project.name, project.entity_name, project.code, project.oa_project_no, project.ims_project_no].join(' ').toLowerCase();
    return !keyword || text.includes(keyword);
  });
}

export function setReportPreference(projectId, includeReport) {
  if (!projectId) return;
  localStorage.setItem(`audit_flow_project_report_${projectId}`, includeReport ? '1' : '0');
}

export function reportPreference(project) {
  if (!project) return true;
  const stored = localStorage.getItem(`audit_flow_project_report_${project.id}`);
  return stored === null ? true : stored === '1';
}

function issueProjectYear(projectIssue) {
  const project = state.projects.find(item => Number(item.id) === Number(projectIssue.project_id));
  if (project?.audit_year) return String(project.audit_year);
  const matched = String(projectIssue.project_name || '').match(/20\d{2}/);
  return matched ? matched[0] : '未维护';
}

function severityTone(value) {
  const key = String(value || '').toLowerCase();
  if (['high', '高', '重大'].includes(key)) return 'red';
  if (['medium', '中'].includes(key)) return 'amber';
  if (['low', '低'].includes(key)) return 'blue';
  return 'state-not-started';
}

function clientIssueTrend(data) {
  const counts = new Map();
  (data?.projects || []).forEach(project => {
    const year = issueProjectYear(project);
    counts.set(year, (counts.get(year) || 0) + (project.issues || []).length);
  });
  return Array.from(counts.entries()).sort(([a], [b]) => String(a).localeCompare(String(b)));
}

function topClientIssues(data, limit = 5) {
  const rows = (data?.issues || []).filter(item => item.title || item.description);
  return rows
    .sort((a, b) => {
      const weight = {high: 3, '高': 3, medium: 2, '中': 2, low: 1, '低': 1};
      return (weight[b.severity] || 0) - (weight[a.severity] || 0);
    })
    .slice(0, limit);
}

function clientIssueFocusText(data) {
  const issues = topClientIssues(data, 8);
  if (!issues.length) return '';
  return [
    '历年问题重点关注：',
    ...issues.map((item, index) => `${index + 1}. ${item.project_name || '历史项目'} / ${item.control_code || '未维护控制点'} / ${item.title || item.description || '未命名问题'}${item.severity ? `（${item.severity}）` : ''}`),
  ].join('\n');
}

function renderProjectClientHistoryBox(data = null, {loading = false} = {}) {
  const box = $('projectClientHistoryBox');
  if (!box) return;
  const clientId = Number($('projectClientSelect')?.value || 0);
  if (!clientId) {
    box.classList.add('hidden');
    box.innerHTML = '';
    return;
  }
  box.classList.remove('hidden');
  if (loading) {
    box.innerHTML = '<div class="muted">正在读取该客户历年 C21-1 问题...</div>';
    return;
  }
  if (!data || !(data.project_count || data.issue_count)) {
    box.innerHTML = '<div class="muted">该客户暂无可引用的历年 C21-1 问题。</div>';
    return;
  }
  const trend = clientIssueTrend(data);
  const max = Math.max(1, ...trend.map(([, count]) => count));
  const issues = topClientIssues(data, 5);
  box.innerHTML = `
    <div class="history-box-head">
      <strong>历年问题参考</strong>
      <span>${esc(data.project_count || 0)} 个项目 / ${esc(data.issue_count || 0)} 个问题</span>
      <button class="secondary" type="button" data-project-insert-client-issues>插入重点关注</button>
    </div>
    <div class="issue-trend-bars">
      ${trend.map(([year, count]) => `<div class="issue-trend-bar"><span>${esc(year)}</span><strong style="--bar:${Math.max(6, Math.round(count / max * 100))}%"></strong><em>${esc(count)}</em></div>`).join('')}
    </div>
    <div class="history-issue-list">
      ${issues.map(item => `<div>${tag(item.severity || '未分级', severityTone(item.severity))}<span>${esc(item.project_name || '')} / ${esc(item.control_code || '未维护控制点')} / ${esc(item.title || item.description || '未命名问题')}</span></div>`).join('') || '<span class="muted">暂无可展示问题</span>'}
    </div>
  `;
}

async function loadProjectClientHistory(clientId) {
  if (!clientId) return renderProjectClientHistoryBox();
  if (projectClientIssueCache.has(Number(clientId))) {
    renderProjectClientHistoryBox(projectClientIssueCache.get(Number(clientId)));
    return;
  }
  renderProjectClientHistoryBox(null, {loading: true});
  try {
    const data = await request(`/api/clients/${clientId}/issues`);
    projectClientIssueCache.set(Number(clientId), data);
    renderProjectClientHistoryBox(data);
  } catch (err) {
    renderProjectClientHistoryBox({project_count: 0, issue_count: 0});
    setStatus('客户历史问题读取失败：' + err.message);
  }
}

function insertClientHistoryIntoProjectDescription() {
  const clientId = Number($('projectClientSelect')?.value || 0);
  const data = projectClientIssueCache.get(clientId);
  const text = clientIssueFocusText(data);
  if (!text) return setStatus('该客户暂无可插入的历年问题');
  const field = $('projectForm').querySelector('textarea[name="description"]');
  const current = String(field.value || '').trim();
  field.value = current.includes('历年问题重点关注：') ? current : [current, text].filter(Boolean).join('\n\n');
  setStatus('已插入客户历年问题重点关注');
}

async function openProjectFromClientIssues(clientId) {
  const client = state.clients.find(item => Number(item.id) === Number(clientId));
  setProjectFormMode(null);
  if (clientId) {
    $('projectClientSelect').value = clientId;
    const entityField = $('projectForm').querySelector('input[name="entity_name"]');
    if (client?.entity_name && entityField) entityField.value = client.entity_name;
    await loadProjectClientHistory(clientId);
    insertClientHistoryIntoProjectDescription();
  }
}

export function projectSearchLabel(p) {
  return [
    p.name,
    p.entity_name,
    p.code,
    p.oa_project_no,
    p.ims_project_no,
    p.audit_year,
  ].filter(value => value !== null && value !== undefined && String(value).trim()).join(' / ');
}

function projectById(id) {
  return state.projects.find(project => Number(project.id) === Number(id));
}

export function syncProjectPicker(projectId = state.selectedProjectId || activeProjectId()) {
  const project = projectById(projectId);
  const value = project ? String(project.id) : '';
  if ($('activeProject')) $('activeProject').value = value;
  if ($('projectQuickSelect')) $('projectQuickSelect').value = value;
  if ($('activeProjectSearch')) $('activeProjectSearch').value = project ? projectSearchLabel(project) : '';
}

function renderProjectPickerOptions() {
  const pickerRows = projectPickerRows();
  if ($('projectQuickSelect')) fillSelect($('projectQuickSelect'), pickerRows, p => projectSearchLabel(p), false);
  const options = $('projectOptions');
  if (options) {
    options.innerHTML = pickerRows.map(project => `
      <option value="${esc(projectSearchLabel(project))}" data-project-id="${esc(project.id)}"></option>
    `).join('');
  }
}

async function chooseProjectFromPicker(projectId) {
  if (!projectId) return;
  state.selectedProjectId = Number(projectId);
  syncProjectPicker(projectId);
  void refreshProjectScoped();
}

async function chooseProjectFromSearchValue(value) {
  const text = String(value || '').trim().toLowerCase();
  if (!text) return;
  const option = Array.from($('projectOptions')?.options || []).find(item => item.value.toLowerCase() === text);
  const exactId = option?.dataset.projectId;
  const fuzzyProject = exactId ? null : projectPickerRows().find(project => projectSearchLabel(project).toLowerCase().includes(text));
  const projectId = exactId || fuzzyProject?.id;
  if (!projectId) return setStatus('未找到匹配项目');
  await chooseProjectFromPicker(projectId);
}

function syncProjectEntityFromClient() {
  const form = $('projectForm');
  const field = $('projectEntityName') || form?.querySelector('input[name="entity_name"]');
  if (!field) return;
  const clientId = Number($('projectClientSelect')?.value || 0);
  const client = state.clients.find(item => Number(item.id) === clientId);
  field.value = client?.entity_name || '';
}

function plannedWorkpaperText(rows = []) {
  return rows.map(row => [row.code, row.name, row.stage || 'execution'].join(' | ')).join('\n');
}

function parsePlannedWorkpapers(value = '') {
  return String(value || '').split(/\r?\n/).map(line => line.trim()).filter(Boolean).map(line => {
    const parts = line.split('|').map(item => item.trim());
    return {code: parts[0] || '', name: parts[1] || '', stage: parts[2] || 'execution'};
  }).filter(item => item.code && item.name);
}

async function loadProjectPlannedWorkpapers(projectId) {
  const field = $('plannedWorkpapers');
  if (!field || !projectId) return;
  try {
    const rows = await request(`/api/projects/${projectId}/planned-workpapers`);
    field.value = plannedWorkpaperText(rows);
  } catch (err) {
    setStatus('项目底稿目录读取失败：' + err.message);
  }
}

export function renderProjects() {
  // Rebuilding a <select> resets it to the first option. Preserve the intended
  // project before replacing its options, otherwise any later async render
  // jumps the user back to the newest visible project.
  const intendedProjectId = Number(state.selectedProjectId || activeProjectId() || 0);
  const pickerRows = projectPickerRows(intendedProjectId);
  const current = pickerRows.find(project => Number(project.id) === intendedProjectId)
    || pickerRows[0]
    || null;
  if (current) state.selectedProjectId = Number(current.id);
  fillSelect($('activeProject'), pickerRows, p => projectSearchLabel(p), false);
  renderProjectPickerOptions();
  fillSelect($('priorProjectSelect'), state.projects, p => `${p.name}${p.audit_year ? ' / ' + p.audit_year : ''}`);
  const managers = state.users.filter(u => ['manager', 'senior_manager', 'admin'].includes(u.role_code));
  const projectLeaders = state.users.filter(u => ['senior_manager', 'director', 'quality', 'partner', 'admin'].includes(u.role_code));
  fillSelect($('projectLeaderSelect'), projectLeaders, u => u.display_name);
  fillSelect($('projectManagerSelect'), managers, u => u.display_name);
  fillSelect($('qualityReviewerSelect'), state.users.filter(u => ['quality', 'manager', 'senior_manager', 'director', 'partner', 'admin'].includes(u.role_code)), u => u.display_name, false);
  fillSelect($('fieldLeaderSelect'), state.users, u => u.display_name);
  fillSelect($('partnerReviewerSelect'), state.users.filter(u => ['partner', 'admin'].includes(u.role_code)), u => u.display_name);
  fillSelect($('memberUserSelect'), state.users, u => u.display_name);
  const visibleProjects = projectListRows();
  if (current) syncProjectPicker(current.id);
  if ($('openProjectModalBtn')) $('openProjectModalBtn').disabled = !canFeature('projects', 'edit');
  if ($('openMemberModalBtn')) $('openMemberModalBtn').disabled = current ? !(current.can_edit && canFeature('projects', 'edit')) : true;
  $('projectRows').innerHTML = visibleProjects.map(p => `
    <tr class="selectable-row ${p.id === state.selectedProjectId ? 'selected-row' : ''}" data-project-row="${esc(p.id)}">
      <td>${p.id}</td>
      <td><strong>${esc(p.name)}</strong><div class="muted">${esc(p.entity_name || '')}</div></td>
      <td>${esc(p.code || '')}<div class="muted">OA:${esc(p.oa_project_no || '')} IMS:${esc(p.ims_project_no || '')}</div></td>
      <td>${tag(projectStatusLabel(p.status), statusClass(p.status))}</td>
      <td>${esc(p.audit_scope_start || '')} 至 ${esc(p.audit_scope_end || '')}</td>
      <td><div>负责人：${esc(p.project_leader_name || '')}</div><div class="muted">经理：${esc(p.manager_name || '')}</div></td>
      <td>${reportPreference(p) ? tag('需要报告', 'green') : tag('不出报告', 'amber')}</td>
      <td class="actions">
        <button class="secondary" data-project-action="select" data-project-id="${esc(p.id)}">切换</button>
        <button class="secondary" data-project-action="edit" data-project-id="${esc(p.id)}" ${p.can_edit && canFeature('projects', 'edit') ? '' : 'disabled'}>编辑</button>
        <button class="danger" data-project-action="delete" data-project-id="${esc(p.id)}" ${p.can_edit && canFeature('projects', 'manage') ? '' : 'disabled'}>删除</button>
        ${p.can_edit && canFeature('projects', 'edit') ? tag('可编辑', 'green') : tag('只读', 'amber')}
      </td>
    </tr>
  `).join('') || '<tr><td colspan="8" class="empty">暂无项目</td></tr>';
  renderProjectSnapshot();
  renderWorkpaperTemplateTree();
}

export function setProjectFormMode(project = null) {
  const form = $('projectForm');
  state.editingProjectId = project ? project.id : null;
  $('projectModalTitle').textContent = project ? `编辑项目 #${project.id}` : '新增项目';
  $('projectSubmitBtn').textContent = project ? `保存修改 #${project.id}` : '保存项目';
  openModal('projectModal');
  if (!project) {
    form.reset();
    const [scopeStart, scopeEnd] = defaultAuditScope();
    $('auditScopeStart').value = scopeStart;
    $('auditScopeEnd').value = scopeEnd;
    form.elements.status.value = 'in_progress';
    const leader = state.users.find(user => user.display_name === '任德昀');
    const partner = state.users.find(user => user.display_name === '任德昀');
    if (leader) $('projectLeaderSelect').value = String(leader.id);
    if (partner) $('partnerReviewerSelect').value = String(partner.id);
    const qualityIds = new Set(state.users.filter(user => ['占志权', '闫晓濛'].includes(user.display_name)).map(user => Number(user.id)));
    Array.from($('qualityReviewerSelect')?.options || []).forEach(option => { option.selected = qualityIds.has(Number(option.value)); });
    $('projectNeedReport').checked = true;
    syncProjectEntityFromClient();
    renderProjectClientHistoryBox();
    if ($('plannedWorkpapers')) $('plannedWorkpapers').value = '';
    return;
  }
  for (const [key, value] of Object.entries(project)) {
    if (form.elements[key]) form.elements[key].value = value ?? '';
  }
  const qualityIds = new Set((project.quality_reviewer_user_ids || [project.quality_reviewer_user_id].filter(Boolean)).map(Number));
  Array.from($('qualityReviewerSelect')?.options || []).forEach(option => { option.selected = qualityIds.has(Number(option.value)); });
  $('projectNeedReport').checked = reportPreference(project);
  syncProjectEntityFromClient();
  loadProjectClientHistory(project.client_id);
  loadProjectPlannedWorkpapers(project.id);
}

export function renderProjectSnapshot() {
  if (!$('projectSnapshot')) return;
  const p = state.projects.find(row => row.id === activeProjectId());
  $('projectSnapshot').innerHTML = p ? `
    <div class="form-grid">
      <div><strong>${esc(p.name)}</strong> ${tag(projectStatusLabel(p.status), statusClass(p.status))}</div>
      <div class="muted">编号：${esc(p.code || '未维护')}</div>
      <div class="muted">OA/IMS：${esc(p.oa_project_no || '未维护')} / ${esc(p.ims_project_no || '未维护')}</div>
      <div class="muted">单位：${esc(p.entity_name || '未维护')}</div>
      <div class="muted">年度：${esc(p.audit_year || '未维护')}</div>
      <div class="muted">审计范围：${esc(p.audit_scope_start || '')} 至 ${esc(p.audit_scope_end || '')}</div>
      <div class="muted">项目负责人/经理：${esc(p.project_leader_name || '')} / ${esc(p.manager_name || '')}</div>
      <div class="muted">根目录：${esc(p.project_root || '未维护')}</div>
    </div>
  ` : '<div class="empty">暂无当前项目</div>';
}

export function renderMembers() {
  const project = state.projects.find(p => p.id === state.selectedProjectId) || state.projects.find(p => p.id === activeProjectId());
  const canEditMembers = Boolean(project?.can_edit && canFeature('projects', 'edit'));
  if ($('memberPanelTitle')) {
    $('memberPanelTitle').textContent = project ? `项目成员 / ${project.name || `项目 #${project.id}`}` : '项目成员';
  }
  $('memberRows').innerHTML = state.members.map(m => `
    <tr><td>${esc(m.display_name || m.username || '')}</td><td>${esc(m.role_on_project || '')}</td><td>${esc(m.module || '')}</td><td>${esc(m.workload || '')}</td><td><button class="danger" data-member-delete="${esc(m.id)}" ${canEditMembers ? '' : 'disabled'}>删除</button></td></tr>
  `).join('') || '<tr><td colspan="5" class="empty">暂无项目成员</td></tr>';
  projectMembersExtension.onProjectSelected(project, state.members);
}

async function selectProject(id) {
  state.selectedProjectId = Number(id);
  await chooseProjectFromPicker(id);
}

async function selectProjectMembers(id) {
  state.selectedProjectId = Number(id);
  try {
    state.members = await request(`/api/projects/${id}/members`);
    renderProjects();
    renderMembers();
    setStatus('就绪');
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

function editProject(id) {
  const project = state.projects.find(p => p.id === id);
  if (!project) return setStatus('项目不存在');
  setProjectFormMode(project);
  window.activateAppSection?.('projects');
  setStatus(`正在编辑项目 #${id}`);
}

async function deleteProject(id) {
  if (!confirm('确认删除该项目？相关项目成员、底稿、附件和资料清单会一起删除。')) return;
  try {
    await request(`/api/projects/${id}`, {method: 'DELETE'});
    if (state.editingProjectId === id) setProjectFormMode(null);
    await refreshAll();
  } catch (err) { setStatus('错误：' + err.message); }
}

async function deleteMember(id) {
  if (!confirm('确认删除该项目成员？')) return;
  try {
    await request(`/api/members/${id}`, {method: 'DELETE'});
    await refreshProjectScoped();
  } catch (err) { setStatus('错误：' + err.message); }
}

export function bindProjects(options) {
  refreshAll = options.refreshAll;
  refreshProjectScoped = options.refreshProjectScoped;
  renderWorkpaperTemplateTree = options.renderWorkpaperTemplateTree;

  $('activeProject').addEventListener('change', async () => {
    await chooseProjectFromPicker($('activeProject').value);
  });
  $('projectQuickSelect')?.addEventListener('change', async () => {
    await chooseProjectFromPicker($('projectQuickSelect').value);
  });
  $('activeProjectSearch')?.addEventListener('change', async () => {
    await chooseProjectFromSearchValue($('activeProjectSearch').value);
  });
  $('activeProjectSearch')?.addEventListener('keydown', async event => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    await chooseProjectFromSearchValue(event.currentTarget.value);
  });
  $('openProjectModalBtn').addEventListener('click', () => setProjectFormMode(null));
  $('openMemberModalBtn').addEventListener('click', () => openModal('memberModal'));
  $('resetProjectFormBtn').addEventListener('click', () => setProjectFormMode(null));
  $('projectClientSelect')?.addEventListener('change', (event) => {
    syncProjectEntityFromClient();
    loadProjectClientHistory(Number(event.target.value || 0));
  });
  $('projectClientHistoryBox')?.addEventListener('click', (event) => {
    if (event.target.closest('[data-project-insert-client-issues]')) insertClientHistoryIntoProjectDescription();
  });
  $('projectStatusFilter')?.addEventListener('change', renderProjects);
  $('projectSearchInput')?.addEventListener('input', renderProjects);
  $('projectRows').addEventListener('click', (event) => {
    const button = event.target.closest('[data-project-action]');
    if (button) {
      const id = Number(button.dataset.projectId);
      if (button.dataset.projectAction === 'select') selectProject(id).then(() => window.activateAppSection?.('projectWorkspace'));
      if (button.dataset.projectAction === 'edit') editProject(id);
      if (button.dataset.projectAction === 'delete') deleteProject(id);
      return;
    }
    const row = event.target.closest('[data-project-row]');
    if (row) selectProjectMembers(Number(row.dataset.projectRow));
  });
  $('memberRows').addEventListener('click', (event) => {
    const button = event.target.closest('[data-member-delete]');
    if (button) deleteMember(Number(button.dataset.memberDelete));
  });
  $('projectForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const data = formData(e.target);
      const plannedWorkpapers = parsePlannedWorkpapers(data.planned_workpapers);
      delete data.planned_workpapers;
      data.quality_reviewer_user_ids = Array.from($('qualityReviewerSelect')?.selectedOptions || []).map(option => Number(option.value));
      // Keep the legacy single-value field for a rolling deployment where an
      // existing application process may still be serving the old schema.
      data.quality_reviewer_user_id = data.quality_reviewer_user_ids[0] || null;
      syncProjectEntityFromClient();
      data.entity_name = $('projectEntityName')?.value || data.entity_name || '';
      const includeReport = $('projectNeedReport').checked;
      let savedProject = null;
      if (state.editingProjectId) {
        savedProject = await request(`/api/projects/${state.editingProjectId}`, {method: 'PATCH', body: JSON.stringify(data)});
        setReportPreference(state.editingProjectId, includeReport);
      } else {
        savedProject = await request('/api/projects', {method: 'POST', body: JSON.stringify(data)});
        setReportPreference(savedProject?.id, includeReport);
      }
      if (savedProject?.id) {
        state.workpaperPreviews = {};
        state.workpaperTreeByProject[savedProject.id] = null;
        $('activeProject').value = savedProject.id;
        await request(`/api/projects/${savedProject.id}/planned-workpapers`, {method: 'PUT', body: JSON.stringify({items: plannedWorkpapers})});
      }
      e.target.reset();
      closeModal('projectModal');
      state.editingProjectId = null;
      await refreshAll();
      const generated = Number(savedProject?.workspace?.workpapers_created || savedProject?.template_workpapers_created || 0);
      setStatus(generated ? `项目已保存，已生成 ${generated} 份基础底稿并写入项目主数据` : '项目主数据已保存，底稿定位预览已刷新');
    } catch (err) { setStatus('错误：' + err.message); }
  });
  $('memberForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const pid = state.selectedProjectId || activeProjectId();
    if (!pid) return setStatus('请先选择项目');
    try {
      await request(`/api/projects/${pid}/members`, {method: 'POST', body: JSON.stringify(formData(e.target))});
      e.target.reset();
      closeModal('memberModal');
      await refreshProjectScoped();
    } catch (err) { setStatus('错误：' + err.message); }
  });

  window.selectProject = selectProject;
  window.editProject = editProject;
  window.openProjectFromClientIssues = openProjectFromClientIssues;
  window.deleteProject = deleteProject;
  window.deleteMember = deleteMember;
}
