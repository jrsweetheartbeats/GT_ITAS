import { api, authHeaders, request } from '../api.js?v=20260920-state12';
import { state } from '../state.js?v=20260920-state12';
import { $, activeProjectId, esc, setStatus, statusClass, tag } from '../utils.js?v=20260630a';
import {
  getProjectChecks,
  getProjectFindings,
  getProjectPbc,
  getProjectReviews,
  getProjectSystems,
  getProjectWorkpapers,
  getWorkflowProject,
  getWorkpaper,
  workflowChecks,
  workflowFindings,
  workflowProjects,
  workflowStages,
  workflowTemplates,
  workflowUsers,
  workflowWorkpapers,
} from './workflowMock.js';

const closedStatuses = new Set(['已关闭', '已解决', 'closed', 'resolved']);
const kanbanColumns = [
  ['待处理', '待处理'],
  ['已分派', '已分派'],
  ['保留', '保留/待确认'],
  ['已修订', '已修订'],
  ['待复核', '待复核'],
  ['已关闭', '已关闭'],
];

const demoMode = new URLSearchParams(location.search).get('demoMode') === 'true';
let workflowDashboardApi = null;
let workflowApiError = '';
let workflowQualityApi = null;
let reviewIssueCatalog = [];
let reviewEntryOpen = false;
let reviewEntryWorkpaperId = null;
let reviewStandardKeyword = '';
let reviewRecordScope = '';
let reviewRecordWorkpaperId = null;
let reviewEntryDraft = {};
let skipReviewEntryDraftCapture = false;
let workflowProjectRequestSeq = 0;
let workflowProjectApi = {
  projectId: null,
  summary: null,
  scope: null,
  pbc: null,
  workpapers: null,
  reviewRuns: [],
  reviewSteps: [],
  findings: [],
  autofillRuns: [],
};
let selectedProjectId = workflowProjects[0].id;
let selectedWorkpaperId = localStorage.getItem('itas_workflow_workpaper') || '';

async function openReviewedWorkpaper(workpaperId) {
  setStatus('正在打开底稿…');
  const response = await fetch(`${api}/api/workpapers/${workpaperId}/download`, {headers: authHeaders()});
  if (!response.ok) {
    let detail = await response.text();
    try { detail = JSON.parse(detail).detail || detail; } catch {}
    throw new Error(detail || '无法打开底稿文件');
  }
  const contentType = String(response.headers.get('content-type') || '').toLowerCase();
  const disposition = String(response.headers.get('content-disposition') || '');
  const filename = (disposition.match(/filename="?([^";]+)"?/i)?.[1] || '底稿文件').trim();
  const extension = filename.split('.').pop().toLowerCase();
  const canPreview = contentType.includes('pdf') || contentType.startsWith('image/') || ['txt', 'csv'].includes(extension);
  const objectUrl = URL.createObjectURL(await response.blob());
  if (canPreview) {
    window.open(objectUrl, '_blank', 'noopener');
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
    setStatus('已在新窗口打开底稿');
    return;
  }
  const link = document.createElement('a');
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1_000);
  setStatus('浏览器无法直接预览该格式，已下载到底稿文件夹');
}

function isRealMode() {
  return !demoMode;
}

function currentWorkflowProjectId() {
  return demoMode ? selectedProjectId : activeProjectId();
}

function currentWorkflowProjectKey() {
  const value = currentWorkflowProjectId();
  return value === null || value === undefined ? '' : String(value);
}

function setProject(projectId) {
  const value = String(projectId || '');
  if (!demoMode) {
    const activeProject = $('activeProject');
    if (activeProject) activeProject.value = value;
    return;
  }
  selectedProjectId = workflowProjects.some(project => project.id === value) ? value : workflowProjects[0].id;
  const firstWorkpaper = getProjectWorkpapers(selectedProjectId)[0];
  selectedWorkpaperId = firstWorkpaper?.id || '';
  if (selectedWorkpaperId) localStorage.setItem('itas_workflow_workpaper', selectedWorkpaperId);
}

function project() {
  return getWorkflowProject(selectedProjectId);
}

function percent(value, tone = 'blue') {
  const safe = Math.max(0, Math.min(100, Number(value) || 0));
  return `<div class="workflow-progress ${tone}"><span style="width:${safe}%"></span></div>`;
}

function severityTag(value) {
  const key = String(value || '').toLowerCase();
  const label = {
    high: '高',
    medium: '中',
    low: '低',
    info: '提示',
    critical: '高',
  }[key] || value || '待评估';
  const cls = ['high', 'critical', '高', '重大'].includes(key) || value === '高'
    ? 'red'
    : ['medium', '中'].includes(key) || value === '中'
      ? 'amber'
      : ['low', '低'].includes(key) || value === '低'
        ? 'blue'
        : 'gray';
  return tag(label, cls);
}

function statusTag(value) {
  return tag(value, statusClass(value));
}

function compactText(value, limit = 120) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

function isOpenFindingStatus(status) {
  return !closedStatuses.has(String(status || '').toLowerCase());
}

function findingSource(row) {
  return row.run_mode === 'manual' || row.rule_code === 'MANUAL' ? '人工' : '系统';
}

function findingBucket(row) {
  const status = String(row.status || '').toLowerCase();
  if (['assigned', '已分派'].includes(status)) return '已分派';
  if (['retained', '保留'].includes(status)) return '保留';
  if (['revised', '已修订'].includes(status)) return '已修订';
  if (['resolved', '待复核', '已解决'].includes(status)) return '待复核';
  if (['closed', '已关闭'].includes(status)) return '已关闭';
  return '待处理';
}

function renderInto(id, html) {
  const node = $(id);
  if (node) node.innerHTML = html;
}

function workflowProjectSelect() {
  if (!demoMode) return '';
  return `
    <label class="workflow-project-picker">项目
      <select data-workflow-project-select>
        ${workflowProjects.map(row => `<option value="${esc(row.id)}" ${row.id === selectedProjectId ? 'selected' : ''}>${esc(row.name)}</option>`).join('')}
      </select>
    </label>
  `;
}

function realDashboardProjectRows() {
  return (workflowDashboardApi?.projects || []).map(row => {
    const monitoring = row.monitoring || {};
    const workpapers = monitoring.workpapers || {};
    const review = monitoring.review || {};
    return {
      id: row.id,
      shortName: row.client || row.name,
      name: row.name,
      auditScope: `${row.audit_scope?.start || '未维护'} 至 ${row.audit_scope?.end || '未维护'}`,
      stage: row.stage || '未维护',
      progress: row.progress || 0,
      materialRate: row.material_rate || 0,
      workpaperRate: row.workpaper_rate || 0,
      reviewRate: row.review_rate || 0,
      dueDays: row.due_days ?? '-',
      deliveryDate: row.delivery_date || '',
      projectExitDate: row.project_exit_date || '',
      deliverySource: row.delivery_source || '',
      riskLevel: row.risk_level || '待评估',
      pbcGaps: row.pbc_gap_count || 0,
      openFindings: row.open_finding_count || 0,
      monitoring,
      workpapers,
      review,
    };
  });
}

function deliveryText(row) {
  const days = Number(row?.dueDays);
  if (row?.dueDays === '-' || Number.isNaN(days)) return '交付日期未维护';
  return days < 0 ? `已逾期${Math.abs(days)}天` : `${days}天后交付`;
}

function deliverySourceText(row) {
  if (row?.deliveryDate) {
    return `${row.deliveryDate}${row.deliverySource ? ' / ' + row.deliverySource : ''}`;
  }
  return row?.deliverySource || '';
}

function monitoringTone(status) {
  if (status === 'red') return 'risk';
  if (status === 'amber') return 'warn';
  return '';
}

function reviewSourceLabel(review = {}) {
  return review.source === 'review_workbook' ? '最新复核表' : '系统复核记录';
}

function mergeWorkflowDeliveryToProjects() {
  const rows = workflowDashboardApi?.projects || [];
  if (!rows.length || !state.projects?.length) return;
  rows.forEach(row => {
    const project = state.projects.find(item => Number(item.id) === Number(row.id));
    if (!project) return;
    project.due_days = row.due_days;
    project.delivery_date = row.delivery_date || '';
    project.project_exit_date = row.project_exit_date || '';
    project.delivery_source = row.delivery_source || '';
    project.delivery_source_type = row.delivery_source_type || '';
    project.delivery_source_workpaper_id = row.delivery_source_workpaper_id || null;
    project.delivery_source_workpaper_code = row.delivery_source_workpaper_code || '';
    project.delivery_source_workpaper_name = row.delivery_source_workpaper_name || '';
  });
}

async function loadWorkflowProjectData(projectId) {
  if (demoMode || !projectId) return;
  const id = String(projectId);
  const requestSeq = ++workflowProjectRequestSeq;
  const [summary, scope, pbc, workpapers, reviewRuns, reviewSteps, findings, autofillRuns] = await Promise.all([
    request(`/api/projects/${id}/workflow-summary`),
    request(`/api/projects/${id}/scope-items`),
    request(`/api/projects/${id}/pbc-gaps`),
    request(`/api/projects/${id}/workpaper-execution-summary`),
    request(`/api/review-runs?projectId=${id}`),
    request(`/api/projects/${id}/review-steps`),
    request(`/api/review-findings?projectId=${id}`),
    request(`/api/autofill-runs?projectId=${id}`),
  ]);
  if (requestSeq !== workflowProjectRequestSeq || currentWorkflowProjectKey() !== id) return false;
  workflowProjectApi = {projectId: id, summary, scope, pbc, workpapers, reviewRuns, reviewSteps, findings, autofillRuns};
  if (reviewRecordWorkpaperId && !(workpapers?.items || []).some(row => Number(row.id) === Number(reviewRecordWorkpaperId))) {
    reviewRecordWorkpaperId = null;
  }
  const firstWorkpaper = workpapers?.items?.[0];
  if (firstWorkpaper && !workpapers.items.some(row => String(row.id) === String(selectedWorkpaperId))) {
    selectedWorkpaperId = String(firstWorkpaper.id);
    localStorage.setItem('itas_workflow_workpaper', selectedWorkpaperId);
  }
  return true;
}

export async function refreshWorkflowReviewCenterData() {
  const projectId = currentWorkflowProjectKey();
  if (demoMode) return [];
  const tasks = [
    request('/api/workflow/dashboard').then(data => {
      workflowDashboardApi = data;
      mergeWorkflowDeliveryToProjects();
    }),
    request('/api/review-dashboard').then(data => { workflowQualityApi = data; }),
  ];
  if (projectId) tasks.push(loadWorkflowProjectData(projectId));
  const results = await Promise.allSettled(tasks);
  const failed = results.find(result => result.status === 'rejected');
  workflowApiError = failed ? (failed.reason?.message || '复核监控数据加载失败') : '';
  renderReviewCenter();
  renderWorkflowDashboard();
  renderQualityDashboard();
  return results;
}

async function loadReviewIssueCatalog() {
  if (reviewIssueCatalog.length) return;
  const payload = await request('/api/review-issue-catalog?limit=2000');
  reviewIssueCatalog = payload.items || [];
}

function renderRealWorkflowDashboard() {
  const metrics = workflowDashboardApi?.metrics || {};
  const rows = realDashboardProjectRows();
  const alerts = workflowDashboardApi?.alerts || [];
  const pendingConfirmations = workflowDashboardApi?.pending_confirmations || [];
  renderInto('workflowDashboardPanel', `
    <div class="workflow-shell">
      ${pageHeader('项目监控', '以最新底稿文件、编制/复核签名和复核问题闭环为核心，集中识别交付阻塞。', `
        ${actionButton('projectWorkspace', 'ti-folder-open', '项目总览')}
        ${actionButton('qualityDashboard', 'ti-chart-dots-3', '复核质控')}
      `)}
      ${pendingConfirmations.length ? `
        <div class="panel quality-attention-panel">
          <div class="panel-head"><h2>质控待确认 · 助理已回复</h2><span>${esc(pendingConfirmations.length)} 条未确认解决，已置顶</span></div>
          <div class="workflow-alert-list">
            ${pendingConfirmations.map(item => `
              <button type="button" data-workflow-open-pending-confirmation="${esc(item.finding_id)}" data-project-id="${esc(item.project_id)}">
                <span>${tag('立即处理', 'red')}</span>
                <strong>${esc(item.project_name)}：${esc(item.responder_name || '项目组成员')}已回复${item.issue_no ? `（${esc(item.issue_no)}）` : ''}</strong>
                <small>${esc(compactText(item.issue || '复核问题', 100))}${item.workpaper ? ` / ${esc(compactText(item.workpaper, 50))}` : ''}${item.responded_at ? ` / ${esc(item.responded_at)}` : ''}</small>
              </button>
            `).join('')}
          </div>
        </div>
      ` : ''}
      <div class="workflow-metric-grid">
        ${metricCard('在审项目', metrics.visible_projects ?? rows.length, '含计划、实施与复核整改阶段')}
        ${metricCard('底稿路径失联', metrics.workpaper_missing_count ?? 0, '系统登记路径中找不到文件', Number(metrics.workpaper_missing_count || 0) ? 'risk' : '')}
        ${metricCard('编制签名缺口', metrics.preparation_gap_count ?? 0, '可用底稿中编制人或日期不完整', Number(metrics.preparation_gap_count || 0) ? 'warn' : '')}
        ${metricCard('待复核确认', metrics.review_pending_confirmation_count ?? 0, '项目组已回复、复核人尚未确认', Number(metrics.review_pending_confirmation_count || 0) ? 'warn' : '')}
      </div>
      <div class="workflow-grid">
        <div class="panel">
          <div class="panel-head"><h2>项目交付准备度</h2><span class="muted">文件25% · 编制30% · 复核25% · 问题关闭20%</span></div>
          <div class="table-wrap workflow-table">
            <table>
              <thead><tr><th>项目</th><th>阶段/交付</th><th>准备度</th><th>文件</th><th>编制</th><th>复核</th><th>整改确认</th><th>状态</th><th></th></tr></thead>
              <tbody>
                ${rows.map(row => `
                  <tr>
                    <td><strong>${esc(row.shortName)}</strong><div class="muted">${esc(row.auditScope)}</div></td>
                    <td>${statusTag(row.stage)}<div class="muted">${esc(deliveryText(row))}</div></td>
                    <td>${percent(row.progress, row.progress < 70 ? 'amber' : 'green')}<div class="muted">${row.progress}%</div></td>
                    <td><strong>${esc(row.workpapers.available_count || 0)}/${esc(row.workpapers.total || 0)}</strong><div class="muted">可定位</div></td>
                    <td><strong>${esc(row.workpapers.prepared_count || 0)}/${esc(row.workpapers.total || 0)}</strong><div class="muted">签名完整</div></td>
                    <td><strong>${esc(row.workpapers.reviewed_count || 0)}/${esc(row.workpapers.total || 0)}</strong><div class="muted">签名完整</div></td>
                    <td><strong>${esc(row.review.resolved_count || 0)}/${esc(row.review.issue_count || 0)}</strong><div class="muted">${esc(row.review.pending_confirmation_count || 0)} 待确认</div></td>
                    <td>${severityTag(row.riskLevel)}<div class="muted">${esc(row.monitoring.next_action || '')}</div></td>
                    <td><button type="button" class="secondary" data-workflow-open-real-project="${esc(row.id)}">打开</button></td>
                  </tr>
                `).join('') || '<tr><td colspan="9" class="empty">暂无在审项目</td></tr>'}
              </tbody>
            </table>
          </div>
        </div>
        <div class="panel">
          <div class="panel-head"><h2>优先处理</h2></div>
          <div class="workflow-alert-list">
            ${alerts.slice(0, 8).map(row => `
              <button type="button" data-workflow-open-real-project="${esc(row.project_id)}">
                <span>${tag(row.level === 'high' ? '阻塞' : '关注', row.level === 'high' ? 'red' : 'amber')}</span>
                <strong>${esc(row.project_name)}：${esc(row.title)}</strong>
                <small>${esc(row.detail || '进入项目查看明细')}</small>
              </button>
            `).join('') || '<div class="empty">当前项目底稿与复核未识别到阻塞。</div>'}
          </div>
        </div>
      </div>
    </div>
  `);
}

function pageHeader(title, subtitle, actions = '') {
  return `
    <div class="workflow-page-head">
      <div>
        <div class="muted">ITAS 核心监控</div>
        <h2>${esc(title)}</h2>
        <p>${esc(subtitle)}</p>
      </div>
      <div class="workflow-head-actions">
        ${workflowProjectSelect()}
        ${actions}
      </div>
    </div>
  `;
}

function metricCard(label, value, note, tone = '') {
  return `
    <div class="workflow-metric ${esc(tone)}">
      <span>${esc(label)}</span>
      <strong>${esc(value)}</strong>
      <small>${esc(note)}</small>
    </div>
  `;
}

function actionButton(section, icon, text, cls = 'secondary') {
  if (section === 'qualityDashboard' && !state.me?.is_admin) {
    const permission = state.me?.permissions?.qualityDashboard;
    if (!permission?.view && !permission?.edit && !permission?.manage) return '';
  }
  return `<button type="button" class="${esc(cls)}" data-workflow-route="${esc(section)}"><i class="ti ${esc(icon)}"></i> ${esc(text)}</button>`;
}

function renderRealProjectPending(containerId, title) {
  const projectId = currentWorkflowProjectKey();
  renderInto(containerId, `
    <div class="workflow-shell">
      ${pageHeader(title, projectId ? '正在加载当前全局项目的真实工作流数据。' : '请先选择一个正在执行项目。', projectId ? '<button type="button" class="secondary" data-workflow-retry-review-data><i class="ti ti-refresh"></i> 重试</button>' : '')}
      <div class="panel"><div class="panel-body">${projectId ? `当前项目 #${esc(projectId)} 的工作流数据尚未加载完成。` : '请选择一个正在执行项目后查看工作流详情。'}</div></div>
    </div>
  `);
}

function openItems(rows) {
  return rows.filter(row => !closedStatuses.has(String(row.status || '').toLowerCase()) && !closedStatuses.has(row.status));
}

function projectSummary(projectRow) {
  const pbc = getProjectPbc(projectRow.id);
  const workpapers = getProjectWorkpapers(projectRow.id);
  const checks = getProjectChecks(projectRow.id);
  const findings = getProjectFindings(projectRow.id);
  const pbcGaps = pbc.filter(row => row.status !== '已收到').length;
  const openFindings = openItems(findings).length;
  const failedChecks = checks.filter(row => row.result !== '通过').length;
  const returned = getProjectReviews(projectRow.id).filter(row => row.status === '退回').length;
  return {
    pbcGaps,
    openFindings,
    failedChecks,
    returned,
    workpapers: workpapers.length,
    completedWorkpapers: workpapers.filter(row => ['已完成', '已关闭'].includes(row.status)).length,
  };
}

function renderWorkflowDashboard() {
  if (!demoMode && workflowDashboardApi) return renderRealWorkflowDashboard();
  if (!demoMode && workflowApiError) {
    renderInto('workflowDashboardPanel', `
      <div class="workflow-shell">
        ${pageHeader('首页驾驶舱', '真实工作流聚合数据加载失败。', '')}
        <div class="panel"><div class="panel-body">${tag('API异常', 'red')} <span class="muted">${esc(workflowApiError)}</span></div></div>
      </div>
    `);
    return;
  }
  if (!demoMode) {
    renderInto('workflowDashboardPanel', `
      <div class="workflow-shell">
        ${pageHeader('首页驾驶舱', '正在加载真实工作流聚合数据。', '')}
        <div class="panel"><div class="panel-body">正在读取 /api/workflow/dashboard。</div></div>
      </div>
    `);
    return;
  }
  const openFindingRows = openItems(workflowFindings);
  const pbcGaps = workflowProjects.reduce((sum, row) => sum + projectSummary(row).pbcGaps, 0);
  const returned = workflowProjects.reduce((sum, row) => sum + projectSummary(row).returned, 0);
  const highRisks = workflowFindings.filter(row => row.severity === '高' && row.status !== '已关闭').length;
  renderInto('workflowDashboardPanel', `
    <div class="workflow-shell">
      ${pageHeader('首页驾驶舱', '围绕项目生命周期集中展示进度、资料缺口、底稿执行、自动检核、复核退回和质量风险。', `
        ${actionButton('projectWorkspace', 'ti-folder-open', '进入项目')}
        ${actionButton('reviewCenter', 'ti-user-check', '进入复核中心')}
      `)}
      <div class="workflow-metric-grid">
        ${metricCard('在审项目', workflowProjects.length, '含准备、实施、复核整改')}
        ${metricCard('资料缺口', pbcGaps, 'PBC待补充、部分收到、缺失', 'warn')}
        ${metricCard('复核退回', returned, '需编制人处理', 'warn')}
        ${metricCard('高风险问题', highRisks, '未关闭高风险', 'risk')}
      </div>
      <div class="workflow-grid">
        <div class="panel">
          <div class="panel-head"><h2>项目进度</h2><span class="muted">按交付压力排序</span></div>
          <div class="table-wrap workflow-table">
            <table>
              <thead><tr><th>项目</th><th>阶段</th><th>整体进度</th><th>资料</th><th>底稿</th><th>检核</th><th>风险</th><th></th></tr></thead>
              <tbody>
                ${workflowProjects.map(row => `
                  <tr>
                    <td><strong>${esc(row.shortName)}</strong><div class="muted">${esc(row.auditScope)}</div></td>
                    <td>${statusTag(row.stage)}<div class="muted">${esc(deliveryText(row))}</div></td>
                    <td>${percent(row.progress)}<div class="muted">${row.progress}%</div></td>
                    <td>${percent(row.materialRate, row.materialRate < 70 ? 'amber' : 'green')}<div class="muted">${row.materialRate}%</div></td>
                    <td>${percent(row.workpaperRate, row.workpaperRate < 70 ? 'amber' : 'green')}<div class="muted">${row.workpaperRate}%</div></td>
                    <td>${percent(row.checkPassRate, row.checkPassRate < 75 ? 'amber' : 'green')}<div class="muted">${row.checkPassRate}%</div></td>
                    <td>${severityTag(row.riskLevel)}</td>
                    <td><button type="button" class="secondary" data-workflow-open-project="${esc(row.id)}">打开</button></td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
        <div class="panel">
          <div class="panel-head"><h2>待办与风险提醒</h2></div>
          <div class="workflow-alert-list">
            ${openFindingRows.slice(0, 5).map(row => `
              <button type="button" data-workflow-open-project="${esc(row.projectId)}" data-workflow-route="reviewCenter">
                <span>${severityTag(row.severity)} ${tag(row.source, row.source === '系统' ? 'blue' : 'purple')}</span>
                <strong>${esc(row.title)}</strong>
                <small>${esc(getWorkflowProject(row.projectId).shortName)} / ${esc(row.workpaper)} / ${esc(row.owner)} / ${esc(row.due)}</small>
              </button>
            `).join('')}
          </div>
        </div>
      </div>
      <div class="panel">
        <div class="panel-head"><h2>模板与规则更新</h2></div>
        <div class="workflow-template-strip">
          ${workflowTemplates.map(row => `
            <div>
              <strong>${esc(row.name)}</strong>
              <span>${esc(row.version)}</span>
              <small>${esc(row.changed)}</small>
            </div>
          `).join('')}
        </div>
      </div>
    </div>
  `);
}

function renderProjectWorkspacePrototype() {
  if (isRealMode()) {
    const rows = realDashboardProjectRows();
    const projectId = currentWorkflowProjectKey();
    const row = rows.find(item => String(item.id) === projectId);
    if (!row) {
      renderInto('workflowProjectPanel', `
        <div class="workflow-shell">
          ${pageHeader('项目中心', workflowDashboardApi ? '当前全局项目未出现在正在执行项目列表中。' : '正在加载当前全局项目的工作流数据。', `
            ${actionButton('dashboard', 'ti-layout-dashboard', '返回驾驶舱')}
          `)}
          <div class="panel"><div class="panel-body">${workflowDashboardApi ? '请选择一个正在执行项目后查看工作流详情。' : '正在读取 /api/workflow/dashboard。'}</div></div>
        </div>
      `);
      return;
    }
    const workpapers = row.workpapers || {};
    const review = row.review || {};
    const blockers = row.monitoring?.blockers || [];
    renderInto('workflowProjectPanel', `
      <div class="workflow-shell">
        ${pageHeader('项目执行总览', '围绕底稿定位、编制、复核和问题闭环展示当前项目真实进展。', `
          ${actionButton('workpaperExecution', 'ti-file-analytics', '底稿进度')}
          ${actionButton('attachments', 'ti-paperclip', '资料附件')}
          ${actionButton('reviewCenter', 'ti-user-check', '进入复核中心')}
        `)}
        <div class="workflow-project-hero">
          <div>
            <span>${statusTag(row.stage)} ${severityTag(row.riskLevel)}</span>
            <h2>${esc(row.name)}</h2>
            <p>${esc(row.shortName)} / ${esc(row.auditScope)}</p>
            <div class="workflow-inline-meta">
              <span>最近底稿/复核活动：${esc(row.monitoring?.last_activity_at || '未识别')}</span>
              <span>复核来源：${esc(reviewSourceLabel(review))}</span>
              <span>当前阻塞：${esc(row.monitoring?.blocker_count || 0)}</span>
            </div>
          </div>
          <div class="workflow-delivery-box">
            <strong>${esc(row.progress)}%</strong>
            <span>交付准备度</span>
            ${deliverySourceText(row) ? `<small>${esc(deliverySourceText(row))}</small>` : ''}
            ${percent(row.progress, row.progress < 60 ? 'amber' : 'green')}
          </div>
        </div>
        <div class="workflow-metric-grid">
          ${metricCard('文件可用', `${workpapers.available_count || 0}/${workpapers.total || 0}`, `${workpapers.missing_count || 0} 份路径失联`, Number(workpapers.missing_count || 0) ? 'risk' : '')}
          ${metricCard('编制完成', `${workpapers.prepared_count || 0}/${workpapers.total || 0}`, `${workpapers.preparation_partial_count || 0} 份仅部分签名`, (workpapers.prepared_count || 0) < (workpapers.total || 0) ? 'warn' : '')}
          ${metricCard('复核完成', `${workpapers.reviewed_count || 0}/${workpapers.total || 0}`, `${workpapers.review_partial_count || 0} 份仅部分签名`, (workpapers.reviewed_count || 0) < (workpapers.total || 0) ? 'warn' : '')}
          ${metricCard('整改已回复', `${review.replied_count || 0}/${review.issue_count || 0}`, `${review.unreplied_count || 0} 条尚未回复`, Number(review.unreplied_count || 0) ? 'risk' : '')}
          ${metricCard('复核已确认', `${review.resolved_count || 0}/${review.issue_count || 0}`, `${review.pending_confirmation_count || 0} 条回复待确认`, Number(review.pending_confirmation_count || 0) ? 'warn' : '')}
          ${metricCard('距交付', deliveryText(row), deliverySourceText(row) || '交付日期未维护', Number(row.dueDays) < 0 ? 'risk' : '')}
        </div>
        <div class="workflow-grid">
          <div class="panel">
            <div class="panel-head"><h2>下一步动作</h2></div>
            <div class="workflow-list">
              ${blockers.map(item => `
                <div>
                  <i class="ti ${item.level === 'high' ? 'ti-alert-triangle' : 'ti-circle-dot'}"></i>
                  <span>${tag(item.level === 'high' ? '阻塞' : '关注', item.level === 'high' ? 'red' : 'amber')} ${esc(item.message)}</span>
                </div>
              `).join('') || '<div><i class="ti ti-circle-check"></i><span>底稿、复核与整改均已形成闭环。</span></div>'}
            </div>
          </div>
          <div class="panel">
            <div class="panel-head"><h2>监控口径</h2></div>
            <div class="workflow-list">
              <div><i class="ti ti-file-check"></i><span>底稿文件：以系统登记路径能否读取为准。</span></div>
              <div><i class="ti ti-signature"></i><span>编制/复核：以底稿页眉姓名与日期是否同时完整为准。</span></div>
              <div><i class="ti ti-message-check"></i><span>整改闭环：${esc(reviewSourceLabel(review))}优先于历史系统问题记录。</span></div>
              <div><i class="ti ti-calculator"></i><span>${esc(row.monitoring?.readiness_formula || '')}</span></div>
            </div>
          </div>
        </div>
      </div>
    `);
    return;
  }
  const row = project();
  const summary = projectSummary(row);
  renderInto('workflowProjectPanel', `
    <div class="workflow-shell">
      ${pageHeader('项目工作台', '在项目上下文内串起基本信息、系统范围、PBC、底稿、检核、复核和问题整改。', `
        ${actionButton('scopeCenter', 'ti-sitemap', '审计范围')}
        ${actionButton('pbcCenter', 'ti-inbox', '资料缺口')}
      `)}
      <div class="workflow-project-hero">
        <div>
          <span>${statusTag(row.stage)} ${severityTag(row.riskLevel)}</span>
          <h2>${esc(row.name)}</h2>
          <p>${esc(row.client)} / ${row.auditYear} / ${esc(row.auditScope)}</p>
          <div class="workflow-inline-meta">
            <span>项目负责人：${esc(row.leader)}</span>
            <span>现场负责人：${esc(row.fieldLead)}</span>
            <span>质控复核：${esc(row.qualityReviewer)}</span>
          </div>
        </div>
        <div class="workflow-delivery-box">
          <strong>${esc(row.dueDays)}</strong>
          <span>距交付天数</span>
          ${deliverySourceText(row) ? `<small>${esc(deliverySourceText(row))}</small>` : ''}
          ${percent(row.progress, row.progress < 60 ? 'amber' : 'green')}
        </div>
      </div>
      <div class="workflow-metric-grid">
        ${metricCard('系统范围', getProjectSystems(row.id).length, row.auditScopeSource)}
        ${metricCard('PBC缺口', summary.pbcGaps, '待补充或缺失资料', summary.pbcGaps ? 'warn' : '')}
        ${metricCard('底稿执行', `${summary.completedWorkpapers}/${summary.workpapers}`, '已完成/全部底稿')}
        ${metricCard('检核异常', summary.failedChecks, '自动与人工检核未通过', summary.failedChecks ? 'risk' : '')}
      </div>
      <div class="workflow-stage-grid">
        ${workflowStages.map(stage => {
          const isActive = (stage.id === 'execute' && row.stage === '项目实施') || (stage.id === 'deliver' && row.stage === '复核整改') || (stage.id === 'prepare' && row.stage === '项目准备');
          return `
            <div class="workflow-stage ${isActive ? 'active' : ''}">
              <strong>${esc(stage.name)}</strong>
              <span>${esc(stage.description)}</span>
            </div>
          `;
        }).join('')}
      </div>
      <div class="workflow-grid three-col">
        <div class="panel">
          <div class="panel-head"><h2>下一步动作</h2></div>
          <div class="workflow-list">
            ${row.nextActions.map(item => `<div><i class="ti ti-circle-dot"></i><span>${esc(item)}</span></div>`).join('')}
          </div>
        </div>
        <div class="panel">
          <div class="panel-head"><h2>成员安排</h2></div>
          <div class="workflow-user-list">
            ${workflowUsers.filter(user => row.members.includes(user.name) || user.name === row.qualityReviewer || user.name === row.manager).map(user => `
              <div>
                <strong>${esc(user.name)}</strong>
                <span>${esc(user.role)}</span>
                <small>${esc(user.email)} / ${esc(user.phone)}</small>
              </div>
            `).join('')}
          </div>
        </div>
        <div class="panel">
          <div class="panel-head"><h2>快速入口</h2></div>
          <div class="workflow-quick-actions">
            ${actionButton('workpaperExecution', 'ti-file-analytics', '底稿详情')}
            ${actionButton('autoCheck', 'ti-shield-check', '自动检核')}
            ${actionButton('reviewCenter', 'ti-user-check', '复核中心')}
            ${actionButton('qualityDashboard', 'ti-chart-dots-3', '质量看板')}
          </div>
        </div>
      </div>
    </div>
  `);
}

function renderScopeCenter() {
  const projectId = currentWorkflowProjectKey();
  if (isRealMode() && String(workflowProjectApi.projectId) === projectId && workflowProjectApi.scope?.items) {
    const row = realDashboardProjectRows().find(item => String(item.id) === projectId) || realDashboardProjectRows()[0];
    const systems = workflowProjectApi.scope.items || [];
    const confirmed = systems.filter(item => item.manager_confirmed).length;
    renderInto('scopeCenterContent', `
      <div class="workflow-shell">
        ${pageHeader('审计范围识别', '真实接口优先展示系统清单、纳入理由、证据来源、置信度和经理确认状态。', actionButton('pbcCenter', 'ti-inbox', '查看PBC缺口'))}
        <div class="workflow-metric-grid">
          ${metricCard('识别系统', systems.length, '从现有项目记录或范围表读取')}
          ${metricCard('纳入范围', systems.filter(item => item.in_scope).length, '参与IT审计测试')}
          ${metricCard('经理确认', `${confirmed}/${systems.length}`, 'SystemScopeItem落地前为推导状态', confirmed === systems.length && systems.length ? '' : 'warn')}
          ${metricCard('项目风险', row?.riskLevel || '待评估', '按资料缺口和问题推导', row?.riskLevel === '高' ? 'risk' : '')}
        </div>
        <div class="panel">
            <div class="panel-head"><h2>系统范围矩阵</h2><span class="muted">/api/projects/${esc(projectId)}/scope-items</span></div>
          <div class="table-wrap workflow-table">
            <table>
              <thead><tr><th>系统</th><th>业务流程</th><th>范围判断</th><th>纳入/排除理由</th><th>风险</th><th>置信度</th><th>来源</th></tr></thead>
              <tbody>
                ${systems.map(item => `
                  <tr>
                    <td><strong>${esc(item.system_name)}</strong><div class="muted">${esc(item.system_type || item.owner || '')}</div></td>
                    <td>${esc(item.business_process || '')}<div class="muted">${esc(item.data_sensitivity || '')}</div></td>
                    <td>${item.in_scope ? tag('纳入', 'green') : tag('待确认', 'amber')}</td>
                    <td>${esc(item.scope_reason || '')}</td>
                    <td>${severityTag(item.risk_level || '待评估')}</td>
                    <td>${percent(item.confidence || 0, Number(item.confidence || 0) < 75 ? 'amber' : 'green')}<div class="muted">${esc(item.confidence || 0)}%</div></td>
                    <td>${esc(item.source || '')}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `);
    return;
  }
  if (isRealMode()) {
    renderRealProjectPending('scopeCenterContent', '审计范围识别');
    return;
  }
  const row = project();
  const systems = getProjectSystems(row.id);
  renderInto('scopeCenterContent', `
    <div class="workflow-shell">
      ${pageHeader('审计范围识别', '展示系统清单、纳入范围理由、风险等级、依赖关系和识别置信度。', actionButton('pbcCenter', 'ti-inbox', '生成PBC入口'))}
      <div class="workflow-metric-grid">
        ${metricCard('纳入范围系统', systems.filter(item => item.inScope).length, '已进入ITGC/ITAC评估')}
        ${metricCard('高风险系统', systems.filter(item => item.risk === '高').length, '需优先补证据', systems.some(item => item.risk === '高') ? 'risk' : '')}
        ${metricCard('平均置信度', `${Math.round(systems.reduce((sum, item) => sum + item.confidence, 0) / systems.length)}%`, '来自系统清单、访谈和底稿标识')}
        ${metricCard('审计范围', row.auditScope, row.auditScopeSource)}
      </div>
      <div class="panel">
        <div class="panel-head"><h2>系统范围矩阵</h2></div>
        <div class="table-wrap workflow-table">
          <table>
            <thead><tr><th>系统</th><th>业务流程</th><th>范围判断</th><th>纳入理由</th><th>风险</th><th>置信度</th><th>依赖关系</th></tr></thead>
            <tbody>
              ${systems.map(item => `
                <tr>
                  <td><strong>${esc(item.name)}</strong><div class="muted">${esc(item.owner)}</div></td>
                  <td>${esc(item.process)}<div class="muted">${esc(item.dataSensitivity)}</div></td>
                  <td>${item.inScope ? tag('纳入', 'green') : tag('排除', 'gray')}</td>
                  <td>${esc(item.reason)}</td>
                  <td>${severityTag(item.risk)}</td>
                  <td>${percent(item.confidence, item.confidence < 80 ? 'amber' : 'green')}<div class="muted">${item.confidence}%</div></td>
                  <td>${esc(item.dependencies)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `);
}

function renderPbcCenter() {
  const projectId = currentWorkflowProjectKey();
  if (isRealMode() && String(workflowProjectApi.projectId) === projectId && workflowProjectApi.pbc?.items) {
    const pbc = workflowProjectApi.pbc.items || [];
    const gaps = pbc.filter(row => row.is_gap);
    renderInto('pbcCenterContent', `
      <div class="workflow-shell">
        ${pageHeader('PBC资料管理', '真实 DocumentRequest 数据展示资料需求、状态、缺口原因和关联控制。', actionButton('workpaperExecution', 'ti-file-analytics', '查看底稿执行'))}
        <div class="workflow-metric-grid">
          ${metricCard('资料需求', workflowProjectApi.pbc.total || pbc.length, '全部 PBC / DocumentRequest')}
          ${metricCard('资料缺口', workflowProjectApi.pbc.gap_count || gaps.length, '必需资料未关闭', gaps.length ? 'warn' : '')}
          ${metricCard('已关闭', pbc.filter(row => !row.is_gap).length, '已上传、已收到或已完成')}
          ${metricCard('缺口率', pbc.length ? `${Math.round(gaps.length / pbc.length * 100)}%` : '0%', '用于项目质量看板')}
        </div>
        <div class="panel">
          <div class="toolbar">
            <div class="toolbar-title"><strong>资料缺口工作台</strong><span>/api/projects/${esc(projectId)}/pbc-gaps</span></div>
            <div class="actions">
              <button type="button" class="secondary"><i class="ti ti-upload"></i> 批量上传</button>
              <button type="button" class="secondary"><i class="ti ti-send"></i> 催办</button>
            </div>
          </div>
          <div class="table-wrap workflow-table">
            <table>
              <thead><tr><th>资料编号</th><th>资料要求</th><th>控制/方向</th><th>状态</th><th>缺口</th><th>上传文件</th></tr></thead>
              <tbody>
                ${pbc.map(item => `
                  <tr>
                    <td>${esc(item.code || item.id)}</td>
                    <td><strong>${esc(item.title)}</strong></td>
                    <td>${esc(item.control_code || '')}<div class="muted">${esc(item.direction || '')}</div></td>
                    <td>${statusTag(item.status)}</td>
                    <td>${item.is_gap ? tag(item.gap_reason || '待补充', 'amber') : tag('无缺口', 'green')}</td>
                    <td>${esc(item.file_path || '未上传')}</td>
                  </tr>
                `).join('') || '<tr><td colspan="6" class="empty">当前项目暂无PBC资料需求</td></tr>'}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `);
    return;
  }
  if (isRealMode()) {
    renderRealProjectPending('pbcCenterContent', 'PBC资料管理');
    return;
  }
  const row = project();
  const pbc = getProjectPbc(row.id);
  const grouped = ['已收到', '部分收到', '待补充', '缺失'].map(status => [status, pbc.filter(item => item.status === status).length]);
  renderInto('pbcCenterContent', `
    <div class="workflow-shell">
      ${pageHeader('PBC资料管理', '按资料类别、系统、关联底稿和缺口状态管理客户需提供资料。', actionButton('workpaperExecution', 'ti-file-analytics', '查看底稿关联'))}
      <div class="workflow-metric-grid">
        ${grouped.map(([label, count]) => metricCard(label, count, label === '已收到' ? '可支持底稿执行' : '需跟进资料缺口', label === '已收到' ? '' : 'warn')).join('')}
      </div>
      <div class="panel">
        <div class="toolbar">
          <div class="toolbar-title"><strong>资料清单</strong><span>Mock阶段展示清单状态，不触发真实文件上传。</span></div>
          <div class="actions">
            <button type="button" class="secondary"><i class="ti ti-upload"></i> 批量上传</button>
            <button type="button" class="secondary"><i class="ti ti-list-check"></i> 生成清单</button>
          </div>
        </div>
        <div class="table-wrap workflow-table">
          <table>
            <thead><tr><th>资料类别</th><th>系统</th><th>资料要求</th><th>状态</th><th>截止日期</th><th>责任人</th><th>关联底稿</th><th>缺口说明</th></tr></thead>
            <tbody>
              ${pbc.map(item => `
                <tr>
                  <td>${esc(item.category)}</td>
                  <td>${esc(item.system)}</td>
                  <td><strong>${esc(item.requirement)}</strong></td>
                  <td>${statusTag(item.status)}</td>
                  <td>${esc(item.due)}</td>
                  <td>${esc(item.owner)}</td>
                  <td>${esc(item.linked)}</td>
                  <td>${item.gap ? esc(item.gap) : tag('无缺口', 'green')}</td>
                </tr>
              `).join('') || '<tr><td colspan="8" class="empty">当前项目暂无PBC清单</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `);
}

function groupedWorkpapers(projectId) {
  const workpapers = getProjectWorkpapers(projectId);
  return workflowStages.map(stage => ({
    stage,
    rows: workpapers.filter(row => row.group === stage.name),
  }));
}

function ensureSelectedWorkpaper(projectId) {
  const rows = getProjectWorkpapers(projectId);
  if (!rows.some(row => row.id === selectedWorkpaperId)) {
    selectedWorkpaperId = rows[0]?.id || workflowWorkpapers[0].id;
  }
  localStorage.setItem('itas_workflow_workpaper', selectedWorkpaperId);
}

function renderWorkpaperExecution() {
  const projectId = currentWorkflowProjectKey();
  if (isRealMode() && String(workflowProjectApi.projectId) === projectId && workflowProjectApi.workpapers?.items) {
    const summary = workflowProjectApi.workpapers;
    const rows = summary.items || [];
    const selected = rows.find(item => String(item.id) === String(selectedWorkpaperId)) || rows[0];
    const selectedMonitor = selected?.monitoring || {};
    renderInto('workpaperExecutionContent', `
      <div class="workflow-shell">
        ${pageHeader('底稿进度', '逐份核对文件可用性、编制签名、复核签名及关联问题，避免仅依赖台账状态。', actionButton('reviewCenter', 'ti-user-check', '进入复核中心'))}
        <div class="workflow-metric-grid">
          ${metricCard('登记底稿', summary.total || 0, '当前项目底稿总数')}
          ${metricCard('文件可用', `${summary.available_count || 0}/${summary.total || 0}`, `${summary.missing_count || 0} 份路径失联`, Number(summary.missing_count || 0) ? 'risk' : '')}
          ${metricCard('编制完成', `${summary.prepared_count || 0}/${summary.total || 0}`, `完整签名率 ${summary.execution_rate || 0}%`, (summary.prepared_count || 0) < (summary.total || 0) ? 'warn' : '')}
          ${metricCard('复核完成', `${summary.reviewed_count || 0}/${summary.total || 0}`, `完整签名率 ${summary.review_rate || 0}%`, (summary.reviewed_count || 0) < (summary.total || 0) ? 'warn' : '')}
        </div>
        <div class="workflow-workpaper-layout">
          <aside class="tree-panel workflow-tree-panel">
            <div class="tree-head">底稿结构</div>
            <div class="tree-list">
              ${rows.map(item => `
                <button type="button" class="workflow-tree-item ${String(item.id) === String(selected?.id) ? 'active' : ''}" data-workflow-workpaper="${esc(item.id)}">
                  <span class="status-dot ${item.monitoring?.file_exists ? (item.monitoring?.review_complete ? 'state-done' : 'state-running') : 'state-risk'}"></span>
                  <span title="${esc(item.name)}">${esc(item.code)} ${esc(item.name)}</span>
                </button>
              `).join('') || '<div class="workflow-tree-empty">暂无底稿</div>'}
            </div>
          </aside>
          <div class="panel">
            <div class="toolbar">
              <div class="toolbar-title"><strong>${esc(selected?.code || '未选择')} ${esc(selected?.name || '')}</strong><span>${esc(selected?.stage || '未分阶段')}</span></div>
            </div>
            <div class="panel-body">
              ${selected ? `
                <div class="workflow-metric-grid compact">
                  ${metricCard('文件', selectedMonitor.file_exists ? '可用' : '失联', selectedMonitor.file_modified_at || '未找到文件', selectedMonitor.file_exists ? '' : 'risk')}
                  ${metricCard('编制签名', selectedMonitor.preparation_complete ? '完整' : selectedMonitor.preparation_partial ? '部分' : '缺失', `${selectedMonitor.preparer || '未识别编制人'} / ${selectedMonitor.prepared_date || '未识别日期'}`, selectedMonitor.preparation_complete ? '' : 'warn')}
                  ${metricCard('复核签名', selectedMonitor.review_complete ? '完整' : selectedMonitor.review_partial ? '部分' : '缺失', `${selectedMonitor.reviewer || '未识别复核人'} / ${selectedMonitor.reviewed_date || '未识别日期'}`, selectedMonitor.review_complete ? '' : 'warn')}
                  ${metricCard('关联附件', selected.attachment_count || 0, 'Attachment关联数量')}
                  ${metricCard('关联问题', selected.finding_count || 0, 'ReviewFinding定位数量', Number(selected.finding_count || 0) ? 'warn' : '')}
                </div>
                <div class="workflow-detail-grid">
                  <div>
                    <h3>底稿路径</h3>
                    <div class="muted">${esc(selected.file_path || '未维护文件路径')}</div>
                  </div>
                  <div>
                    <h3>当前结论</h3>
                    <div>${!selectedMonitor.file_exists ? tag('先修复文件定位', 'red') : selectedMonitor.review_complete ? tag('编制复核签名完整', 'green') : tag('待补齐签名', 'amber')}</div>
                  </div>
                  <div>
                    <h3>后续动作</h3>
                    <div class="workflow-list compact"><div><i class="ti ti-circle-dot"></i><span>${!selectedMonitor.file_exists ? '重新同步最新底稿目录并核对登记路径。' : !selectedMonitor.preparation_complete ? '补齐编制人和编制日期。' : !selectedMonitor.review_complete ? '补齐复核人和复核日期。' : '进入复核整改页确认未关闭问题。'}</span></div></div>
                  </div>
                </div>
              ` : '<div class="empty">当前项目暂无底稿</div>'}
            </div>
          </div>
        </div>
      </div>
    `);
    return;
  }
  if (isRealMode()) {
    renderRealProjectPending('workpaperExecutionContent', '底稿详情页');
    return;
  }
  const row = project();
  ensureSelectedWorkpaper(row.id);
  const selected = getWorkpaper(selectedWorkpaperId);
  const checks = getProjectChecks(row.id).filter(item => item.workpaperId === selected.id);
  renderInto('workpaperExecutionContent', `
    <div class="workflow-shell">
      ${pageHeader('底稿详情页', '左侧按项目文件夹层级展示底稿，右侧集中查看编制、复核、自动填写建议、问题和附件。', actionButton('autoCheck', 'ti-shield-check', '查看检核'))}
      <div class="workflow-workpaper-layout">
        <aside class="tree-panel workflow-tree-panel">
          <div class="tree-head">底稿结构</div>
          <div class="tree-list">
            ${groupedWorkpapers(row.id).map(group => `
              <div class="workflow-tree-stage">
                <strong><i class="ti ti-chevron-down"></i>${esc(group.stage.name)}</strong>
                ${group.rows.length ? group.rows.map(item => `
                  <button type="button" class="workflow-tree-item ${item.id === selected.id ? 'active' : ''}" data-workflow-workpaper="${esc(item.id)}">
                    <span class="status-dot ${esc(statusClass(item.status))}"></span>
                    <span title="${esc(item.name)}">${esc(item.code)} ${esc(item.name)}</span>
                  </button>
                `).join('') : '<div class="workflow-tree-empty">暂无底稿</div>'}
              </div>
            `).join('')}
            <div class="workflow-tree-stage">
              <strong><i class="ti ti-chevron-down"></i>附件</strong>
              ${selected.attachments.map(item => `<div class="workflow-tree-empty"><i class="ti ti-paperclip"></i>${esc(item)}</div>`).join('') || '<div class="workflow-tree-empty">暂无附件</div>'}
            </div>
          </div>
        </aside>
        <div class="panel">
          <div class="toolbar">
            <div class="toolbar-title"><strong>${esc(selected.code)} ${esc(selected.name)}</strong><span>${esc(selected.group)} / ${esc(selected.type)}</span></div>
            <div class="actions">
              <button type="button" class="secondary"><i class="ti ti-download"></i> 下载原始文件</button>
              <button type="button" class="secondary"><i class="ti ti-copy"></i> 写入测试副本</button>
              <button type="button" class="secondary"><i class="ti ti-history"></i> 查看历史</button>
            </div>
          </div>
          <div class="panel-body">
            <div class="workflow-metric-grid compact">
              ${metricCard('状态', selected.status, '底稿执行状态')}
              ${metricCard('编制人', selected.preparer, '按底稿类型规则带入')}
              ${metricCard('复核人', selected.reviewer, '项目负责人/经理或财审一签')}
              ${metricCard('证据齐套率', `${selected.evidenceReady}/${selected.evidenceNeeded}`, '已关联/应收证据')}
            </div>
            <div class="workflow-detail-grid">
              <div>
                <h3>自动填写建议</h3>
                <div class="workflow-chip-list">
                  ${selected.autoFillFields.map(field => tag(field, 'blue')).join('')}
                </div>
              </div>
              <div>
                <h3>关联附件</h3>
                <div class="workflow-chip-list">
                  ${selected.attachments.map(item => tag(item, 'gray')).join('') || '<span class="muted">暂无附件</span>'}
                </div>
              </div>
              <div>
                <h3>检核问题</h3>
                <div class="workflow-list compact">
                  ${checks.map(item => `<div><i class="ti ti-alert-triangle"></i><span>${severityTag(item.severity)} ${esc(item.finding)}</span></div>`).join('') || '<div><i class="ti ti-circle-check"></i><span>当前底稿无未通过检核。</span></div>'}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `);
}

function renderAutoCheck() {
  const projectId = currentWorkflowProjectKey();
  if (isRealMode() && String(workflowProjectApi.projectId) === projectId) {
    const findings = workflowProjectApi.findings || [];
    const systemFindings = findings.filter(item => findingSource(item) === '系统');
    const rows = systemFindings.length ? systemFindings : findings;
    const openRows = rows.filter(item => isOpenFindingStatus(item.status));
    const highRows = openRows.filter(item => ['high', 'critical', '高', '重大'].includes(String(item.severity || '').toLowerCase()));
    const autofillRuns = workflowProjectApi.autofillRuns || [];
    renderInto('autoCheckContent', `
      <div class="workflow-shell">
        ${pageHeader('自动检核结果', '真实接口展示系统检核/复核发现与自动填写记录；无问题时显示为空状态，不再使用演示清单。', actionButton('reviewCenter', 'ti-user-check', '进入复核'))}
        <div class="workflow-metric-grid">
          ${metricCard('检核问题', rows.length, '/api/review-findings?projectId')}
          ${metricCard('未关闭', openRows.length, '待处理、已分派、保留、已修订、退回', openRows.length ? 'warn' : '')}
          ${metricCard('高风险', highRows.length, '未关闭高风险问题', highRows.length ? 'risk' : '')}
          ${metricCard('自动填写记录', autofillRuns.length, '/api/autofill-runs?projectId')}
        </div>
        <div class="workflow-grid">
          <div class="panel">
            <div class="panel-head"><h2>检核明细</h2><span class="muted">/api/review-findings?projectId=${esc(projectId)}</span></div>
            <div class="table-wrap workflow-table">
              <table>
                <thead><tr><th>结果</th><th>严重程度</th><th>规则</th><th>底稿/位置</th><th>问题描述</th><th>来源</th><th>状态</th><th>建议处理</th></tr></thead>
                <tbody>
                  ${rows.map(item => `
                    <tr>
                      <td>${isOpenFindingStatus(item.status) ? tag('未通过', 'red') : tag('已关闭', 'green')}</td>
                      <td>${severityTag(item.severity)}</td>
                      <td>${esc(item.rule_code || '未分类')}</td>
                      <td title="${esc(item.target || '')}">${esc(compactText(item.target || item.workpaper_code || '未定位', 80))}<div class="muted">${esc(item.workpaper_name || item.entity_name || '')}</div></td>
                      <td title="${esc(item.issue || '')}">${esc(compactText(item.issue || '', 120))}</td>
                      <td>${tag(findingSource(item), findingSource(item) === '系统' ? 'blue' : 'amber')}</td>
                      <td>${statusTag(item.status || 'open')}</td>
                      <td title="${esc(item.review_comment || item.evidence || '')}">${esc(compactText(item.review_comment || item.evidence || '补充证据、处理整改并提交复核。', 120))}</td>
                    </tr>
                  `).join('') || '<tr><td colspan="8" class="empty">当前项目暂无检核异常。</td></tr>'}
                </tbody>
              </table>
            </div>
          </div>
          <div class="panel">
            <div class="panel-head"><h2>自动填写记录</h2><span class="muted">/api/autofill-runs?projectId=${esc(projectId)}</span></div>
            <div class="table-wrap workflow-table">
              <table>
                <thead><tr><th>批次</th><th>模式</th><th>范围</th><th>建议</th><th>计划</th><th>变更</th><th>阻塞</th></tr></thead>
                <tbody>
                  ${autofillRuns.slice(0, 8).map(run => `
                    <tr>
                      <td>#${esc(run.id)}</td>
                      <td>${tag(run.apply ? '写回' : '预览', run.apply ? 'green' : 'blue')}</td>
                      <td>${esc(run.scope || '全部')}</td>
                      <td>${esc(run.suggestion_count || 0)}</td>
                      <td>${esc(run.plan_count || 0)}</td>
                      <td>${esc(run.changed_count || 0)}</td>
                      <td>${tag(run.blocked_count || 0, Number(run.blocked_count || 0) ? 'red' : 'green')}</td>
                    </tr>
                  `).join('') || '<tr><td colspan="7" class="empty">当前项目暂无自动填写记录。</td></tr>'}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    `);
    return;
  }
  if (isRealMode()) {
    renderRealProjectPending('autoCheckContent', '自动检核结果');
    return;
  }
  const row = project();
  const checks = getProjectChecks(row.id);
  renderInto('autoCheckContent', `
    <div class="workflow-shell">
      ${pageHeader('自动检核结果', '集中展示系统范围、PBC、底稿字段、复核闭环等规则的检查结果。', actionButton('reviewCenter', 'ti-user-check', '进入复核'))}
      <div class="workflow-metric-grid">
        ${metricCard('检查规则', checks.length, '本项目已执行规则')}
        ${metricCard('未通过', checks.filter(item => item.result !== '通过').length, '需保留、修订或补证据', 'risk')}
        ${metricCard('高风险', checks.filter(item => item.severity === '高' && item.result !== '通过').length, '优先跟进', 'risk')}
        ${metricCard('已关闭', checks.filter(item => item.status === '已关闭').length, '完成验证')}
      </div>
      <div class="panel">
        <div class="panel-head"><h2>检核明细</h2></div>
        <div class="table-wrap workflow-table">
          <table>
            <thead><tr><th>结果</th><th>严重程度</th><th>规则</th><th>底稿/位置</th><th>问题描述</th><th>来源</th><th>状态</th><th>建议处理</th></tr></thead>
            <tbody>
              ${checks.map(item => `
                <tr>
                  <td>${item.result === '通过' ? tag('通过', 'green') : tag('未通过', 'red')}</td>
                  <td>${severityTag(item.severity)}</td>
                  <td>${esc(item.rule)}</td>
                  <td>${esc(item.locator)}<div class="muted">${esc(item.evidence)}</div></td>
                  <td>${esc(item.finding)}</td>
                  <td>${tag(item.source, item.source === '系统' ? 'blue' : 'purple')}</td>
                  <td>${statusTag(item.status)}</td>
                  <td>${esc(item.recommendation)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `);
}

function findingAuditStage(item) {
  if (item.audit_stage) return item.audit_stage;
  const target = String(item.workpaper_file || item.target || item.workpaper_code || '').trim().toUpperCase();
  if (target.startsWith('B')) return '计划阶段';
  if (target.startsWith('A')) return '报告阶段';
  return '执行阶段';
}

function findingTypeLabel(item) {
  if (item.finding_type) return item.finding_type;
  const target = String(item.workpaper_file || item.target || item.workpaper_code || '').trim().toUpperCase();
  if (target.startsWith('S')) return 'CAATs';
  if (target.startsWith('C26')) return 'ITAC';
  return 'ITGC';
}

function filteredReviewRecords(findings) {
  return findings.filter(item => {
    const inScope = !reviewRecordScope || (reviewRecordScope === 'C22') === Boolean(item.c22_related);
    const inWorkpaper = !reviewRecordWorkpaperId || Number(item.workpaper_id) === Number(reviewRecordWorkpaperId);
    return inScope && inWorkpaper;
  });
}

function reviewRecordRows(findings) {
  const visible = filteredReviewRecords(findings);
  return visible.map((item, index) => {
    const responses = item.responses || [];
    const latestResponse = responses[responses.length - 1];
    const reply = latestResponse?.response_text || item.project_reply || '';
    return `
      <tr class="review-record-row" data-workflow-open-finding="${esc(item.id)}">
        <td>${esc(item.issue_no || index + 1)}</td>
        <td><strong>${esc(item.workpaper_code || item.workpaper_file || item.target || '未关联底稿')}</strong><div class="muted">${esc(findingAuditStage(item))} / ${esc(findingTypeLabel(item))}</div></td>
        <td class="review-record-issue"><strong>${esc(compactText(item.issue || '', 100))}</strong><div class="muted">${esc(item.issue_category || item.rule_code || '')}</div></td>
        <td>${statusTag(item.status || 'open')}</td>
        <td class="review-record-reply">${esc(compactText(reply, 90) || '待回复')}</td>
        <td>${esc(item.assignee_name || item.owner_name || item.field_lead || '未分派')}</td>
        <td><button type="button" class="secondary" data-workflow-open-finding="${esc(item.id)}">查看详情</button></td>
      </tr>
    `;
  }).join('') || '<tr><td colspan="7" class="empty">当前筛选范围暂无复核问题。</td></tr>';
}

function exportReviewRecords(findings) {
  const headers = ['序号', '阶段', '问题类型', '添加人', '复核问题', '具体描述补充', '问题步骤归属', '问题类别', '对应文件名', '问题出现的复核阶段', '项目组回复', '确认满意解决', '现场负责人', '项目组内复核人', '状态', '复核意见'];
  const rows = filteredReviewRecords(findings).map((item, index) => {
    const responses = item.responses || [];
    const latest = responses[responses.length - 1];
    const reply = latest?.response_text || item.project_reply || '';
    const confirmed = Boolean(item.resolution_confirmed) || closedStatuses.has(String(item.status || '').toLowerCase());
    return [
      item.issue_no || index + 1, findingAuditStage(item), findingTypeLabel(item), item.created_by_name || '', item.issue || '', item.evidence || '',
      item.issue_step || item.location || '', item.issue_category || item.rule_code || '', item.workpaper_file || item.target || item.workpaper_code || '',
      item.review_stage || '', reply, confirmed ? '是' : '否', item.field_lead || item.owner_name || '', item.project_reviewer || item.assignee_name || '',
      item.status || '', item.review_comment || '',
    ];
  });
  const quote = value => `"${String(value ?? '').replace(/"/g, '""')}"`;
  const csv = [headers, ...rows].map(row => row.map(quote).join(',')).join('\r\n');
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([`\ufeff${csv}`], {type: 'text/csv;charset=utf-8'}));
  link.download = `ITAS_复核记录_${currentWorkflowProjectKey() || '未选择项目'}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(link.href), 1_000);
}

function reviewRefreshMessage(results, successMessage) {
  const failed = (results || []).find(result => result?.status === 'rejected');
  return failed ? `${successMessage}，但页面刷新失败：${failed.reason?.message || '请重试'}` : successMessage;
}

function rememberReviewEntryDraft() {
  if (skipReviewEntryDraftCapture) {
    skipReviewEntryDraftCapture = false;
    return;
  }
  const form = document.querySelector('[data-workflow-review-finding-form]');
  if (!reviewEntryOpen || !form) return;
  const fields = Array.from(form.elements).reduce((draft, field) => {
    if (!field.name || field.type === 'hidden' || ['button', 'file', 'submit'].includes(field.type)) return draft;
    draft[field.name] = field.type === 'checkbox' ? field.checked : field.value;
    return draft;
  }, {});
  reviewEntryDraft = {projectId: String(form.elements.project_id?.value || currentWorkflowProjectKey()), fields};
}

function restoreReviewEntryDraft() {
  const form = document.querySelector('[data-workflow-review-finding-form]');
  if (!reviewEntryOpen || !form || String(reviewEntryDraft.projectId || '') !== currentWorkflowProjectKey()) return;
  Object.entries(reviewEntryDraft.fields || {}).forEach(([name, value]) => {
    const field = form.elements[name];
    if (!field || field.readOnly || field.type === 'hidden') return;
    if (field.type === 'checkbox') field.checked = Boolean(value);
    else if (field.tagName !== 'SELECT' || Array.from(field.options).some(option => option.value === value)) field.value = value;
  });
}

function reviewEntryForm(projectId, workpapers) {
  const project = (state.projects || []).find(item => Number(item.id) === Number(projectId));
  const reviewer = state.me?.display_name || state.me?.username || '';
  const fieldLead = project?.manager_name || project?.project_leader_name || '';
  const keyword = reviewStandardKeyword.trim().toLowerCase();
  const selectedWorkpaper = workpapers.find(item => Number(item.id) === Number(reviewEntryWorkpaperId));
  const standards = reviewIssueCatalog.filter(item => {
    const text = [item.scope, item.workpaper, item.index_code, item.description, item.category].join(' ').toLowerCase();
    const associated = !selectedWorkpaper || standardMatchesWorkpaper(item, selectedWorkpaper);
    return associated && (!keyword || text.includes(keyword));
  }).map(item => `
    <option value="${esc(item.id)}">${esc(item.scope)} · ${esc(item.workpaper)} · ${esc(item.index_code)} · ${esc(compactText(item.description, 70))}</option>
  `).join('');
  return `
    <div class="panel review-entry-panel ${reviewEntryOpen ? '' : 'hidden'}" id="reviewEntryPanel">
      <div class="panel-head review-entry-head"><h2>增加复核问题</h2><span>按复核记录表字段登记</span></div>
      <form class="review-entry-form" data-workflow-review-finding-form>
        <input type="hidden" name="project_id" value="${esc(projectId)}">
        <input type="hidden" name="source" value="manual">
        <input type="hidden" name="rule_code" value="REVIEW_WORKBOOK">
        <div class="review-entry-grid compact">
          <label>C22 与否<select name="scope"><option value="非C22">非C22</option><option value="C22">C22</option></select></label>
          <label>阶段<select name="audit_stage"><option>计划阶段</option><option selected>执行阶段</option><option>报告阶段</option></select></label>
          <label>问题类型<select name="finding_type"><option>ITGC</option><option>ITAC</option><option>CAATs</option><option>ITGC/ITAC/CAATs</option></select></label>
          <label>严重程度<select name="severity"><option value="high">高</option><option value="medium" selected>中</option><option value="low">低</option></select></label>
          <label>对应底稿<select name="workpaper_id"><option value="">请选择底稿</option>${workpapers.map(item => `<option value="${esc(item.id)}" data-code="${esc(item.code || '')}" data-name="${esc(item.name || '')}">${esc(item.code || '')} ${esc(item.name || '')}</option>`).join('')}</select></label>
          <label>问题步骤归属<input name="issue_step" placeholder="如 E1、E2"></label>
          <label>问题出现的复核阶段<input name="review_stage" value="${esc(automaticFindingReviewStage(workflowProjectApi.findings || []))}" readonly title="当前阶段全部问题由质控确认完成后，新增问题自动进入下一阶段"></label>
          <label>现场负责人<input name="field_lead" value="${esc(fieldLead)}"></label>
          <label>项目组内复核人<input name="project_reviewer" value="${esc(reviewer)}"></label>
        </div>
        <label class="review-standard-picker">从问题标准集选择<input name="standard_keyword" value="${esc(reviewStandardKeyword)}" placeholder="输入编号、底稿、问题内容或类别模糊搜索" data-review-standard-search><select name="standard_id"><option value="">不套用标准问题，手工填写（当前底稿匹配 ${esc(String(standards ? standards.match(/<option/g)?.length || 0 : 0))} 条）</option>${standards}</select></label>
        <div class="review-entry-grid">
          <label>复核问题<textarea name="issue" required placeholder="复核问题"></textarea></label>
          <label>具体描述补充<textarea name="evidence" placeholder="结合当前项目说明具体差异、证据或需补充事项"></textarea></label>
          <label>问题类别<input name="issue_category" placeholder="选择标准问题后自动带出"></label>
          <label>建议处理<textarea name="recommendation"></textarea></label>
        </div>
        <div class="review-entry-actions">
          <label class="inline-check"><input type="checkbox" name="resolution_confirmed"> 确认复核问题已满意解决</label>
          <button type="button" class="secondary" data-review-entry-cancel>取消</button>
          <button type="submit"><i class="ti ti-device-floppy"></i> 记录问题</button>
        </div>
      </form>
    </div>
  `;
}

// 标准问题的 workpaper 字段以底稿索引号为归属键，避免用描述文本的模糊包含导致串底稿。
function standardMatchesWorkpaper(standard, workpaper) {
  const code = String(workpaper?.code || '').trim().toLowerCase();
  const standardWorkpaper = String(standard?.workpaper || '').trim().toLowerCase();
  if (!code || !standardWorkpaper) return false;
  return standardWorkpaper === code || standardWorkpaper.startsWith(`${code} `) || standardWorkpaper.startsWith(`${code}-`);
}

function nextWorkpaperIssueStep(workpaperId, findings) {
  const rows = (findings || []).filter(item => Number(item.workpaper_id) === Number(workpaperId));
  const steps = rows.map(item => String(item.issue_step || '').trim()).filter(Boolean);
  const numeric = steps.map(step => {
    const match = step.match(/^(.*?)(\d+)$/);
    return match ? {prefix: match[1], number: Number(match[2])} : null;
  }).filter(Boolean);
  if (numeric.length) {
    const latest = numeric.sort((a, b) => b.number - a.number)[0];
    return `${latest.prefix}${latest.number + 1}`;
  }
  return `复核问题${rows.length + 1}`;
}

function reviewStageNumber(value) {
  const text = String(value || '').trim();
  const digit = text.match(/第\s*(\d+)\s*(?:阶段|轮)/);
  if (digit) return Number(digit[1]);
  const chinese = text.match(/第\s*([一二三四五六七八九十])\s*(?:阶段|轮)/);
  return chinese ? ({一:1, 二:2, 三:3, 四:4, 五:5, 六:6, 七:7, 八:8, 九:9, 十:10}[chinese[1]] || null) : null;
}

function reviewStageLabel(number) {
  const chinese = {1:'一', 2:'二', 3:'三', 4:'四', 5:'五', 6:'六', 7:'七', 8:'八', 9:'九', 10:'十'}[number];
  return `第${chinese || number}阶段`;
}

function automaticFindingReviewStage(findings) {
  const rows = [...(findings || [])].sort((a, b) => Number(a.id || 0) - Number(b.id || 0));
  if (!rows.length) return reviewStageLabel(1);
  const normalized = rows.map(item => ({stage: String(item.review_stage || '').trim() || reviewStageLabel(1), status: String(item.status || 'open').toLowerCase()}));
  const currentStage = normalized[normalized.length - 1].stage;
  const currentRows = normalized.filter(item => item.stage === currentStage);
  if (currentRows.some(item => !['closed', 'resolved'].includes(item.status))) return currentStage;
  const known = normalized.map(item => reviewStageNumber(item.stage)).filter(Number.isFinite);
  return reviewStageLabel(Math.max(known.length ? Math.max(...known) : new Set(normalized.map(item => item.stage)).size, 0) + 1);
}

function renderReviewCenter() {
  rememberReviewEntryDraft();
  const projectId = currentWorkflowProjectKey();
  if (reviewEntryOpen && reviewEntryDraft.projectId && String(reviewEntryDraft.projectId) !== projectId) {
    reviewEntryOpen = false;
    reviewEntryWorkpaperId = null;
  }
  if (isRealMode() && String(workflowProjectApi.projectId) === projectId) {
    const runs = workflowProjectApi.reviewRuns || [];
    const reviewSteps = workflowProjectApi.reviewSteps || [];
    const findings = workflowProjectApi.findings || [];
    const workpapers = workflowProjectApi.workpapers?.items || [];
    const returned = findings.filter(item => ['returned', '退回'].includes(String(item.status || '').toLowerCase()));
    const waitingReview = reviewSteps.filter(item => item.status === 'pending');
    const myPending = reviewSteps.filter(item => item.can_decide);
    const overdueSteps = reviewSteps.filter(item => item.is_overdue && !['approved', 'closed'].includes(String(item.status || '').toLowerCase()));
    const closed = findings.filter(item => closedStatuses.has(String(item.status || '').toLowerCase()));
    const filteredWorkpaper = workpapers.find(item => Number(item.id) === Number(reviewRecordWorkpaperId));
    renderInto('reviewCenterContent', `
      <div class="workflow-shell">
        ${pageHeader('复核中心', '统一处理待复核、问题整改与历史记录；完整问题字段请在详情抽屉或导出中查看。', `
          <button type="button" data-review-entry-open><i class="ti ti-plus"></i> 增加问题</button>
          <button type="button" class="secondary" data-workflow-retry-review-data><i class="ti ti-refresh"></i> 刷新</button>
        `)}
        <div class="workflow-metric-grid">
          ${metricCard('复核问题', findings.length, `C22 ${findings.filter(item => item.c22_related).length} / 非C22 ${findings.filter(item => !item.c22_related).length}`)}
          ${metricCard('待回复', findings.filter(item => !item.project_reply && !(item.responses || []).length && isOpenFindingStatus(item.status)).length, '项目组尚未回复')}
          ${metricCard('待复核确认', findings.filter(item => String(item.status) === 'responded').length, '回复后仍需复核人确认', findings.some(item => String(item.status) === 'responded') ? 'warn' : '')}
          ${metricCard('已满意解决', closed.length, '复核人已确认关闭')}
          ${metricCard('当前复核阶段', automaticFindingReviewStage(findings), '当前阶段全部完成后自动进入下一阶段')}
          ${metricCard('问题标准库', reviewIssueCatalog.length, 'C22 与非 C22 标准问题')}
        </div>
        ${reviewEntryForm(projectId, workpapers)}
        <div class="panel review-record-panel">
          <div class="toolbar review-record-toolbar">
            <div class="toolbar-title"><strong>问题整改</strong><span>日常列表保留关键字段；点击“查看详情”处理回复、退回和关闭。</span></div>
            <div class="actions review-record-actions">
              ${filteredWorkpaper ? `<span class="review-workpaper-filter-label">当前底稿：${esc(filteredWorkpaper.code || '')} ${esc(filteredWorkpaper.name || '')}</span><button type="button" class="secondary" data-review-workpaper-filter="">清除底稿筛选</button>` : ''}
              <button type="button" class="${reviewRecordScope === '' ? '' : 'secondary'}" data-review-record-scope="">全部</button>
              <button type="button" class="${reviewRecordScope === '非C22' ? '' : 'secondary'}" data-review-record-scope="非C22">非C22</button>
              <button type="button" class="${reviewRecordScope === 'C22' ? '' : 'secondary'}" data-review-record-scope="C22">C22</button>
              <button type="button" class="secondary" data-review-record-export><i class="ti ti-download"></i> 导出完整字段</button>
              <label class="review-import-control">导入复核记录表<input type="file" accept=".xlsx,.xlsm" data-review-record-file></label>
              <button type="button" class="secondary" data-review-record-import><i class="ti ti-file-upload"></i> 导入 Excel</button>
            </div>
          </div>
          <div class="table-wrap review-record-table-wrap">
            <table class="review-record-table">
              <thead><tr><th>编号</th><th>底稿 / 阶段</th><th>问题</th><th>状态</th><th>最新回复</th><th>责任人</th><th>操作</th></tr></thead>
              <tbody>${reviewRecordRows(findings)}</tbody>
            </table>
          </div>
        </div>
        <div class="panel">
          <div class="panel-head"><h2>我的待复核</h2><span class="muted">仅显示当前可处理步骤</span></div>
          <div class="table-wrap workflow-table">
            <table>
              <thead><tr><th>底稿</th><th>复核层级</th><th>复核人</th><th>轮次</th><th>状态</th><th>截止日期</th><th>操作</th></tr></thead>
              <tbody>
                ${myPending.map(step => `
                  <tr class="${step.is_overdue ? 'row-overdue' : ''}">
                    <td><strong>${esc(step.workpaper_code || '')}</strong><div class="muted">${esc(step.workpaper_name || '')}</div></td>
                    <td>${esc({project_manager: '项目经理', responsible_manager: '项目负责经理', director: '总监', partner: '合伙人', quality: '质控'}[step.reviewer_role_code] || step.reviewer_role_code || '')}</td>
                    <td>${esc(step.reviewer_name || '未指定')}</td>
                    <td>第 ${esc(step.round_no || 1)} 轮</td>
                    <td>${statusTag(step.status || 'waiting')}</td>
                    <td>${esc(step.due_date || '未进入本级')}${step.is_overdue ? `<div class="muted">逾期 ${esc(step.overdue_days || 0)} 天</div>` : ''}</td>
                    <td class="actions">
                      <button type="button" class="secondary" data-workflow-open-workpaper-review="${esc(step.workpaper_id)}">打开底稿</button>
                      ${step.can_decide ? `<button type="button" data-workflow-review-step="${esc(step.id)}" data-review-action="approve">通过</button><button type="button" class="danger" data-workflow-review-step="${esc(step.id)}" data-review-action="reject">退回</button>` : '<span class="muted">等待流转</span>'}
                    </td>
                  </tr>
                `).join('') || '<tr><td colspan="7" class="empty">当前没有需要您处理的复核步骤。</td></tr>'}
              </tbody>
            </table>
          </div>
        </div>
        <div class="workflow-grid review-support-grid">
          <div class="panel">
            <div class="panel-head"><h2>历史记录</h2><span class="muted">复核运行与导入记录</span></div>
            <div class="table-wrap workflow-table">
              <table>
                <thead><tr><th>任务</th><th>状态</th><th>问题数</th><th>范围</th><th>开始时间</th><th>完成时间</th><th>摘要</th></tr></thead>
                <tbody>
                  ${runs.map(run => `
                    <tr>
                      <td>#${esc(run.id)}</td>
                      <td>${statusTag(run.status || 'unknown')}</td>
                      <td>${esc(run.finding_count ?? 0)}</td>
                      <td>${esc(run.workpaper_id ? `底稿 #${run.workpaper_id}` : '项目')}</td>
                      <td>${esc(run.started_at || '')}</td>
                      <td>${esc(run.finished_at || '')}</td>
                      <td>${esc(run.summary || '')}</td>
                    </tr>
                  `).join('') || '<tr><td colspan="7" class="empty">当前项目暂无复核任务。</td></tr>'}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    `);
    restoreReviewEntryDraft();
    return;
  }
  if (isRealMode()) {
    renderRealProjectPending('reviewCenterContent', '复核中心');
    return;
  }
  const row = project();
  const reviews = getProjectReviews(row.id);
  renderInto('reviewCenterContent', `
    <div class="workflow-shell">
      ${pageHeader('复核中心', '按复核轮次跟踪退回意见、责任人、截止日期和关闭状态。', actionButton('reviewCenter', 'ti-user-check', '查看复核记录'))}
      <div class="workflow-metric-grid">
        ${metricCard('复核任务', reviews.length, '本项目复核记录')}
        ${metricCard('退回意见', reviews.filter(item => item.status === '退回').length, '需编制人处理', 'warn')}
        ${metricCard('待复核', reviews.filter(item => item.status === '待复核').length, '等待复核人')}
        ${metricCard('已关闭', reviews.filter(item => item.status === '已关闭').length, '完成复核')}
      </div>
      <div class="panel">
        <div class="panel-head"><h2>复核队列</h2></div>
        <div class="table-wrap workflow-table">
          <table>
            <thead><tr><th>状态</th><th>底稿</th><th>复核人</th><th>轮次</th><th>责任人</th><th>截止日期</th><th>复核意见</th></tr></thead>
            <tbody>
              ${reviews.map(item => {
                const wp = getWorkpaper(item.workpaperId);
                return `
                  <tr>
                    <td>${statusTag(item.status)}</td>
                    <td><strong>${esc(wp.code)}</strong><div class="muted">${esc(wp.name)}</div></td>
                    <td>${esc(item.reviewer)}</td>
                    <td>第${esc(item.round)}轮</td>
                    <td>${esc(item.owner)}</td>
                    <td>${esc(item.due)}</td>
                    <td>${esc(item.comment)}</td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `);
}

function renderFindingKanban() {
  const projectId = currentWorkflowProjectKey();
  if (isRealMode() && String(workflowProjectApi.projectId) === projectId) {
    renderInto('findingKanbanContent', `
      <div class="workflow-shell">
        ${pageHeader('复核整改', '问题整改已收拢到复核中心，与待复核和历史记录共用同一问题详情。', actionButton('reviewCenter', 'ti-user-check', '进入复核中心'))}
        <div class="panel"><div class="panel-body">请在“复核中心”的问题整改列表打开详情，提交整改回复或处理复核决定。</div></div>
      </div>
    `);
    return;
  }
  if (isRealMode()) {
    renderRealProjectPending('findingKanbanContent', '问题整改看板');
    return;
  }
  const row = project();
  const findings = getProjectFindings(row.id);
  renderInto('findingKanbanContent', `
    <div class="workflow-shell">
      ${pageHeader('问题整改看板', '自动检核和人工复核问题统一进入整改流转，支持保留、修订、待复核和关闭状态。', actionButton('qualityDashboard', 'ti-chart-dots-3', '查看质量风险'))}
      <div class="workflow-kanban">
        ${kanbanColumns.map(([status, label]) => {
          const rows = findings.filter(item => item.status === status);
          return `
            <section class="workflow-kanban-col">
              <h3>${esc(label)} <span>${rows.length}</span></h3>
              ${rows.map(item => `
                <article class="workflow-finding-card">
                  <div>${severityTag(item.severity)} ${tag(item.source, item.source === '系统' ? 'blue' : 'purple')}</div>
                  <strong>${esc(item.title)}</strong>
                  <p>${esc(item.cause)}</p>
                  <small>${esc(item.workpaper)} / ${esc(item.owner)} / ${esc(item.due)}</small>
                  <div class="workflow-card-action">${esc(item.action)}</div>
                </article>
              `).join('') || '<div class="workflow-empty-small">暂无</div>'}
            </section>
          `;
        }).join('')}
      </div>
    </div>
  `);
}

function renderQualityDashboard() {
  if (!demoMode && workflowDashboardApi && workflowQualityApi) {
    const projectRows = realDashboardProjectRows();
    const qualityByProject = new Map((workflowQualityApi.by_project || []).map(row => [Number(row.project_id), row]));
    const typeRows = workflowQualityApi.by_rule || [];
    const openTotal = workflowQualityApi.open || 0;
    const severityRows = workflowQualityApi.by_severity || [];
    const highTotal = severityRows
      .filter(row => ['high', 'critical', '高', '重大'].includes(String(row.severity || '').toLowerCase()))
      .reduce((sum, row) => sum + Number(row.count || 0), 0);
    const avgWorkpaper = projectRows.length
      ? Math.round(projectRows.reduce((sum, item) => sum + Number(item.workpaperRate || 0), 0) / projectRows.length)
      : 0;
    renderInto('qualityDashboardContent', `
      <div class="workflow-shell">
        ${pageHeader('项目质量看板', '真实跨项目统计展示资料缺口、底稿完成度、复核问题、逾期整改和质量风险。', actionButton('architecture', 'ti-route', '查看架构'))}
        <div class="workflow-metric-grid">
          ${metricCard('项目数', projectRows.length, '/api/workflow/dashboard')}
          ${metricCard('未关闭问题', openTotal, '/api/review-dashboard', openTotal ? 'warn' : '')}
          ${metricCard('高风险问题', highTotal, '按 ReviewFinding.severity 统计', highTotal ? 'risk' : '')}
          ${metricCard('平均底稿完成度', `${avgWorkpaper}%`, 'Workpaper 完成率均值')}
        </div>
        <div class="workflow-grid">
          <div class="panel">
            <div class="panel-head"><h2>项目风险矩阵</h2><span class="muted">/api/workflow/dashboard + /api/review-dashboard</span></div>
            <div class="table-wrap workflow-table">
              <table>
                <thead><tr><th>项目</th><th>阶段</th><th>资料缺口</th><th>底稿完成</th><th>未关闭问题</th><th>高风险</th><th>质量风险</th></tr></thead>
                <tbody>
                  ${projectRows.map(item => {
                    const quality = qualityByProject.get(Number(item.id)) || {};
                    return `
                      <tr>
                        <td><strong>${esc(item.shortName)}</strong><div class="muted">${esc(item.auditScope)}</div></td>
                        <td>${statusTag(item.stage)}</td>
                        <td>${esc(item.pbcGaps || 0)}</td>
                        <td>${percent(item.workpaperRate, item.workpaperRate < 70 ? 'amber' : 'green')}<div class="muted">${esc(item.workpaperRate)}%</div></td>
                        <td>${esc(quality.open ?? item.openFindings ?? 0)}</td>
                        <td>${tag(quality.high || item.high_risk_count || 0, Number(quality.high || item.high_risk_count || 0) ? 'red' : 'green')}</td>
                        <td>${severityTag(item.riskLevel)}</td>
                      </tr>
                    `;
                  }).join('') || '<tr><td colspan="7" class="empty">暂无质量看板项目。</td></tr>'}
                </tbody>
              </table>
            </div>
          </div>
          <div class="panel">
            <div class="panel-head"><h2>问题分布分析</h2><span class="muted">类型柱状图 · 严重程度饼图</span></div>
            ${qualityBiCharts(typeRows, severityRows)}
          </div>
        </div>
      </div>
    `);
    return;
  }
  if (!demoMode) {
    renderInto('qualityDashboardContent', `
      <div class="workflow-shell">
        ${pageHeader('项目质量看板', workflowDashboardApi ? '真实质量统计暂不可用。' : '正在加载真实质量统计。', actionButton('architecture', 'ti-route', '查看架构'))}
        <div class="panel"><div class="panel-body">${workflowDashboardApi ? '未能读取 /api/review-dashboard，暂不显示演示质量数据。' : '正在读取真实项目质量统计。'}</div></div>
      </div>
    `);
    return;
  }
  const rows = workflowProjects.map(projectRow => {
    const summary = projectSummary(projectRow);
    return {...projectRow, summary};
  });
  const typeRows = ['离职账号未及时禁用', '权限新增审批证据不完整', '变更缺少测试记录', '日志未定期审阅', '备份恢复测试缺失', '职责分离规则清单缺失']
    .map(type => ({
      type,
      count: workflowFindings.filter(item => item.title === type).length,
      high: workflowFindings.filter(item => item.title === type && item.severity === '高').length,
      open: workflowFindings.filter(item => item.title === type && item.status !== '已关闭').length,
    }))
    .filter(item => item.count);
  const demoSeverityRows = ['高', '中', '低'].map(severity => ({severity, count: workflowFindings.filter(item => item.severity === severity).length}));
  renderInto('qualityDashboardContent', `
    <div class="workflow-shell">
      ${pageHeader('项目质量看板', '跨项目汇总资料缺口、底稿完成度、自动检核失败、复核退回和问题整改压力。', actionButton('architecture', 'ti-route', '查看架构'))}
      <div class="workflow-metric-grid">
        ${metricCard('项目数', workflowProjects.length, '纳入质量看板')}
        ${metricCard('未关闭问题', openItems(workflowFindings).length, '自动和人工问题', 'warn')}
        ${metricCard('高风险问题', workflowFindings.filter(item => item.severity === '高' && item.status !== '已关闭').length, '需经理关注', 'risk')}
        ${metricCard('平均底稿完成度', `${Math.round(workflowProjects.reduce((sum, item) => sum + item.workpaperRate, 0) / workflowProjects.length)}%`, '按项目Mock进度')}
      </div>
      <div class="workflow-grid">
        <div class="panel">
          <div class="panel-head"><h2>项目风险矩阵</h2></div>
          <div class="table-wrap workflow-table">
            <table>
              <thead><tr><th>项目</th><th>阶段</th><th>资料缺口</th><th>检核异常</th><th>复核退回</th><th>未关闭问题</th><th>质量风险</th></tr></thead>
              <tbody>
                ${rows.map(item => `
                  <tr>
                    <td><strong>${esc(item.shortName)}</strong><div class="muted">${esc(item.auditScope)}</div></td>
                    <td>${statusTag(item.stage)}</td>
                    <td>${item.summary.pbcGaps}</td>
                    <td>${item.summary.failedChecks}</td>
                    <td>${item.summary.returned}</td>
                    <td>${item.summary.openFindings}</td>
                    <td>${severityTag(item.riskLevel)}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
        <div class="panel">
          <div class="panel-head"><h2>问题分布分析</h2><span class="muted">类型柱状图 · 严重程度饼图</span></div>
          ${qualityBiCharts(typeRows.map(item => ({rule_code: item.type, count: item.count})), demoSeverityRows)}
        </div>
      </div>
    </div>
  `);
}

function qualityBiCharts(typeRows, severityRows) {
  const bars = (typeRows || []).map(item => ({label: item.rule_code || item.type || '未分类', count: Number(item.count || 0)}))
    .sort((a, b) => b.count - a.count).slice(0, 8);
  const maxCount = Math.max(1, ...bars.map(item => item.count));
  const severityCounts = {high: 0, medium: 0, low: 0};
  (severityRows || []).forEach(item => {
    const key = String(item.severity || '').toLowerCase();
    if (['critical', 'high', '重大', '高'].includes(key)) severityCounts.high += Number(item.count || 0);
    else if (['medium', '中'].includes(key)) severityCounts.medium += Number(item.count || 0);
    else severityCounts.low += Number(item.count || 0);
  });
  const total = severityCounts.high + severityCounts.medium + severityCounts.low;
  const highEnd = total ? severityCounts.high / total * 360 : 0;
  const mediumEnd = total ? highEnd + severityCounts.medium / total * 360 : 0;
  return `
    <div class="quality-bi-grid">
      <div class="quality-bi-chart">
        <h3>问题类型 Top ${esc(Math.min(8, bars.length))}</h3>
        <div class="quality-bar-chart">
          ${bars.map(item => `<div class="quality-bar-row"><span title="${esc(item.label)}">${esc(compactText(item.label, 18))}</span><div><i style="width:${Math.round(item.count / maxCount * 100)}%"></i></div><strong>${esc(item.count)}</strong></div>`).join('') || '<div class="empty">暂无问题类型统计</div>'}
        </div>
      </div>
      <div class="quality-bi-chart quality-pie-chart">
        <h3>严重程度占比</h3>
        ${total ? `<div class="quality-donut" style="--high-end:${highEnd}deg;--medium-end:${mediumEnd}deg"><strong>${esc(total)}</strong><span>问题总数</span></div>
        <div class="quality-chart-legend"><span><i class="high"></i>高 ${esc(severityCounts.high)}</span><span><i class="medium"></i>中 ${esc(severityCounts.medium)}</span><span><i class="low"></i>低 ${esc(severityCounts.low)}</span></div>` : '<div class="empty">暂无严重程度统计</div>'}
      </div>
    </div>
  `;
}

function renderArchitecture() {
  renderInto('architectureContent', `
    <div class="workflow-shell">
      ${pageHeader('功能架构页', '以审计项目生命周期组织系统入口，明确资料、底稿、规则、复核、整改和质量风险的流转关系.', '')}
      <div class="workflow-architecture">
        ${[
          ['首页驾驶舱', '项目总览、待办、质量风险'],
          ['项目工作台', '项目上下文、成员、范围、进度'],
          ['审计范围识别', '系统清单、范围理由、置信度'],
          ['PBC资料管理', '资料清单、缺口、关联底稿'],
          ['底稿详情', '文件树、表头规则、附件和问题'],
          ['自动检核', '规则结果、缺口定位、处理建议'],
          ['复核中心', '退回意见、轮次、责任人'],
          ['问题整改看板', '保留、修订、待复核、关闭'],
          ['项目质量看板', '跨项目质量风险和问题分布'],
        ].map(([title, text], index, arr) => `
          <div class="workflow-arch-node">
            <span>${index + 1}</span>
            <strong>${esc(title)}</strong>
            <small>${esc(text)}</small>
          </div>
          ${index < arr.length - 1 ? '<i class="ti ti-arrow-right workflow-arch-arrow"></i>' : ''}
        `).join('')}
      </div>
      <div class="workflow-grid">
        <div class="panel">
          <div class="panel-head"><h2>本阶段实现边界</h2></div>
          <div class="workflow-list">
            <div><i class="ti ti-circle-check"></i><span>核心路由、左侧导航、Mock数据、驾驶舱、范围、PBC、底稿、检核、复核、整改和质量看板已形成可点击闭环。</span></div>
            <div><i class="ti ti-circle-check"></i><span>页面展示重点覆盖项目进度、资料缺口、系统范围、底稿执行、复核退回和质量风险。</span></div>
            <div><i class="ti ti-circle-dashed"></i><span>真实文件解析、AI填报、数据库改造和报告导出保留为后续阶段。</span></div>
          </div>
        </div>
        <div class="panel">
          <div class="panel-head"><h2>数据对象</h2></div>
          <div class="workflow-chip-list padded">
            ${['Client', 'Project', 'SystemScopeItem', 'PBCRequest', 'EvidenceFile', 'Workpaper', 'Finding', 'ReviewComment', 'Task', 'Report', 'User'].map(item => tag(item, 'blue')).join('')}
          </div>
        </div>
      </div>
    </div>
  `);
}

export function renderWorkflowPrototype() {
  if (demoMode && !workflowProjects.some(projectRow => projectRow.id === selectedProjectId)) setProject(workflowProjects[0].id);
  renderWorkflowDashboard();
  renderProjectWorkspacePrototype();
  renderScopeCenter();
  renderPbcCenter();
  renderWorkpaperExecution();
  renderAutoCheck();
  renderReviewCenter();
  renderFindingKanban();
  renderQualityDashboard();
  renderArchitecture();
}

export async function loadWorkflowPrototypeData({silent = false} = {}) {
  if (demoMode) {
    workflowDashboardApi = null;
    workflowQualityApi = null;
    workflowApiError = '';
    renderWorkflowPrototype();
    return;
  }
  try {
    const [dashboard, quality] = await Promise.all([
      request('/api/workflow/dashboard'),
      request('/api/review-dashboard').catch(() => null),
      loadReviewIssueCatalog().catch(() => null),
    ]);
    workflowDashboardApi = dashboard;
    workflowQualityApi = quality;
    mergeWorkflowDeliveryToProjects();
    workflowApiError = '';
    const projectId = currentWorkflowProjectKey();
    if (projectId) void loadWorkflowProjectData(projectId).then(renderWorkflowPrototype);
    renderWorkflowPrototype();
  } catch (err) {
    workflowDashboardApi = null;
    workflowQualityApi = null;
    workflowApiError = err.message || String(err);
    if (!silent) renderWorkflowPrototype();
  }
}

async function createWorkflowReviewFinding(form) {
  const data = new FormData(form);
  const selectedWorkpaper = form.elements.workpaper_id?.selectedOptions?.[0];
  const standard = reviewIssueCatalog.find(item => item.id === data.get('standard_id'));
  const scope = String(data.get('scope') || '非C22');
  const payload = Object.fromEntries(data.entries());
  delete payload.scope;
  delete payload.standard_id;
  delete payload.standard_keyword;
  const currentProjectId = Number(currentWorkflowProjectKey());
  if (!currentProjectId) throw new Error('请先选择当前项目');
  if (String(workflowProjectApi.projectId || '') !== String(currentProjectId)) throw new Error('当前项目数据仍在加载，请刷新后重试');
  payload.project_id = currentProjectId;
  payload.workpaper_id = payload.workpaper_id ? Number(payload.workpaper_id) : null;
  const availableWorkpapers = workflowProjectApi.workpapers?.items || [];
  if (payload.workpaper_id && !availableWorkpapers.some(item => Number(item.id) === payload.workpaper_id)) {
    throw new Error('所选底稿不属于当前项目，请刷新后重试');
  }
  payload.c22_related = scope === 'C22';
  payload.resolution_confirmed = data.get('resolution_confirmed') === 'on';
  payload.standard_index_code = standard?.index_code || '';
  payload.workpaper_file = `${selectedWorkpaper?.dataset.code || ''} ${selectedWorkpaper?.dataset.name || ''}`.trim() || standard?.workpaper || '';
  payload.target = payload.workpaper_file;
  payload.location = payload.issue_step || '';
  if (!String(payload.issue || '').trim()) throw new Error('请填写复核问题');
  await request('/api/review-findings', {method: 'POST', body: JSON.stringify(payload)});
  reviewEntryOpen = false;
  reviewEntryDraft = {};
  const refreshResults = await window.refreshReviewData?.({projectScoped: true});
  renderWorkflowPrototype();
  setStatus(reviewRefreshMessage(refreshResults, '复核问题已按记录表格式保存'));
}

async function importWorkflowReviewWorkbook() {
  const projectId = currentWorkflowProjectKey();
  const input = document.querySelector('[data-review-record-file]');
  const file = input?.files?.[0];
  if (!projectId) throw new Error('请先选择项目');
  if (!file) throw new Error('请先选择复核记录 Excel');
  const body = new FormData();
  body.append('file', file);
  const result = await request(`/api/projects/${projectId}/review-findings/import`, {method: 'POST', body});
  const refreshResults = await window.refreshReviewData?.({projectScoped: true});
  renderWorkflowPrototype();
  setStatus(reviewRefreshMessage(refreshResults, `复核记录导入完成：新增 ${result.created} 项，更新 ${result.updated} 项`));
}

export function bindWorkflowPrototype() {
  document.addEventListener('input', event => {
    const search = event.target.closest('[data-review-standard-search]');
    if (!search) return;
    reviewStandardKeyword = search.value || '';
    const form = search.closest('form');
    const select = form?.elements.standard_id;
    if (!select) return;
    const keyword = reviewStandardKeyword.trim().toLowerCase();
    const current = select.value;
    const workpaper = (workflowProjectApi.workpapers?.items || []).find(item => Number(item.id) === Number(reviewEntryWorkpaperId));
    select.innerHTML = `<option value="">不套用标准问题，手工填写</option>` + reviewIssueCatalog.filter(item => (!workpaper || standardMatchesWorkpaper(item, workpaper)) && (!keyword || [item.scope, item.workpaper, item.index_code, item.description, item.category].join(' ').toLowerCase().includes(keyword))).map(item => `<option value="${esc(item.id)}">${esc(item.scope)} · ${esc(item.workpaper)} · ${esc(item.index_code)} · ${esc(compactText(item.description, 70))}</option>`).join('');
    if (current && Array.from(select.options).some(option => option.value === current)) select.value = current;
  });
  document.addEventListener('change', event => {
    const workpaperSelect = event.target.closest('[data-workflow-review-finding-form] select[name="workpaper_id"]');
    if (workpaperSelect) {
      const form = workpaperSelect.closest('form');
      reviewEntryWorkpaperId = workpaperSelect.value ? Number(workpaperSelect.value) : null;
      if (form?.elements.review_stage) form.elements.review_stage.value = automaticFindingReviewStage(workflowProjectApi.findings || []);
      if (form?.elements.issue_step && reviewEntryWorkpaperId) form.elements.issue_step.value = nextWorkpaperIssueStep(reviewEntryWorkpaperId, workflowProjectApi.findings || []);
      const keyword = String(form?.elements.standard_keyword?.value || '').trim().toLowerCase();
      const selected = form?.elements.standard_id?.value || '';
      const selectedWorkpaper = (workflowProjectApi.workpapers?.items || []).find(item => Number(item.id) === Number(reviewEntryWorkpaperId));
      if (form?.elements.standard_id) {
        form.elements.standard_id.innerHTML = '<option value="">不套用标准问题，手工填写</option>' + reviewIssueCatalog.filter(item => {
          const text = [item.scope, item.workpaper, item.index_code, item.description, item.category].join(' ').toLowerCase();
          return (!selectedWorkpaper || standardMatchesWorkpaper(item, selectedWorkpaper)) && (!keyword || text.includes(keyword));
        }).map(item => `<option value="${esc(item.id)}">${esc(item.scope)} · ${esc(item.workpaper)} · ${esc(item.index_code)} · ${esc(compactText(item.description, 70))}</option>`).join('');
        if (selected && Array.from(form.elements.standard_id.options).some(option => option.value === selected)) form.elements.standard_id.value = selected;
      }
      return;
    }
    const standardSelect = event.target.closest('[data-workflow-review-finding-form] select[name="standard_id"]');
    if (!standardSelect) return;
    const form = standardSelect.closest('form');
    const standard = reviewIssueCatalog.find(item => item.id === standardSelect.value);
    if (!form || !standard) return;
    form.elements.scope.value = standard.scope || '非C22';
    form.elements.issue.value = standard.description || '';
    form.elements.issue_category.value = standard.category || '';
    form.elements.issue_step.value = standard.source_step || '';
    const workpaperOption = Array.from(form.elements.workpaper_id.options).find(option => {
      return standardMatchesWorkpaper(standard, {code: option.dataset.code || '', name: option.dataset.name || ''});
    });
    if (workpaperOption) {
      form.elements.workpaper_id.value = workpaperOption.value;
      reviewEntryWorkpaperId = Number(workpaperOption.value);
      if (form.elements.review_stage) form.elements.review_stage.value = automaticFindingReviewStage(workflowProjectApi.findings || []);
    }
  });
  document.addEventListener('change', async event => {
    const select = event.target.closest('[data-workflow-project-select]');
    if (!select) return;
    setProject(select.value);
    if (isRealMode()) {
      void window.refreshProjectScoped?.();
      const projectId = currentWorkflowProjectKey();
      if (projectId) void loadWorkflowProjectData(projectId).then(renderWorkflowPrototype);
    }
    renderWorkflowPrototype();
  });
  document.addEventListener('click', async event => {
    if (event.target.closest('[data-workflow-retry-review-data]')) {
      try {
        const results = await window.refreshReviewData?.({projectScoped: true});
        const failed = (results || []).filter(result => result.status === 'rejected');
        setStatus(failed.length ? `复核数据部分刷新失败：${failed[0].reason?.message || '请重试'}` : '复核数据已刷新');
      } catch (err) {
        setStatus(`复核数据部分刷新失败：${err.message || '请重试'}`);
      }
      return;
    }
    const pendingConfirmation = event.target.closest('[data-workflow-open-pending-confirmation]');
    if (pendingConfirmation) {
      const projectId = pendingConfirmation.dataset.projectId;
      const findingId = Number(pendingConfirmation.dataset.workflowOpenPendingConfirmation);
      const activeProject = $('activeProject');
      if (activeProject && projectId) activeProject.value = projectId;
      if (projectId) {
        await window.refreshProjectScoped?.();
        await loadWorkflowProjectData(projectId);
      }
      renderWorkflowPrototype();
      window.activateAppSection?.('reviewCenter');
      window.openQualityFinding?.(findingId);
      return;
    }
    const filterWorkpaper = event.target.closest('[data-review-workpaper-filter]');
    if (filterWorkpaper) {
      reviewRecordWorkpaperId = filterWorkpaper.dataset.reviewWorkpaperFilter ? Number(filterWorkpaper.dataset.reviewWorkpaperFilter) : null;
      renderReviewCenter();
      renderFindingKanban();
      document.querySelector('.section.active .review-record-panel')?.scrollIntoView({block: 'start', behavior: 'smooth'});
      return;
    }
    const addForWorkpaper = event.target.closest('[data-review-add-for-workpaper]');
    if (addForWorkpaper) {
      reviewEntryDraft = {};
      skipReviewEntryDraftCapture = true;
      reviewEntryWorkpaperId = Number(addForWorkpaper.dataset.reviewAddForWorkpaper);
      reviewEntryOpen = true;
      renderReviewCenter();
      const form = document.querySelector('[data-workflow-review-finding-form]');
      if (form) {
        if (form.elements.workpaper_id) form.elements.workpaper_id.value = String(reviewEntryWorkpaperId);
        if (form.elements.issue_step) form.elements.issue_step.value = nextWorkpaperIssueStep(reviewEntryWorkpaperId, workflowProjectApi.findings || []);
        if (form.elements.review_stage) form.elements.review_stage.value = automaticFindingReviewStage(workflowProjectApi.findings || []);
        if (form.elements.project_reviewer) form.elements.project_reviewer.value = state.me?.display_name || state.me?.username || '';
        form.scrollIntoView({block: 'start'});
      }
      return;
    }
    const openReviewEntry = event.target.closest('[data-review-entry-open]');
    if (openReviewEntry) {
      reviewEntryDraft = {};
      skipReviewEntryDraftCapture = true;
      reviewEntryOpen = true;
      reviewEntryWorkpaperId = null;
      renderReviewCenter();
      document.querySelector('[data-workflow-review-finding-form]')?.scrollIntoView({block: 'start'});
      return;
    }
    if (event.target.closest('[data-review-entry-cancel]')) {
      reviewEntryDraft = {};
      reviewEntryOpen = false;
      renderReviewCenter();
      return;
    }
    const scopeButton = event.target.closest('[data-review-record-scope]');
    if (scopeButton) {
      reviewRecordScope = scopeButton.dataset.reviewRecordScope || '';
      renderReviewCenter();
      renderFindingKanban();
      return;
    }
    if (event.target.closest('[data-review-record-export]')) {
      exportReviewRecords(workflowProjectApi.findings || []);
      setStatus('已导出当前筛选范围的完整复核字段');
      return;
    }
    if (event.target.closest('[data-review-record-import]')) {
      try { await importWorkflowReviewWorkbook(); } catch (err) { setStatus('错误：' + err.message); }
      return;
    }
    const realProjectButton = event.target.closest('[data-workflow-open-real-project]');
    if (realProjectButton) {
      const id = realProjectButton.dataset.workflowOpenRealProject;
      const activeProject = $('activeProject');
      if (activeProject) activeProject.value = id;
      void window.refreshProjectScoped?.();
      if (id) void loadWorkflowProjectData(id).then(renderWorkflowPrototype);
      renderWorkflowPrototype();
      window.activateAppSection?.('projectWorkspace');
      return;
    }
    const openProject = event.target.closest('[data-workflow-open-project]');
    if (openProject) {
      setProject(openProject.dataset.workflowOpenProject);
      if (isRealMode()) {
        void window.refreshProjectScoped?.();
        const projectId = currentWorkflowProjectKey();
        if (projectId) void loadWorkflowProjectData(projectId).then(renderWorkflowPrototype);
      }
      renderWorkflowPrototype();
      window.activateAppSection?.(openProject.dataset.workflowRoute || 'projectWorkspace');
      return;
    }
    const routeButton = event.target.closest('[data-workflow-route]');
    if (routeButton) {
      window.activateAppSection?.(routeButton.dataset.workflowRoute);
      return;
    }
    const findingButton = event.target.closest('[data-workflow-open-finding]');
    if (findingButton) {
      const findingId = Number(findingButton.dataset.workflowOpenFinding);
      await window.refreshReviewData?.({focusFindingId: findingId});
      window.openQualityFinding?.(findingId);
      return;
    }
    const workpaperReviewButton = event.target.closest('[data-workflow-open-workpaper-review]');
    if (workpaperReviewButton) {
      selectedWorkpaperId = workpaperReviewButton.dataset.workflowOpenWorkpaperReview;
      localStorage.setItem('itas_workflow_workpaper', selectedWorkpaperId);
      try {
        await openReviewedWorkpaper(selectedWorkpaperId);
      } catch (err) {
        setStatus('打开底稿失败：' + err.message);
      }
      return;
    }
    const reviewStepButton = event.target.closest('[data-workflow-review-step]');
    if (reviewStepButton) {
      const stepId = Number(reviewStepButton.dataset.workflowReviewStep);
      const action = reviewStepButton.dataset.reviewAction;
      const input = window.prompt(action === 'reject' ? '请输入退回原因和整改要求' : '请输入复核意见（可留空）');
      if (input === null) return;
      const comment = input;
      if (action === 'reject' && !comment.trim()) {
        setStatus('退回必须填写复核意见');
        return;
      }
      try {
        await request(`/api/review-steps/${stepId}/${action}`, {method: 'POST', body: JSON.stringify({comment})});
        const refreshResults = await window.refreshReviewData?.({projectScoped: true});
        renderWorkflowPrototype();
        setStatus(reviewRefreshMessage(refreshResults, action === 'approve' ? '本级复核已通过' : '底稿已退回并自动下发整改问题'));
      } catch (err) {
        setStatus('错误：' + err.message);
      }
      return;
    }
    const workpaperButton = event.target.closest('[data-workflow-workpaper]');
    if (workpaperButton) {
      selectedWorkpaperId = workpaperButton.dataset.workflowWorkpaper;
      localStorage.setItem('itas_workflow_workpaper', selectedWorkpaperId);
      renderWorkpaperExecution();
    }
  });
  document.addEventListener('submit', async event => {
    const form = event.target.closest('[data-workflow-review-finding-form]');
    if (!form) return;
    event.preventDefault();
    try { await createWorkflowReviewFinding(form); } catch (err) { setStatus('错误：' + err.message); }
  });
}
