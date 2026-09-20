import { api, authHeaders, request } from '../api.js?v=20260920-state12';
import { state } from '../state.js?v=20260920-state12';
import { $, activeProjectId, closeModal, esc, fillSelect, formData, openModal, setStatus, statusClass, tag } from '../utils.js?v=20260630a';

export const workpaperTreeExtension = {
  onTemplateNodeClick(node, event) {
    selectTreeNode(node, event);
  }
};

let refreshProjectScoped = async () => {};
let quickUploadTarget = null;
let selectedWorkpaperIds = new Set();

const stageLabels = {
  planning: '1.项目准备',
  execution: '2.项目实施',
  delivery: '3.项目交付',
  reporting: '4.项目报告',
  completion: '3.项目交付'
};

function currentTree() {
  const pid = activeProjectId();
  return pid ? (state.workpaperTreeByProject[pid] || []) : [];
}

function flattenTree(nodes = []) {
  return nodes.flatMap(node => [node, ...flattenTree(node.children || [])]);
}

function fileNameFromPath(path = '') {
  const value = String(path || '').trim();
  if (!value) return '未维护文件路径';
  return value.split(/[\\/]/).filter(Boolean).pop() || value;
}

function compactPath(path = '') {
  const parts = String(path || '').split(/[\\/]/).filter(Boolean);
  if (!parts.length) return '';
  return parts.slice(-4).join(' / ');
}

function displayDateTime(value) {
  if (!value) return '未维护';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 16);
  return date.toLocaleString('zh-CN', {hour12: false}).replace(/\//g, '-');
}

function reviewStepTone(step) {
  if (step.is_overdue) return 'state-risk';
  if (String(step.status || '').toLowerCase() === 'approved') return 'state-done';
  if (String(step.status || '').toLowerCase() === 'pending') return 'state-running';
  return statusClass(step.status || 'waiting');
}

function renderReviewStepStrip(workpaperId) {
  const steps = state.reviewStepsByWorkpaper?.[workpaperId] || [];
  if (!steps.length) return '<div class="subtle-note">复核流程尚未发起。</div>';
  return `
    <div class="review-step-strip">
      ${steps.map(step => `
        <div class="review-step-item ${step.is_overdue ? 'overdue' : ''}">
          <strong>${esc({project_manager: '项目经理', responsible_manager: '项目负责经理', director: '总监', partner: '合伙人', quality: '质控'}[step.reviewer_role_code] || step.reviewer_role_code || `第${step.sequence_no}级复核`)}</strong>
          ${tag(step.status || 'waiting', reviewStepTone(step))}
          <small>${esc(step.reviewer_name || '未指定复核人')} / 第 ${esc(step.round_no || 1)} 轮</small>
          <small>已停留 ${esc(step.waiting_days || 0)} 天 / SLA ${esc(step.sla_days || 3)} 天</small>
          <span>${esc(step.due_date || '未维护截止日')}</span>
          ${step.can_decide ? `<div class="actions"><button type="button" data-review-step-approve="${esc(step.id)}">通过</button><button type="button" class="danger" data-review-step-reject="${esc(step.id)}">退回</button></div>` : ''}
        </div>
      `).join('')}
    </div>
  `;
}

function stageLabel(stage = '') {
  return stageLabels[stage] || stage || '未分组';
}

function stageFromTreeNode(nodeId) {
  return flattenTree(currentTree()).find(node => node.id === nodeId && node.type === 'stage')?.stage || '';
}

function workpaperIdsUnderStage(stage) {
  if (!stage) return new Set();
  const stageNode = currentTree().find(node => node.type === 'stage' && node.stage === stage);
  return new Set(flattenTree(nodeChildren(stageNode)).filter(node => ['workpaper', 'test_point'].includes(node.type) && node.workpaper_id).map(node => node.workpaper_id));
}

function selectedTreeNode() {
  return flattenTree(currentTree()).find(node => node.id === state.selectedWorkpaperTreeNode) || null;
}

function selectedPreview() {
  return state.selectedWorkpaperId ? state.workpaperPreviews[state.selectedWorkpaperId] : null;
}

function expandedTreeState() {
  if (!state.expandedWorkpaperTreeNodes || typeof state.expandedWorkpaperTreeNodes !== 'object') {
    state.expandedWorkpaperTreeNodes = {};
  }
  return state.expandedWorkpaperTreeNodes;
}

function nodeChildren(node) {
  return Array.isArray(node?.children) ? node.children : [];
}

function isExpanded(node) {
  if (!node) return false;
  const expanded = expandedTreeState();
  if (Object.prototype.hasOwnProperty.call(expanded, node.id)) {
    return Boolean(expanded[node.id]);
  }
  return node.type === 'stage';
}

function toggleNode(node) {
  if (!nodeChildren(node).length) return;
  expandedTreeState()[node.id] = !isExpanded(node);
}

function treeNodeTypeLabel(type = '') {
  return {
    stage: '阶段',
    workpaper: '底稿',
    workpaper_placeholder: '底稿',
    test_point_folder: 'C22测试点目录',
    test_point: 'C22测试点',
    attachment_folder: '附件文件夹',
    attachment_path_folder: '导入文件夹',
    attachment_sheet_folder: '附件Sheet',
    attachment: '附件'
  }[type] || type || '节点';
}

function statusDotClass(status = '') {
  const cls = statusClass(status || 'not_started');
  return cls || 'state-not-started';
}

function childCount(node, type) {
  return flattenTree(nodeChildren(node)).filter(child => child.type === type).length;
}

function renderTreeNode(node, depth = 0) {
  const children = nodeChildren(node);
  const count = children.length;
  const expanded = isExpanded(node);
  const active = node.id === state.selectedWorkpaperTreeNode || (node.workpaper_id && node.workpaper_id === state.selectedWorkpaperId);
  const isWorkpaper = node.type === 'workpaper';
  const isPlaceholder = node.type === 'workpaper_placeholder';
  const isTestPoint = node.type === 'test_point';
  const isWorkpaperLike = isWorkpaper || isPlaceholder || isTestPoint;
  const isAttachment = node.type === 'attachment';
  const isFolder = ['attachment_folder', 'attachment_sheet_folder', 'attachment_path_folder', 'test_point_folder'].includes(node.type);
  const path = node.file_path || '';
  const title = (isWorkpaperLike || isAttachment)
    ? `${node.code || node.index_no || ''} ${node.name || node.label || ''}\n${path || '未维护文件路径'}`
    : `${node.label || ''}，${count} 项`;
  const meta = isFolder
    ? `${count}个`
    : isAttachment
      ? (node.index_no || node.file_type || '附件')
      : isPlaceholder
        ? '待上传'
        : isTestPoint
          ? 'C22内部测试点'
        : isWorkpaper
          ? (node.status || '已登记')
          : `${count}份`;
  const primary = isAttachment
    ? (node.name || fileNameFromPath(path) || node.label || '未命名附件')
    : isWorkpaper || isPlaceholder
      ? `${node.code || '未维护索引号'} ${node.name || fileNameFromPath(path) || '未命名底稿'}`.trim()
      : isTestPoint
        ? (node.label || node.name || 'C22测试点')
      : (node.label || stageLabel(node.stage));
  const fileLine = isAttachment || isWorkpaper
    ? fileNameFromPath(path)
    : isPlaceholder
      ? '未登记到底稿台账'
      : '';
  return `
    <div class="tree-node tree-node-${esc(node.type || 'group')} ${active ? 'active' : ''}" style="--tree-depth:${depth}" title="${esc(title)}" data-template-node="${esc(node.id)}" data-tree-id="${esc(node.id)}" data-tree-type="${esc(node.type || '')}" data-template-stage="${esc(node.stage || '')}" data-workpaper-id="${esc(node.workpaper_id || '')}" data-attachment-id="${esc(node.attachment_id || '')}">
      <div class="tree-node-main">
        ${count ? `<span class="tree-toggle" data-tree-toggle="${esc(node.id)}">${expanded ? '▾' : '▸'}</span>` : '<span class="tree-spacer"></span>'}
        ${isWorkpaperLike ? `<span class="status-dot ${statusDotClass(node.status)}"></span>` : ''}
        <strong>${esc(primary)}</strong>
        <span class="tree-node-meta">${esc(meta)}</span>
      </div>
      ${fileLine ? `
        <div class="tree-file-name">${esc(fileLine)}</div>
      ` : ''}
    </div>
    ${count && expanded ? `<div class="tree-children">${children.map(child => renderTreeNode(child, depth + 1)).join('')}</div>` : ''}
  `;
}

export async function loadWorkpaperTree(projectId = activeProjectId(), {force = false} = {}) {
  if (!projectId) return [];
  if (!force && state.workpaperTreeByProject[projectId]) return state.workpaperTreeByProject[projectId];
  state.workpaperTreeByProject[projectId] = await request(`/api/projects/${projectId}/workpaper-tree`);
  return state.workpaperTreeByProject[projectId];
}

export function renderWorkpaperTemplateTree() {
  const tree = $('workpaperTemplateTree');
  if (!tree) return;
  const nodes = currentTree();
  tree.innerHTML = nodes.length
    ? nodes.map(node => renderTreeNode(node)).join('')
    : '<div class="empty">暂无底稿文件</div>';
}

export function renderWorkpapers() {
  fillSelect($('attachmentWorkpaper'), state.workpapers, w => `${w.code} ${w.name}`);
  renderWorkpaperTemplateTree();
  const selectedStage = stageFromTreeNode(state.selectedWorkpaperTreeNode);
  const selectedStageWorkpaperIds = workpaperIdsUnderStage(selectedStage);
  const rows = selectedStage
    ? state.workpapers.filter(w => selectedStageWorkpaperIds.has(w.id) || w.stage === selectedStage)
    : state.workpapers;
  if ($('workpaperHistoryBtn')) $('workpaperHistoryBtn').disabled = !state.selectedWorkpaperId;
  if ($('downloadWorkpaperBtn')) $('downloadWorkpaperBtn').disabled = !state.selectedWorkpaperId;
  const eligibleIds = new Set(rows.filter(w => String(w.status || '').toLowerCase() === 'draft').map(w => w.id));
  selectedWorkpaperIds = new Set([...selectedWorkpaperIds].filter(id => eligibleIds.has(id)));
  const selectAll = $('workpaperSelectAll');
  if (selectAll) {
    selectAll.checked = eligibleIds.size > 0 && selectedWorkpaperIds.size === eligibleIds.size;
    selectAll.indeterminate = selectedWorkpaperIds.size > 0 && selectedWorkpaperIds.size < eligibleIds.size;
    selectAll.disabled = !eligibleIds.size;
  }
  if ($('batchSubmitWorkpapersBtn')) $('batchSubmitWorkpapersBtn').disabled = !selectedWorkpaperIds.size;
  $('workpaperRows').innerHTML = rows.map(w => `
    <tr class="selectable-row ${w.id === state.selectedWorkpaperId ? 'selected-row' : ''}" data-workpaper-row="${esc(w.id)}">
      <td>${String(w.status || '').toLowerCase() === 'draft' ? `<input type="checkbox" data-workpaper-select="${esc(w.id)}" ${selectedWorkpaperIds.has(w.id) ? 'checked' : ''} aria-label="选择 ${esc(w.code)}">` : ''}</td>
      <td>${esc(w.code)}</td>
      <td><strong>${esc(w.name)}</strong><div class="muted">${esc(compactPath(w.file_path || '') || '未维护文件路径')}</div></td>
      <td>${esc(stageLabel(w.stage))}</td>
      <td>${tag(w.status, statusClass(w.status))}</td>
      <td>${w.year_updated ? tag('已更新', 'green') : tag('待确认', 'amber')}</td>
      <td class="actions">${['draft', 'returned'].includes(String(w.status || '').toLowerCase())
        ? `<button class="secondary" data-workpaper-submit="${esc(w.id)}">${String(w.status || '').toLowerCase() === 'returned' ? '整改后重提' : '提交复核'}</button>`
        : '<span class="muted">按流程处理中</span>'}</td>
    </tr>
  `).join('') || '<tr><td colspan="7" class="empty">暂无底稿</td></tr>';
  renderWorkpaperHeaderBatch();
  renderWorkpaperDetail();
}

function renderPreviewText(preview) {
  if (!preview) return '<div class="empty">正在加载底稿预览...</div>';
  if (preview.error) return `<div class="subtle-note">${esc(preview.error)}</div>`;
  const text = preview.preview_text || (preview.lines || []).join('\n');
  if (!text) return '<div class="empty">该底稿暂无可预览内容。</div>';
  return `<pre>${esc(text)}</pre>`;
}

function renderStructuredPreview(preview) {
  if (!preview) return '<div class="empty">正在加载底稿预览...</div>';
  if (preview.error) return `<div class="subtle-note">${esc(preview.error)}</div>`;
  const sections = Array.isArray(preview.sheet_sections) ? preview.sheet_sections : [];
  const nonEmptySections = sections
    .map(section => ({
      sheet: section.sheet || '未命名Sheet',
      rows: Array.isArray(section.rows) ? section.rows.filter(row => Array.isArray(row.cells) && row.cells.length) : []
    }))
    .filter(section => section.rows.length);
  if (!nonEmptySections.length) return renderPreviewText(preview);
  return `
    <div class="sheet-preview">
      ${preview.recognition_note ? `<div class="subtle-note">${esc(preview.recognition_note)}</div>` : ''}
      ${nonEmptySections.map(section => `
        <div class="sheet-preview-section">
          <h4>${esc(section.sheet)}</h4>
          <table>
            <thead><tr><th>底稿位置</th><th>内容</th></tr></thead>
            <tbody>
              ${section.rows.slice(0, 80).flatMap(row => row.cells.map(cell => `
                <tr>
                  <td>${esc(cell.location || `${section.sheet}!${cell.cell || ''}`)}</td>
                  <td>${esc(cell.value || '')}</td>
                </tr>
              `)).join('')}
            </tbody>
          </table>
        </div>
      `).join('')}
    </div>
  `;
}

function headerStatusTone(status = '') {
  if (status === 'ok') return 'green';
  if (status === 'needs_update') return 'amber';
  if (status === 'missing_target') return 'state-risk';
  return statusClass(status || 'not_started');
}

function headerStatusLabel(status = '') {
  return {
    ok: '已一致',
    needs_update: '待更新',
    missing_target: '缺目标值',
    unsupported: '不支持',
    no_header_found: '未识别',
    error: '错误',
  }[status] || status || '未检查';
}

function renderWorkpaperHeaderBatch() {
  const panel = $('workpaperHeaderPanel');
  if (!panel) return;
  const batch = state.workpaperHeaderBatch;
  const applyBtn = $('testCopyHeadersBtn');
  const realBtn = $('applyHeadersBtn');
  if (!batch) {
    panel.classList.add('hidden');
    if (applyBtn) applyBtn.disabled = true;
    if (realBtn) realBtn.disabled = true;
    return;
  }
  panel.classList.remove('hidden');
  if (applyBtn) applyBtn.disabled = !activeProjectId() || !Number(batch.field_count || 0);
  if (realBtn) realBtn.disabled = !activeProjectId() || !Number(batch.field_count || 0);
  const fields = Array.isArray(batch.fields) ? batch.fields : [];
  const summary = $('workpaperHeaderSummary');
  if (summary) {
    const style = batch.style || {};
    summary.innerHTML = `
      <span class="pill">底稿 ${esc(batch.workpaper_count || 0)} 份</span>
      <span class="pill">支持 ${esc(batch.supported_count || 0)} 份</span>
      <span class="pill">字段 ${esc(batch.field_count || 0)} 个</span>
      <span class="pill">待更新 ${esc(batch.needs_update_count || 0)} 个</span>
      <span class="pill">字体 ${esc(style.font_name || '宋体')} / ${esc(style.font_size || 10)}号</span>
      ${batch.mode === 'test_copy' ? `<span class="path-note">测试副本目录：${esc(batch.output_dir || '')}</span>` : ''}
      ${batch.mode === 'real_write' ? `<span class="path-note">真实写入备份目录：${esc(batch.backup_dir || '')}</span>` : ''}
      ${batch.report_json ? `<span class="path-note">报告：${esc(batch.report_json)}</span>` : ''}
    `;
  }
  const rows = $('workpaperHeaderRows');
  if (!rows) return;
  rows.innerHTML = fields.slice(0, 200).map(item => `
    <tr>
      <td><strong>${esc(item.workpaper_code || '')}</strong><div class="muted">${esc(item.workpaper_name || '')}</div></td>
      <td>${esc(item.label || item.field || '')}</td>
      <td>${esc([item.sheet_name, item.value_cell].filter(Boolean).join('!'))}</td>
      <td>${esc(item.current_value || '')}</td>
      <td>${esc(item.target_value || '')}</td>
      <td>${tag(headerStatusLabel(item.status), headerStatusTone(item.status))}</td>
    </tr>
  `).join('') || '<tr><td colspan="6" class="empty">未识别到底稿表头字段</td></tr>';
}

function renderNodeChildrenList(node) {
  const children = nodeChildren(node);
  if (!children.length) return '<div class="empty">该节点下暂无内容。</div>';
  return `
    <div class="detail-list">
      ${children.map(item => `
        <div class="detail-list-item">
          <strong>${esc(item.code || item.index_no || treeNodeTypeLabel(item.type))}</strong>
          <span>${esc(item.name || item.label || '未命名')}
            <small>${esc(compactPath(item.file_path || '') || treeNodeTypeLabel(item.type))}</small>
          </span>
          ${item.status ? tag(item.status, statusClass(item.status)) : ''}
        </div>
      `).join('')}
    </div>
  `;
}

function renderWorkpaperDetail() {
  const detail = $('workpaperDetail');
  if (!detail) return;
  const preview = selectedPreview();
  const base = state.workpapers.find(row => row.id === state.selectedWorkpaperId) || {};
  const selected = state.selectedWorkpaperId ? {...base, ...(preview || {})} : null;
  const node = selectedTreeNode();
  if (selected) {
    const relatedAttachments = state.attachments.filter(item => Number(item.workpaper_id) === Number(selected.id));
    const projectId = String(selected.project_id || activeProjectId() || '');
    const relatedFindings = state.reviewFindings.filter(item => (
      String(item.project_id || '') === projectId
      && String(item.workpaper_id || '') === String(selected.id)
    ));
    const versions = state.workpaperVersionsById?.[selected.id] || [];
    detail.innerHTML = `
      <div class="detail-view">
        <h3>${esc(selected.code || '未维护编号')} / ${esc(selected.name || '未命名底稿')}</h3>
        <div class="detail-grid">
          <div class="detail-card"><span>阶段</span><strong>${esc(stageLabel(selected.stage || ''))}</strong></div>
          <div class="detail-card"><span>状态</span><strong>${tag(selected.status || 'unknown', statusClass(selected.status))}</strong></div>
          <div class="detail-card"><span>文件类型</span><strong>${esc(preview?.file_type || '未读取')}</strong></div>
          <div class="detail-card"><span>编制人</span><strong>${esc(selected.preparer_name || '未维护')}</strong></div>
          <div class="detail-card"><span>编制日期</span><strong>${esc(displayDateTime(selected.prepared_at || selected.created_at))}</strong></div>
          <div class="detail-card"><span>复核人</span><strong>${esc(selected.reviewer_name || '未维护')}</strong></div>
          <div class="detail-card"><span>复核日期</span><strong>${esc(displayDateTime(selected.reviewed_at))}</strong></div>
          <div class="detail-card"><span>是否发起复核</span><strong>${tag(selected.review_started ? '已发起' : '未发起', selected.review_started ? 'state-running' : 'state-not-started')}</strong></div>
          <div class="detail-card"><span>关联问题/附件</span><strong>${esc(relatedFindings.length)} / ${esc(relatedAttachments.length)}</strong></div>
        </div>
        <div class="subtle-note">文件：${esc(selected.file_path || '未维护文件路径')}</div>
        <div class="subtle-note">自动填写建议：请在“自动填写配置”页签查看字段级 dry-run 和测试副本验证状态。表头维护可在本页扫描后备份并真实写入。</div>
        ${renderReviewStepStrip(selected.id)}
        <div class="detail-list" id="workpaperVersionHistory">
          ${versions.map(version => `<div class="detail-list-item"><strong>V${esc(version.version_no)}</strong><span>${esc(version.original_filename || '')}<small>${esc(version.uploaded_by_name || '未知上传人')} / ${esc(displayDateTime(version.created_at))}</small></span></div>`).join('') || '<div class="subtle-note">暂无上传版本记录；后续上传将从 V1 开始保留。</div>'}
        </div>
        ${relatedFindings.length ? `<div class="detail-list">${relatedFindings.slice(0, 5).map(item => `<div class="detail-list-item"><strong>${esc(item.rule_code || '')}</strong><span>${esc(item.issue || '')}</span>${tag(item.status || 'open', statusClass(item.status || 'open'))}</div>`).join('')}</div>` : ''}
        ${relatedAttachments.length ? `<div class="detail-list">${relatedAttachments.slice(0, 5).map(item => `<div class="detail-list-item"><strong>${esc(item.index_no || '')}</strong><span>${esc(item.title || '')}<small>${esc(item.file_path || '')}</small></span>${tag(item.status || 'active', statusClass(item.status || 'active'))}</div>`).join('')}</div>` : ''}
        ${preview?.sheets?.length ? `<div class="muted">页签：${esc(preview.sheets.join('、'))}</div>` : ''}
        ${renderStructuredPreview(preview)}
      </div>
    `;
    return;
  }
  if (node) {
    if (node.type === 'attachment') {
      detail.innerHTML = `
        <div class="detail-view">
          <h3>${esc(node.index_no || '附件')} / ${esc(node.name || node.label || '未命名附件')}</h3>
          <div class="detail-grid">
            <div class="detail-card"><span>节点类型</span><strong>附件</strong></div>
            <div class="detail-card"><span>文件类型</span><strong>${esc(node.file_type || '未维护')}</strong></div>
            <div class="detail-card"><span>状态</span><strong>${tag(node.status || 'active', statusClass(node.status || 'active'))}</strong></div>
          </div>
          <div class="subtle-note">文件：${esc(node.file_path || '未维护文件路径')}</div>
          ${node.referenced_in ? `<div class="subtle-note">底稿引用：${esc(node.referenced_in)}</div>` : ''}
        </div>
      `;
      return;
    }
    const descendantWorkpaperCount = childCount(node, 'workpaper') + childCount(node, 'workpaper_placeholder');
    const descendantAttachmentCount = childCount(node, 'attachment');
    detail.innerHTML = `
      <div class="detail-view">
        <h3>${esc(node.label || '底稿节点')}</h3>
        <div class="detail-grid">
          <div class="detail-card"><span>节点类型</span><strong>${esc(treeNodeTypeLabel(node.type))}</strong></div>
          <div class="detail-card"><span>阶段</span><strong>${esc(stageLabel(node.stage || ''))}</strong></div>
          <div class="detail-card"><span>底稿/附件</span><strong>${esc(descendantWorkpaperCount)} / ${esc(descendantAttachmentCount)}</strong></div>
        </div>
        <div class="subtle-note">点击左侧箭头展开或收起层级。点击具体底稿查看预览，点击附件查看文件信息。</div>
        ${renderNodeChildrenList(node)}
      </div>
    `;
    return;
  }
  detail.innerHTML = '<div class="empty">点击左侧结构或底稿行后查看详情</div>';
}

async function selectTreeNode(nodeEl, event) {
  const pid = activeProjectId();
  if (!pid) return setStatus('请先选择项目');
  try {
    await loadWorkpaperTree(pid);
    const treeId = nodeEl.dataset.treeId || null;
    const node = flattenTree(currentTree()).find(item => item.id === treeId) || null;
    const shouldToggle = Boolean(event?.target?.closest('[data-tree-toggle]'))
      || node?.type === 'stage'
      || node?.type === 'attachment_folder'
      || node?.type === 'attachment_sheet_folder'
      || node?.type === 'attachment_path_folder'
      || node?.type === 'test_point_folder';
    state.selectedWorkpaperTreeNode = treeId;
    const workpaperId = Number(nodeEl.dataset.workpaperId || 0);
    state.selectedWorkpaperId = shouldToggle ? null : (workpaperId || null);
    if (shouldToggle && nodeChildren(node).length) toggleNode(node);
    if (state.selectedWorkpaperId) await Promise.all([loadWorkpaperPreview(state.selectedWorkpaperId), loadReviewSteps(state.selectedWorkpaperId), loadWorkpaperVersions(state.selectedWorkpaperId)]);
    renderWorkpapers();
    setStatus('就绪');
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

async function loadWorkpaperPreview(id) {
  if (!id) return null;
  if (!state.workpaperPreviews[id]) {
    state.workpaperPreviews[id] = await request(`/api/workpapers/${id}/preview`);
  }
  return state.workpaperPreviews[id];
}

async function loadReviewSteps(id, {force = false} = {}) {
  if (!id) return [];
  if (!state.reviewStepsByWorkpaper) state.reviewStepsByWorkpaper = {};
  if (!force && state.reviewStepsByWorkpaper[id]) return state.reviewStepsByWorkpaper[id];
  state.reviewStepsByWorkpaper[id] = await request(`/api/workpapers/${id}/review-steps`);
  return state.reviewStepsByWorkpaper[id];
}

async function loadWorkpaperVersions(id, {force = false} = {}) {
  if (!id) return [];
  if (!state.workpaperVersionsById) state.workpaperVersionsById = {};
  if (!force && state.workpaperVersionsById[id]) return state.workpaperVersionsById[id];
  state.workpaperVersionsById[id] = await request(`/api/workpapers/${id}/versions`);
  return state.workpaperVersionsById[id];
}

async function selectWorkpaper(id) {
  state.selectedWorkpaperId = Number(id);
  const item = state.workpapers.find(row => row.id === state.selectedWorkpaperId);
  if (item) {
    const node = flattenTree(currentTree()).find(row => row.workpaper_id === item.id);
    state.selectedWorkpaperTreeNode = node?.id || state.selectedWorkpaperTreeNode;
  }
  renderWorkpapers();
  try {
    await Promise.all([loadWorkpaperPreview(id), loadReviewSteps(id), loadWorkpaperVersions(id)]);
    renderWorkpapers();
    setStatus('就绪');
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

async function submitWorkpaper(id) {
  try {
    await request(`/api/workpapers/${id}/submit`, {method: 'POST', body: '{}'});
    if (state.reviewStepsByWorkpaper) delete state.reviewStepsByWorkpaper[id];
    await refreshProjectScoped();
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

async function downloadSelectedWorkpaper(workpaperId) {
  const response = await fetch(`${api}/api/workpapers/${workpaperId}/download`, {headers: authHeaders()});
  if (!response.ok) {
    let detail = await response.text();
    try { detail = JSON.parse(detail).detail || detail; } catch {}
    throw new Error(detail || '无法下载底稿文件');
  }
  const disposition = String(response.headers.get('content-disposition') || '');
  const filename = (disposition.match(/filename="?([^";]+)"?/i)?.[1] || '底稿文件').trim();
  const objectUrl = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1_000);
}

async function openSelectedWorkpaper() {
  const workpaperId = Number(state.selectedWorkpaperId);
  if (!workpaperId) return setStatus('请先选择底稿');
  try {
    const result = await request(`/api/workpapers/${workpaperId}/open-local`, {method: 'POST', body: '{}'});
    if (result.opened) {
      setStatus(`已直接打开本地底稿：${result.filename || ''}`);
      return;
    }
    await downloadSelectedWorkpaper(workpaperId);
    setStatus('本地未找到该底稿，已下载文件');
  } catch (err) {
    setStatus('打开底稿失败：' + err.message);
  }
}

async function openBatchReviewSubmit() {
  const workpaperIds = [...selectedWorkpaperIds];
  if (!workpaperIds.length) return setStatus('请先勾选待提交复核的底稿');
  const projectId = activeProjectId();
  if (!projectId) return setStatus('请先选择项目');
  try {
    const reviewers = await request(`/api/projects/${projectId}/reviewer-options`);
    if (!reviewers.length) return setStatus('项目尚未配置可选复核人，请先在项目资料中配置复核链');
    const select = $('batchReviewReviewer');
    select.innerHTML = reviewers.map(item => `<option value="${esc(item.user_id)}">${esc(item.display_name)}（${esc(item.role_name)}）</option>`).join('');
    const codes = workpaperIds.map(id => state.workpapers.find(item => item.id === id)?.code || id);
    $('batchReviewSubmitSummary').textContent = `已选择 ${workpaperIds.length} 份底稿：${codes.join('、')}`;
    openModal('batchReviewSubmitModal');
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

async function submitSelectedWorkpapers(event) {
  event.preventDefault();
  const workpaperIds = [...selectedWorkpaperIds];
  const reviewerId = Number($('batchReviewReviewer')?.value);
  if (!workpaperIds.length || !reviewerId) return setStatus('请选择底稿和下一层复核人');
  try {
    const result = await request('/api/workpapers/batch-submit', {
      method: 'POST',
      body: JSON.stringify({workpaper_ids: workpaperIds, next_reviewer_user_id: reviewerId})
    });
    selectedWorkpaperIds = new Set();
    closeModal('batchReviewSubmitModal');
    await refreshProjectScoped();
    setStatus(`已提交 ${result.count || workpaperIds.length} 份底稿，等待复核`);
  } catch (err) {
    setStatus('批量提交失败，未提交任何底稿：' + err.message);
  }
}

async function decideReviewStep(id, action) {
  try {
    const input = window.prompt(action === 'reject' ? '请输入退回原因和整改要求' : '复核通过意见（可留空）');
    if (input === null) return;
    const comment = input;
    if (action === 'reject' && !comment.trim()) return setStatus('退回必须填写复核意见');
    await request(`/api/review-steps/${id}/${action}`, {method: 'POST', body: JSON.stringify({comment})});
    state.reviewStepsByWorkpaper = {};
    await refreshProjectScoped();
    if (state.selectedWorkpaperId) await loadReviewSteps(state.selectedWorkpaperId, {force: true});
    renderWorkpapers();
    setStatus(action === 'approve' ? '本级复核已通过' : '底稿已退回整改');
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

async function initFromPrior() {
  const pid = activeProjectId();
  if (!pid) return setStatus('请先选择项目');
  try {
    const data = await request(`/api/projects/${pid}/init-from-prior`, {method: 'POST', body: JSON.stringify({copy_files: true})});
    state.workpaperTreeByProject[pid] = null;
    setStatus(`已引用 ${data.created_workpapers} 份底稿`);
    await refreshProjectScoped();
  } catch (err) { setStatus('错误：' + err.message); }
}

function openManualWorkpaperForm() {
  const pid = activeProjectId();
  if (!pid) return setStatus('请先选择项目');
  const form = $('workpaperForm');
  form?.reset();
  const node = selectedTreeNode();
  const stage = node?.type === 'stage' ? node.stage : node?.stage;
  if (form?.elements?.stage && stage) form.elements.stage.value = stage;
  openModal('workpaperModal');
}

function openSelectedWorkpaperFilePicker() {
  const pid = activeProjectId();
  if (!pid) return setStatus('请先选择项目');
  const node = selectedTreeNode();
  if (!node || !['workpaper', 'workpaper_placeholder'].includes(node.type)) {
    checkBasicWorkpapers();
    return setStatus('请在“基础底稿检查”中选择未上传底稿，再点击上传');
  }
  quickUploadTarget = {
    code: node.code,
    name: node.name || node.label || node.code,
    stage: node.stage || 'execution',
  };
  const input = $('quickWorkpaperFileInput');
  input.value = '';
  input.click();
}

async function uploadSelectedWorkpaperFile(event) {
  const file = event.target.files?.[0];
  const target = quickUploadTarget;
  const pid = activeProjectId();
  if (!file || !target || !pid) return;
  const uploadBody = new FormData();
  uploadBody.append('project_id', String(pid));
  uploadBody.append('code', target.code);
  uploadBody.append('name', target.name);
  uploadBody.append('stage', target.stage);
  uploadBody.append('file', file);
  setStatus(`正在上传 ${target.code} / ${file.name}`);
  try {
    const saved = await request('/api/workpapers/upload', {method: 'POST', body: uploadBody});
    state.workpaperTreeByProject[pid] = null;
    delete state.workpaperPreviews[saved.id];
    if (state.workpaperVersionsById) delete state.workpaperVersionsById[saved.id];
    state.selectedWorkpaperId = saved.id;
    state.selectedWorkpaperTreeNode = `workpaper-${saved.id}`;
    await refreshProjectScoped();
    setStatus(`${target.code} 已上传到 ${stageLabel(target.stage)}，当前为 V${saved.version_no || 1}`);
  } catch (err) {
    setStatus('错误：' + err.message);
  } finally {
    event.target.value = '';
    quickUploadTarget = null;
  }
}

function renderBasicWorkpaperCheck(data) {
  const content = $('basicWorkpaperCheckContent');
  if (!content) return;
  const scopeText = data.scope === 'mine' ? '仅统计我可操作的底稿' : '统计项目全部基础底稿';
  content.innerHTML = `
    <div class="summary-strip">
      <div class="summary-card"><span>基础底稿</span><strong>${esc(data.total || 0)}</strong></div>
      <div class="summary-card"><span>已上传</span><strong>${esc(data.uploaded || 0)}</strong></div>
      <div class="summary-card"><span>未上传</span><strong>${esc(data.missing || 0)}</strong></div>
    </div>
    <div class="subtle-note">${esc(scopeText)}。该清单不会在左侧文件树预先生成空白底稿节点。</div>
    <div class="table-wrap"><table><thead><tr><th>索引号</th><th>基础底稿</th><th>阶段</th><th>状态</th><th></th></tr></thead><tbody>
      ${(data.items || []).map(item => `<tr>
        <td>${esc(item.code)}</td><td>${esc(item.name)}</td><td>${esc(stageLabel(item.stage))}</td>
        <td>${tag(item.status === 'uploaded' ? '已上传' : '未上传', item.status === 'uploaded' ? 'state-done' : 'state-risk')}</td>
        <td>${item.status === 'missing' ? `<button type="button" class="secondary" data-basic-workpaper-upload="${esc(item.code)}" data-basic-workpaper-name="${esc(item.name)}" data-basic-workpaper-stage="${esc(item.stage)}">上传</button>` : ''}</td>
      </tr>`).join('') || '<tr><td colspan="5" class="muted">暂无基础底稿配置</td></tr>'}
    </tbody></table></div>
  `;
}

async function checkBasicWorkpapers() {
  const pid = activeProjectId();
  if (!pid) return setStatus('请先选择项目');
  $('basicWorkpaperCheckContent').innerHTML = '<div class="empty">正在检查基础底稿。</div>';
  openModal('basicWorkpaperCheckModal');
  try {
    const data = await request(`/api/projects/${pid}/basic-workpaper-check`);
    renderBasicWorkpaperCheck(data);
    setStatus(`基础底稿检查完成：已上传 ${data.uploaded || 0}，未上传 ${data.missing || 0}`);
  } catch (err) {
    $('basicWorkpaperCheckContent').innerHTML = `<div class="empty">检查失败：${esc(err.message)}</div>`;
    setStatus('错误：' + err.message);
  }
}

function openBatchWorkpaperFolderPicker() {
  const pid = activeProjectId();
  if (!pid) return setStatus('请先选择项目');
  const input = $('batchWorkpaperFolderInput');
  input.value = '';
  input.click();
}

async function uploadWorkpaperFolder(event) {
  const files = Array.from(event.target.files || []);
  const pid = activeProjectId();
  if (!pid || !files.length) return;
  const maxFileSize = 50 * 1024 * 1024;
  const largeFiles = files.filter(file => file.size > maxFileSize);
  if (largeFiles.length) {
    const list = largeFiles.slice(0, 8).map(file => `${file.webkitRelativePath || file.name}（${(file.size / 1024 / 1024).toFixed(1)}MB）`).join('\n');
    const suffix = largeFiles.length > 8 ? `\n另有 ${largeFiles.length - 8} 个超过 50MB 的文件。` : '';
    if (!window.confirm(`以下文件超过 50MB，导入可能需要较长时间：\n${list}${suffix}\n\n确认继续导入吗？`)) {
      event.target.value = '';
      return;
    }
  }
  const node = selectedTreeNode();
  const body = new FormData();
  body.append('project_id', String(pid));
  if (largeFiles.length) body.append('confirm_large_files', 'true');
  if (node?.type === 'workpaper' && node.workpaper_id) body.append('target_workpaper_id', String(node.workpaper_id));
  files.forEach(file => {
    body.append('files', file);
    body.append('relative_paths', file.webkitRelativePath || file.name);
  });
  setStatus(`正在导入文件夹：${files.length} 个文件`);
  try {
    const result = await request('/api/workpapers/batch-upload', {method: 'POST', body});
    state.workpaperTreeByProject[pid] = null;
    state.workpaperPreviews = {};
    if (state.workpaperVersionsById) state.workpaperVersionsById = {};
    await refreshProjectScoped();
    const skipped = result.skipped?.length || 0;
    setStatus(`文件夹已导入：底稿 ${result.workpapers_created + result.workpapers_updated} 份，资料 ${result.attachments_created} 份${skipped ? `，跳过 ${skipped} 份` : ''}`);
  } catch (err) {
    setStatus('错误：' + err.message);
  } finally {
    event.target.value = '';
  }
}

function uploadBasicWorkpaperFromCheck(button) {
  quickUploadTarget = {
    code: button.dataset.basicWorkpaperUpload,
    name: button.dataset.basicWorkpaperName,
    stage: button.dataset.basicWorkpaperStage || 'execution',
  };
  closeModal('basicWorkpaperCheckModal');
  const input = $('quickWorkpaperFileInput');
  input.value = '';
  input.click();
}

async function scanWorkpaperHeaders() {
  const pid = activeProjectId();
  if (!pid) return setStatus('请先选择项目');
  setStatus('正在扫描底稿表头');
  try {
    state.workpaperHeaderBatch = await request(`/api/projects/${pid}/workpaper-headers`);
    renderWorkpaperHeaderBatch();
    setStatus(`表头扫描完成：识别 ${state.workpaperHeaderBatch.field_count || 0} 个字段，待更新 ${state.workpaperHeaderBatch.needs_update_count || 0} 个`);
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

async function writeHeaderTestCopies() {
  const pid = activeProjectId();
  if (!pid) return setStatus('请先选择项目');
  setStatus('正在写入表头测试副本');
  try {
    state.workpaperHeaderBatch = await request(`/api/projects/${pid}/workpaper-headers/test-copy`, {method: 'POST', body: '{}'});
    renderWorkpaperHeaderBatch();
    setStatus(`表头测试副本已生成：${state.workpaperHeaderBatch.updated_count || 0} 份，错误 ${state.workpaperHeaderBatch.error_count || 0} 份`);
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

async function applyHeadersToRealWorkpapers() {
  const pid = activeProjectId();
  if (!pid) return setStatus('请先选择项目');
  const batch = state.workpaperHeaderBatch;
  const missing = Number(batch?.missing_target_count || 0);
  const needs = Number(batch?.needs_update_count || 0);
  const warning = [
    '确认真实写入当前项目底稿表头？',
    '系统会先备份原文件，再写入真实底稿。',
    missing ? `仍有 ${missing} 个字段缺少目标值，将跳过这些字段。` : '',
    needs ? `当前待更新字段 ${needs} 个。` : '当前没有字段值差异，但仍会统一可识别表头字体。',
  ].filter(Boolean).join('\n');
  if (!confirm(warning)) return;
  setStatus('正在真实写入底稿表头');
  try {
    const report = await request(`/api/projects/${pid}/workpaper-headers/apply`, {
      method: 'POST',
      body: JSON.stringify({confirm_real_write: true}),
    });
    state.workpaperPreviews = {};
    await refreshProjectScoped();
    state.workpaperHeaderBatch = report;
    renderWorkpaperHeaderBatch();
    setStatus(`真实写入完成：${report.updated_count || 0} 份，错误 ${report.error_count || 0} 份，已生成备份`);
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

export function bindWorkpapers(options) {
  refreshProjectScoped = options.refreshProjectScoped;

  $('openWorkpaperModalBtn').addEventListener('click', openSelectedWorkpaperFilePicker);
  $('openWorkpaperManualModalBtn')?.addEventListener('click', openManualWorkpaperForm);
  $('quickWorkpaperFileInput')?.addEventListener('change', uploadSelectedWorkpaperFile);
  $('batchWorkpaperFolderBtn')?.addEventListener('click', openBatchWorkpaperFolderPicker);
  $('batchWorkpaperFolderInput')?.addEventListener('change', uploadWorkpaperFolder);
  $('basicWorkpaperCheckBtn')?.addEventListener('click', checkBasicWorkpapers);
  $('basicWorkpaperCheckContent')?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-basic-workpaper-upload]');
    if (button) uploadBasicWorkpaperFromCheck(button);
  });
  $('initPriorBtn').addEventListener('click', initFromPrior);
  $('scanWorkpaperHeadersBtn')?.addEventListener('click', scanWorkpaperHeaders);
  $('testCopyHeadersBtn')?.addEventListener('click', writeHeaderTestCopies);
  $('applyHeadersBtn')?.addEventListener('click', applyHeadersToRealWorkpapers);
  $('downloadWorkpaperBtn')?.addEventListener('click', openSelectedWorkpaper);
  ['testCopyWorkpaperBtn', 'markWorkpaperStatusBtn'].forEach(id => {
    $(id)?.addEventListener('click', () => setStatus('该操作入口已预留；自动填写真实写回仍禁用，表头维护请使用本页扫描/测试副本/真实写入按钮。'));
  });
  $('workpaperHistoryBtn')?.addEventListener('click', async () => {
    if (!state.selectedWorkpaperId) return setStatus('请先选择底稿');
    await loadWorkpaperVersions(state.selectedWorkpaperId, {force: true});
    renderWorkpapers();
    $('workpaperVersionHistory')?.scrollIntoView({block: 'center'});
  });
  $('batchSubmitWorkpapersBtn')?.addEventListener('click', openBatchReviewSubmit);
  $('batchReviewSubmitForm')?.addEventListener('submit', submitSelectedWorkpapers);
  $('workpaperSelectAll')?.addEventListener('change', (event) => {
    const rows = state.workpapers.filter(workpaper => String(workpaper.status || '').toLowerCase() === 'draft');
    selectedWorkpaperIds = event.target.checked ? new Set(rows.map(workpaper => workpaper.id)) : new Set();
    renderWorkpapers();
  });
  $('workpaperRows').addEventListener('click', (event) => {
    const select = event.target.closest('[data-workpaper-select]');
    if (select) {
      const id = Number(select.dataset.workpaperSelect);
      if (select.checked) selectedWorkpaperIds.add(id); else selectedWorkpaperIds.delete(id);
      renderWorkpapers();
      return;
    }
    const button = event.target.closest('[data-workpaper-submit]');
    if (button) {
      submitWorkpaper(Number(button.dataset.workpaperSubmit));
      return;
    }
    const row = event.target.closest('[data-workpaper-row]');
    if (row) selectWorkpaper(Number(row.dataset.workpaperRow));
  });
  $('workpaperDetail')?.addEventListener('click', (event) => {
    const approve = event.target.closest('[data-review-step-approve]');
    if (approve) return decideReviewStep(Number(approve.dataset.reviewStepApprove), 'approve');
    const reject = event.target.closest('[data-review-step-reject]');
    if (reject) return decideReviewStep(Number(reject.dataset.reviewStepReject), 'reject');
  });
  $('workpaperTemplateTree').addEventListener('click', (event) => {
    const node = event.target.closest('[data-template-node]');
    if (node) workpaperTreeExtension.onTemplateNodeClick(node, event);
  });
  $('workpaperForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const pid = activeProjectId();
    if (!pid) return setStatus('请先选择项目');
    try {
      const form = e.target;
      const file = form.elements.file?.files?.[0];
      if (file) {
        const uploadBody = new FormData();
        uploadBody.append('project_id', String(pid));
        uploadBody.append('code', form.elements.code.value);
        uploadBody.append('name', form.elements.name.value);
        uploadBody.append('stage', form.elements.stage.value);
        if (form.elements.preparer_user_id.value) uploadBody.append('preparer_user_id', form.elements.preparer_user_id.value);
        uploadBody.append('file', file);
        await request('/api/workpapers/upload', {method: 'POST', body: uploadBody});
      } else {
        const data = formData(form);
        data.project_id = pid;
        data.extracted_fields = {};
        await request('/api/workpapers', {method: 'POST', body: JSON.stringify(data)});
      }
      state.workpaperTreeByProject[pid] = null;
      e.target.reset();
      closeModal('workpaperModal');
      await refreshProjectScoped();
    } catch (err) { setStatus('错误：' + err.message); }
  });

  window.submitWorkpaper = submitWorkpaper;
}
