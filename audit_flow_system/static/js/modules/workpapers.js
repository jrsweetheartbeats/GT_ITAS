import { request } from '../api.js?v=20260630a';
import { state } from '../state.js?v=20260630a';
import { $, activeProjectId, closeModal, esc, fillSelect, openModal, setStatus, statusClass, tag } from '../utils.js?v=20260816a';

export const workpaperTreeExtension = {
  onTemplateNodeClick(node, event) {
    selectTreeNode(node, event);
  }
};

export function openWorkpaperUploadModal(workpaperId = null) {
  const select = $('workpaperUploadTemplate');
  if (!select) return;
  const id = Number(workpaperId || state.selectedWorkpaperId || 0);
  if (id && !state.workpapers.some(row => Number(row.id) === id)) {
    setStatus('底稿列表正在加载，请稍后再试');
    return;
  }
  if (id) select.value = String(id);
  openModal('workpaperModal');
}

let refreshProjectScoped = async () => {};

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
          <strong>${esc(step.reviewer_role_code || `第${step.sequence_no}级复核`)}</strong>
          ${tag(step.status || 'waiting', reviewStepTone(step))}
          <small>已停留 ${esc(step.waiting_days || 0)} 天 / SLA ${esc(step.sla_days || 3)} 天</small>
          <span>${esc(step.due_date || '未维护截止日')}</span>
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
  return new Set(flattenTree(nodeChildren(stageNode)).filter(node => node.type === 'workpaper' && node.workpaper_id).map(node => node.workpaper_id));
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
    attachment_folder: '附件文件夹',
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
  const isAttachment = node.type === 'attachment';
  const isFolder = ['attachment_folder', 'attachment_sheet_folder'].includes(node.type);
  const path = node.file_path || '';
  const title = (isWorkpaper || isPlaceholder || isAttachment)
    ? `${node.code || node.index_no || ''} ${node.name || node.label || ''}\n${path || '未维护文件路径'}`
    : `${node.label || ''}，${count} 项`;
  const meta = isFolder
    ? `${count}个`
    : isAttachment
      ? (node.index_no || node.file_type || '附件')
      : isPlaceholder
        ? '未登记'
        : isWorkpaper
          ? (node.code || '未维护编号')
          : `${count}份`;
  const primary = isAttachment
    ? (node.name || fileNameFromPath(path) || node.label || '未命名附件')
    : isWorkpaper || isPlaceholder
      ? (node.name || fileNameFromPath(path) || node.label || node.code || '未命名底稿')
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
        ${isWorkpaper || isPlaceholder ? `<span class="status-dot ${statusDotClass(node.status)}"></span>` : ''}
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
  fillSelect($('workpaperUploadTemplate'), state.workpapers, w => `${w.code} ${w.name}`, false);
  renderWorkpaperTemplateTree();
  const selectedStage = stageFromTreeNode(state.selectedWorkpaperTreeNode);
  const selectedStageWorkpaperIds = workpaperIdsUnderStage(selectedStage);
  const rows = selectedStage
    ? state.workpapers.filter(w => selectedStageWorkpaperIds.has(w.id) || w.stage === selectedStage)
    : state.workpapers;
  $('workpaperRows').innerHTML = rows.map(w => `
    <tr class="selectable-row ${w.id === state.selectedWorkpaperId ? 'selected-row' : ''}" data-workpaper-row="${esc(w.id)}">
      <td>${esc(w.code)}</td>
      <td><strong>${esc(w.name)}</strong><div class="muted">${esc(compactPath(w.file_path || '') || '未维护文件路径')}</div></td>
      <td>${esc(stageLabel(w.stage))}</td>
      <td>${tag(w.status, statusClass(w.status))}</td>
      <td>${w.year_updated ? tag('已更新', 'green') : tag('待确认', 'amber')}</td>
      <td class="actions"><button type="button" data-workpaper-upload="${esc(w.id)}"><i class="ti ti-upload"></i> 上传</button><button class="secondary" data-workpaper-submit="${esc(w.id)}">标记完成</button></td>
    </tr>
  `).join('') || '<tr><td colspan="6" class="empty">暂无底稿</td></tr>';
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
    const relatedFindings = state.reviewFindings.filter(item => String(item.target || '').includes(selected.code || '') || String(item.target || '').includes(selected.name || ''));
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
        <div class="actions"><button type="button" data-workpaper-upload="${esc(selected.id)}"><i class="ti ti-upload"></i> 上传对应底稿</button></div>
        <div class="subtle-note">自动填写建议：请在“自动填写配置”页签查看字段级 dry-run 和测试副本验证状态。表头维护可在本页扫描后备份并真实写入。</div>
        ${renderReviewStepStrip(selected.id)}
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
      || node?.type === 'attachment_sheet_folder';
    state.selectedWorkpaperTreeNode = treeId;
    const workpaperId = Number(nodeEl.dataset.workpaperId || 0);
    state.selectedWorkpaperId = shouldToggle ? null : (workpaperId || null);
    if (shouldToggle && nodeChildren(node).length) toggleNode(node);
    if (state.selectedWorkpaperId) await Promise.all([loadWorkpaperPreview(state.selectedWorkpaperId), loadReviewSteps(state.selectedWorkpaperId)]);
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

async function selectWorkpaper(id) {
  state.selectedWorkpaperId = Number(id);
  const item = state.workpapers.find(row => row.id === state.selectedWorkpaperId);
  if (item) {
    const node = flattenTree(currentTree()).find(row => row.workpaper_id === item.id);
    state.selectedWorkpaperTreeNode = node?.id || state.selectedWorkpaperTreeNode;
  }
  renderWorkpapers();
  try {
    await Promise.all([loadWorkpaperPreview(id), loadReviewSteps(id)]);
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

  $('openWorkpaperModalBtn').addEventListener('click', () => openWorkpaperUploadModal());
  $('initPriorBtn').addEventListener('click', initFromPrior);
  $('scanWorkpaperHeadersBtn')?.addEventListener('click', scanWorkpaperHeaders);
  $('testCopyHeadersBtn')?.addEventListener('click', writeHeaderTestCopies);
  $('applyHeadersBtn')?.addEventListener('click', applyHeadersToRealWorkpapers);
  ['downloadWorkpaperBtn', 'testCopyWorkpaperBtn', 'markWorkpaperStatusBtn', 'workpaperHistoryBtn'].forEach(id => {
    $(id)?.addEventListener('click', () => setStatus('该操作入口已预留；自动填写真实写回仍禁用，表头维护请使用本页扫描/测试副本/真实写入按钮。'));
  });
  $('workpaperRows').addEventListener('click', (event) => {
    const uploadButton = event.target.closest('[data-workpaper-upload]');
    if (uploadButton) {
      openWorkpaperUploadModal(Number(uploadButton.dataset.workpaperUpload));
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
  $('workpaperTemplateTree').addEventListener('click', (event) => {
    const node = event.target.closest('[data-template-node]');
    if (node) workpaperTreeExtension.onTemplateNodeClick(node, event);
  });
  $('workpaperDetail').addEventListener('click', event => {
    const button = event.target.closest('[data-workpaper-upload]');
    if (button) openWorkpaperUploadModal(Number(button.dataset.workpaperUpload));
  });
  $('workpaperForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const pid = activeProjectId();
    if (!pid) return setStatus('请先选择项目');
    const workpaperId = Number(e.target.elements.workpaper_id.value || 0);
    if (!workpaperId) return setStatus('请选择对应底稿模板');
    const data = new FormData();
    data.append('file', e.target.elements.file.files[0]);
    try {
      await request(`/api/workpapers/${workpaperId}/upload`, {method: 'POST', body: data});
      state.workpaperTreeByProject[pid] = null;
      e.target.reset();
      closeModal('workpaperModal');
      await refreshProjectScoped();
      setStatus('底稿已直接上传并绑定模板');
    } catch (err) { setStatus('错误：' + err.message); }
  });

  window.submitWorkpaper = submitWorkpaper;
}
