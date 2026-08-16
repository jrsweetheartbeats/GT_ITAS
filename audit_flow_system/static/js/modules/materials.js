import { request } from '../api.js?v=20260630a';
import { state } from '../state.js?v=20260630a';
import { $, activeProjectId, closeModal, esc, fillSelect, formData, openModal, setStatus, statusClass, tag } from '../utils.js?v=20260816a';

let refreshProjectScoped = async () => {};
const collapsedAttachmentGroups = new Set();

const fileIconMap = {
  xlsx: 'ti-table',
  xls: 'ti-table',
  docx: 'ti-file-text',
  doc: 'ti-file-text',
  pdf: 'ti-file-type-pdf',
  png: 'ti-photo',
  jpg: 'ti-photo',
  jpeg: 'ti-photo',
  pptx: 'ti-presentation',
  ppt: 'ti-presentation',
  zip: 'ti-file-zip',
  rar: 'ti-file-zip',
  txt: 'ti-file-description',
};

function attachmentStatusLabel(status) {
  const value = String(status || 'active').toLowerCase();
  if (['active', 'uploaded', 'provided', 'received', 'completed', 'done', '已收到', '有效', '已完成'].includes(value)) return '已收到';
  if (['pending', 'requested', 'open', '待补充', '待上传'].includes(value)) return '待补充';
  if (['missing', 'failed', '缺失'].includes(value)) return '缺失';
  return status || '未维护';
}

function attachmentStatusTone(status) {
  const label = attachmentStatusLabel(status);
  if (label === '已收到') return 'green';
  if (label === '缺失') return 'red';
  if (label === '待补充') return 'amber';
  return statusClass(status);
}

function isReceivedAttachment(attachment) {
  return attachmentStatusLabel(attachment.status) === '已收到';
}

function attachmentFileType(attachment) {
  const file = String(attachment.file_path || attachment.title || '');
  const match = file.match(/\.([a-z0-9]+)$/i);
  return match ? match[1].toLowerCase() : 'file';
}

function attachmentFileIcon(attachment) {
  return fileIconMap[attachmentFileType(attachment)] || 'ti-file';
}

function flattenWorkpaperTree(nodes = []) {
  return nodes.flatMap(node => [node, ...flattenWorkpaperTree(node.children || [])]);
}

function treeWorkpaperInfo(workpaperId) {
  if (!workpaperId) return null;
  const pid = activeProjectId();
  const nodes = pid ? flattenWorkpaperTree(state.workpaperTreeByProject?.[pid] || []) : [];
  const node = nodes.find(item => item.workpaper_id && Number(item.workpaper_id) === Number(workpaperId));
  if (!node) return null;
  return {code: node.code || '', name: node.name || node.label || node.code || ''};
}

function fallbackWorkpaperCode(attachment) {
  if (attachment.referenced_in) return String(attachment.referenced_in).split(/[;,，、\s]+/).filter(Boolean)[0] || '';
  const index = String(attachment.index_no || '');
  const match = index.match(/^([A-Za-z]+\d+[A-Za-z]?(?:-\d+[A-Za-z]?){0,3})/);
  return match ? match[1] : '';
}

function attachmentWorkpaperInfo(attachment) {
  if (!attachment.workpaper_id) return {key: '__unlinked__', code: '', name: '未关联底稿'};
  const wp = (state.workpapers || []).find(row => Number(row.id) === Number(attachment.workpaper_id || 0));
  if (wp) return {key: `wp-${wp.id}`, code: wp.code || '', name: wp.name || wp.code || '未命名底稿'};
  const treeInfo = treeWorkpaperInfo(attachment.workpaper_id);
  if (treeInfo) return {key: `wp-${attachment.workpaper_id}`, code: treeInfo.code, name: treeInfo.name || treeInfo.code || `底稿 #${attachment.workpaper_id}`};
  const fallbackCode = fallbackWorkpaperCode(attachment);
  return {key: `wp-${attachment.workpaper_id}`, code: fallbackCode, name: fallbackCode || `底稿 #${attachment.workpaper_id}`};
}

function attachmentSearchText(attachment) {
  const wp = attachmentWorkpaperInfo(attachment);
  return [
    attachment.index_no,
    attachment.title,
    attachment.file_path,
    attachment.referenced_in,
    wp.code,
    wp.name,
    attachment.status,
  ].join(' ').toLowerCase();
}

function attachmentMatchesStatus(attachment, status) {
  if (!status || status === 'all') return true;
  if (status === 'received') return isReceivedAttachment(attachment);
  if (status === 'pending') return attachmentStatusLabel(attachment.status) === '待补充';
  if (status === 'missing') return attachmentStatusLabel(attachment.status) === '缺失';
  if (status === 'unlinked') return !attachment.workpaper_id;
  return String(attachment.status || '') === status;
}

function materialDueCell(item) {
  const due = item.due_date || '';
  const days = Number(item.overdue_days || 0);
  if (!due) return '<span class="muted">未维护</span>';
  if (item.is_overdue) return `<span class="tag red">逾期 ${esc(days)} 天</span><div class="muted">${esc(due)}</div>`;
  return `<span>${esc(due)}</span>`;
}

function filteredAttachments() {
  const workpaperId = $('attachmentWorkpaperFilter')?.value;
  const activeStatusButton = $('attStatusSeg')?.querySelector('.active');
  const status = activeStatusButton?.dataset.attFilter || $('attachmentStatusFilter')?.value || '';
  const keyword = String($('attachmentSearchInput')?.value || '').trim().toLowerCase();
  return (state.attachments || []).filter(attachment => {
    if (workpaperId && Number(attachment.workpaper_id || 0) !== Number(workpaperId)) return false;
    if (!attachmentMatchesStatus(attachment, status)) return false;
    if (keyword && !attachmentSearchText(attachment).includes(keyword)) return false;
    return true;
  });
}

function groupAttachments(rows) {
  const groups = new Map();
  rows.forEach(attachment => {
    const wp = attachmentWorkpaperInfo(attachment);
    if (!groups.has(wp.key)) groups.set(wp.key, {key: wp.key, code: wp.code, name: wp.name, items: []});
    groups.get(wp.key).items.push(attachment);
  });
  const linked = Array.from(groups.values()).filter(group => group.key !== '__unlinked__').sort((a, b) => {
    return String(a.code || a.name).localeCompare(String(b.code || b.name), 'zh-Hans-CN', {numeric: true});
  });
  const unlinked = groups.get('__unlinked__');
  return unlinked ? [...linked, unlinked] : linked;
}

function renderAttachmentSummary(rows = state.attachments || []) {
  const total = rows.length;
  const received = rows.filter(isReceivedAttachment).length;
  const pending = rows.filter(row => attachmentStatusLabel(row.status) === '待补充').length;
  const missing = rows.filter(row => attachmentStatusLabel(row.status) === '缺失').length;
  const unlinked = rows.filter(row => !row.workpaper_id).length;
  if ($('attTotal')) $('attTotal').textContent = total;
  if ($('attOk')) $('attOk').textContent = received;
  if ($('attWarn')) $('attWarn').textContent = pending + missing;
  if ($('attUnlinked')) $('attUnlinked').textContent = unlinked;
  const box = $('attachmentSummary');
  if (box) {
    box.innerHTML = `
      <div class="mini-stat"><span>附件总数</span><strong>${esc(total)}</strong></div>
      <div class="mini-stat"><span>已收到</span><strong>${esc(received)}</strong></div>
      <div class="mini-stat"><span>待补充</span><strong>${esc(pending)}</strong></div>
      <div class="mini-stat"><span>未关联底稿</span><strong>${esc(unlinked)}</strong></div>
    `;
  }
}

function renderAttachmentItem(attachment) {
  const wp = attachmentWorkpaperInfo(attachment);
  const subText = attachment.index_no ? `索引 ${attachment.index_no}` : '未生成索引号';
  const wpTag = attachment.workpaper_id
    ? `<span class="att-wp-tag">${esc(wp.code || wp.name || '已关联')}</span>`
    : '<span class="att-wp-tag none">未关联</span>';
  return `
    <div class="att-item">
      <i class="ti ${esc(attachmentFileIcon(attachment))} att-icon" aria-hidden="true"></i>
      <div class="att-main">
        <div class="att-name">${esc(attachment.title || '未命名附件')}</div>
        <div class="att-sub">${esc(subText)}${attachment.file_path ? ` / ${esc(attachment.file_path)}` : ''}</div>
      </div>
      <div>${wpTag}</div>
      <span class="att-badge ${esc(attachmentStatusTone(attachment.status))}">${esc(attachmentStatusLabel(attachment.status))}</span>
    </div>
  `;
}

function renderAttachmentGroup(group) {
  if (group.key === '__unlinked__') {
    return `
      <div class="att-ungrouped-note">
        <span>${esc(group.items.length)} 个附件尚未关联底稿</span>
        <button type="button" class="link-button" data-attachment-filter="unlinked">只看未关联</button>
      </div>
      <div class="att-item-list">${group.items.map(renderAttachmentItem).join('')}</div>
    `;
  }
  const received = group.items.filter(isReceivedAttachment).length;
  const collapsed = collapsedAttachmentGroups.has(group.key);
  return `
    <div class="att-group" data-attachment-group="${esc(group.key)}">
      <button type="button" class="att-group-hd" data-attachment-group-toggle="${esc(group.key)}">
        <span class="att-chev ${collapsed ? '' : 'open'}">›</span>
        <strong class="att-wp-name">${esc(group.name || group.code || '未命名底稿')}</strong>
        <span class="att-wp-code">${esc(group.code || '')}</span>
        <span class="att-wp-ok">${esc(received)}/${esc(group.items.length)}</span>
      </button>
      <div class="att-item-list ${collapsed ? 'hidden' : ''}">
        ${group.items.map(renderAttachmentItem).join('')}
      </div>
    </div>
  `;
}

export function renderMaterials() {
  fillSelect($('materialRequestSelect'), state.materials, m => `${m.control_code} ${m.title}`);
  $('materialRows').innerHTML = state.materials.map(m => `
    <tr class="${m.is_overdue ? 'timeliness-overdue-row' : ''}">
      <td>${esc(m.control_code || '')}</td>
      <td><strong>${esc(m.title || '')}</strong></td>
      <td>${esc(m.direction || '')}</td>
      <td>${tag(m.status, m.status === 'uploaded' ? 'green' : 'amber')}</td>
      <td>${materialDueCell(m)}</td>
      <td>${esc(m.file_path || '')}</td>
      <td class="actions">
        <button class="secondary" data-material-select="${esc(m.id)}">上传</button>
        <button class="secondary" data-material-due="${esc(m.id)}">改期</button>
      </td>
    </tr>
  `).join('') || '<tr><td colspan="7" class="empty">暂无资料清单</td></tr>';
}

export function renderAttachments() {
  renderAttachmentSummary();
  if ($('attachmentWorkpaperFilter')) {
    const current = $('attachmentWorkpaperFilter').value;
    fillSelect($('attachmentWorkpaperFilter'), state.workpapers, w => `${w.code} ${w.name}`);
    $('attachmentWorkpaperFilter').value = current;
  }
  const rows = filteredAttachments();
  const target = $('attGroupList') || $('attachmentRows');
  if (!target) return;
  if (state.projectScopedLoading && !(state.attachments || []).length) {
    target.innerHTML = '<div class="att-none">正在加载当前项目附件...</div>';
    return;
  }
  target.innerHTML = groupAttachments(rows).map(renderAttachmentGroup).join('') || '<div class="att-none">暂无符合条件的附件</div>';
}

export function renderScanRows(items) {
  $('attScanPanel')?.classList.remove('hidden');
  $('scanRows').innerHTML = items.map(item => `
    <tr class="${item.status === 'skipped' ? 'skipped-row' : ''}">
      <td>${esc(item.index_no || '')}</td>
      <td title="${esc(item.file_path || item.workpaper_path || '')}">${esc((item.file_path || item.workpaper_path || '').split('/').slice(-3).join('/'))}</td>
      <td>${esc(item.file_type || '')}</td>
      <td>${esc(item.workpaper_code || '')}</td>
      <td>${tag(item.status, item.status === 'skipped' || item.status === 'missing' ? 'amber' : item.status === 'error' ? 'red' : 'green')}</td>
      <td>${esc(item.message || '')}</td>
    </tr>
  `).join('') || '<tr><td colspan="6" class="empty">暂无扫描结果</td></tr>';
}

function selectMaterial(id) {
  $('materialRequestSelect').value = id;
  $('materialRequestPanel')?.classList.remove('hidden');
  window.activateAppSection?.('attachments');
}

async function scanAttachments(dryRun = true) {
  const pid = activeProjectId();
  if (!pid) return setStatus('请先选择项目');
  if (!dryRun && !confirm('确认将扫描结果登记为附件？已登记文件会跳过，新文件会自动生成附件索引号。')) return;
  try {
    setStatus(dryRun ? '扫描附件中' : '登记附件中');
    const data = await request(`/api/projects/${pid}/attachments/scan`, {
      method: 'POST',
      body: JSON.stringify({dry_run: dryRun})
    });
    $('scanSummary').textContent = `${dryRun ? '扫描预览' : '登记完成'}：发现 ${data.found} 个文件，新增 ${data.created} 个，跳过 ${data.skipped} 个。`;
    renderScanRows(data.items);
    setAttachmentPreviewMode(dryRun ? 'scan' : 'idle');
    if (!dryRun) await refreshProjectScoped();
    setStatus('就绪');
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

async function reconcileAttachmentReferences(dryRun = true) {
  const pid = activeProjectId();
  if (!pid) return setStatus('请先选择项目');
  if (!dryRun && !confirm('确认根据底稿中的附件索引引用更新附件台账？')) return;
  try {
    setStatus(dryRun ? '勾稽附件引用中' : '更新附件引用中');
    const data = await request(`/api/projects/${pid}/attachments/reconcile-references`, {
      method: 'POST',
      body: JSON.stringify({dry_run: dryRun})
    });
    $('scanSummary').textContent = `${dryRun ? '引用勾稽预览' : '引用更新完成'}：扫描 ${data.scanned_workpapers} 份底稿，匹配 ${data.matched_count} 条引用，更新 ${data.updated} 条，缺失 ${data.missing_count} 条。`;
    renderScanRows(data.items);
    setAttachmentPreviewMode(dryRun ? 'refs' : 'idle');
    if (!dryRun) await refreshProjectScoped();
    setStatus('就绪');
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

async function generateMaterials() {
  const pid = activeProjectId();
  if (!pid) return setStatus('请先选择项目');
  try {
    const data = await request(`/api/projects/${pid}/document-requests/generate`, {method: 'POST', body: '{}'});
    $('materialSummary').textContent = `已生成 ${data.created} 条新资料清单。`;
    $('materialRequestPanel')?.classList.remove('hidden');
    await refreshProjectScoped();
  } catch (err) { setStatus('错误：' + err.message); }
}

async function ensureMeetingMinutes() {
  const pid = activeProjectId();
  if (!pid) return setStatus('请先选择项目');
  try {
    const item = await request(`/api/projects/${pid}/document-requests/meeting-minutes`, {method: 'POST', body: '{}'});
    await refreshProjectScoped();
    $('materialRequestSelect').value = item.id;
    $('materialSummary').textContent = `${item.created ? '已新增' : '已定位'}访谈会议纪要资料项，可直接上传会议纪要文件或登记路径。`;
    $('materialRequestPanel')?.classList.remove('hidden');
    setStatus('访谈会议纪要资料项已就绪');
  } catch (err) { setStatus('错误：' + err.message); }
}

async function nextAttachmentIndex() {
  const pid = activeProjectId();
  if (!pid) return setStatus('请先选择项目');
  const wp = state.workpapers.find(w => String(w.id) === $('attachmentWorkpaper').value);
  const code = wp ? encodeURIComponent(wp.code) : '';
  const data = await request(`/api/attachments/next-index?projectId=${pid}&workpaperCode=${code}`);
  $('attachmentIndex').value = data.index_no;
  openModal('attachmentModal');
}

async function changeMaterialDueDate(id) {
  const item = state.materials.find(row => Number(row.id) === Number(id));
  const value = prompt('请输入新的截止日期（YYYY-MM-DD），留空则清空截止日期', item?.due_date || '');
  if (value === null) return;
  const dueDate = value.trim();
  if (dueDate && !/^\d{4}-\d{2}-\d{2}$/.test(dueDate)) return setStatus('截止日期格式应为 YYYY-MM-DD');
  try {
    await request(`/api/document-requests/${id}/due-date`, {
      method: 'PATCH',
      body: JSON.stringify({due_date: dueDate || null})
    });
    await refreshProjectScoped();
    setStatus('资料截止日期已更新');
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

function setAttachmentPreviewMode(mode = 'idle') {
  const importBtn = $('importAttachmentsBtn');
  const applyBtn = $('applyRefsBtn');
  if (importBtn) {
    importBtn.classList.toggle('hidden', mode !== 'scan');
    importBtn.disabled = mode !== 'scan';
  }
  if (applyBtn) {
    applyBtn.classList.toggle('hidden', mode !== 'refs');
    applyBtn.disabled = mode !== 'refs';
  }
}

export function bindMaterials(options) {
  refreshProjectScoped = options.refreshProjectScoped;

  $('openAttachmentModalBtn').addEventListener('click', () => openModal('attachmentModal'));
  $('nextIndexBtn').addEventListener('click', nextAttachmentIndex);
  $('scanAttachmentsBtn').addEventListener('click', () => scanAttachments(true));
  $('importAttachmentsBtn').addEventListener('click', () => scanAttachments(false));
  $('reconcileRefsBtn').addEventListener('click', () => reconcileAttachmentReferences(true));
  $('applyRefsBtn').addEventListener('click', () => reconcileAttachmentReferences(false));
  $('scanAttachmentsBarBtn')?.addEventListener('click', () => scanAttachments(true));
  $('focusMaterialUploadBtn')?.addEventListener('click', () => {
    $('materialRequestPanel')?.classList.remove('hidden');
    $('materialFiles')?.click();
  });
  $('collapseScanPanelBtn')?.addEventListener('click', () => $('attScanPanel')?.classList.add('hidden'));
  $('collapseMaterialPanelBtn')?.addEventListener('click', () => $('materialRequestPanel')?.classList.add('hidden'));
  $('attStatusSeg')?.addEventListener('click', event => {
    const button = event.target.closest('[data-att-filter]');
    if (!button) return;
    $('attStatusSeg').querySelectorAll('[data-att-filter]').forEach(item => item.classList.toggle('active', item === button));
    renderAttachments();
  });
  $('generateMaterialsBtn').addEventListener('click', generateMaterials);
  $('ensureMeetingMinutesBtn')?.addEventListener('click', ensureMeetingMinutes);
  ['attachmentWorkpaperFilter', 'attachmentStatusFilter', 'attachmentSearchInput'].forEach(id => {
    $(id)?.addEventListener('input', renderAttachments);
    $(id)?.addEventListener('change', renderAttachments);
  });
  $('materialRows').addEventListener('click', (event) => {
    const button = event.target.closest('[data-material-select]');
    const dueButton = event.target.closest('[data-material-due]');
    if (dueButton) {
      changeMaterialDueDate(Number(dueButton.dataset.materialDue));
      return;
    }
    if (button) selectMaterial(Number(button.dataset.materialSelect));
  });
  ($('attGroupList') || $('attachmentRows'))?.addEventListener('click', event => {
    const toggle = event.target.closest('[data-attachment-group-toggle]');
    if (toggle) {
      const key = toggle.dataset.attachmentGroupToggle;
      if (collapsedAttachmentGroups.has(key)) collapsedAttachmentGroups.delete(key);
      else collapsedAttachmentGroups.add(key);
      renderAttachments();
      return;
    }
    const filterButton = event.target.closest('[data-attachment-filter]');
    if (filterButton?.dataset.attachmentFilter === 'unlinked') {
      if ($('attachmentStatusFilter')) $('attachmentStatusFilter').value = 'unlinked';
      if ($('attStatusSeg')) {
        $('attStatusSeg').querySelectorAll('[data-att-filter]').forEach(item => item.classList.toggle('active', item.dataset.attFilter === 'unlinked'));
      }
      renderAttachments();
    }
  });
  setAttachmentPreviewMode('idle');
  $('attachmentForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const pid = activeProjectId();
    if (!pid) return setStatus('请先选择项目');
    const data = formData(e.target);
    data.project_id = pid;
    try {
      await request('/api/attachments', {method: 'POST', body: JSON.stringify(data)});
      e.target.reset();
      closeModal('attachmentModal');
      await refreshProjectScoped();
    } catch (err) { setStatus('错误：' + err.message); }
  });
  $('materialFiles')?.addEventListener('change', async () => {
    const files = $('materialFiles').files;
    if (!files.length) return;
    const requestId = $('materialRequestSelect')?.value;
    if (!requestId) {
      $('materialRequestPanel')?.classList.remove('hidden');
      setStatus('请先在资料清单中选择资料项，再上传文件');
      return;
    }
    try {
      const uploadBody = new FormData();
      Array.from(files).forEach(file => uploadBody.append('files', file));
      await request(`/api/document-requests/${requestId}/files`, {method: 'POST', body: uploadBody});
      $('materialFiles').value = '';
      await refreshProjectScoped();
      setStatus('文件上传完成');
    } catch (err) { setStatus('错误：' + err.message); }
  });
  $('materialUploadForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = formData(e.target);
    if (!data.request_id) return setStatus('请先选择资料项');
    const paths = String(data.file_paths || '').split(/\n+/).map(x => x.trim()).filter(Boolean);
    try {
      const files = $('materialFiles').files;
      if (files.length) {
        const uploadBody = new FormData();
        Array.from(files).forEach(file => uploadBody.append('files', file));
        await request(`/api/document-requests/${data.request_id}/files`, {method: 'POST', body: uploadBody});
      }
      if (paths.length) {
        await request(`/api/document-requests/${data.request_id}/upload`, {method: 'POST', body: JSON.stringify({file_paths: paths})});
      }
      if (!files.length && !paths.length) return setStatus('请选择文件或填写文件路径');
      e.target.reset();
      await refreshProjectScoped();
    } catch (err) { setStatus('错误：' + err.message); }
  });

  window.selectMaterial = selectMaterial;
}
