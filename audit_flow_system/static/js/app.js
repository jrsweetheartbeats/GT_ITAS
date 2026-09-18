import { login, publicJson, request, setUnauthorizedHandler } from './api.js?v=20260908-password1';
import { clearToken, defaultModuleOrder, setToken, state } from './state.js?v=20260630a';
import { $, activeProjectId, closeModal, esc, fillSelect, formData, openModal, setStatus, tag } from './utils.js?v=20260630b';
import { bindClients, openNewClientForm, renderClients } from './modules/clients.js?v=20260707a';
import { bindProjects, renderMembers, renderProjectSnapshot, renderProjects, setProjectFormMode, syncProjectPicker } from './modules/projects.js?v=20260905-project-switch1';
import { bindWorkpapers, loadWorkpaperTree, renderWorkpaperTemplateTree, renderWorkpapers } from './modules/workpapers.js?v=20260906-p1-review1';
import { bindMaterials, renderAttachments, renderMaterials } from './modules/materials.js?v=20260627a';
import { bindReview, renderAutofillRuns, renderAutofillSummary, renderRuns } from './modules/review.js?v=20260823-deepseek1';
import { bindRuleInspection, loadRuleInspection } from './modules/ruleInspection.js';
import { bindRuleVisualization, loadRuleVisualization } from './modules/ruleVisualization.js?v=20260701a';
import { bindQualityModules, closeQualityFindingDrawer, openQualityFinding, refreshQualityModules, refreshQualityReviewData, renderQualityModules } from './modules/quality.js?v=20260907-drawer-draft1';
import { renderDashboardHub, renderProjectContext, renderProjectWorkspace } from './modules/projectWorkspace.js?v=20260707b';
import { bindWorkflowPrototype, loadWorkflowPrototypeData, refreshWorkflowReviewCenterData, renderWorkflowPrototype } from './modules/workflowPrototype.js?v=20260906-review-fix5';
import { bindLearning, loadLearning } from './modules/learning.js?v=20260820a';
import { bindDevelopmentOverview, loadDevelopmentOverview, loadLearner } from './modules/developmentOverview.js?v=20260918-training-role1';
import { bindMentorWorkbench } from './modules/mentorWorkbench.js?v=20260821-mentor1';

let projectScopedRefreshSeq = 0;
const TRAINING_MANAGER_ROLES = new Set(['admin', 'partner', 'quality', 'director', 'senior_manager', 'manager']);

function canManageTraining() {
  return Boolean(state.me?.is_admin || TRAINING_MANAGER_ROLES.has(state.me?.role_code));
}

async function refreshReviewData({projectScoped = false, focusFindingId} = {}) {
  const requests = [
    refreshQualityReviewData({focusFindingId}),
    refreshWorkflowReviewCenterData(),
  ];
  if (projectScoped) requests.push(refreshProjectScoped());
  const results = await Promise.allSettled(requests);
  const sourceResults = results.flatMap(result => result.status === 'fulfilled' && Array.isArray(result.value) ? result.value : [result]);
  try {
    renderWorkflowPrototype();
    renderQualityModules();
  } catch (err) {
    sourceResults.push({status: 'rejected', reason: err});
  }
  return sourceResults;
}

function withTimeout(promise, ms, label, {soft = false} = {}) {
  return Promise.race([
    promise,
    new Promise((resolve, reject) => window.setTimeout(() => {
      const error = new Error(`${label}加载超时`);
      if (soft) {
        resolve({__timedOut: true, error});
      } else {
        reject(error);
      }
    }, ms)),
  ]);
}

function showLogin() {
  $('loginScreen').classList.remove('hidden');
  $('appShell').classList.add('hidden');
}

function showApp() {
  $('loginScreen').classList.add('hidden');
  $('appShell').classList.remove('hidden');
}

function canAccessModule(module, level = 'view') {
  if (state.me?.is_admin) return true;
  const permission = state.me?.permissions?.[module];
  if (!permission) return false;
  if (level === 'manage') return Boolean(permission.manage);
  if (level === 'edit') return Boolean(permission.edit || permission.manage);
  return Boolean(permission.view || permission.edit || permission.manage);
}

function applyAuthUi() {
  const admin = Boolean(state.me?.is_admin);
  const trainingManagers = new Set(['admin', 'partner', 'quality', 'director', 'senior_manager', 'manager']);
  const canManageTraining = admin || trainingManagers.has(state.me?.role_code);
  document.querySelectorAll('[data-admin-only="true"]').forEach(el => el.classList.toggle('hidden', !admin));
  const can = canAccessModule;
  document.querySelectorAll('#nav button[data-tab]').forEach(button => {
    const module = button.dataset.tab;
    button.classList.toggle('hidden', module !== 'dashboard' && !can(module, 'view'));
  });
  document.querySelectorAll('[data-project-section]').forEach(button => {
    button.classList.toggle('hidden', !can(button.dataset.projectSection, 'view'));
  });
  document.querySelectorAll('[data-board-section]').forEach(button => {
    button.classList.toggle('hidden', !can(button.dataset.boardSection, 'view'));
  });
  document.querySelectorAll('[data-system-section]').forEach(button => {
    button.classList.toggle('hidden', !can(button.dataset.systemSection, 'view'));
  });
  document.querySelectorAll('[data-dashboard-section]').forEach(button => {
    button.classList.toggle('hidden', !can(button.dataset.dashboardSection, 'view'));
  });
  document.querySelectorAll('#developmentTabs [data-development-view]').forEach(button => {
    const isMine = button.dataset.developmentView === 'mine';
    button.classList.toggle('hidden', !canManageTraining && !isMine);
    if (!canManageTraining && isMine) button.classList.add('active');
  });
  document.querySelectorAll('[data-development-action="import"], [data-development-action="new-employee"]').forEach(button => {
    button.classList.toggle('hidden', !canManageTraining);
    button.disabled = !canManageTraining;
  });
  const activePrimary = primaryForSection(state.activeSection || 'dashboard');
  if (activePrimary !== 'dashboard' && !can(activePrimary, 'view')) {
    activateSection(can('projectWorkspace', 'view') ? 'projectWorkspace' : 'dashboard');
  }
  document.querySelectorAll('[data-dashboard-action="new-project"], #openProjectModalBtn').forEach(button => {
    button.disabled = !can('projects', 'edit');
  });
  document.querySelectorAll('#newClientBtn').forEach(button => {
    button.disabled = !can('clients', 'edit');
  });
  $('currentUser').textContent = state.me ? `${state.me.display_name || state.me.username} / ${state.me.role_name || ''}` : '';
  activateSection(state.activeSection || 'dashboard');
}

function moduleLabel(tab) {
  const labels = {
    dashboard: '项目监控',
    projectWorkspace: '项目执行',
    scopeCenter: '审计范围',
    pbcCenter: 'PBC资料',
    workpaperExecution: '底稿详情',
    autoCheck: '自动检核',
    reviewCenter: '复核中心',
    findingKanban: '问题整改',
    qualityDashboard: '复核质控',
    issueDashboard: '问题看板',
    resourcePlan: '人员计划',
    architecture: '功能架构',
    templates: '模板规则',
    learning: '学习刷题',
    config: '系统管理',
  };
  const button = document.querySelector(`#nav button[data-tab="${tab}"]`);
  return button ? button.textContent.trim() : labels[tab] || tab;
}

function normalizeModuleOrder(order) {
  const rawOrder = Array.isArray(order) ? order.map(String) : [];
  if (rawOrder.some(tab => !defaultModuleOrder.includes(tab))) return defaultModuleOrder.slice();
  const seen = new Set(['dashboard']);
  const normalized = ['dashboard'];
  rawOrder.forEach(tab => {
    if (tab !== 'dashboard' && defaultModuleOrder.includes(tab) && !seen.has(tab)) {
      seen.add(tab);
      normalized.push(tab);
    }
  });
  defaultModuleOrder.forEach(tab => {
    if (!seen.has(tab)) normalized.push(tab);
  });
  return normalized;
}

function applyModuleOrder() {
  state.moduleOrder = normalizeModuleOrder(state.moduleOrder);
  const nav = $('nav');
  state.moduleOrder.forEach(tab => {
    const button = nav.querySelector(`button[data-tab="${tab}"]`);
    if (button) nav.appendChild(button);
  });
  renderModuleOrder();
}

function renderModuleOrder() {
  const list = $('moduleOrderList');
  if (!list) return;
  list.innerHTML = state.moduleOrder.map((tab, index) => `
    <div class="actions" style="align-items:center;justify-content:space-between;border:1px solid var(--line);border-radius:6px;padding:8px;background:#fbfcfd">
      <strong>${esc(moduleLabel(tab))}</strong>
      <span class="actions">
        <button type="button" class="secondary" data-module-move="${esc(tab)}" data-module-delta="-1" ${index === 0 ? 'disabled' : ''}>上移</button>
        <button type="button" class="secondary" data-module-move="${esc(tab)}" data-module-delta="1" ${index === state.moduleOrder.length - 1 ? 'disabled' : ''}>下移</button>
      </span>
    </div>
  `).join('');
}

function renderOverview(data) {
  if ($('sMyProjects')) $('sMyProjects').textContent = data.projects;
  if ($('sMyOpenFindings')) $('sMyOpenFindings').textContent = data.open_findings;
}

function renderPeople() {
  fillSelect($('userRoleSelect'), state.roles, r => r.name);
  fillSelect($('preparerSelect'), state.users, u => u.display_name);
  $('userRows').innerHTML = state.users.map(u => `
    <tr>
      <td>${u.id}</td>
      <td>${esc(u.username)}</td>
      <td>${esc(u.display_name)}<div class="muted">${esc(u.email || '')} ${esc(u.phone || '')}</div></td>
      <td>${esc(u.role_name || '')}</td>
      <td>${tag(u.status, u.status === 'active' ? 'green' : 'amber')}</td>
      <td><button class="danger" data-user-delete="${esc(u.id)}" ${u.username === 'admin' ? 'disabled' : ''}>删除</button></td>
    </tr>
  `).join('') || '<tr><td colspan="6" class="empty">暂无用户</td></tr>';
  $('roleRows').innerHTML = state.roles.map(r => `
    <tr>
      <td>${esc(r.code)}</td>
      <td>${esc(r.name)}</td>
      <td>${r.rank}</td>
      <td>${r.can_review ? tag('是', 'green') : tag('否')}</td>
      <td>${esc(r.description)}</td>
      <td><button class="danger" data-role-delete="${esc(r.id)}" ${r.code === 'admin' ? 'disabled' : ''}>删除</button></td>
    </tr>
  `).join('');
}

async function loadPasswordPolicy() {
  if (!state.me?.is_admin) return;
  try {
    const policy = await request('/api/config/password-policy');
    const form = $('passwordPolicyForm');
    form.min_length.value = policy.min_length ?? 3;
    form.require_digit.checked = Boolean(policy.require_digit);
    form.require_upper.checked = Boolean(policy.require_upper);
    form.require_special.checked = Boolean(policy.require_special);
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

function renderAutofillScopeConfig(config = state.autofillScopeConfig || {}) {
  const box = $('autofillScopeConfigFields');
  if (!box) return;
  const rows = config.field_groups || [];
  box.innerHTML = rows.map(row => `
    <label>
      <input type="checkbox" name="enabled_keys" value="${esc(row.key)}" ${row.enabled ? 'checked' : ''}>
      <span>${esc(row.label)}</span>
    </label>
  `).join('') || '<div class="empty">暂无可配置字段</div>';
}

const PROJECT_PAYLOAD_FIELDS = [
  'name',
  'code',
  'oa_project_no',
  'ims_project_no',
  'client_id',
  'entity_name',
  'audit_year',
  'audit_scope_start',
  'audit_scope_end',
  'status',
  'project_leader_user_id',
  'manager_user_id',
  'quality_reviewer_user_id',
  'field_leader_user_id',
  'first_partner_name',
  'first_partner_email',
  'first_partner_phone',
  'second_partner_name',
  'second_partner_email',
  'second_partner_phone',
  'start_date',
  'end_date',
  'prior_project_id',
  'project_root',
  'description',
];
const PROJECT_STRING_FIELDS = new Set([
  'name',
  'code',
  'oa_project_no',
  'ims_project_no',
  'entity_name',
  'status',
  'first_partner_name',
  'first_partner_email',
  'first_partner_phone',
  'second_partner_name',
  'second_partner_email',
  'second_partner_phone',
  'project_root',
  'description',
]);

function projectPatchPayload(project, overrides = {}) {
  const payload = {};
  for (const field of PROJECT_PAYLOAD_FIELDS) {
    const value = project[field];
    payload[field] = value ?? (PROJECT_STRING_FIELDS.has(field) ? '' : null);
  }
  return {...payload, ...overrides};
}

function mergeProjectState(project) {
  if (!project?.id) return;
  const index = state.projects.findIndex(item => Number(item.id) === Number(project.id));
  if (index >= 0) state.projects[index] = {...state.projects[index], ...project};
  else state.projects.unshift(project);
  renderProjects();
  syncProjectPicker(project.id);
  renderProjectSnapshot();
  renderProjectWorkspace();
  renderDashboardHub();
  renderWorkflowPrototype();
}

async function saveProjectAuditScope(projectId) {
  const project = state.projects.find(item => Number(item.id) === Number(projectId));
  if (!project) return setStatus('项目不存在');
  const start = document.querySelector(`[data-project-scope-start="${projectId}"]`)?.value || '';
  const end = document.querySelector(`[data-project-scope-end="${projectId}"]`)?.value || '';
  if (!start || !end) return setStatus('请填写完整审计范围');
  if (start > end) return setStatus('审计范围开始日期不能晚于结束日期');
  setStatus('正在保存审计范围');
  try {
    const saved = await request(`/api/projects/${projectId}`, {
      method: 'PATCH',
      body: JSON.stringify(projectPatchPayload(project, {
        audit_year: Number(end.slice(0, 4)) || project.audit_year,
        audit_scope_start: start,
        audit_scope_end: end,
      })),
    });
    mergeProjectState(saved);
    setStatus(`审计范围已更新：${start} 至 ${end}`);
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

async function inferProjectAuditScope(projectId) {
  setStatus('正在从底稿首页识别审计范围');
  try {
    const saved = await request(`/api/projects/${projectId}/audit-scope/infer`, {method: 'POST'});
    mergeProjectState(saved);
    setStatus(`已按底稿识别范围：${saved.audit_scope_start || '未维护'} 至 ${saved.audit_scope_end || '未维护'}`);
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

async function loadAutofillScopeConfig() {
  if (!state.me?.is_admin) return;
  try {
    state.autofillScopeConfig = await request('/api/config/autofill-scope');
    renderAutofillScopeConfig(state.autofillScopeConfig);
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

async function loadModuleOrder() {
  try {
    const data = await request('/api/config/module-order');
    state.moduleOrder = normalizeModuleOrder(data.order);
    applyModuleOrder();
  } catch (err) {
    state.moduleOrder = defaultModuleOrder.slice();
    applyModuleOrder();
  }
}

function loadDeferredStartupData() {
  void loadPasswordPolicy();
  void loadAutofillScopeConfig();
  void refreshProjectScoped();
  void refreshQualityModules().then(() => {
    renderProjectWorkspace();
    renderDashboardHub();
    renderWorkflowPrototype();
  });
  void loadWorkflowPrototypeData({silent: true}).then(() => {
    renderProjects();
    renderProjectWorkspace();
    renderDashboardHub();
    renderWorkflowPrototype();
  });
  if (state.me?.is_admin || state.me?.permissions?.learning?.view || state.me?.permissions?.learning?.edit || state.me?.permissions?.learning?.manage) {
    void loadLearning({silent: true});
  }
}

export async function refreshAll() {
  setStatus('加载中');
  try {
    const [overview, roles, users, clients, projects] = await Promise.all([
      request('/api/overview'),
      request('/api/roles'),
      request('/api/users'),
      request('/api/clients'),
      request('/api/projects')
    ]);
    state.roles = roles;
    state.users = users;
    state.clients = clients;
    state.projects = projects;
    await loadModuleOrder();
    renderOverview(overview);
    renderClients();
    renderProjects();
    renderPeople();
    renderProjectWorkspace();
    renderDashboardHub();
    renderWorkflowPrototype();
    applyAuthUi();
    setStatus('基础数据已加载，项目明细后台加载中');
    loadDeferredStartupData();
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

export async function refreshProjectScoped() {
  const pid = activeProjectId();
  const sameProject = Number(state.selectedProjectId) === Number(pid);
  if (!sameProject) closeQualityFindingDrawer();
  const preservedWorkpaperId = sameProject ? state.selectedWorkpaperId : null;
  const preservedWorkpaperTreeNode = sameProject ? state.selectedWorkpaperTreeNode : null;
  const refreshSeq = ++projectScopedRefreshSeq;
  state.selectedProjectId = pid;
  syncProjectPicker(pid);
  state.projectScopedLoading = Boolean(pid);
  state.members = [];
  state.workpapers = [];
  state.workpaperHeaderBatch = null;
  state.attachments = [];
  state.materials = [];
  state.runs = [];
  state.autofillRuns = [];
  state.selectedWorkpaperTreeNode = preservedWorkpaperTreeNode;
  state.selectedWorkpaperId = preservedWorkpaperId;
  state.reviewStepsByWorkpaper = {};
  $('suggestionRows').innerHTML = '<tr><td colspan="6" class="empty">请先生成建议</td></tr>';
  $('planRows').innerHTML = '<tr><td colspan="9" class="empty">请先预览写入计划</td></tr>';
  $('suggestionSummary').textContent = '根据当前项目附件索引和文件名匹配 C22/B 类底稿填写规则。写回前请先预览计划并检查 blocked 项。';
  $('scanRows').innerHTML = '<tr><td colspan="6" class="empty">请先扫描项目根目录</td></tr>';
  $('scanSummary').textContent = '扫描项目根目录后可预览将登记的附件，确认登记后会生成统一索引号。';
  $('attScanPanel')?.classList.add('hidden');
  $('materialRequestPanel')?.classList.add('hidden');
  ['importAttachmentsBtn', 'applyRefsBtn'].forEach(id => {
    const button = $(id);
    if (button) {
      button.classList.add('hidden');
      button.disabled = true;
    }
  });
  renderAutofillSummary({suggestion_count: 0, summary: {}});
  renderProjectSnapshot();
  renderWorkpaperTemplateTree();
  renderMembers();
  renderWorkpapers();
  renderAttachments();
  renderMaterials();
  renderRuns();
  renderAutofillRuns();
  renderQualityModules();
  renderProjectWorkspace();
  renderDashboardHub();
  renderWorkflowPrototype();
  if (!pid) {
    state.projectScopedLoading = false;
    setStatus('就绪');
    return;
  }
  setStatus('加载项目数据');
  const isCurrentRefresh = () => refreshSeq === projectScopedRefreshSeq && activeProjectId() === pid;
  const failures = [];
  const loadPiece = async (label, loader, apply) => {
    try {
      const data = await loader();
      if (!isCurrentRefresh()) return;
      apply(data);
    } catch (err) {
      if (isCurrentRefresh()) failures.push(`${label}：${err.message}`);
    }
  };
  const applyWorkpapers = (data) => {
    state.workpapers = data;
    if (preservedWorkpaperId && !data.some(item => Number(item.id) === Number(preservedWorkpaperId))) {
      state.selectedWorkpaperId = null;
      state.selectedWorkpaperTreeNode = null;
    }
    renderWorkpaperTemplateTree();
    renderWorkpapers();
    renderAttachments();
    renderProjectWorkspace();
    renderDashboardHub();
    renderWorkflowPrototype();
  };
  let workpapersTimedOut = false;
  const workpapersRequest = request(`/api/workpapers?projectId=${pid}`);
  workpapersRequest.then(data => {
    if (workpapersTimedOut && isCurrentRefresh()) applyWorkpapers(data);
  }).catch(() => {});
  void loadPiece('底稿树', () => loadWorkpaperTree(pid, {force: true}), () => {
    renderWorkpaperTemplateTree();
    renderWorkpapers();
    renderAttachments();
  });
  await Promise.allSettled([
    loadPiece('成员', () => request(`/api/projects/${pid}/members`), data => {
      state.members = data;
      renderMembers();
      renderProjectWorkspace();
      renderDashboardHub();
      renderWorkflowPrototype();
    }),
    loadPiece('底稿', () => withTimeout(workpapersRequest, 3500, '底稿台账', {soft: true}), data => {
      if (data?.__timedOut) {
        workpapersTimedOut = true;
        return;
      }
      applyWorkpapers(data);
    }),
    loadPiece('附件', () => request(`/api/attachments?projectId=${pid}`), data => {
      state.attachments = data;
      renderAttachments();
      renderProjectWorkspace();
      renderDashboardHub();
      renderWorkflowPrototype();
    }),
    loadPiece('资料清单', () => request(`/api/projects/${pid}/document-requests`), data => {
      state.materials = data;
      renderMaterials();
      renderProjectWorkspace();
      renderWorkflowPrototype();
    }),
    loadPiece('复核记录', () => request(`/api/review-runs?projectId=${pid}`), data => {
      state.runs = data;
      renderRuns();
    }),
    loadPiece('自动填写记录', () => request(`/api/autofill-runs?projectId=${pid}`), data => {
      state.autofillRuns = data;
      renderAutofillRuns();
    }),
  ]);
  if (!isCurrentRefresh()) return;
  state.projectScopedLoading = false;
  void loadWorkflowPrototypeData({silent: true}).then(() => {
    if (!isCurrentRefresh()) return;
    renderProjects();
    renderProjectWorkspace();
    renderDashboardHub();
  });
  if (!isCurrentRefresh()) return;
  renderProjectSnapshot();
  renderWorkpaperTemplateTree();
  renderMembers();
  renderWorkpapers();
  renderAttachments();
  renderMaterials();
  renderRuns();
  renderAutofillRuns();
  renderQualityModules();
  renderProjectWorkspace();
  renderDashboardHub();
  renderWorkflowPrototype();
  void Promise.allSettled([
    loadPiece('合规检核', () => loadRuleInspection({silent: true}), () => {}),
    loadPiece('自动填写配置', () => loadRuleVisualization({silent: true}), () => {}),
  ]).then(() => {
    if (!isCurrentRefresh()) return;
    renderProjectWorkspace();
    renderWorkflowPrototype();
  });
  setStatus(failures.length ? `项目部分数据加载失败：${failures.slice(0, 3).join('；')}` : '就绪');
}

async function initializeSession() {
  if (!localStorage.getItem('audit_flow_token')) return showLogin();
  try {
    state.me = await request('/api/me');
    showApp();
    applyAuthUi();
    await refreshAll();
  } catch {
    showLogin();
  }
}

function moveModule(tab, delta) {
  const index = state.moduleOrder.indexOf(tab);
  const next = index + delta;
  if (index < 0 || next < 0 || next >= state.moduleOrder.length) return;
  const copy = state.moduleOrder.slice();
  [copy[index], copy[next]] = [copy[next], copy[index]];
  state.moduleOrder = copy;
  applyModuleOrder();
}

async function deleteUser(id) {
  if (!confirm('确认删除该用户？')) return;
  try {
    await request(`/api/users/${id}`, {method: 'DELETE'});
    await refreshAll();
  } catch (err) { setStatus('错误：' + err.message); }
}

async function deleteRole(id) {
  if (!confirm('确认删除该角色？')) return;
  try {
    await request(`/api/roles/${id}`, {method: 'DELETE'});
    await refreshAll();
  } catch (err) { setStatus('错误：' + err.message); }
}

const sectionTitles = {
  dashboard: '项目监控',
  projectWorkspace: '项目执行 / 项目总览',
  scopeCenter: '项目中心 / 审计范围识别',
  pbcCenter: '项目中心 / PBC资料管理',
  workpaperExecution: '项目执行 / 底稿进度',
  autoCheck: '项目中心 / 自动检核结果',
  reviewCenter: '项目中心 / 复核中心',
  findingKanban: '项目执行 / 复核整改',
  qualityDashboard: '复核质控 / 项目质量看板',
  architecture: '功能架构',
  projects: '项目 / 项目列表',
  clients: '项目 / 客户档案',
  workpapers: '项目 / 底稿管理',
  attachments: '项目 / 资料与附件',
  quality: '项目 / 质量问题',
  ruleVisualization: '项目 / 自动填写',
  ruleInspection: '项目 / 合规检核',
  reviews: '项目 / 复核记录',
  issueDashboard: '质量中心 / 问题看板',
  projectOverview: '质量中心 / 项目状态',
  resourcePlan: '质量中心 / 人员计划',
  templates: '知识库 / 模板库',
  learning: '学习刷题 / 章节题库',
  architecture: '知识库 / 功能架构',
  config: '系统设置 / 配置管理',
  people: '系统设置 / 用户与角色',
};

function primaryForSection(section) {
  if (['projectWorkspace', 'projects', 'clients', 'scopeCenter', 'pbcCenter', 'workpaperExecution', 'attachments', 'autoCheck', 'reviewCenter', 'quality', 'findingKanban', 'workpapers', 'ruleVisualization', 'ruleInspection', 'reviews'].includes(section)) return 'projectWorkspace';
  if (section === 'qualityDashboard') return 'dashboard';
  if (['issueDashboard', 'projectOverview', 'resourcePlan'].includes(section)) return 'dashboard';
  if (['templates', 'architecture'].includes(section)) return 'templates';
  if (section === 'learning') return 'learning';
  if (['config', 'people'].includes(section)) return 'config';
  return section;
}

export function activateSection(section) {
  if (section === 'quality' || section === 'findingKanban') section = 'reviewCenter';
  if (section === 'qualityDashboard') section = 'dashboard';
  const requestedPrimary = primaryForSection(section);
  const ownFindingSelfService = section === 'quality' && canAccessModule('projectWorkspace', 'view');
  if (requestedPrimary !== 'dashboard' && !ownFindingSelfService && !canAccessModule(requestedPrimary, 'view')) {
    section = canAccessModule('projectWorkspace', 'view') ? 'projectWorkspace' : 'dashboard';
  }
  const target = $(section);
  if (!target) return;
  state.activeSection = section;
  if (primaryForSection(section) === 'projectWorkspace') state.activeProjectSubsection = section;
  if (primaryForSection(section) === 'qualityDashboard') state.activeBoardSubsection = section;
  if (['templates', 'config'].includes(primaryForSection(section))) state.activeSystemSubsection = section;
  document.querySelectorAll('#nav button').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === primaryForSection(section));
  });
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  target.classList.add('active');
  if (section === 'dashboard' && canAccessModule('qualityDashboard', 'view')) $('qualityDashboard')?.classList.add('active');
  $('pageTitle').textContent = sectionTitles[section] || moduleLabel(section);
  $('projectContextBar').classList.toggle('hidden', primaryForSection(section) !== 'projectWorkspace');
  $('boardContextBar').classList.add('hidden');
  $('systemContextBar').classList.toggle('hidden', !['templates', 'config'].includes(primaryForSection(section)));
  renderProjectContext();
  document.querySelectorAll('[data-board-section]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.boardSection === state.activeBoardSubsection);
  });
  document.querySelectorAll('[data-system-section]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.systemSection === state.activeSystemSubsection);
  });
}

function bindNavigation() {
  document.querySelectorAll('#nav button').forEach(btn => {
    btn.addEventListener('click', () => {
      activateSection(btn.dataset.tab);
      if (btn.dataset.tab === 'development') void (canManageTraining() ? loadDevelopmentOverview({silent: true}) : loadLearner());
    });
  });
  document.querySelectorAll('[data-project-section]').forEach(btn => {
    btn.addEventListener('click', () => activateSection(btn.dataset.projectSection));
  });
  document.querySelectorAll('[data-board-section]').forEach(btn => {
    btn.addEventListener('click', () => activateSection(btn.dataset.boardSection));
  });
  document.querySelectorAll('[data-system-section]').forEach(btn => {
    btn.addEventListener('click', () => activateSection(btn.dataset.systemSection));
  });
  document.addEventListener('click', async (event) => {
    const projectButton = event.target.closest('[data-dashboard-project]');
    if (projectButton) {
      $('activeProject').value = projectButton.dataset.dashboardProject;
      void refreshProjectScoped();
      activateSection('projectWorkspace');
      return;
    }
    const dashboardAction = event.target.closest('[data-dashboard-action]');
    if (dashboardAction) {
      if (dashboardAction.dataset.dashboardAction === 'new-project') {
        activateSection('projects');
        setProjectFormMode(null);
      }
      if (dashboardAction.dataset.dashboardAction === 'new-client') {
        activateSection('clients');
        openNewClientForm();
      }
      return;
    }
    const dashboardSection = event.target.closest('[data-dashboard-section]');
    if (dashboardSection) {
      activateSection(dashboardSection.dataset.dashboardSection);
      return;
    }
    const editMasterButton = event.target.closest('[data-project-edit-master]');
    if (editMasterButton) {
      const id = Number(editMasterButton.dataset.projectEditMaster);
      if (id) {
        $('activeProject').value = id;
        void refreshProjectScoped();
        window.editProject?.(id);
      }
      return;
    }
    const refreshWorkpaperButton = event.target.closest('[data-project-refresh-workpaper]');
    if (refreshWorkpaperButton) {
      const id = Number(refreshWorkpaperButton.dataset.projectRefreshWorkpaper);
      if (id) {
        $('activeProject').value = id;
        state.workpaperPreviews = {};
        state.workpaperTreeByProject[id] = null;
        setStatus('正在刷新底稿定位');
        await refreshProjectScoped();
        await loadWorkpaperTree(id, {force: true});
        await loadRuleInspection({silent: true});
        await loadRuleVisualization({silent: true});
        renderWorkpapers();
        activateSection('ruleVisualization');
        setStatus('已刷新底稿定位预览；真实底稿写回仍禁用');
      }
      return;
    }
    const saveScopeButton = event.target.closest('[data-project-save-scope]');
    if (saveScopeButton) {
      await saveProjectAuditScope(Number(saveScopeButton.dataset.projectSaveScope));
      return;
    }
    const inferScopeButton = event.target.closest('[data-project-infer-scope]');
    if (inferScopeButton) {
      await inferProjectAuditScope(Number(inferScopeButton.dataset.projectInferScope));
      return;
    }
    const workspaceButton = event.target.closest('[data-workspace-section]');
    if (workspaceButton) activateSection(workspaceButton.dataset.workspaceSection);
  });
}

function setLoginView(view) {
  const views = {
    login: $('loginForm'),
    change: $('changePasswordForm'),
    forgot: $('forgotPasswordForm')
  };
  Object.entries(views).forEach(([key, form]) => {
    form.classList.toggle('hidden', key !== view);
  });
  $('loginTabs').querySelectorAll('[data-login-view]').forEach(button => {
    button.classList.toggle('active', button.dataset.loginView === view);
  });
  const hints = {
    login: '请输入账号和密码',
    change: '请输入账号、原密码和新密码',
    forgot: '请输入账号、登记姓名和新密码'
  };
  if (!$('loginStatus').textContent.startsWith('ITAS 密码已更新')) {
    $('loginStatus').textContent = hints[view] || hints.login;
  }
}

function bindAuth() {
  $('loginTabs').addEventListener('click', (event) => {
    const button = event.target.closest('[data-login-view]');
    if (button) {
      $('loginStatus').textContent = '';
      setLoginView(button.dataset.loginView);
    }
  });
  $('loginForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const data = await login(formData(e.target));
      setToken(data.token);
      state.me = data.user;
      showApp();
      applyAuthUi();
      await refreshAll();
    } catch (err) {
      $('loginStatus').textContent = '错误：' + err.message;
    }
  });
  $('changePasswordForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = formData(e.target);
    if (payload.new_password !== payload.confirm_password) {
      $('loginStatus').textContent = '错误：两次输入的新密码不一致';
      return;
    }
    try {
      const result = await publicJson('/api/password/change', payload);
      e.target.reset();
      $('loginStatus').textContent = result.message || '密码已更新';
      setLoginView('login');
    } catch (err) {
      $('loginStatus').textContent = '错误：' + err.message;
    }
  });
  $('forgotPasswordForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = formData(e.target);
    if (payload.new_password !== payload.confirm_password) {
      $('loginStatus').textContent = '错误：两次输入的新密码不一致';
      return;
    }
    try {
      const result = await publicJson('/api/password/forgot', payload);
      e.target.reset();
      $('loginStatus').textContent = result.message || '密码已重置';
      setLoginView('login');
    } catch (err) {
      $('loginStatus').textContent = '错误：' + err.message;
    }
  });
  $('logoutBtn').addEventListener('click', async () => {
    try { await request('/api/logout', {method: 'POST', body: '{}'}); } catch {}
    clearToken();
    showLogin();
  });
}

function bindPeopleAndConfig() {
  $('userRows').addEventListener('click', (event) => {
    const button = event.target.closest('[data-user-delete]');
    if (button) deleteUser(Number(button.dataset.userDelete));
  });
  $('roleRows').addEventListener('click', (event) => {
    const button = event.target.closest('[data-role-delete]');
    if (button) deleteRole(Number(button.dataset.roleDelete));
  });
  $('moduleOrderList').addEventListener('click', (event) => {
    const button = event.target.closest('[data-module-move]');
    if (button) moveModule(button.dataset.moduleMove, Number(button.dataset.moduleDelta));
  });
  $('userForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await request('/api/users', {method: 'POST', body: JSON.stringify(formData(e.target))});
      e.target.reset();
      await refreshAll();
    } catch (err) { setStatus('错误：' + err.message); }
  });
  $('roleForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const payload = {
      code: form.code.value.trim(),
      name: form.name.value.trim(),
      rank: Number(form.rank.value || 0),
      can_review: form.can_review.checked,
      description: form.description.value || ''
    };
    try {
      await request('/api/roles', {method: 'POST', body: JSON.stringify(payload)});
      form.reset();
      await refreshAll();
    } catch (err) { setStatus('错误：' + err.message); }
  });
  $('passwordPolicyForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const payload = {
      min_length: Number(form.min_length.value || 6),
      require_digit: form.require_digit.checked,
      require_upper: form.require_upper.checked,
      require_special: form.require_special.checked
    };
    try {
      await request('/api/config/password-policy', {method: 'PATCH', body: JSON.stringify(payload)});
      setStatus('密码策略已保存');
    } catch (err) { setStatus('错误：' + err.message); }
  });
  $('saveModuleOrderBtn').addEventListener('click', async () => {
    try {
      const data = await request('/api/config/module-order', {method: 'PATCH', body: JSON.stringify({order: state.moduleOrder})});
      state.moduleOrder = normalizeModuleOrder(data.order);
      applyModuleOrder();
      setStatus('功能模块顺序已保存');
    } catch (err) { setStatus('错误：' + err.message); }
  });
  $('autofillScopeConfigForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const enabled_keys = Array.from(e.target.querySelectorAll('input[name="enabled_keys"]:checked')).map(input => input.value);
    try {
      state.autofillScopeConfig = await request('/api/config/autofill-scope', {method: 'PATCH', body: JSON.stringify({enabled_keys})});
      renderAutofillScopeConfig(state.autofillScopeConfig);
      setStatus('自动填写范围已保存');
    } catch (err) { setStatus('错误：' + err.message); }
  });
}

function bindGlobalCompatibility() {
  window.refreshAll = refreshAll;
  window.refreshProjectScoped = refreshProjectScoped;
  window.openModal = openModal;
  window.closeModal = closeModal;
  window.moveModule = moveModule;
  window.deleteUser = deleteUser;
  window.deleteRole = deleteRole;
  window.activateAppSection = activateSection;
  window.openQualityFinding = openQualityFinding;
  window.refreshReviewData = refreshReviewData;
  window.refreshWorkflowReviewCenterData = refreshWorkflowReviewCenterData;
}

function bindModalCloseButtons() {
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-modal-close]');
    if (button) closeModal(button.dataset.modalClose);
  });
}

function bindApp() {
  setUnauthorizedHandler(showLogin);
  bindGlobalCompatibility();
  bindModalCloseButtons();
  bindNavigation();
  bindAuth();
  bindClients({refreshAll});
  bindProjects({refreshAll, refreshProjectScoped, renderWorkpaperTemplateTree});
  bindWorkpapers({refreshProjectScoped});
  bindMaterials({refreshProjectScoped});
  bindRuleInspection();
  bindRuleVisualization();
  bindReview({refreshProjectScoped});
  bindQualityModules();
  bindWorkflowPrototype();
  bindLearning();
  bindDevelopmentOverview();
  bindMentorWorkbench();
  bindPeopleAndConfig();
  $('dashRefresh')?.addEventListener('click', refreshAll);
  activateSection('dashboard');
  renderWorkflowPrototype();
}

window.refreshLearning = () => loadLearning({weekId: state.selectedLearningWeekId, refresh: true});

bindApp();
initializeSession();
