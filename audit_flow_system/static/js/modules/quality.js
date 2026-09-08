import { api, authHeaders, request } from '../api.js?v=20260630a';
import { state } from '../state.js?v=20260630a';
import { $, PROJECT_STATUS_OPTIONS, activeProjectId, closeModal, esc, fillSelect, formData, isActiveProjectStatus, openModal, projectStatusLabel, setStatus, statusClass, tag } from '../utils.js?v=20260904-project-filter1';

const ISSUE_TYPE_OPTIONS = [
  ['MANUAL', '人工复核问题'],
  ['EVIDENCE_MISSING', '证据缺失'],
  ['WORKPAPER_INCOMPLETE', '底稿填写不完整'],
  ['INDEX_MISMATCH', '索引勾稽不一致'],
  ['REVIEW_COMMENT', '复核意见待整改'],
  ['AUTOFILL_CONFLICT', '自动填写冲突'],
  ['CONTROL_EXCEPTION', '控制执行例外'],
];

const ISSUE_TYPE_META = {
  MANUAL: {label: '人工复核问题', principle: '由复核人员人工登记，按人工复核入口分类'},
  EVIDENCE_MISSING: {label: '证据缺失', principle: '问题描述或复核证据指向资料、截图、附件缺失'},
  WORKPAPER_INCOMPLETE: {label: '底稿填写不完整', principle: '底稿字段、结论或执行过程未填写完整'},
  INDEX_MISMATCH: {label: '索引勾稽不一致', principle: '附件索引、底稿引用或编号勾稽关系不一致'},
  REVIEW_COMMENT: {label: '复核意见待整改', principle: '来源于复核退回意见或待整改复核记录'},
  AUTOFILL_CONFLICT: {label: '自动填写冲突', principle: '自动填写规则、人工修正或目标字段发生冲突'},
  CONTROL_EXCEPTION: {label: '控制执行例外', principle: '控制设计、执行或样本测试发现例外'},
  'GLOBAL-001': {label: '项目基础信息缺失', principle: '项目级基础字段或底稿基础信息完整性检查'},
  'GLOBAL-002': {label: '底稿编码重复', principle: '同一项目底稿编码唯一性检查'},
  'GLOBAL-003': {label: '底稿文件路径异常', principle: '底稿台账文件路径存在性检查'},
  'FLOW-001': {label: '复核流转缺失', principle: '底稿提交后是否建立复核流转检查'},
  'ATT-001': {label: '附件索引异常', principle: '附件索引号完整性和唯一性检查'},
  'ATT-002': {label: '附件引用不一致', principle: '附件索引号与底稿引用说明勾稽检查'},
  'ATT-003': {label: '附件文件路径异常', principle: '附件台账文件路径存在性检查'},
  'ATT-004': {label: '资料文件时间超出审计期间', principle: '文件系统创建/元数据变更时间或修改时间落在项目审计期间外；仅作为辅助审计线索，需结合文件内容、签署日期及取得记录核实'},
  'EXT-000': {label: '外部规则前置条件不足', principle: '外部规则入口、项目根目录等运行前置条件检查'},
  'EXT-001': {label: '外部规则执行失败', principle: '外部规则脚本运行结果检查'},
  'EXT-002': {label: '外部规则报告缺失', principle: '外部规则执行后报告产物检查'},
  'SYS-001': {label: '自动复核运行异常', principle: '系统执行自动复核任务时捕获的运行异常'},
};

const ISSUE_PREFIX_META = [
  ['GLOBAL', {label: '项目全局规则', principle: '按项目级基础信息、底稿台账完整性归类'}],
  ['FLOW', {label: '复核流转规则', principle: '按底稿提交、复核节点和闭环状态归类'}],
  ['ATT', {label: '附件证据规则', principle: '按附件索引、引用勾稽和文件存在性归类'}],
  ['EXT', {label: '外部检核规则', principle: '按外部复核脚本返回的规则编号归类'}],
  ['SYS', {label: '系统运行规则', principle: '按系统自动复核运行异常归类'}],
  ['AUTO', {label: '自动填写规则', principle: '按自动填写计划、字段定位和写入冲突归类'}],
];

let ganttCursor = new Date(new Date().getFullYear(), new Date().getMonth(), 1);
const expandedTemplateCodes = new Set();
const templateCompareTargets = {};
let qualityProjectContextId = '';
const ACTIVE_TASK_STATUSES = new Set(['open', 'running', 'assigned', 'in_progress', 'active', 'blocked', '待处理', '进行中', '已分派', '阻塞']);
const CLOSED_TASK_STATUSES = new Set(['completed', 'closed', 'resolved', 'done', '已完成', '已关闭', '已解决']);

function severityClass(value) {
  const key = String(value || '').toLowerCase();
  if (['high', '重大', '高'].includes(key)) return 'state-risk severity-high';
  if (['medium', '中'].includes(key)) return 'amber';
  if (['low', '低'].includes(key)) return 'blue severity-low';
  return 'state-not-started';
}

function severityKey(value) {
  const key = String(value || '').toLowerCase();
  if (['high', 'critical', '重大', '高'].includes(key)) return 'high';
  if (['medium', '中'].includes(key)) return 'medium';
  return 'low';
}

function severityLabel(value) {
  return {high: '高', medium: '中', low: '低'}[severityKey(value)];
}

function issueTypeMeta(code) {
  const value = String(code || 'MANUAL').trim() || 'MANUAL';
  if (ISSUE_TYPE_META[value]) return ISSUE_TYPE_META[value];
  const prefixMeta = ISSUE_PREFIX_META.find(([prefix]) => value.toUpperCase().startsWith(prefix));
  if (prefixMeta) return prefixMeta[1];
  return {label: '其他问题规则', principle: '未命中预置类型，按规则编号保留原始分类'};
}

function findingSourceKey(finding) {
  return finding.run_mode === 'manual' || finding.rule_code === 'MANUAL' ? 'manual' : 'system';
}

function findingSourceLabel(finding) {
  return findingSourceKey(finding) === 'manual' ? '人工' : '系统';
}

function findingStatusKey(finding) {
  const status = String(finding.status || 'open').toLowerCase();
  if (['closed', 'resolved', 'completed', 'done', '已关闭', '已解决', '已完成'].includes(status)) return 'done';
  if (status === 'responded') return 'awaiting_review';
  if (['assigned', 'changes_requested', 'retained', 'revised', 'blocked', 'running', 'in_progress', '已分派', '保留', '已修订', '阻塞', '整改中'].includes(status)) return 'in_progress';
  return 'unassigned';
}

function findingStatusLabel(finding) {
  return {unassigned: '待回复', in_progress: '待补充回复', awaiting_review: '待复核确认', done: '已关闭'}[findingStatusKey(finding)];
}

function findingStatusClass(finding) {
  return {unassigned: 'state-not-started', in_progress: 'state-running', awaiting_review: 'amber', done: 'state-done'}[findingStatusKey(finding)];
}

function compactText(value, limit = 50) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

function stageLabel(value) {
  return {
    planning: '项目准备',
    execution: '项目实施',
    delivery: '项目交付',
    reporting: '项目报告',
  }[value] || value || '';
}

function projectLabel(project) {
  if (!project) return '';
  return `${project.name || ''}${project.audit_year ? ' / ' + project.audit_year : ''}`.trim();
}

function resourceUsers() {
  const rows = (state.users || []).filter(user => user.status !== 'disabled' && user.username !== 'admin' && user.role_code !== 'admin');
  return rows.length ? rows : (state.users || []);
}

function activeProjects() {
  return (state.projects || []).filter(project => isActiveProjectStatus(project.status));
}

function canReviewAnyProject() {
  if (state.me?.role_code === 'admin') return true;
  const userId = Number(state.me?.id || 0);
  return (state.projects || []).some(project => [
    project.project_leader_user_id,
    project.manager_user_id,
    project.partner_user_id,
    ...(project.quality_reviewer_user_ids || [project.quality_reviewer_user_id].filter(Boolean)),
  ].some(value => Number(value || 0) === userId));
}

function projectChoices() {
  return activeProjects().length ? activeProjects() : (state.projects || []);
}

function fillSharedSelects() {
  const projects = projectChoices();
  if ($('planProjectSelect')) fillSelect($('planProjectSelect'), projects, projectLabel);
  if ($('planOwnerSelect')) fillSelect($('planOwnerSelect'), resourceUsers(), u => u.display_name || u.username);
  if ($('resourcePlanOwnerFilter')) {
    const current = $('resourcePlanOwnerFilter').value;
    fillSelect($('resourcePlanOwnerFilter'), resourceUsers(), u => `${u.display_name || u.username}${u.role_name ? ' / ' + u.role_name : ''}`, false);
    $('resourcePlanOwnerFilter').insertAdjacentHTML('afterbegin', '<option value="">全部人员</option>');
    $('resourcePlanOwnerFilter').value = current;
  }
  if ($('resourcePlanProjectFilter')) {
    const current = $('resourcePlanProjectFilter').value;
    fillSelect($('resourcePlanProjectFilter'), projects, projectLabel, false);
    $('resourcePlanProjectFilter').insertAdjacentHTML('afterbegin', '<option value="">全部项目</option>');
    $('resourcePlanProjectFilter').value = current;
  }
  if ($('findingProjectSelect')) fillSelect($('findingProjectSelect'), projects, projectLabel);
  if ($('qualityProjectFilter')) {
    const current = $('qualityProjectFilter').value;
    fillSelect($('qualityProjectFilter'), projects, projectLabel);
    const pid = String(activeProjectId() || '');
    if (pid && pid !== qualityProjectContextId) {
      qualityProjectContextId = pid;
      $('qualityProjectFilter').value = pid;
    } else {
      $('qualityProjectFilter').value = current;
    }
  }
  const pid = activeProjectId();
  if (pid && $('planProjectSelect')) $('planProjectSelect').value = pid;
  if (pid && $('findingProjectSelect')) $('findingProjectSelect').value = pid;
}

function selectOptions(options, selected) {
  return options.map(([value, label]) => `<option value="${esc(value)}" ${value === selected ? 'selected' : ''}>${esc(label)}</option>`).join('');
}

function userOptions(selectedId) {
  const selected = selectedId === null || selectedId === undefined ? '' : String(selectedId);
  const rows = (state.users || []).map(user => {
    const value = String(user.id);
    const label = user.display_name || user.username || `用户 #${user.id}`;
    return `<option value="${esc(value)}" ${value === selected ? 'selected' : ''}>${esc(label)}</option>`;
  });
  return `<option value="">未分配</option>${rows.join('')}`;
}

function dateInputValue(value) {
  return value ? String(value).slice(0, 10) : '';
}

function fillOptionsFromValues(el, values, {includeBlank = true, blankLabel = '全部'} = {}) {
  if (!el) return;
  const current = el.value;
  const unique = Array.from(new Set(values.filter(value => value !== null && value !== undefined && String(value) !== ''))).sort();
  el.innerHTML = `${includeBlank ? `<option value="">${esc(blankLabel)}</option>` : ''}${unique.map(value => `<option value="${esc(value)}">${esc(value)}</option>`).join('')}`;
  el.value = unique.map(String).includes(String(current)) ? current : '';
}

function fillProjectOverviewStatusFilter() {
  const el = $('projectOverviewStatusFilter');
  if (!el) return;
  const current = el.dataset.initialized ? el.value : 'active';
  el.innerHTML = `<option value="active">正在执行项目</option><option value="">全部</option>${PROJECT_STATUS_OPTIONS.map(([value, label]) => `<option value="${esc(value)}">${esc(label)}</option>`).join('')}`;
  el.value = Array.from(el.options).some(option => option.value === current) ? current : 'active';
  el.dataset.initialized = '1';
}

function findingProjectId() {
  return Number($('findingProjectSelect')?.value || activeProjectId() || 0);
}

function issueTypeOptions() {
  const known = new Map(ISSUE_TYPE_OPTIONS);
  (state.reviewFindings || []).forEach(row => {
    if (row.rule_code && !known.has(row.rule_code)) known.set(row.rule_code, issueTypeMeta(row.rule_code).label);
  });
  return Array.from(known.entries());
}

function workpapersForFindingProject() {
  const pid = findingProjectId();
  const activeRows = (state.workpapers || []).filter(row => !pid || Number(row.project_id) === pid);
  const overviewRows = (state.overviewWorkpapers || []).filter(row => !pid || Number(row.project_id) === pid);
  return activeRows.length ? activeRows : overviewRows;
}

function targetLocationOptions() {
  const rows = [];
  workpapersForFindingProject().forEach(wp => {
    const label = `${wp.code || '未编号'} ${wp.name || ''}`.trim();
    rows.push([`${wp.code || ''} / ${wp.name || ''}`.trim(), label]);
  });
  (state.attachments || []).forEach(attachment => {
    const wp = state.workpapers.find(row => Number(row.id) === Number(attachment.workpaper_id));
    const location = attachment.referenced_in || attachment.index_no || attachment.title || '';
    if (!location) return;
    rows.push([
      `${wp?.code || '附件'} / ${location}`,
      `${attachment.index_no || '附件'} ${attachment.title || ''} / ${location}`.trim(),
    ]);
  });
  (state.reviewFindings || []).forEach(row => {
    if (row.target) rows.push([row.target, row.target]);
  });
  const seen = new Set();
  return rows.filter(([value]) => {
    if (!value || seen.has(value)) return false;
    seen.add(value);
    return true;
  });
}

function renderFindingIndexes() {
  const issueSelect = $('findingIssueTypeSelect');
  if (issueSelect) {
    const current = issueSelect.value || 'MANUAL';
    issueSelect.innerHTML = issueTypeOptions().map(([value, label]) => `<option value="${esc(value)}">${esc(label)}</option>`).join('');
    issueSelect.value = Array.from(issueSelect.options).some(option => option.value === current) ? current : 'MANUAL';
  }
  const targetSelect = $('findingTargetSelect');
  if (targetSelect) {
    const current = targetSelect.value;
    const options = targetLocationOptions();
    targetSelect.innerHTML = `<option value="">请选择底稿位置</option>${options.map(([value, label]) => `<option value="${esc(value)}">${esc(label)}</option>`).join('')}`;
    targetSelect.value = options.some(([value]) => value === current) ? current : '';
  }
  renderFindingDefaultMeta();
}

function matchWorkpaperForTarget(target = '') {
  const text = String(target || '').toLowerCase();
  return workpapersForFindingProject().find(wp => {
    const code = String(wp.code || '').toLowerCase();
    const name = String(wp.name || '').toLowerCase();
    return (code && text.includes(code)) || (name && text.includes(name));
  }) || null;
}

function fiveDaysFromToday() {
  const today = new Date();
  today.setDate(today.getDate() + 5);
  return today.toISOString().slice(0, 10);
}

function renderFindingDefaultMeta() {
  const box = $('findingDefaultMeta');
  if (!box) return;
  const target = $('findingTargetSelect')?.value || '';
  const workpaper = matchWorkpaperForTarget(target);
  const owner = workpaper?.preparer_name || '未维护编制人';
  box.textContent = target
    ? `默认责任人：${owner}；整改截止日期：${fiveDaysFromToday()}（发现当天+5天）。`
    : '选择底稿位置后自动带出责任人和整改截止日期。';
}

function daysToDelivery(project) {
  const raw = project?.end_date || project?.audit_scope_end;
  if (!raw) return null;
  const end = new Date(`${raw}T00:00:00`);
  if (Number.isNaN(end.getTime())) return null;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.ceil((end - today) / 86400000);
}

function projectIssueCount(projectId) {
  const byProject = state.issueDashboard?.by_project || [];
  const found = byProject.find(row => Number(row.project_id) === Number(projectId));
  if (found) return Number(found.total || 0);
  return (state.reviewFindings || []).filter(row => Number(row.project_id) === Number(projectId)).length;
}

function projectWorkpaperProgress(projectId) {
  const rows = (state.overviewWorkpapers || []).filter(row => Number(row.project_id) === Number(projectId));
  if (!rows.length) return {total: 0, done: 0, percent: 0};
  const done = rows.filter(row => ['completed', 'approved', 'submitted', '已完成', '已提交'].includes(String(row.status || '').toLowerCase())).length;
  return {total: rows.length, done, percent: Math.round(done / rows.length * 100)};
}

function projectMemberCount(projectId) {
  const project = state.projects.find(row => Number(row.id) === Number(projectId));
  if (project && project.member_count !== undefined && project.member_count !== null) return Number(project.member_count);
  if (Number(project?.id) === activeProjectId()) return state.members.length;
  return 0;
}

export function renderIssueDashboard() {
  const data = state.issueDashboard || {total: 0, open: 0, manual: 0, projects_with_findings: 0, by_project: [], by_rule: [], recent: []};
  if (!$('issueDashTotal')) return;
  $('issueDashTotal').textContent = data.total || 0;
  $('issueDashOpen').textContent = data.open || 0;
  $('issueDashManual').textContent = data.manual || 0;
  $('issueDashProjects').textContent = data.projects_with_findings || 0;
  $('issueProjectRows').innerHTML = (data.by_project || []).map(row => `
    <tr>
      <td><strong>${esc(row.project_name)}</strong><div class="muted">${esc(row.entity_name || '')}</div></td>
      <td>${esc(row.total || 0)}</td>
      <td>${tag(row.open || 0, row.open ? 'amber' : 'green')}</td>
      <td>${tag(row.high || 0, row.high ? 'red' : '')}</td>
      <td>${esc(row.medium || 0)}</td>
      <td>${esc(row.low || 0)}</td>
      <td>${esc(row.manual || 0)}</td>
    </tr>
  `).join('') || '<tr><td colspan="7" class="empty">暂无问题统计</td></tr>';
  $('issueRuleRows').innerHTML = (data.by_rule || []).map(row => `
    <tr>
      <td><strong>${esc(issueTypeMeta(row.rule_code).label)}</strong><div class="muted">${esc(row.rule_code || '未分类')}</div></td>
      <td>${esc(issueTypeMeta(row.rule_code).principle)}</td>
      <td>${esc(row.count)}</td>
    </tr>
  `).join('') || '<tr><td colspan="3" class="empty">暂无规则问题</td></tr>';
  $('issueRecentRows').innerHTML = (data.recent || []).slice(0, 12).map(row => `
    <tr>
      <td>${esc(row.project_name)}</td>
      <td><strong>${esc(issueTypeMeta(row.rule_code).label)}</strong><div class="muted">${esc(row.rule_code || '未分类')}</div></td>
      <td>${tag(severityLabel(row.severity), severityClass(row.severity))}</td>
      <td>${esc(compactText(row.issue, 50))}</td>
      <td>${tag(findingStatusLabel(row), findingStatusClass(row))}</td>
    </tr>
  `).join('') || '<tr><td colspan="5" class="empty">暂无最近问题</td></tr>';
}

export function renderProjectOverview() {
  if (!$('projectOverviewRows')) return;
  fillOptionsFromValues($('projectOverviewYearFilter'), state.projects.map(project => project.audit_year));
  fillProjectOverviewStatusFilter();
  const year = $('projectOverviewYearFilter')?.value;
  const status = $('projectOverviewStatusFilter')?.value;
  const keyword = String($('projectOverviewSearchInput')?.value || '').trim().toLowerCase();
  const rows = (state.projects || []).filter(project => {
    const text = [project.name, project.entity_name, project.code, project.oa_project_no, project.ims_project_no].join(' ').toLowerCase();
    if (year && String(project.audit_year || '') !== String(year)) return false;
    if (status === 'active' && !isActiveProjectStatus(project.status)) return false;
    if (status && status !== 'active' && String(project.status || '') !== String(status)) return false;
    if (keyword && !text.includes(keyword)) return false;
    return true;
  });
  $('projectOverviewRows').innerHTML = rows.map(project => {
    const progress = projectWorkpaperProgress(project.id);
    const days = daysToDelivery(project);
    return `
      <tr class="selectable-row" data-overview-project="${esc(project.id)}">
        <td><strong>${esc(project.name || `项目 #${project.id}`)}</strong><div class="muted">${esc(project.entity_name || '')} ${esc(project.code || '')}</div></td>
        <td>${tag(projectStatusLabel(project.status), statusClass(project.status))}</td>
        <td>${esc(projectMemberCount(project.id) || '未维护')}</td>
        <td><div class="progress-line"><span style="width:${progress.percent}%"></span></div><div class="muted">${progress.done}/${progress.total} · ${progress.percent}%</div></td>
        <td>${tag(projectIssueCount(project.id), projectIssueCount(project.id) ? 'state-risk' : 'state-done')}</td>
        <td>${days === null ? '<span class="muted">未维护</span>' : days < 0 ? tag(`已逾期 ${Math.abs(days)} 天`, 'state-risk') : tag(`${days} 天`, days <= 7 ? 'amber' : 'state-running')}</td>
        <td><button class="secondary" data-overview-open="${esc(project.id)}">进入项目</button></td>
      </tr>
    `;
  }).join('') || '<tr><td colspan="7" class="empty">暂无项目</td></tr>';
}

export function renderResourcePlan() {
  if (!$('resourcePlanRows')) return;
  fillSharedSelects();
  renderResourcePlanSummary();
  renderResourcePlanPeopleRows();
  renderResourcePlanGantt();
  const tasks = filteredResourceTasks();
  $('resourcePlanRows').innerHTML = tasks.map(task => {
    const progress = Math.max(0, Math.min(100, Number(task.progress || 0)));
    const conflict = isTaskConflict(task);
    return `
      <tr>
        <td><strong>${esc(task.owner_name || '未分配')}</strong><div class="muted">${esc(task.module || '')}</div></td>
        <td>${esc(task.project_name || '')}<div class="muted">${esc(task.entity_name || '')}</div></td>
        <td>${esc(task.name || '')}</td>
        <td>${esc(task.start_date || '')} 至 ${esc(task.end_date || '')}</td>
        <td><div class="progress-line"><span style="width:${progress}%"></span></div><div class="muted">${progress}%</div></td>
        <td>${tag(task.status || 'open', statusClass(task.status || 'open'))}${conflict ? tag('冲突', 'amber') : ''}</td>
        <td><button class="danger" data-task-delete="${esc(task.id)}">删除</button></td>
      </tr>
    `;
  }).join('') || '<tr><td colspan="7" class="empty">暂无符合筛选条件的人员安排</td></tr>';
}

function parseDate(value) {
  const date = value ? new Date(`${value}T00:00:00`) : null;
  return date && !Number.isNaN(date.getTime()) ? date : null;
}

function toDateInputValue(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function overlaps(a, b) {
  const aStart = parseDate(a.start_date);
  const aEnd = parseDate(a.end_date || a.start_date);
  const bStart = parseDate(b.start_date);
  const bEnd = parseDate(b.end_date || b.start_date);
  if (!aStart || !aEnd || !bStart || !bEnd) return false;
  return aStart <= bEnd && bStart <= aEnd;
}

function todayDate() {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

function normalizedTaskStatus(task) {
  return String(task?.status || 'open').toLowerCase();
}

function isTaskClosed(task) {
  return CLOSED_TASK_STATUSES.has(normalizedTaskStatus(task));
}

function isTaskActive(task) {
  return ACTIVE_TASK_STATUSES.has(normalizedTaskStatus(task)) && !isTaskClosed(task);
}

function taskTiming(task) {
  if (isTaskClosed(task)) return 'ended';
  const start = parseDate(task.start_date);
  const end = parseDate(task.end_date || task.start_date);
  if (!start && !end) return 'unscheduled';
  const effectiveStart = start || end;
  const effectiveEnd = end || start;
  const today = todayDate();
  if (effectiveEnd < today) return 'ended';
  if (effectiveStart > today) return 'upcoming';
  return isTaskActive(task) ? 'current' : 'ended';
}

function isTaskConflict(task, tasks = state.tasks || []) {
  if (!task?.owner_user_id || !isTaskActive(task)) return false;
  return tasks.some(other => (
    Number(other.id || 0) !== Number(task.id || 0) &&
    Number(other.owner_user_id || 0) === Number(task.owner_user_id || 0) &&
    isTaskActive(other) &&
    overlaps(task, other)
  ));
}

function resourceFilterValues() {
  return {
    ownerId: $('resourcePlanOwnerFilter')?.value || '',
    projectId: $('resourcePlanProjectFilter')?.value || '',
    status: $('resourcePlanStatusFilter')?.value || '',
    keyword: String($('resourcePlanSearchInput')?.value || '').trim().toLowerCase(),
  };
}

function resourceTaskText(task) {
  return [
    task.owner_name,
    task.project_name,
    task.entity_name,
    task.module,
    task.name,
    task.status,
    task.start_date,
    task.end_date,
  ].join(' ').toLowerCase();
}

function taskMatchesResourceFilters(task, filters = resourceFilterValues()) {
  if (filters.ownerId && Number(task.owner_user_id || 0) !== Number(filters.ownerId)) return false;
  if (filters.projectId && Number(task.project_id || 0) !== Number(filters.projectId)) return false;
  if (filters.keyword && !resourceTaskText(task).includes(filters.keyword)) return false;
  if (filters.status === 'idle') return false;
  if (filters.status === 'conflict') return isTaskConflict(task);
  if (filters.status && taskTiming(task) !== filters.status) return false;
  return true;
}

function filteredResourceTasks() {
  const filters = resourceFilterValues();
  return (state.tasks || []).filter(task => taskMatchesResourceFilters(task, filters));
}

function userResourceText(user, tasks) {
  return [
    user.display_name,
    user.username,
    user.role_name,
    user.role_code,
    ...tasks.flatMap(task => [task.project_name, task.entity_name, task.module, task.name, task.start_date, task.end_date]),
  ].join(' ').toLowerCase();
}

function userMatchesResourceFilters(user, userTasks, filters = resourceFilterValues()) {
  if (filters.ownerId && Number(user.id) !== Number(filters.ownerId)) return false;
  if (filters.projectId && !userTasks.some(task => Number(task.project_id || 0) === Number(filters.projectId))) return false;
  if (filters.keyword && !userResourceText(user, userTasks).includes(filters.keyword)) return false;
  if (filters.status === 'current') return userTasks.some(task => taskTiming(task) === 'current');
  if (filters.status === 'upcoming') return userTasks.some(task => taskTiming(task) === 'upcoming');
  if (filters.status === 'ended') return userTasks.some(task => taskTiming(task) === 'ended');
  if (filters.status === 'conflict') return userTasks.some(task => isTaskConflict(task));
  if (filters.status === 'idle') return !userTasks.some(task => taskTiming(task) === 'current');
  return true;
}

function taskPeriod(task) {
  if (!task?.start_date && !task?.end_date) return '未维护周期';
  return `${task.start_date || '未维护'} 至 ${task.end_date || task.start_date || '未维护'}`;
}

function assignmentList(tasks, emptyText) {
  if (!tasks.length) return `<span class="muted">${esc(emptyText)}</span>`;
  return `<div class="resource-assignment-list">${tasks.map(task => `
    <div>
      <strong>${esc(task.project_name || '未命名项目')}</strong>
      <small>${esc(task.name || task.module || '未命名事项')} / ${esc(taskPeriod(task))}</small>
    </div>
  `).join('')}</div>`;
}

function renderResourcePlanSummary() {
  const box = $('resourcePlanSummary');
  if (!box) return;
  const users = resourceUsers();
  const tasks = state.tasks || [];
  const currentTasks = tasks.filter(task => taskTiming(task) === 'current');
  const currentOwners = new Set(currentTasks.map(task => Number(task.owner_user_id || 0)).filter(Boolean));
  const conflictTasks = tasks.filter(task => isTaskConflict(task));
  const idleCount = users.filter(user => !currentOwners.has(Number(user.id))).length;
  box.innerHTML = `
    <div class="mini-stat"><span>人员</span><strong>${esc(users.length)}</strong></div>
    <div class="mini-stat"><span>当前安排</span><strong>${esc(currentTasks.length)}</strong></div>
    <div class="mini-stat"><span>当前空闲</span><strong>${esc(idleCount)}</strong></div>
    <div class="mini-stat"><span>排期冲突</span><strong>${esc(conflictTasks.length)}</strong></div>
  `;
}

function renderResourcePlanPeopleRows() {
  const body = $('resourcePlanPeopleRows');
  if (!body) return;
  const filters = resourceFilterValues();
  const tasks = state.tasks || [];
  const users = resourceUsers().filter(user => {
    const userTasks = tasks.filter(task => Number(task.owner_user_id || 0) === Number(user.id));
    return userMatchesResourceFilters(user, userTasks, filters);
  });
  body.innerHTML = users.map(user => {
    const userTasks = tasks.filter(task => Number(task.owner_user_id || 0) === Number(user.id));
    const currentTasks = userTasks.filter(task => taskTiming(task) === 'current').sort((a, b) => String(a.end_date || '').localeCompare(String(b.end_date || '')));
    const upcomingTasks = userTasks.filter(task => taskTiming(task) === 'upcoming').sort((a, b) => String(a.start_date || '').localeCompare(String(b.start_date || ''))).slice(0, 2);
    const conflictCount = userTasks.filter(task => isTaskConflict(task)).length;
    return `
      <tr>
        <td><strong>${esc(user.display_name || user.username || `用户 #${user.id}`)}</strong><div class="muted">${esc(user.username || '')}</div></td>
        <td>${esc(user.role_name || '未维护')}</td>
        <td>${assignmentList(currentTasks, '当前无项目安排')}</td>
        <td>${currentTasks.length ? currentTasks.map(task => esc(taskPeriod(task))).join('<br>') : tag('当前空闲', 'state-done')}</td>
        <td>${assignmentList(upcomingTasks, '暂无后续安排')}</td>
        <td>${conflictCount ? tag(`${conflictCount}项冲突`, 'amber') : tag('无冲突', 'state-done')}</td>
      </tr>
    `;
  }).join('') || '<tr><td colspan="6" class="empty">暂无符合筛选条件的人员</td></tr>';
}

function renderResourcePlanGantt() {
  if (!$('resourcePlanGantt')) return;
  const tasks = filteredResourceTasks();
  const year = ganttCursor.getFullYear();
  const month = ganttCursor.getMonth();
  const days = new Date(year, month + 1, 0).getDate();
  const monthWindow = {
    start_date: toDateInputValue(new Date(year, month, 1)),
    end_date: toDateInputValue(new Date(year, month, days)),
  };
  $('resourcePlanGanttMonth').textContent = `${year}-${String(month + 1).padStart(2, '0')}`;
  const visibleTasks = tasks.filter(task => overlaps(task, monthWindow));
  if (!tasks.length || !visibleTasks.length) {
    $('resourcePlanGantt').innerHTML = '<div class="empty">暂无人员排期</div>';
    return;
  }
  const byOwner = new Map();
  visibleTasks.forEach(task => {
    const key = task.owner_name || '未分配';
    if (!byOwner.has(key)) byOwner.set(key, []);
    byOwner.get(key).push(task);
  });
  const dayHeaders = Array.from({length: days}, (_, i) => `<span>${i + 1}</span>`).join('');
  const rows = Array.from(byOwner.entries()).map(([owner, ownerTasks]) => {
    const bars = ownerTasks.map((task, index) => {
      const start = parseDate(task.start_date) || new Date(year, month, 1);
      const end = parseDate(task.end_date || task.start_date) || start;
      const startDay = start.getFullYear() === year && start.getMonth() === month ? start.getDate() : 1;
      const endDay = end.getFullYear() === year && end.getMonth() === month ? end.getDate() : days;
      const left = Math.max(1, Math.min(days, startDay));
      const width = Math.max(1, Math.min(days, endDay) - left + 1);
      const conflict = ownerTasks.some((other, otherIndex) => otherIndex !== index && overlaps(task, other));
      return `
        <div class="gantt-bar ${conflict ? 'conflict' : ''}" style="--start:${left};--span:${width}" title="${esc(task.project_name || '')} / ${esc(task.name || '')} / ${esc(task.start_date || '')} 至 ${esc(task.end_date || '')}">
          <strong>${esc(task.project_name || '未命名项目')}</strong>
          <span>${esc(task.module || task.name || '')} · ${esc(task.progress || 0)}%</span>
        </div>
      `;
    }).join('');
    return `
      <div class="gantt-row">
        <div class="gantt-owner">${esc(owner)}</div>
        <div class="gantt-lane">${bars}</div>
      </div>
    `;
  }).join('');
  $('resourcePlanGantt').innerHTML = `
    <div class="gantt-header" style="--days:${days}"><div></div><div class="gantt-days" style="--days:${days}">${dayHeaders}</div></div>
    ${rows}
  `;
  $('resourcePlanGantt').querySelectorAll('.gantt-lane').forEach(lane => lane.style.setProperty('--days', days));
}

function shiftGanttMonth(delta) {
  ganttCursor = new Date(ganttCursor.getFullYear(), ganttCursor.getMonth() + delta, 1);
  renderResourcePlanGantt();
}

function templateCodeKey(template) {
  return String(template?.code || '').trim() || `template-${template?.id || ''}`;
}

function templateYearText(template) {
  return String(template?.applicable_year || '');
}

function templateNoteText(template) {
  return template?.update_note || '';
}

function templateFileStatus(template) {
  return template?.file_exists ? tag('可下载', 'green') : tag('文件缺失', 'red');
}

function templateTimestamp(template) {
  return template?.updated_at || template?.created_at || '';
}

function formatTemplateTime(value) {
  if (!value) return '未维护';
  return String(value).replace('T', ' ').replace(/\.\d+$/, '').slice(0, 19);
}

function compareTemplateVersions(a, b) {
  if (Boolean(a?.is_latest) !== Boolean(b?.is_latest)) return a?.is_latest ? -1 : 1;
  const aTime = Date.parse(templateTimestamp(a));
  const bTime = Date.parse(templateTimestamp(b));
  if (!Number.isNaN(aTime) && !Number.isNaN(bTime) && aTime !== bTime) return bTime - aTime;
  if ((a?.sort_order || 0) !== (b?.sort_order || 0)) return (a?.sort_order || 0) - (b?.sort_order || 0);
  return String(b?.version || '').localeCompare(String(a?.version || ''), 'zh-Hans-CN', {numeric: true});
}

function groupTemplates(templates) {
  const groups = new Map();
  (templates || []).forEach(template => {
    const key = templateCodeKey(template);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(template);
  });
  return Array.from(groups.entries()).map(([code, versions]) => {
    const sorted = versions.slice().sort(compareTemplateVersions);
    const latest = sorted.find(row => row.is_latest) || sorted[0];
    return {code, latest, versions: sorted};
  }).sort((a, b) => {
    const stageCompare = String(stageLabel(a.latest?.stage)).localeCompare(String(stageLabel(b.latest?.stage)), 'zh-Hans-CN');
    if (stageCompare) return stageCompare;
    return String(a.code).localeCompare(String(b.code), 'zh-Hans-CN', {numeric: true});
  });
}

function templateGroupMatches(group, {stage, year, keyword}) {
  if (stage && stageLabel(group.latest?.stage) !== stage) return false;
  return group.versions.some(template => {
    const text = [
      template.code,
      template.name,
      template.filename,
      template.version,
      template.update_note,
      template.description,
      stageLabel(template.stage),
      templateYearText(template),
    ].join(' ').toLowerCase();
    if (year && !templateYearText(template).toLowerCase().includes(year)) return false;
    if (keyword && !text.includes(keyword)) return false;
    return true;
  });
}

function renderTemplateCompareField(label, latestValue, selectedValue) {
  const normalizedLatest = String(latestValue || '');
  const normalizedSelected = String(selectedValue || '');
  const changed = normalizedLatest !== normalizedSelected;
  return `
    <div class="template-compare-field ${changed ? 'changed' : ''}">
      <span>${esc(label)}</span>
      <strong>${esc(normalizedLatest || '未维护')}</strong>
      <em>${esc(normalizedSelected || '未维护')}</em>
    </div>
  `;
}

function renderTemplateMetadataCompare(latest, selected) {
  if (!selected) return '<div class="empty">暂无可对比的历史版本</div>';
  return `
    <div class="template-compare">
      <div class="template-compare-head">
        <strong>元数据对比</strong>
        <span class="muted">上方为最新版本，下方为选中历史版本</span>
      </div>
      <div class="template-compare-grid">
        ${renderTemplateCompareField('模板名称', latest?.name, selected?.name)}
        ${renderTemplateCompareField('阶段', stageLabel(latest?.stage), stageLabel(selected?.stage))}
        ${renderTemplateCompareField('适用年度', templateYearText(latest), templateYearText(selected))}
        ${renderTemplateCompareField('更新说明', templateNoteText(latest), templateNoteText(selected))}
        ${renderTemplateCompareField('文件名', latest?.filename, selected?.filename)}
        ${renderTemplateCompareField('更新时间', formatTemplateTime(templateTimestamp(latest)), formatTemplateTime(templateTimestamp(selected)))}
      </div>
    </div>
  `;
}

function renderTemplateHistory(group) {
  const selectedId = Number(templateCompareTargets[group.code] || 0);
  const historical = group.versions.filter(template => !template.is_latest);
  const selected = group.versions.find(template => Number(template.id) === selectedId) || historical[0] || null;
  if (selected) templateCompareTargets[group.code] = selected.id;
  const options = historical.map(template => `
    <option value="${esc(template.id)}" ${Number(template.id) === Number(selected?.id) ? 'selected' : ''}>
      ${esc(template.version || `版本 #${template.id}`)} / ${esc(templateYearText(template) || '未维护年度')} / ${esc(formatTemplateTime(templateTimestamp(template)))}
    </option>
  `).join('');
  const historyRows = group.versions.map(template => `
    <tr>
      <td>${esc(template.version || '')}</td>
      <td>${esc(templateYearText(template) || '未维护')}</td>
      <td>${esc(templateNoteText(template) || '未维护')}</td>
      <td>${template.is_latest ? tag('最新', 'state-done') : tag('历史', 'state-closed')}</td>
      <td>${templateFileStatus(template)}</td>
      <td>${esc(formatTemplateTime(templateTimestamp(template)))}</td>
      <td><button class="secondary" data-template-download="${esc(template.id)}" ${template.file_exists ? '' : 'disabled'}>下载</button></td>
    </tr>
  `).join('');
  return `
    <tr class="template-history-row">
      <td colspan="8">
        <div class="template-history-panel">
          <div class="template-history-toolbar">
            <strong>${esc(group.code)} 全部版本</strong>
            <label>对比历史版本<select data-template-compare-code="${esc(group.code)}" ${historical.length ? '' : 'disabled'}>${options || '<option value="">暂无历史版本</option>'}</select></label>
          </div>
          <div class="table-wrap compact-table">
            <table>
              <thead><tr><th>版本</th><th>适用年度</th><th>更新说明</th><th>状态</th><th>文件状态</th><th>更新时间</th><th></th></tr></thead>
              <tbody>${historyRows || '<tr><td colspan="7" class="empty">暂无版本记录</td></tr>'}</tbody>
            </table>
          </div>
          ${renderTemplateMetadataCompare(group.latest, selected)}
        </div>
      </td>
    </tr>
  `;
}

export function renderTemplates() {
  if (!$('templateRows')) return;
  fillOptionsFromValues($('templateStageFilter'), state.templates.map(template => stageLabel(template.stage)));
  const stage = $('templateStageFilter')?.value;
  const year = String($('templateYearFilter')?.value || '').trim().toLowerCase();
  const keyword = String($('templateSearchInput')?.value || '').trim().toLowerCase();
  const groups = groupTemplates(state.templates).filter(group => templateGroupMatches(group, {stage, year, keyword}));
  $('templateRows').innerHTML = groups.map(group => {
    const template = group.latest || {};
    const historyCount = Math.max(0, group.versions.length - 1);
    const expanded = expandedTemplateCodes.has(group.code);
    return `
    <tr data-template-code="${esc(group.code)}">
      <td><strong>${esc(template.code)}</strong><div class="muted">${esc(template.filename || '')}</div></td>
      <td>${esc(template.name)}</td>
      <td>${esc(stageLabel(template.stage))}</td>
      <td>${esc(template.version || '')}<div>${template.is_latest ? tag('最新', 'state-done') : tag('历史', 'state-closed')}</div></td>
      <td>${esc(templateYearText(template) || '未维护')}</td>
      <td>${esc(templateNoteText(template) || '未维护')}</td>
      <td>${templateFileStatus(template)}<div class="muted">${esc(formatTemplateTime(templateTimestamp(template)))}</div></td>
      <td>
        <div class="row-actions">
          <button class="secondary" data-template-toggle="${esc(group.code)}" type="button">${expanded ? '收起' : '历史版本'}${historyCount ? `(${historyCount})` : ''}</button>
          <button class="secondary" data-template-download="${esc(template.id)}" ${template.file_exists ? '' : 'disabled'} type="button">下载</button>
        </div>
      </td>
    </tr>
    ${expanded ? renderTemplateHistory(group) : ''}
  `;
  }).join('') || '<tr><td colspan="8" class="empty">暂无底稿模板</td></tr>';
}

export function renderQualityFindings() {
  if (!$('qualityFindingRows')) return;
  fillSharedSelects();
  if ($('openQualityFormBtn')) $('openQualityFormBtn').disabled = !canReviewAnyProject();
  renderFindingIndexes();
  const projectId = $('qualityProjectFilter')?.value;
  const severity = $('qualitySeverityFilter')?.value;
  const status = $('qualityStatusFilter')?.value;
  const source = $('qualitySourceFilter')?.value;
  const keyword = String($('qualitySearchInput')?.value || '').trim().toLowerCase();
  const rows = (state.reviewFindings || []).filter(finding => {
    const ruleMeta = issueTypeMeta(finding.rule_code);
    const text = [finding.rule_code, ruleMeta.label, ruleMeta.principle, finding.target, finding.issue, finding.evidence, finding.owner_name, finding.assignee_name].join(' ').toLowerCase();
    if (projectId && Number(finding.project_id) !== Number(projectId)) return false;
    if (severity && severityKey(finding.severity) !== severity) return false;
    if (status && findingStatusKey(finding) !== status) return false;
    if (source && findingSourceKey(finding) !== source) return false;
    if (keyword && !text.includes(keyword)) return false;
    return true;
  });
  $('qualityFindingRows').innerHTML = rows.map(finding => {
    const findingSource = findingSourceLabel(finding);
    const ruleMeta = issueTypeMeta(finding.rule_code);
    return `
      <tr class="selectable-row" data-finding-row="${esc(finding.id)}">
        <td>${tag(findingSource, findingSource === '人工' ? 'amber' : 'blue')}</td>
        <td>${tag(severityLabel(finding.severity), severityClass(finding.severity))}</td>
        <td><strong>${esc(finding.issue_no || finding.target || finding.workpaper_code || '未维护')}</strong><div class="muted">${finding.c22_related ? tag('C22', 'blue') : tag('非C22', 'green')} ${esc(finding.target || finding.workpaper_code || '')}</div></td>
        <td><strong>${esc(ruleMeta.label)}</strong><div class="muted">${esc(finding.rule_code || 'MANUAL')} · ${esc(ruleMeta.principle)}</div></td>
        <td>${esc(compactText(finding.issue, 50))}</td>
        <td>${tag(findingStatusLabel(finding), findingStatusClass(finding))}</td>
        <td class="actions">
          <button class="secondary" data-finding-open="${esc(finding.id)}">查看</button>
          ${finding.can_reply && ['open', 'assigned', 'changes_requested'].includes(String(finding.status || 'open')) ? `<button type="button" data-finding-reply="${esc(finding.id)}">回复问题</button>` : ''}
        </td>
      </tr>
    `;
  }).join('') || '<tr><td colspan="7" class="empty">暂无质量问题记录</td></tr>';
}

function renderQualityOverdueMonitor() {
  const box = $('qualityOverdueMonitor');
  if (!box) return;
  const rows = (state.reviewFindings || []).filter(row => row.is_overdue);
  if (!rows.length) {
    box.innerHTML = '<div class="empty">暂无逾期整改问题</div>';
    return;
  }
  box.innerHTML = `
    <div class="overdue-monitor">
      <div class="summary-strip">
        <div class="mini-stat"><span>逾期问题</span><strong>${esc(rows.length)}</strong></div>
        <div class="mini-stat"><span>最长逾期</span><strong>${esc(Math.max(...rows.map(row => Number(row.overdue_days || 0))))}天</strong></div>
      </div>
      <div class="overdue-list">
        ${rows.slice(0, 8).map(row => `
          <button type="button" class="overdue-item" data-finding-open="${esc(row.id)}">
            <span><strong>${esc(row.project_name || '')} / ${esc(row.target || '未维护位置')}</strong><small>${esc(row.rule_code || '')} · ${esc(row.assignee_name || row.owner_name || '未维护责任人')}</small></span>
            ${tag(`逾期${row.overdue_days || 0}天`, 'state-risk')}
          </button>
        `).join('')}
      </div>
    </div>
  `;
}

export function renderQualityModules() {
  renderIssueDashboard();
  renderProjectOverview();
  renderResourcePlan();
  renderTemplates();
  renderQualityFindings();
}

export async function loadIssueDashboard() {
  state.issueDashboard = await request('/api/review-dashboard');
  renderIssueDashboard();
}

export async function loadResourcePlan() {
  state.tasks = await request('/api/tasks');
  renderResourcePlan();
}

export async function loadTemplates() {
  state.templates = await request('/api/workpaper-templates');
  renderTemplates();
}

export async function loadProjectOverview() {
  state.overviewWorkpapers = await request('/api/workpapers');
  renderProjectOverview();
}

export async function loadQualityFindings() {
  state.reviewFindings = await request('/api/review-findings');
  renderQualityFindings();
}

let openedFindingId = null;
let openedFindingProjectId = null;
const findingDrawerDrafts = new Map();

function currentDrawerProjectId() {
  const id = Number(activeProjectId() || 0);
  return id || null;
}

function findingMatchesCurrentProject(finding) {
  const activeId = currentDrawerProjectId();
  const findingProjectId = Number(finding?.project_id || 0);
  return Boolean(activeId && findingProjectId && activeId === findingProjectId);
}

function rememberFindingDrawerDraft() {
  const id = Number(openedFindingId || 0);
  const body = $('qualityFindingDrawerBody');
  if (!id || !body) return;
  const fields = {};
  body.querySelectorAll('[data-response-field], [data-decision-comment], [data-drawer-field]').forEach(field => {
    const key = field.dataset.responseField || field.dataset.drawerField || 'decision_comment';
    fields[key] = field.value;
  });
  if (Object.keys(fields).length) findingDrawerDrafts.set(id, fields);
}

function restoreFindingDrawerDraft(id) {
  const fields = findingDrawerDrafts.get(Number(id));
  if (!fields) return;
  const body = $('qualityFindingDrawerBody');
  body?.querySelectorAll('[data-response-field], [data-decision-comment], [data-drawer-field]').forEach(field => {
    const key = field.dataset.responseField || field.dataset.drawerField || 'decision_comment';
    if (Object.prototype.hasOwnProperty.call(fields, key) && !field.disabled && !field.readOnly) field.value = fields[key];
  });
}

function clearFindingDrawerDraft(id) {
  findingDrawerDrafts.delete(Number(id));
  if (Number(openedFindingId) === Number(id)) openedFindingId = null;
}

export async function refreshQualityReviewData({focusFindingId = openedFindingId} = {}) {
  const openedProjectId = openedFindingProjectId;
  const results = await Promise.allSettled([loadQualityFindings(), loadIssueDashboard()]);
  const id = Number(focusFindingId || 0);
  const finding = (state.reviewFindings || []).find(item => Number(item.id) === id);
  if (id && (!openedProjectId || Number(openedProjectId) === currentDrawerProjectId()) && findingMatchesCurrentProject(finding)) {
    openFindingDrawer(id);
  } else if (id) {
    closeFindingDrawer();
  }
  return results;
}

export async function refreshQualityModules() {
  await Promise.allSettled([
    loadIssueDashboard(),
    loadResourcePlan(),
    loadTemplates(),
    loadProjectOverview(),
    loadQualityFindings(),
  ]);
}

async function saveTask(form) {
  const payload = formData(form);
  if (!payload.project_id) payload.project_id = activeProjectId();
  if (!payload.project_id) return setStatus('请先选择项目');
  const ownerId = Number(payload.owner_user_id || 0);
  const payloadTask = {...payload, owner_user_id: ownerId};
  const conflicts = ownerId
    ? (state.tasks || []).filter(task => (
      Number(task.owner_user_id || 0) === ownerId &&
      isTaskActive(payloadTask) &&
      isTaskActive(task) &&
      overlaps(payload, task)
    ))
    : [];
  if (conflicts.length) {
    const detail = conflicts.slice(0, 3).map(task => `${task.project_name || '未命名项目'} / ${task.name || '未命名事项'} / ${task.start_date || '-'} 至 ${task.end_date || '-'}`).join('\n');
    if (!confirm(`该人员在所选周期已有 ${conflicts.length} 条安排：\n${detail}\n是否仍继续保存？`)) return;
  }
  await request('/api/tasks', {method: 'POST', body: JSON.stringify(payload)});
  form.reset();
  await loadResourcePlan();
  setStatus('人员安排计划已保存');
}

async function deleteTask(id) {
  if (!confirm('确认删除该人员安排？')) return;
  await request(`/api/tasks/${id}`, {method: 'DELETE'});
  await loadResourcePlan();
  setStatus('人员安排计划已删除');
}

async function createFinding(form) {
  const payload = formData(form);
  if (!payload.project_id) payload.project_id = activeProjectId();
  if (!payload.project_id) return setStatus('请先选择项目');
  await request('/api/review-findings', {method: 'POST', body: JSON.stringify(payload)});
  form.reset();
  $('qualityFormPanel')?.classList.add('hidden');
  await refreshReviewViews();
  setStatus('人工复核问题已记录');
}

function openFindingDrawer(id, {focusReply = false} = {}) {
  const finding = (state.reviewFindings || []).find(row => Number(row.id) === Number(id));
  if (!finding || !findingMatchesCurrentProject(finding) || !$('qualityFindingDrawer')) return;
  rememberFindingDrawerDraft();
  openedFindingId = Number(id);
  openedFindingProjectId = Number(finding.project_id);
  const source = findingSourceLabel(finding);
  const historyRows = (finding.histories || []).map(history => `
    <div class="history-item">
      <strong>${esc(history.operator_name || '系统')}</strong>
      <span>${esc(history.change_summary || '处理记录')}</span>
      <small>${esc(history.created_at || '')}${history.comment ? ` / ${esc(history.comment)}` : ''}</small>
    </div>
  `).join('');
  const responseRows = (finding.responses || []).map(response => `
    <div class="history-item">
      <strong>第 ${esc(response.round_no)} 轮 / ${esc(response.responder_name || '整改责任人')}</strong>
      <span>${esc(response.response_text || '')}</span>
      <small>${esc(response.created_at || '')}${response.attachment ? ` / 附件或链接：${esc(response.attachment)}` : ''}</small>
    </div>
  `).join('');
  const canReview = Boolean(finding.can_review);
  const canReply = Boolean(finding.can_reply) && ['open', 'assigned', 'changes_requested'].includes(String(finding.status || 'open'));
  const fieldDisabled = canReview ? '' : 'disabled';
  const replyPanel = canReply ? `
    <div class="assignment-panel" id="findingReplyPanel">
      <h3>提交整改回复</h3>
      <label>本轮回复<textarea data-response-field="response_text" placeholder="说明已完成的修改、判断依据及证据位置"></textarea></label>
      <label>附件路径或链接<input data-response-field="attachment" placeholder="可填写附件路径或链接"></label>
      <div class="actions"><button type="button" data-response-save="${esc(finding.id)}">提交给复核人</button></div>
    </div>
  ` : '';
  const decisionPanel = canReview && String(finding.status) === 'responded' ? `
    <div class="assignment-panel">
      <h3>复核整改回复</h3>
      <label>复核结论<textarea data-decision-comment placeholder="必须填写确认意见或继续整改要求"></textarea></label>
      <div class="actions"><button type="button" class="danger" data-finding-decision="changes_requested" data-finding-id="${esc(finding.id)}">要求继续整改</button><button type="button" data-finding-decision="closed" data-finding-id="${esc(finding.id)}">确认关闭</button></div>
    </div>
  ` : (canReview && ['closed', 'resolved'].includes(String(finding.status)) ? `
    <div class="assignment-panel"><h3>已关闭问题</h3><label>重新打开原因<textarea data-decision-comment></textarea></label><div class="actions"><button type="button" class="danger" data-finding-decision="reopened" data-finding-id="${esc(finding.id)}">重新打开</button></div></div>
  ` : '');
  $('qualityFindingDrawerBody').innerHTML = `
    <div class="detail-view">
      <div class="detail-grid">
        <div class="detail-card"><span>来源</span><strong>${esc(source)}</strong></div>
        <div class="detail-card"><span>状态</span><strong>${tag(findingStatusLabel(finding), findingStatusClass(finding))}</strong></div>
        <div class="detail-card"><span>添加人</span><strong>${esc(finding.created_by_name || finding.created_by_username || '未记录')}</strong></div>
      </div>
      <div class="two">
        <label>C22 与否<input value="${esc(finding.c22_related ? 'C22' : '非C22')}" disabled></label>
        <label>阶段<input data-drawer-field="audit_stage" value="${esc(finding.audit_stage || auditStageForFinding(finding))}" ${fieldDisabled}></label>
        <label>问题类型<input data-drawer-field="finding_type" value="${esc(findingTypeForDrawer(finding))}" ${fieldDisabled}></label>
        <label>严重程度<select data-drawer-field="severity" ${fieldDisabled}>${selectOptions([['high', '高'], ['medium', '中'], ['low', '低']], severityKey(finding.severity))}</select></label>
        <label>对应底稿<input data-drawer-field="target" value="${esc(finding.workpaper_file || finding.target || finding.workpaper_code || '')}" ${fieldDisabled}></label>
        <label>问题步骤归属<input data-drawer-field="issue_step" value="${esc(finding.issue_step || finding.location || '')}" ${fieldDisabled}></label>
        <label>问题出现的复核阶段<input value="${esc(finding.review_stage || '')}" readonly title="由系统根据项目当前复核阶段自动生成"></label>
        <label>现场负责人<input data-drawer-field="field_lead" value="${esc(finding.field_lead || finding.owner_name || '')}" ${fieldDisabled}></label>
        <label>项目组内复核人<input data-drawer-field="project_reviewer" value="${esc(finding.project_reviewer || finding.assignee_name || '')}" ${fieldDisabled}></label>
      </div>
      <label>复核问题<textarea data-drawer-field="issue" ${fieldDisabled}>${esc(finding.issue || '')}</textarea></label>
      <label>具体描述补充<textarea data-drawer-field="evidence" ${fieldDisabled}>${esc(finding.evidence || '')}</textarea></label>
      <label>问题类别<input data-drawer-field="issue_category" value="${esc(finding.issue_category || '')}" ${fieldDisabled}></label>
      <label>建议处理<textarea data-drawer-field="recommendation" ${fieldDisabled}>${esc(finding.recommendation || '')}</textarea></label>
      ${replyPanel}
      <div class="history-list"><h3>整改回复记录</h3>${responseRows || '<div class="empty">暂无整改回复</div>'}</div>
      ${decisionPanel}
      ${finding.review_comment ? `<div class="subtle-note"><strong>最近复核意见：</strong>${esc(finding.review_comment)}</div>` : ''}
      <div class="history-list">
        <h3>问题修改日志</h3>
        ${historyRows || '<div class="empty">暂无历史记录</div>'}
      </div>
      ${canReview ? `<div class="actions"><button type="button" data-drawer-save="${esc(finding.id)}">保存问题信息</button></div>` : ''}
    </div>
  `;
  $('qualityFindingDrawer').classList.add('open');
  $('qualityFindingDrawer').setAttribute('aria-hidden', 'false');
  restoreFindingDrawerDraft(id);
  if (focusReply) {
    window.setTimeout(() => $('findingReplyPanel')?.scrollIntoView({block: 'start'}), 0);
  }
}

function auditStageForFinding(finding) {
  const target = String(finding.workpaper_file || finding.target || finding.workpaper_code || '').trim().toUpperCase();
  if (target.startsWith('B')) return '计划阶段';
  if (target.startsWith('A')) return '报告阶段';
  return '执行阶段';
}

function findingTypeForDrawer(finding) {
  if (finding.finding_type) return finding.finding_type;
  const target = String(finding.workpaper_file || finding.target || finding.workpaper_code || '').trim().toUpperCase();
  if (target.startsWith('S')) return 'CAATs';
  if (target.startsWith('C26')) return 'ITAC';
  return 'ITGC';
}

export function openQualityFinding(id) {
  openFindingDrawer(Number(id));
}

export function closeQualityFindingDrawer({preserveDraft = true} = {}) {
  if (preserveDraft) rememberFindingDrawerDraft();
  else clearFindingDrawerDraft(openedFindingId);
  openedFindingId = null;
  openedFindingProjectId = null;
  $('qualityFindingDrawer')?.classList.remove('open');
  $('qualityFindingDrawer')?.setAttribute('aria-hidden', 'true');
}

function closeFindingDrawer() {
  closeQualityFindingDrawer();
}

async function saveFindingFromDrawer(id) {
  const payload = {};
  $('qualityFindingDrawerBody').querySelectorAll('[data-drawer-field]').forEach(input => {
    payload[input.dataset.drawerField] = input.value;
  });
  await request(`/api/review-findings/${id}`, {method: 'PATCH', body: JSON.stringify(payload)});
  closeQualityFindingDrawer({preserveDraft: false});
  const refreshResults = await refreshReviewViews();
  setStatus(refreshFailureMessage(refreshResults, '质量问题已保存'));
}

async function submitFindingResponse(id) {
  const payload = {};
  $('qualityFindingDrawerBody').querySelectorAll('[data-response-field]').forEach(input => {
    payload[input.dataset.responseField] = input.value;
  });
  if (!String(payload.response_text || '').trim()) return setStatus('请填写本轮整改回复');
  await request(`/api/review-findings/${id}/responses`, {method: 'POST', body: JSON.stringify(payload)});
  clearFindingDrawerDraft(id);
  openedFindingId = null;
  openedFindingProjectId = null;
  const refreshResults = await refreshReviewViews({focusFindingId: id});
  setStatus(refreshFailureMessage(refreshResults, '整改回复已提交，等待复核确认'));
}

async function decideFinding(id, result) {
  const comment = String($('qualityFindingDrawerBody').querySelector('[data-decision-comment]')?.value || '').trim();
  if (!comment) return setStatus('请填写复核决定说明');
  await request(`/api/review-findings/${id}/decision`, {method: 'POST', body: JSON.stringify({result, comment})});
  clearFindingDrawerDraft(id);
  openedFindingId = null;
  openedFindingProjectId = null;
  const refreshResults = await refreshReviewViews({focusFindingId: id});
  const message = result === 'closed' ? '问题已复核关闭' : result === 'reopened' ? '问题已重新打开' : '问题已退回继续整改';
  setStatus(refreshFailureMessage(refreshResults, message));
}

async function refreshReviewViews(options = {}) {
  if (typeof window.refreshReviewData === 'function') return window.refreshReviewData(options);
  return refreshQualityReviewData(options);
}

function refreshFailureMessage(results, successMessage) {
  const failed = (results || []).find(result => result?.status === 'rejected');
  return failed ? `${successMessage}，但页面刷新失败：${failed.reason?.message || '请重试'}` : successMessage;
}

async function downloadTemplate(id) {
  const template = state.templates.find(item => Number(item.id) === Number(id));
  const res = await fetch(`${api}/api/workpaper-templates/${id}/download`, {headers: authHeaders()});
  if (!res.ok) {
    let detail = await res.text();
    try { detail = JSON.parse(detail).detail || detail; } catch {}
    throw new Error(detail);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = template?.filename || `workpaper-template-${id}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function uploadTemplate(form) {
  const payload = new FormData(form);
  if (!payload.get('file')?.name) return setStatus('请选择模板文件');
  payload.set('is_latest', form.elements.is_latest?.checked ? 'true' : 'false');
  await request('/api/workpaper-templates', {method: 'POST', body: payload});
  form.reset();
  closeModal('templateUploadModal');
  await loadTemplates();
  setStatus('模板已上传');
}

export function bindQualityModules() {
  $('resourcePlanForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    try { await saveTask(event.target); } catch (err) { setStatus('错误：' + err.message); }
  });
  $('resourcePlanRows')?.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-task-delete]');
    if (!button) return;
    try { await deleteTask(Number(button.dataset.taskDelete)); } catch (err) { setStatus('错误：' + err.message); }
  });
  $('qualityFindingForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    try { await createFinding(event.target); } catch (err) { setStatus('错误：' + err.message); }
  });
  $('openQualityFormBtn')?.addEventListener('click', () => {
    $('qualityFormPanel')?.classList.remove('hidden');
    renderFindingIndexes();
    renderFindingDefaultMeta();
  });
  $('closeQualityFormBtn')?.addEventListener('click', () => $('qualityFormPanel')?.classList.add('hidden'));
  $('qualityFindingRows')?.addEventListener('click', async (event) => {
    const replyButton = event.target.closest('[data-finding-reply]');
    if (replyButton) {
      openFindingDrawer(Number(replyButton.dataset.findingReply), {focusReply: true});
      return;
    }
    const button = event.target.closest('[data-finding-open]');
    const row = event.target.closest('[data-finding-row]');
    const id = Number(button?.dataset.findingOpen || row?.dataset.findingRow || 0);
    if (!id) return;
    openFindingDrawer(id);
  });
  $('qualityOverdueMonitor')?.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-finding-open]');
    if (!button) return;
    openFindingDrawer(Number(button.dataset.findingOpen));
  });
  $('findingProjectSelect')?.addEventListener('change', renderFindingIndexes);
  $('findingTargetSelect')?.addEventListener('change', renderFindingDefaultMeta);
  $('qualityFindingDrawerBody')?.addEventListener('click', async (event) => {
    const responseButton = event.target.closest('[data-response-save]');
    if (responseButton) {
      try { await submitFindingResponse(Number(responseButton.dataset.responseSave)); } catch (err) { setStatus('错误：' + err.message); }
      return;
    }
    const decisionButton = event.target.closest('[data-finding-decision]');
    if (decisionButton) {
      try { await decideFinding(Number(decisionButton.dataset.findingId), decisionButton.dataset.findingDecision); } catch (err) { setStatus('错误：' + err.message); }
      return;
    }
    const button = event.target.closest('[data-drawer-save]');
    if (!button) return;
    try { await saveFindingFromDrawer(Number(button.dataset.drawerSave)); } catch (err) { setStatus('错误：' + err.message); }
  });
  $('qualityFindingDrawerBody')?.addEventListener('input', event => {
    if (event.target.closest('[data-response-field], [data-decision-comment], [data-drawer-field]')) rememberFindingDrawerDraft();
  });
  $('closeQualityDrawerBtn')?.addEventListener('click', closeFindingDrawer);
  ['qualityProjectFilter', 'qualitySeverityFilter', 'qualityStatusFilter', 'qualitySourceFilter', 'qualitySearchInput'].forEach(id => {
    $(id)?.addEventListener('input', renderQualityFindings);
    $(id)?.addEventListener('change', renderQualityFindings);
  });
  ['resourcePlanOwnerFilter', 'resourcePlanProjectFilter', 'resourcePlanStatusFilter', 'resourcePlanSearchInput'].forEach(id => {
    $(id)?.addEventListener('input', renderResourcePlan);
    $(id)?.addEventListener('change', renderResourcePlan);
  });
  $('resourcePlanViewSwitch')?.addEventListener('click', event => {
    const button = event.target.closest('[data-plan-view]');
    if (!button) return;
    document.querySelectorAll('[data-plan-view]').forEach(item => item.classList.toggle('active', item === button));
    $('resourcePlanGanttPanel').classList.toggle('hidden', button.dataset.planView !== 'gantt');
    $('resourcePlanListPanel').classList.toggle('hidden', button.dataset.planView !== 'list');
  });
  $('ganttPrevBtn')?.addEventListener('click', () => shiftGanttMonth(-1));
  $('ganttNextBtn')?.addEventListener('click', () => shiftGanttMonth(1));
  $('projectOverviewRows')?.addEventListener('click', async (event) => {
    const target = event.target.closest('[data-overview-open], [data-overview-project]');
    if (!target) return;
    const id = Number(target.dataset.overviewOpen || target.dataset.overviewProject || 0);
    if (!id) return;
    $('activeProject').value = id;
    $('activeProject').dispatchEvent(new Event('change'));
    window.activateAppSection?.('projectWorkspace');
    setStatus('已切换项目');
  });
  ['projectOverviewYearFilter', 'projectOverviewStatusFilter', 'projectOverviewSearchInput'].forEach(id => {
    $(id)?.addEventListener('input', renderProjectOverview);
    $(id)?.addEventListener('change', renderProjectOverview);
  });
  ['templateStageFilter', 'templateYearFilter', 'templateSearchInput'].forEach(id => {
    $(id)?.addEventListener('input', renderTemplates);
    $(id)?.addEventListener('change', renderTemplates);
  });
  $('templateRows')?.addEventListener('click', async (event) => {
    const toggle = event.target.closest('[data-template-toggle]');
    if (toggle) {
      const code = toggle.dataset.templateToggle;
      if (expandedTemplateCodes.has(code)) expandedTemplateCodes.delete(code);
      else expandedTemplateCodes.add(code);
      renderTemplates();
      return;
    }
    const button = event.target.closest('[data-template-download]');
    if (!button) return;
    try {
      await downloadTemplate(Number(button.dataset.templateDownload));
      setStatus('模板下载已开始');
    } catch (err) {
      setStatus('错误：' + err.message);
    }
  });
  $('templateRows')?.addEventListener('change', event => {
    const select = event.target.closest('[data-template-compare-code]');
    if (!select) return;
    templateCompareTargets[select.dataset.templateCompareCode] = Number(select.value || 0);
    renderTemplates();
  });
  $('openTemplateUploadBtn')?.addEventListener('click', () => openModal('templateUploadModal'));
  $('templateUploadForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    try { await uploadTemplate(event.target); } catch (err) { setStatus('错误：' + err.message); }
  });
  $('refreshIssueDashboardBtn')?.addEventListener('click', async () => {
    try { await loadIssueDashboard(); setStatus('问题看板已刷新'); } catch (err) { setStatus('错误：' + err.message); }
  });
  $('refreshProjectOverviewBtn')?.addEventListener('click', async () => {
    try {
      await Promise.all([loadProjectOverview(), loadIssueDashboard()]);
      setStatus('项目总览已刷新');
    } catch (err) { setStatus('错误：' + err.message); }
  });
  $('refreshTemplatesBtn')?.addEventListener('click', async () => {
    try { await loadTemplates(); setStatus('模板库已刷新'); } catch (err) { setStatus('错误：' + err.message); }
  });
  $('refreshQualityFindingsBtn')?.addEventListener('click', async () => {
    try { await loadQualityFindings(); setStatus('质量问题已刷新'); } catch (err) { setStatus('错误：' + err.message); }
  });
}
