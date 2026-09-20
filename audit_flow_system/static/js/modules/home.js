import { request } from '../api.js?v=20260920-state12';
import { state } from '../state.js?v=20260920-state12';
import { $, PROJECT_STATUS_OPTIONS, esc, isActiveProjectStatus, openModal, projectStatusLabel } from '../utils.js?v=20260630b';

const homeFilters = {
  keyword: '',
  year: '',
  status: 'all',
  page: 1,
  pageSize: 20,
};

const homeMemberBatch = {
  projectId: null,
  staff: [],
  keyword: '',
  selected: new Map(),
};
let homeDetailRequestSeq = 0;

function captureFilters() {
  if ($('homeSearchInput')) homeFilters.keyword = String($('homeSearchInput').value || '');
  if ($('homeYearFilter')) homeFilters.year = String($('homeYearFilter').value || '');
  if ($('homeStatusFilter')) homeFilters.status = String($('homeStatusFilter').value || 'all');
  if ($('homePageSize')) homeFilters.pageSize = Number($('homePageSize').value || 20);
  return homeFilters;
}

function projectManager(project) {
  return project.manager_name || project.project_leader_name || '';
}

function businessOwner(project) {
  return project.field_leader_name || project.project_leader_name || '';
}

function projectStartDate(project) {
  return project.start_date || project.audit_scope_start || '';
}

function projectEndDate(project) {
  return project.end_date || project.audit_scope_end || '';
}

function projectNumber(project) {
  return project.oa_project_no || project.code || project.ims_project_no || '';
}

function homeRows() {
  const { status, year, keyword } = captureFilters();
  const needle = keyword.trim().toLowerCase();
  const source = Array.isArray(state.homeProjects) && state.homeProjects.length ? state.homeProjects : (state.projects || []);
  return source.filter(project => {
    if (status === 'active' && !isActiveProjectStatus(project.status)) return false;
    if (status && status !== 'all' && status !== 'active' && String(project.status || '') !== status) return false;
    if (year && String(project.audit_year || '') !== year) return false;
    const text = [
      project.name,
      project.entity_name,
      project.client_name,
      project.code,
      project.oa_project_no,
      project.ims_project_no,
      projectManager(project),
      businessOwner(project),
    ].join(' ').toLowerCase();
    return !needle || text.includes(needle);
  });
}

function homeYears() {
  const source = Array.isArray(state.homeProjects) && state.homeProjects.length ? state.homeProjects : (state.projects || []);
  return Array.from(new Set(source.map(project => project.audit_year).filter(Boolean)))
    .sort((a, b) => Number(b) - Number(a));
}

function yearOptionsHtml() {
  return ['<option value="">全部年度</option>']
    .concat(homeYears().map(year => `<option value="${esc(year)}" ${String(year) === String(homeFilters.year) ? 'selected' : ''}>${esc(year)}</option>`))
    .join('');
}

function statusOptionsHtml() {
  const current = homeFilters.status || 'all';
  return [
    ['all', '全部状态'],
    ['active', '进行中'],
    ...PROJECT_STATUS_OPTIONS,
  ].map(([value, label]) => `<option value="${esc(value)}" ${current === value ? 'selected' : ''}>${esc(label)}</option>`).join('');
}

function cell(value, className = '') {
  const text = String(value || '').trim();
  return `<td class="${className}">${esc(text || '—')}</td>`;
}

function renderProjectRow(project) {
  return `
    <tr data-home-project-row="${esc(project.id)}" tabindex="0" aria-label="进入项目 ${esc(project.name || project.id)}">
      <td class="home-check-cell"><input type="checkbox" data-home-project-check="${esc(project.id)}" aria-label="选择项目 ${esc(project.name || project.id)}"></td>
      ${cell(projectStatusLabel(project.status), 'home-status-cell')}
      ${cell(projectNumber(project), 'home-number-cell')}
      ${cell(projectManager(project))}
      ${cell(businessOwner(project))}
      ${cell(projectStartDate(project), 'home-date-cell')}
      ${cell(projectEndDate(project), 'home-date-cell')}
      ${cell(project.audit_year, 'home-year-cell')}
      ${cell(project.name, 'home-name-cell')}
      ${cell(project.entity_name || project.client_name, 'home-unit-cell')}
    </tr>
  `;
}

function pagination(total, pageSize) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  homeFilters.page = Math.min(Math.max(1, homeFilters.page), pages);
  const page = homeFilters.page;
  return `
    <div class="home-table-footer">
      <span>共${esc(total)}条</span>
      <div class="home-pager" aria-label="项目列表分页">
        <button type="button" class="secondary home-page-button" data-home-page="1" ${page === 1 ? 'disabled' : ''} aria-label="首页"><i class="ti ti-chevrons-left"></i></button>
        <button type="button" class="secondary home-page-button" data-home-page="${page - 1}" ${page === 1 ? 'disabled' : ''} aria-label="上一页"><i class="ti ti-chevron-left"></i></button>
        <span class="home-current-page">${esc(page)}</span>
        <button type="button" class="secondary home-page-button" data-home-page="${page + 1}" ${page === pages ? 'disabled' : ''} aria-label="下一页"><i class="ti ti-chevron-right"></i></button>
        <button type="button" class="secondary home-page-button" data-home-page="${pages}" ${page === pages ? 'disabled' : ''} aria-label="末页"><i class="ti ti-chevrons-right"></i></button>
        <select id="homePageSize" aria-label="每页条数">
          ${[20, 50, 100].map(size => `<option value="${size}" ${size === pageSize ? 'selected' : ''}>${size} 条/页</option>`).join('')}
        </select>
        <label class="home-jump">跳至 <input id="homePageJump" type="number" min="1" max="${pages}" value="${page}" aria-label="页码"> 页</label>
      </div>
    </div>
  `;
}

export function renderHome() {
  const box = $('homePanel');
  if (!box) return;
  // Background refreshes must not replace an in-flight detail dialog. Otherwise
  // the first click can open a node that is immediately detached by renderHome.
  if ($('homeProjectDetailModal')?.classList.contains('open') || $('homeMemberBatchModal')?.classList.contains('open')) return;
  captureFilters();
  const rows = homeRows();
  const pageSize = [20, 50, 100].includes(homeFilters.pageSize) ? homeFilters.pageSize : 20;
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  homeFilters.page = Math.min(Math.max(1, homeFilters.page), pages);
  const pageRows = rows.slice((homeFilters.page - 1) * pageSize, homeFilters.page * pageSize);
  box.innerHTML = `
    <div class="home-shell">
      <div class="workflow-page-head home-page-head">
        <div>
          <h2>项目台账</h2>
          <p>在项目台账中查找项目；对已获授权的项目，可从详情进入项目执行。</p>
        </div>
      </div>
      <div class="panel home-table-panel">
        <div class="panel-head home-filter-bar">
          <h2>项目列表</h2>
          <div class="home-filters">
            <input id="homeSearchInput" placeholder="搜索项目名称、编号、单位或负责人" value="${esc(homeFilters.keyword)}">
            <select id="homeYearFilter">${yearOptionsHtml()}</select>
            <select id="homeStatusFilter">${statusOptionsHtml()}</select>
          </div>
        </div>
        <div class="home-table-scroll">
          <table class="home-project-table">
            <thead>
              <tr>
                <th class="home-check-cell"><input id="homeSelectAll" type="checkbox" aria-label="选择本页全部项目"></th>
                <th>项目状态</th>
                <th>项目编号</th>
                <th>项目负责经理</th>
                <th>现场负责人</th>
                <th>预计开始日期</th>
                <th>预计结束日期</th>
                <th>审计年度</th>
                <th>项目名称</th>
                <th>项目归属单位</th>
              </tr>
            </thead>
            <tbody>
              ${pageRows.map(renderProjectRow).join('') || '<tr><td colspan="10" class="empty">暂无符合条件的项目信息</td></tr>'}
            </tbody>
          </table>
        </div>
        ${pagination(rows.length, pageSize)}
      </div>
      <div class="modal" id="homeProjectDetailModal" aria-hidden="true">
        <div class="modal-card modal-wide home-detail-modal">
          <div class="modal-head"><h2 id="homeProjectDetailTitle">项目详情</h2><button type="button" class="modal-close" data-modal-close="homeProjectDetailModal">关闭</button></div>
          <div class="modal-body" id="homeProjectDetailBody"><div class="empty">正在读取项目详情…</div></div>
        </div>
      </div>
      <div class="modal" id="homeMemberBatchModal" aria-hidden="true">
        <div class="modal-card modal-wide home-member-batch-modal">
          <div class="modal-head"><h2>新增项目成员</h2><button type="button" class="modal-close" data-modal-close="homeMemberBatchModal">关闭</button></div>
          <div class="modal-body" id="homeMemberBatchBody"></div>
        </div>
      </div>
    </div>
  `;
}

function detailValue(value) {
  const text = String(value || '').trim();
  return esc(text || '未维护');
}

function detailTeamRows(members) {
  if (!members?.length) return '<div class="empty">暂未维护项目人员安排</div>';
  return `<div class="home-detail-team">${members.map(member => `
    <div><strong>${detailValue(member.name || member.username)}</strong><span>${detailValue(member.role || '项目成员')}</span><small>${detailValue([member.module, member.workload ? `当前项目工时：${member.workload}` : '当前项目工时未维护'].filter(Boolean).join(' · '))}</small></div>
  `).join('')}</div>`;
}

function renderProjectDetail(detail) {
  const title = $('homeProjectDetailTitle');
  const box = $('homeProjectDetailBody');
  if (!box) return;
  if (title) title.textContent = detail.name || '项目详情';
  const systems = detail.systems?.length
    ? `<ul class="home-detail-list">${detail.systems.map(item => `<li>${esc(item)}</li>`).join('')}</ul>`
    : `<p class="muted">${esc(detail.data_availability?.systems || '暂未维护')}</p>`;
  const editAction = detail.can_edit_home
    ? `<button type="button" class="secondary" id="homeEditProject" data-project-id="${esc(detail.id)}">编辑项目资料</button>`
    : '';
  const canEnterWorkspace = (state.projects || []).some(project => Number(project.id) === Number(detail.id));
  const workspaceAction = canEnterWorkspace
    ? `<button type="button" class="primary" data-home-enter-project="${esc(detail.id)}">进入项目执行</button>`
    : '';
  const peopleAction = detail.can_edit_home
    ? `<button type="button" class="secondary" data-home-manage-people="${esc(detail.id)}">人员安排</button>`
    : '';
  const claimAction = detail.claim_status === 'none'
    ? `<button type="button" class="primary" data-home-claim-project="${esc(detail.id)}">领用项目</button>`
    : detail.claim_status === 'pending'
      ? `<span class="home-claim-status">已提交领用申请，等待审批</span>`
      : '';
  const pendingClaims = detail.pending_claims || [];
  const claimApproval = detail.can_edit_home && pendingClaims.length
    ? `<section class="home-detail-full home-claim-approvals"><div class="home-claim-heading"><div><h3>待审批领用申请</h3><p>通过后，申请人会自动加入人员安排，默认负责模块为“待分工”。</p></div><button type="button" class="primary" data-home-approve-claims="${esc(detail.id)}">批量审批通过</button></div><label class="home-claim-select-all"><input type="checkbox" data-home-claim-select-all> 全选</label><div class="home-claim-list">${pendingClaims.map(item => `<label><input type="checkbox" data-home-claim-check="${esc(item.id)}"><span><strong>${detailValue(item.name || item.username)}</strong><small>${detailValue([item.office, item.department, item.job_title, item.workcode].filter(Boolean).join(' · ') || '人员信息未同步')}</small></span><time>${detailValue(item.created_at ? item.created_at.replace('T', ' ') : '')}</time></label>`).join('')}</div></section>`
    : '';
  box.innerHTML = `
    <div class="home-detail-actions">${claimAction}${workspaceAction}${peopleAction}${editAction}</div>
    <div class="home-detail-grid">
      <section><h3>项目基本信息</h3><dl class="home-detail-kv">
        <dt>项目编号</dt><dd>${detailValue(detail.oa_project_no || detail.code || detail.ims_project_no)}</dd>
        <dt>项目状态</dt><dd>${detailValue(projectStatusLabel(detail.status))}</dd>
        <dt>归属单位</dt><dd>${detailValue(detail.entity_name || detail.client_name)}</dd>
        <dt>归属部门</dt><dd>${detailValue(detail.department)}</dd>
        <dt>预计期间</dt><dd>${detailValue(detail.start_date || detail.audit_scope_start)} 至 ${detailValue(detail.end_date || detail.audit_scope_end)}</dd>
      </dl></section>
      <section><h3>审计范围</h3><dl class="home-detail-kv">
        <dt>审计期间</dt><dd>${detailValue(detail.scope?.start)} 至 ${detailValue(detail.scope?.end)}</dd>
        <dt>项目负责人</dt><dd>${detailValue(detail.project_leader_name)}</dd>
        <dt>项目经理</dt><dd>${detailValue(detail.manager_name)}</dd>
        <dt>现场负责人</dt><dd>${detailValue(detail.field_leader_name)}</dd>
      </dl></section>
      <section class="home-detail-full"><h3>人员安排</h3>${detailTeamRows(detail.members)}</section>
      ${claimApproval}
      <section><h3>公司系统清单</h3>${systems}</section>
      <section><h3>主营业务收入</h3><p class="home-detail-emphasis">${detail.business_revenue ? detailValue(detail.business_revenue) : esc(detail.data_availability?.business_revenue || '暂未维护')}</p></section>
      <section class="home-detail-full"><h3>范围说明</h3><p>${detailValue(detail.scope?.description)}</p></section>
    </div>
  `;
}

function homeEditField(label, name, value, {type = "text", wide = false} = {}) {
  return `<label class="${wide ? 'home-edit-wide' : ''}"><span>${esc(label)}</span><input name="${esc(name)}" type="${esc(type)}" value="${esc(value || '')}"></label>`;
}

function homeUserOptions(users, selectedUserId) {
  const selected = Number(selectedUserId || 0);
  return ['<option value="">未安排</option>', ...(users || []).map(user =>
    `<option value="${esc(user.id)}" ${Number(user.id) === selected ? 'selected' : ''}>${esc(user.name)}${user.role_name ? ` / ${esc(user.role_name)}` : ''}</option>`
  )].join('');
}

function homeRoleSelect(label, name, selectedUserId, users) {
  return `<label><span>${esc(label)}</span><select name="${esc(name)}">${homeUserOptions(users, selectedUserId)}</select></label>`;
}

function memberWorkloadFields(members) {
  if (!members?.length) return '<p class="muted">暂未维护项目成员。</p>';
  return `<div class="home-member-workloads">${members.map(member => `
    <div class="home-member-workload-row"><span><strong>${detailValue(member.name || member.username)}</strong><small>${detailValue([member.office, member.department, member.job_title, member.workcode].filter(Boolean).join(' · ') || member.role || '项目成员')}</small></span><input type="text" data-home-member-workload data-member-id="${esc(member.id)}" value="${esc(member.workload || '')}" placeholder="当前项目工时，例如：40 小时"><button type="button" class="danger" data-home-delete-member="${esc(member.id)}">删除</button></div>
  `).join('')}</div>`;
}

function filteredBatchStaff() {
  const keyword = homeMemberBatch.keyword.trim().toLowerCase();
  return homeMemberBatch.staff.filter(item => !keyword || [item.name, item.office, item.department, item.job_title, item.workcode].join(' ').toLowerCase().includes(keyword));
}

function batchMemberRecord(user) {
  return homeMemberBatch.selected.get(Number(user.id)) || {user, role_on_project: '', module: '', workload: ''};
}

function renderHomeMemberBatch() {
  const box = $('homeMemberBatchBody');
  if (!box) return;
  const selected = Array.from(homeMemberBatch.selected.values());
  const staff = filteredBatchStaff().slice(0, 100);
  box.innerHTML = `
    <div class="home-member-batch-head"><div class="home-member-batch-search"><input id="homeMemberBatchSearch" placeholder="搜索姓名、所属办公室、部门、职级或工号" value="${esc(homeMemberBatch.keyword)}"><button type="button" class="secondary" data-home-member-batch-search>筛选</button></div><span>已选择 ${esc(selected.length)} 人</span></div>
    <div class="home-member-batch-table"><table><thead><tr><th></th><th>姓名</th><th>所属办公室</th><th>部门</th><th>职级</th><th>工号</th></tr></thead><tbody>
      ${staff.map(user => `<tr><td><input type="checkbox" data-home-batch-staff="${esc(user.id)}" ${homeMemberBatch.selected.has(Number(user.id)) ? 'checked' : ''}></td><td>${esc(user.name)}</td><td>${detailValue(user.office)}</td><td>${detailValue(user.department)}</td><td>${detailValue(user.job_title)}</td><td>${detailValue(user.workcode)}</td></tr>`).join('') || '<tr><td colspan="6" class="empty">未找到人员</td></tr>'}
    </tbody></table></div>
    <div class="home-member-selected"><h3>待新增成员</h3>${selected.length ? selected.map(item => `<div class="home-member-selected-row" data-home-batch-member-row="${esc(item.user.id)}"><strong>${esc(item.user.name)}</strong><span>${esc([item.user.office, item.user.department, item.user.job_title, item.user.workcode].filter(Boolean).join(' · ') || '人员信息未同步')}</span><input data-home-batch-role placeholder="项目角色" value="${esc(item.role_on_project)}"><input data-home-batch-module placeholder="负责模块" value="${esc(item.module)}"><input data-home-batch-workload placeholder="当前项目工时" value="${esc(item.workload)}"></div>`).join('') : '<p class="muted">勾选人员后，可分别填写项目角色、负责模块和当前项目工时。</p>'}</div>
    <div class="form-actions"><button type="button" class="secondary" data-modal-close="homeMemberBatchModal">取消</button><button type="button" class="primary" data-home-complete-member-batch ${selected.length ? '' : 'disabled'}>完成新增</button></div>
  `;
}

function openHomeMemberBatch(detail) {
  homeMemberBatch.projectId = Number(detail.id);
  homeMemberBatch.staff = detail.available_users || [];
  homeMemberBatch.keyword = '';
  homeMemberBatch.selected = new Map();
  renderHomeMemberBatch();
  openModal('homeMemberBatchModal');
}


function renderHomeProjectEditor(detail) {
  const title = $('homeProjectDetailTitle');
  const box = $('homeProjectDetailBody');
  if (!box) return;
  if (title) title.textContent = `编辑项目资料 · ${detail.name || ''}`;
  const statusOptions = PROJECT_STATUS_OPTIONS.map(([value, label]) =>
    `<option value="${esc(value)}" ${value === detail.status ? 'selected' : ''}>${esc(label)}</option>`
  ).join('');
  const assignments = detail.role_assignments || {};
  const users = detail.available_users || [];
  box.innerHTML = `
    <form id="homeProjectEditForm" class="home-project-edit-form" data-project-id="${esc(detail.id)}">
      <div class="home-edit-grid">
        ${homeEditField('项目名称', 'name', detail.name, {wide: true})}
        ${homeEditField('项目编号', 'oa_project_no', detail.oa_project_no || detail.code)}
        ${homeEditField('IMS 编号', 'ims_project_no', detail.ims_project_no)}
        ${homeEditField('归属单位', 'entity_name', detail.entity_name || detail.client_name, {wide: true})}
        ${homeEditField('审计年度', 'audit_year', detail.audit_year, {type: 'number'})}
        <label><span>项目状态</span><select name="status">${statusOptions}</select></label>
        ${homeEditField('预计开始日期', 'start_date', detail.start_date || detail.audit_scope_start, {type: 'date'})}
        ${homeEditField('预计结束日期', 'end_date', detail.end_date || detail.audit_scope_end, {type: 'date'})}
        ${homeEditField('审计期间开始', 'audit_scope_start', detail.scope?.start, {type: 'date'})}
        ${homeEditField('审计期间结束', 'audit_scope_end', detail.scope?.end, {type: 'date'})}
        ${homeEditField('归属部门', 'department', detail.department)}
        ${homeEditField('主营业务收入', 'business_revenue', detail.business_revenue)}
        <label class="home-edit-wide"><span>范围说明</span><textarea name="scope_description" rows="4">${esc(detail.scope?.description || '')}</textarea></label>
      </div>
      <section class="home-people-editor" id="homeProjectPeopleEditor">
        <h3>人员安排</h3>
        <div class="home-edit-grid">
          ${homeRoleSelect('项目负责人', 'project_leader_user_id', assignments.project_leader_user_id, users)}
          ${homeRoleSelect('项目负责经理', 'manager_user_id', assignments.manager_user_id, users)}
          ${homeRoleSelect('现场负责人', 'field_leader_user_id', assignments.field_leader_user_id, users)}
          ${homeRoleSelect('质控复核人', 'quality_reviewer_user_id', assignments.quality_reviewer_user_id, users)}
          ${homeRoleSelect('项目主管', 'director_user_id', assignments.director_user_id, users)}
          ${homeRoleSelect('合伙人复核人', 'partner_user_id', assignments.partner_user_id, users)}
        </div>
        <div class="home-people-subhead"><h4>成员当前项目工时</h4><button type="button" class="secondary" data-home-open-member-batch="${esc(detail.id)}">新增成员</button></div>
        ${memberWorkloadFields(detail.members)}
      </section>
      <div class="form-actions"><button type="button" class="secondary" id="homeCancelProjectEdit">取消</button><button type="submit" class="primary">保存项目资料</button></div>
    </form>
  `;
}

function editHomeProjectPayload(form) {
  const data = Object.fromEntries(new FormData(form).entries());
  for (const key of ['audit_year']) data[key] = data[key] ? Number(data[key]) : null;
  for (const key of ['project_leader_user_id', 'manager_user_id', 'field_leader_user_id', 'quality_reviewer_user_id', 'director_user_id', 'partner_user_id']) data[key] = data[key] ? Number(data[key]) : null;
  for (const key of ['start_date', 'end_date', 'audit_scope_start', 'audit_scope_end']) data[key] = data[key] || null;
  data.member_workloads = Array.from(form.querySelectorAll('[data-home-member-workload]')).map(input => ({
    member_id: Number(input.dataset.memberId || 0),
    workload: String(input.value || '').trim(),
  })).filter(item => item.member_id > 0);
  return data;
}

async function openProjectDetail(projectId) {
  const requestSeq = ++homeDetailRequestSeq;
  const box = $('homeProjectDetailBody');
  if (box) box.innerHTML = '<div class="empty">正在读取项目详情…</div>';
  const modal = $('homeProjectDetailModal');
  if (modal) modal.dataset.projectId = String(projectId);
  openModal('homeProjectDetailModal');
  try {
    const detail = await request(`/api/home/projects/${projectId}`);
    if (requestSeq !== homeDetailRequestSeq) return;
    renderProjectDetail(detail);
  } catch (error) {
    if (requestSeq !== homeDetailRequestSeq) return;
    const activeBox = $('homeProjectDetailBody');
    if (activeBox) activeBox.innerHTML = `<div class="empty">项目详情读取失败：${esc(error.message)}</div>`;
  }
}


export function bindHome() {
  document.addEventListener('input', (event) => {
    const batchRow = event.target.closest?.('[data-home-batch-member-row]');
    if (batchRow) {
      const member = homeMemberBatch.selected.get(Number(batchRow.dataset.homeBatchMemberRow));
      if (member) {
        if (event.target.matches('[data-home-batch-role]')) member.role_on_project = event.target.value;
        if (event.target.matches('[data-home-batch-module]')) member.module = event.target.value;
        if (event.target.matches('[data-home-batch-workload]')) member.workload = event.target.value;
      }
      return;
    }
    if (event.target?.id === 'homeSearchInput') {
      homeFilters.page = 1;
      renderHome();
    }
  });
  document.addEventListener('change', (event) => {
    const batchCheckbox = event.target.closest?.('[data-home-batch-staff]');
    if (batchCheckbox) {
      const user = homeMemberBatch.staff.find(item => Number(item.id) === Number(batchCheckbox.dataset.homeBatchStaff));
      if (user) {
        if (batchCheckbox.checked) homeMemberBatch.selected.set(Number(user.id), batchMemberRecord(user));
        else homeMemberBatch.selected.delete(Number(user.id));
      }
      renderHomeMemberBatch();
      return;
    }
    if (event.target?.id === 'homeStatusFilter' || event.target?.id === 'homeYearFilter' || event.target?.id === 'homePageSize') {
      homeFilters.page = 1;
      renderHome();
      return;
    }
    if (event.target?.id === 'homeSelectAll') {
      document.querySelectorAll('[data-home-project-check]').forEach(input => { input.checked = event.target.checked; });
    }
    if (event.target?.matches('[data-home-claim-select-all]')) {
      document.querySelectorAll('[data-home-claim-check]').forEach(input => { input.checked = event.target.checked; });
    }
  });
  document.addEventListener('click', async (event) => {
    const closeButton = event.target.closest('[data-modal-close]');
    if (closeButton && ['homeProjectDetailModal', 'homeMemberBatchModal'].includes(closeButton.dataset.modalClose)) {
      window.setTimeout(renderHome, 0);
      return;
    }
    const batchSearch = event.target.closest('[data-home-member-batch-search]');
    if (batchSearch) {
      homeMemberBatch.keyword = String($('homeMemberBatchSearch')?.value || '');
      renderHomeMemberBatch();
      return;
    }
    const pageButton = event.target.closest('[data-home-page]');
    if (pageButton && !pageButton.disabled) {
      homeFilters.page = Number(pageButton.dataset.homePage) || 1;
      renderHome();
      return;
    }
    const claimProject = event.target.closest('[data-home-claim-project]');
    if (claimProject) {
      const projectId = Number(claimProject.dataset.homeClaimProject || 0);
      if (!projectId) return;
      claimProject.disabled = true;
      try {
        const result = await request(`/api/home/projects/${projectId}/claims`, {method: 'POST'});
        await openProjectDetail(projectId);
        setStatus(result.message || '领用申请已提交');
      } catch (error) {
        setStatus('提交领用申请失败：' + error.message);
        claimProject.disabled = false;
      }
      return;
    }
    const approveClaims = event.target.closest('[data-home-approve-claims]');
    if (approveClaims) {
      const projectId = Number(approveClaims.dataset.homeApproveClaims || 0);
      const claim_ids = Array.from(document.querySelectorAll('[data-home-claim-check]:checked')).map(input => Number(input.dataset.homeClaimCheck || 0)).filter(Boolean);
      if (!claim_ids.length) {
        setStatus('请先勾选需要审批的领用申请');
        return;
      }
      approveClaims.disabled = true;
      try {
        const result = await request(`/api/home/projects/${projectId}/claims/approve`, {method: 'POST', body: JSON.stringify({claim_ids})});
        await openProjectDetail(projectId);
        setStatus(`已审批 ${result.approved || claim_ids.length} 条领用申请，并新增 ${result.members_created || 0} 名项目成员`);
      } catch (error) {
        setStatus('审批领用申请失败：' + error.message);
        approveClaims.disabled = false;
      }
      return;
    }
    const enterProject = event.target.closest('[data-home-enter-project]');
    if (enterProject) {
      window.selectHomeProject?.(Number(enterProject.dataset.homeEnterProject || 0));
      return;
    }
    const openMemberBatch = event.target.closest('[data-home-open-member-batch]');
    if (openMemberBatch) {
      const projectId = Number(openMemberBatch.dataset.homeOpenMemberBatch || 0);
      request(`/api/home/projects/${projectId}`).then(openHomeMemberBatch).catch(error => setStatus('人员信息读取失败：' + error.message));
      return;
    }
    const completeMemberBatch = event.target.closest('[data-home-complete-member-batch]');
    if (completeMemberBatch) {
      const projectId = Number(homeMemberBatch.projectId || 0);
      const items = Array.from(homeMemberBatch.selected.values()).map(item => ({
        user_id: item.user.id,
        role_on_project: item.role_on_project || '',
        module: item.module || '',
        workload: item.workload || '',
      }));
      if (!projectId || !items.length) return;
      completeMemberBatch.disabled = true;
      try {
        await request(`/api/home/projects/${projectId}/members/batch`, {method: 'POST', body: JSON.stringify({items})});
        closeModal('homeMemberBatchModal');
        renderHomeProjectEditor(await request(`/api/home/projects/${projectId}`));
        setStatus(`已新增 ${items.length} 名项目成员`);
      } catch (error) {
        setStatus('新增成员失败：' + error.message);
        completeMemberBatch.disabled = false;
      }
      return;
    }
    const deleteMember = event.target.closest('[data-home-delete-member]');
    if (deleteMember) {
      const form = $('homeProjectEditForm');
      const projectId = Number(form?.dataset.projectId || 0);
      const memberId = Number(deleteMember.dataset.homeDeleteMember || 0);
      if (!projectId || !memberId) return;
      deleteMember.disabled = true;
      try {
        await request(`/api/home/projects/${projectId}/members/${memberId}`, {method: 'DELETE'});
        renderHomeProjectEditor(await request(`/api/home/projects/${projectId}`));
        setStatus('项目成员已删除');
      } catch (error) {
        setStatus('删除成员失败：' + error.message);
        deleteMember.disabled = false;
      }
      return;
    }
    const managePeople = event.target.closest('[data-home-manage-people]');
    if (managePeople) {
      const projectId = Number(managePeople.dataset.homeManagePeople || 0);
      request(`/api/home/projects/${projectId}`).then(detail => {
        renderHomeProjectEditor(detail);
        $('homeProjectPeopleEditor')?.scrollIntoView({block: 'start'});
      }).catch(error => {
        const box = $('homeProjectDetailBody');
        if (box) box.innerHTML = `<div class="empty">项目详情读取失败：${esc(error.message)}</div>`;
      });
      return;
    }
    if (event.target.closest('#homeEditProject')) {
      const projectId = Number(event.target.closest('#homeEditProject').dataset.projectId || 0);
      // The current detail is stored on the form-independent modal element.
      request(`/api/home/projects/${projectId || $('homeProjectDetailModal')?.dataset.projectId}`).then(renderHomeProjectEditor).catch(error => {
        const box = $('homeProjectDetailBody');
        if (box) box.innerHTML = `<div class="empty">项目详情读取失败：${esc(error.message)}</div>`;
      });
      return;
    }
    if (event.target.closest('#homeCancelProjectEdit')) {
      const projectId = Number($('homeProjectEditForm')?.dataset.projectId || 0);
      if (projectId) openProjectDetail(projectId);
      return;
    }
    const row = event.target.closest('[data-home-project-row]');
    if (row && !event.target.closest('input, button, select, label')) openProjectDetail(row.dataset.homeProjectRow);
  });
  document.addEventListener('submit', async (event) => {
    const form = event.target;
    if (form?.id !== 'homeProjectEditForm') return;
    event.preventDefault();
    const projectId = Number(form.dataset.projectId || 0);
    const submit = form.querySelector('button[type="submit"]');
    if (submit) submit.disabled = true;
    try {
      const updated = await request(`/api/home/projects/${projectId}`, {method: 'PATCH', body: JSON.stringify(editHomeProjectPayload(form))});
      const rowIndex = (state.homeProjects || []).findIndex(item => Number(item.id) === projectId);
      if (rowIndex >= 0) state.homeProjects[rowIndex] = {...state.homeProjects[rowIndex], ...updated};
      await openProjectDetail(projectId);
    } catch (error) {
      const actions = form.querySelector('.form-actions');
      if (actions) actions.insertAdjacentHTML('beforebegin', `<p class="form-error">保存失败：${esc(error.message)}</p>`);
    } finally {
      if (submit) submit.disabled = false;
    }
  });
  document.addEventListener('keydown', (event) => {
    const row = event.target.closest?.('[data-home-project-row]');
    if (row && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault();
      openProjectDetail(row.dataset.homeProjectRow);
    }
    if (event.target?.id === 'homePageJump' && event.key === 'Enter') {
      const maximum = Number(event.target.max) || 1;
      homeFilters.page = Math.min(Math.max(1, Number(event.target.value) || 1), maximum);
      renderHome();
    }
  });
}
