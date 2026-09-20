import { state } from '../state.js?v=20260920-state12';
import { $, activeProjectId, cleanClientDescription, esc, statusClass, tag } from '../utils.js?v=20260630a';

const PROJECT_SECTIONS = [
  ['scopeCenter', '范围识别', '维护审计范围、系统与关键流程'],
  ['workpapers', '底稿管理', '查看底稿树、预览和台账状态'],
  ['attachments', '资料与附件', '上传资料、扫描附件并勾稽引用'],
  ['reviewCenter', '复核中心', '处理待复核、整改回复与历史记录'],
  ['ruleVisualization', '自动填写配置', '查看字段定位、来源和验证状态'],
  ['ruleInspection', '合规检核', '检查规则定义和项目证据状态'],
  ['resourcePlan', '人员安排', '查看并维护项目成员排期'],
];

function currentProject() {
  const pid = activeProjectId();
  return state.projects.find(p => p.id === pid) || state.projects[0] || null;
}

function projectMembers(project) {
  if (!project || project.id !== activeProjectId()) return [];
  return state.members || [];
}

function canFeature(module, level = 'view') {
  if (state.me?.is_admin) return true;
  const permission = state.me?.permissions?.[module];
  if (!permission) return false;
  if (level === 'manage') return Boolean(permission.manage);
  if (level === 'edit') return Boolean(permission.edit || permission.manage);
  return Boolean(permission.view || permission.edit || permission.manage);
}

function isDoneStatus(value) {
  const status = String(value || '').toLowerCase();
  return ['completed', 'approved', 'submitted', 'uploaded', 'provided', 'closed', 'resolved', 'done', '已完成', '已提交', '已提供', '已关闭', '已解决'].includes(status);
}

function daysToDelivery(project) {
  if (project?.due_days !== undefined && project?.due_days !== null && project?.due_days !== '') {
    const value = Number(project.due_days);
    return Number.isNaN(value) ? null : value;
  }
  const end = project?.delivery_date;
  if (!end) return null;
  const endDate = new Date(`${end}T00:00:00`);
  if (Number.isNaN(endDate.getTime())) return null;
  const today = new Date();
  const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.ceil((endDate - startOfToday) / 86400000);
}

function deliveryNote(project) {
  if (project?.delivery_date) {
    return `${project.delivery_date}${project.delivery_source ? ' / ' + project.delivery_source : ''}`;
  }
  return project?.delivery_source || '交付日期后台加载中';
}

function workpaperProgress(projectId) {
  const rows = state.workpapers || [];
  if (!projectId || !rows.length) return 0;
  const done = rows.filter(w => isDoneStatus(w.status)).length;
  return Math.round((done / rows.length) * 100);
}

function projectWorkpaperStats(projectId) {
  const activeRows = (state.workpapers || []).filter(row => !row.project_id || Number(row.project_id) === Number(projectId));
  const overviewRows = (state.overviewWorkpapers || []).filter(row => Number(row.project_id) === Number(projectId));
  const rows = activeRows.length ? activeRows : overviewRows;
  const done = rows.filter(row => isDoneStatus(row.status)).length;
  return {total: rows.length, done, percent: rows.length ? Math.round((done / rows.length) * 100) : 0};
}

function materialGapStats() {
  const rows = state.materials || [];
  const gaps = rows.filter(row => !isDoneStatus(row.status) && !['not_applicable', '不适用'].includes(String(row.status || '').toLowerCase()));
  const overdue = rows.filter(row => row.is_overdue).length;
  return {total: rows.length, gaps: gaps.length, overdue};
}

function openFindingRows() {
  return (state.reviewFindings || []).filter(row => !['closed', 'resolved', '已关闭', '已解决'].includes(String(row.status || '').toLowerCase()));
}

function projectFindingStats(projectId) {
  const rows = (state.reviewFindings || []).filter(row => Number(row.project_id) === Number(projectId));
  const openRows = rows.filter(row => !isDoneStatus(row.status));
  const highRows = openRows.filter(row => ['high', '重大', '高'].includes(String(row.severity || '').toLowerCase()));
  return {total: rows.length, open: openRows.length, high: highRows.length};
}

function ruleStats() {
  const summary = state.ruleVisualization?.summary || {};
  const verification = summary.verification_status || {};
  return {
    rows: Number(summary.row_count || 0),
    passed: Number(verification.passed || 0),
    conflicts: Number(summary.conflict_count || 0),
    manual: Number(summary.approved_manual_correction || 0),
  };
}

function parseTaskDate(value) {
  const date = value ? new Date(`${value}T00:00:00`) : null;
  return date && !Number.isNaN(date.getTime()) ? date : null;
}

function workingDaysBetween(start, end) {
  let count = 0;
  const cursor = new Date(start.getFullYear(), start.getMonth(), start.getDate());
  const last = new Date(end.getFullYear(), end.getMonth(), end.getDate());
  while (cursor <= last) {
    const day = cursor.getDay();
    if (day !== 0 && day !== 6) count += 1;
    cursor.setDate(cursor.getDate() + 1);
  }
  return count;
}

function taskEstimatedHours(task, weekStart, weekEnd) {
  if (task.hours !== undefined && task.hours !== null && task.hours !== '' && Number.isFinite(Number(task.hours))) {
    return Number(task.hours);
  }
  const workload = String(task.workload || '').trim();
  const matched = workload.match(/\d+(\.\d+)?/);
  if (matched) {
    const value = Number(matched[0]);
    if (/天|day/i.test(workload)) return value * 8;
    if (/小时|hour|hr|h\b/i.test(workload)) return value;
  }
  const start = parseTaskDate(task.start_date);
  const end = parseTaskDate(task.end_date || task.start_date);
  if (!start || !end || start > weekEnd || end < weekStart) return 0;
  const effectiveStart = start > weekStart ? start : weekStart;
  const effectiveEnd = end < weekEnd ? end : weekEnd;
  return workingDaysBetween(effectiveStart, effectiveEnd) * 8;
}

function weekHours() {
  const now = new Date();
  const day = now.getDay() || 7;
  const weekStart = new Date(now.getFullYear(), now.getMonth(), now.getDate() - day + 1);
  const weekEnd = new Date(weekStart.getFullYear(), weekStart.getMonth(), weekStart.getDate() + 6);
  const hours = (state.tasks || []).reduce((sum, task) => sum + taskEstimatedHours(task, weekStart, weekEnd), 0);
  return Number.isInteger(hours) ? hours : hours.toFixed(1);
}

function projectLabel(project) {
  if (!project) return '未选择项目';
  return `${project.name || `项目 #${project.id}`}${project.audit_year ? ` / ${project.audit_year}` : ''}`;
}

function navigateButton(section, label) {
  return `<button type="button" class="secondary" data-workspace-section="${esc(section)}">${esc(label)}</button>`;
}

function metricCard(label, value, note, stateClass = '', section = '') {
  const actionAttrs = section
    ? ` type="button" data-workspace-section="${esc(section)}" aria-label="查看${esc(label)}明细"`
    : ' type="button" disabled';
  return `
    <button${actionAttrs} class="overview-metric ${esc(stateClass)}">
      <span>${esc(label)}</span>
      <strong>${esc(value)}</strong>
      <small>${esc(note)}</small>
    </button>
  `;
}

function renderWorkspaceOverview(project) {
  const box = $('workspaceOverviewMetrics');
  if (!box) return;
  if (!project) {
    box.innerHTML = '<div class="empty">请选择项目后查看总览指标</div>';
    return;
  }
  const workpapers = projectWorkpaperStats(project.id);
  const materials = materialGapStats();
  const findings = projectFindingStats(project.id);
  const rules = ruleStats();
  const days = daysToDelivery(project);
  const deliveryValue = days === null ? '未维护' : days < 0 ? `逾期 ${Math.abs(days)} 天` : `${days} 天`;
  const deliveryTone = days === null ? 'state-not-started' : days < 0 || days <= 7 ? 'state-risk' : 'state-running';
  const materialOverdue = Number(project.material_overdue_count ?? materials.overdue ?? 0);
  const stepOverdue = Number(project.step_overdue_count ?? 0);
  box.innerHTML = [
    metricCard('项目阶段', project.status || '未开始', '项目状态与范围信息保持可见', statusClass(project.status), 'projects'),
    metricCard('底稿完成度', `${workpapers.percent}%`, `${workpapers.done}/${workpapers.total} 份底稿已完成`, workpapers.percent >= 100 ? 'state-done' : 'state-running', 'workpapers'),
    metricCard('资料缺口', `${materials.gaps}`, `${materials.total} 项资料需求中待补齐`, materials.gaps ? 'state-risk' : 'state-done', 'attachments'),
    metricCard('资料逾期', `${materialOverdue}`, '已超过资料截止日期', materialOverdue ? 'state-risk' : 'state-done', 'attachments'),
    metricCard('复核逾期', `${stepOverdue}`, '复核步骤超过角色 SLA', stepOverdue ? 'state-risk' : 'state-done', 'workpapers'),
    metricCard('质量问题', `${findings.open}`, `${findings.total} 条问题，重大/高 ${findings.high} 条`, findings.open ? 'state-risk' : 'state-done', 'quality'),
    metricCard('自动填写', rules.rows ? `${rules.passed}/${rules.rows}` : '待加载', `冲突 ${rules.conflicts}，人工修正 ${rules.manual}`, rules.conflicts ? 'state-risk' : 'state-running', 'ruleVisualization'),
    metricCard('距交付', deliveryValue, deliveryNote(project), deliveryTone, 'projects'),
  ].join('');
}

export function renderProjectContext() {
  const project = currentProject();
  if (!$('projectContextName')) return;
  $('projectContextName').textContent = projectLabel(project);
  $('projectContextMeta').textContent = project
    ? `阶段：${project.status || '未开始'} / 范围：${project.audit_scope_start || '未维护'} 至 ${project.audit_scope_end || '未维护'} / 单位：${project.entity_name || '未维护'}`
    : '请选择项目后进入驾驶舱';
  document.querySelectorAll('[data-project-section]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.projectSection === state.activeProjectSubsection);
  });
}

export function renderProjectWorkspace() {
  const project = currentProject();
  renderProjectContext();
  if (!$('workspaceProjectTitle')) return;
  if (!project) {
    $('workspaceProjectTitle').textContent = '未选择项目';
    $('workspaceProjectMeta').textContent = '';
    $('workspaceProjectStatus').innerHTML = '';
    renderWorkspaceOverview(null);
    $('workspaceProjectMaster').innerHTML = '<div class="empty">暂无项目数据</div>';
    $('workspaceMembers').innerHTML = '<div class="empty">暂无项目成员</div>';
    $('workspaceClientSummary').innerHTML = '<div class="empty">暂无客户信息</div>';
    $('workspaceActionTiles').innerHTML = '';
    return;
  }
  const members = projectMembers(project);
  const client = state.clients.find(c => c.id === project.client_id || c.entity_name === project.entity_name);
  const canEditProjectMaster = Boolean(project.can_edit && canFeature('projects', 'edit'));
  $('workspaceProjectTitle').textContent = project.name || `项目 #${project.id}`;
  $('workspaceProjectMeta').textContent = `审计年度 ${project.audit_year || '未维护'} / ${project.code || '未维护编号'} / ${project.entity_name || '未维护单位'}`;
  $('workspaceProjectStatus').innerHTML = `
    ${tag(project.status || '未开始', statusClass(project.status))}
    <div class="project-hero-actions">
      <button type="button" class="secondary" data-project-edit-master="${esc(project.id)}" ${canEditProjectMaster ? '' : 'disabled'}>编辑主数据</button>
      <button type="button" class="secondary" data-project-refresh-workpaper="${esc(project.id)}">刷新底稿定位</button>
    </div>
  `;
  renderWorkspaceOverview(project);
  const scopeCard = `
    <div class="detail-card project-scope-card">
      <span>审计范围</span>
      <strong>${esc(project.audit_scope_start || '未维护')} 至 ${esc(project.audit_scope_end || '未维护')}</strong>
      <div class="scope-edit-row">
        <input type="date" value="${esc(project.audit_scope_start || '')}" data-project-scope-start="${esc(project.id)}" ${canEditProjectMaster ? '' : 'disabled'}>
        <input type="date" value="${esc(project.audit_scope_end || '')}" data-project-scope-end="${esc(project.id)}" ${canEditProjectMaster ? '' : 'disabled'}>
      </div>
      <div class="scope-action-row">
        <button type="button" class="secondary" data-project-save-scope="${esc(project.id)}" ${canEditProjectMaster ? '' : 'disabled'}>保存范围</button>
        <button type="button" class="secondary" data-project-infer-scope="${esc(project.id)}" ${canEditProjectMaster ? '' : 'disabled'}>从底稿识别</button>
      </div>
      <small>优先读取底稿首页的截止日/审计期间。</small>
    </div>
  `;
  $('workspaceProjectMaster').innerHTML = [
    scopeCard,
    ...[
    ['项目负责人', project.project_leader_name || '未维护'],
    ['项目经理', project.manager_name || '未维护'],
    ['质控复核人', (project.quality_reviewer_names || [project.quality_reviewer_name].filter(Boolean)).join('、') || '未维护'],
    ['现场负责人', project.field_leader_name || '未维护'],
    ['财审一签', [project.first_partner_name, project.first_partner_email, project.first_partner_phone].filter(Boolean).join(' / ') || '未维护'],
    ['财审二签', [project.second_partner_name, project.second_partner_email, project.second_partner_phone].filter(Boolean).join(' / ') || '未维护'],
    ['项目根目录', project.project_root || '未维护'],
    ].map(([label, value]) => `<div class="detail-card"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`),
  ].join('');
  $('workspaceMembers').innerHTML = members.length ? members.map(member => `
    <div class="member-card">
      <strong>${esc(member.display_name || member.username || '未命名')}</strong>
      <span>${esc(member.role_on_project || '项目成员')}</span>
      <small>${esc(member.module || '未维护模块')} / ${esc(member.workload || '未维护工作量')}</small>
    </div>
  `).join('') : '<div class="empty">暂无项目成员</div>';
  const primaryContact = client?.it_contacts?.[0] || null;
  $('workspaceClientSummary').innerHTML = client ? `
    <div class="detail-view">
      <h3>${esc(client.entity_name || project.entity_name || '')}</h3>
      <div class="detail-grid">
        <div class="detail-card"><span>行业/说明</span><strong>${esc(cleanClientDescription(client.description) || '未维护')}</strong></div>
        <div class="detail-card"><span>企业对接人</span><strong>${esc(primaryContact?.name || '未维护')}</strong></div>
        <div class="detail-card"><span>岗位/联系方式</span><strong>${esc([primaryContact?.title, primaryContact?.phone || primaryContact?.email].filter(Boolean).join(' / ') || '未维护')}</strong></div>
      </div>
    </div>
  ` : '<div class="empty">暂无客户信息</div>';
  $('workspaceActionTiles').innerHTML = PROJECT_SECTIONS.map(([section, title, desc]) => `
    <button type="button" class="action-tile" data-workspace-section="${esc(section)}">
      <strong>${esc(title)}</strong>
      <span>${esc(desc)}</span>
    </button>
  `).join('');
}

export function renderDashboardHub() {
  if (!$('sMyProjects')) return;
  const projects = state.projects || [];
  const findings = openFindingRows();
  $('sMyProjects').textContent = projects.length;
  $('sMyOpenFindings').textContent = findings.length;
  $('sWeekHours').textContent = weekHours();
  $('dashboardProjectCards').innerHTML = projects.slice(0, 8).map(project => {
    const progress = project.id === activeProjectId() ? workpaperProgress(project.id) : 0;
    const days = daysToDelivery(project);
    return `
      <button type="button" class="project-card" data-dashboard-project="${esc(project.id)}">
        <strong>${esc(project.name || `项目 #${project.id}`)}</strong>
        <span>${tag(project.status || '未开始', statusClass(project.status))} <em>${esc(project.audit_year || '')}</em></span>
        <div class="progress-line"><span style="width:${progress}%"></span></div>
        <small>底稿完成度 ${progress}% / ${days === null ? '交付日期未维护' : `距交付 ${days} 天`}</small>
      </button>
    `;
  }).join('') || '<div class="empty">暂无项目</div>';
  const materialTodos = (state.materials || []).filter(m => m.status !== 'uploaded').slice(0, 5);
  const reviewTodos = (state.workpapers || []).filter(w => ['submitted', 'running'].includes(String(w.status || '').toLowerCase())).slice(0, 5);
  $('dashboardTodos').innerHTML = `
    <div class="todo-group"><strong>问题待处理</strong>${findings.slice(0, 5).map(item => `<button type="button" data-workspace-section="quality">${esc(item.project_name || '')} / ${esc(item.rule_code || '')}</button>`).join('') || '<span>暂无</span>'}</div>
    <div class="todo-group"><strong>底稿待复核</strong>${reviewTodos.map(item => `<button type="button" data-workspace-section="workpapers">${esc(item.code || '')} ${esc(item.name || '')}</button>`).join('') || '<span>暂无</span>'}</div>
    <div class="todo-group"><strong>资料待上传</strong>${materialTodos.map(item => `<button type="button" data-workspace-section="attachments">${esc(item.control_code || '')} ${esc(item.title || '')}</button>`).join('') || '<span>暂无</span>'}</div>
  `;
  $('dashboardTemplateUpdates').innerHTML = (state.templates || []).slice(0, 8).map(template => `
    <div class="template-update">
      <strong>${esc(template.code || '')}</strong>
      <span>${esc(template.name || '')}</span>
      ${tag(template.version || '未标版本', template.file_exists ? 'state-running' : 'state-risk')}
    </div>
  `).join('') || '<div class="empty">暂无模板更新</div>';
}
