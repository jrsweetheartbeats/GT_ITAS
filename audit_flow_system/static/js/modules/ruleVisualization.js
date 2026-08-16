import { api, authHeaders, request } from '../api.js?v=20260630a';
import { state } from '../state.js?v=20260630a';
import { $, activeProjectId, esc, setStatus, tag } from '../utils.js?v=20260816a';

const STATUS_TONE = {
  passed: 'green',
  failed: 'red',
  skipped: 'amber',
  not_supported: 'amber',
  missing_locator: 'red',
  not_verified: 'blue',
  manual_correction_approved: 'green',
  manual_correction_conflict: 'red',
  rule: 'blue'
};
const PROJECT_MASTER_SOURCE = '项目主数据来源：B60-2-2 IT审计进场前通知表';

function tone(value) {
  return STATUS_TONE[value] || 'blue';
}

function statusLabel(value) {
  return {
    passed: '已验证',
    failed: '有冲突',
    skipped: '已跳过',
    not_supported: '暂不支持',
    missing_locator: '定位失败',
    not_verified: '待验证',
    manual_correction_approved: '已批准人工修正',
    manual_correction_conflict: '人工修正冲突',
    rule: '规则生成',
  }[value] || value || '待验证';
}

function shortText(value, limit = 140) {
  const text = String(value || '');
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

const LOCAL_ACTION_STORAGE_KEY = 'itas_rule_visualization_actions';
let localRuleActions = loadLocalRuleActions();
const ACTION_LABELS = {
  pending_confirm: '已标待确认',
  skipped: '团队暂跳过',
  resolved: '已处理',
  converted_to_manual_correction: '已转人工修正',
};

function loadLocalRuleActions() {
  try {
    return JSON.parse(localStorage.getItem(LOCAL_ACTION_STORAGE_KEY) || '{}') || {};
  } catch {
    return {};
  }
}

function saveLocalRuleActions() {
  localStorage.setItem(LOCAL_ACTION_STORAGE_KEY, JSON.stringify(localRuleActions));
}

function optionRows(rows, key, labelKey, current) {
  const seen = new Set();
  const out = ['<option value="">全部</option>'];
  rows.forEach(row => {
    const value = String(row[key] || '');
    if (!value || seen.has(value)) return;
    seen.add(value);
    const label = String(row[labelKey] || value);
    out.push(`<option value="${esc(value)}" ${current === value ? 'selected' : ''}>${esc(label)}</option>`);
  });
  return out.join('');
}

function renderSummary(data) {
  const summary = data?.summary || {};
  const verification = summary.verification_status || {};
  $('ruleVisualizationSummary').innerHTML = `
    <div class="mini-stat"><span>规则位置</span><strong>${esc(summary.row_count || 0)}</strong></div>
    <div class="mini-stat"><span>已验证</span><strong>${esc(verification.passed || 0)}</strong></div>
    <div class="mini-stat"><span>未验证</span><strong>${esc(verification.not_verified || 0)}</strong></div>
    <div class="mini-stat"><span>跳过</span><strong>${esc(verification.skipped || 0)}</strong></div>
    <div class="mini-stat"><span>人工修正</span><strong>${esc(summary.approved_manual_correction || 0)}</strong></div>
    <div class="mini-stat"><span>冲突</span><strong>${esc(summary.conflict_count || 0)}</strong></div>
  `;
  $('ruleVisualizationContext').textContent = data?.project_name
    ? `当前项目：${data.project_name}；本页仅展示 dry-run、人工修正和测试副本验证状态，不执行真实写回。`
    : '请选择项目后查看填写规则。';
}

function renderFilters(data) {
  const rows = data?.rows || [];
  $('ruleVisualizationCategoryFilter').innerHTML = optionRows(rows, 'category', 'category', $('ruleVisualizationCategoryFilter').value);
  $('ruleVisualizationWorkpaperFilter').innerHTML = optionRows(
    rows.map(row => ({workpaper_code: row.workpaper_code, label: `${row.workpaper_code || ''} ${row.workpaper_name || ''}`.trim()})),
    'workpaper_code',
    'label',
    $('ruleVisualizationWorkpaperFilter').value
  );
}

function filteredRows() {
  const rows = state.ruleVisualization?.rows || [];
  const category = $('ruleVisualizationCategoryFilter').value;
  const workpaper = $('ruleVisualizationWorkpaperFilter').value;
  const verification = $('ruleVisualizationStatusFilter').value;
  const source = $('ruleVisualizationSourceFilter').value;
  return rows.filter(row => {
    if (category && row.category !== category) return false;
    if (workpaper && row.workpaper_code !== workpaper) return false;
    if (verification && row.verification_status !== verification) return false;
    if (source && row.value_source !== source) return false;
    return true;
  });
}

function locatorText(row) {
  return [row.sheet, row.cell, row.locator, row.paragraph, row.table].filter(Boolean).join(' / ');
}

function targetText(row) {
  const parts = [row.cell, row.locator, row.paragraph, row.table].filter(Boolean);
  return Array.from(new Set(parts)).join(' / ');
}

function bClassFillRows(data) {
  return (data?.rows || [])
    .filter(row => {
      const category = String(row.category || '').toUpperCase();
      const code = String(row.workpaper_code || '').toUpperCase();
      return category === 'B' || code.startsWith('B');
    })
    .sort((left, right) => [
      left.workpaper_code || '',
      left.sheet || '',
      left.cell || left.locator || '',
      left.field || left.target_field || '',
    ].join('|').localeCompare([
      right.workpaper_code || '',
      right.sheet || '',
      right.cell || right.locator || '',
      right.field || right.target_field || '',
    ].join('|'), 'zh-Hans-CN'));
}

function sourceText(row) {
  const source = row.fill_source || '';
  if (source.includes('项目主数据')) {
    return source.replace('项目主数据', 'B60-2-2 IT审计进场前通知表');
  }
  return source;
}

function fillText(row) {
  return row.approved_value || row.suggested_value || row.original_rule_value || '';
}

function rowKey(row) {
  return [
    activeProjectId() || 'global',
    row.rule_id || '',
    row.workpaper_code || '',
    row.field || row.target_field || '',
    locatorText(row),
  ].join('|');
}

function rowNeedsAction(row) {
  return ['failed', 'missing_locator', 'not_supported', 'not_verified', 'skipped', 'blocked'].includes(row.verification_status || 'not_verified');
}

function localActionTag(row) {
  const serverStatus = row.action_status || row.action?.action_status || '';
  if (serverStatus) {
    const cls = serverStatus === 'skipped' ? 'amber' : serverStatus === 'resolved' ? 'green' : 'blue';
    return `<div>${tag(ACTION_LABELS[serverStatus] || serverStatus, cls)}</div>`;
  }
  const action = localRuleActions[rowKey(row)];
  if (!action) return '';
  const label = `${ACTION_LABELS[action.status] || '已处理'}（本地未同步）`;
  const cls = action.status === 'skipped' ? 'amber' : 'blue';
  return `<div>${tag(label, cls)}</div>`;
}

function correctionTemplate(row) {
  return [
    '规则编号\t底稿编号\t底稿名称\t字段名\t定位方式\t当前值\t建议值\t人工修正',
    [
      row.rule_id || '',
      row.workpaper_code || '',
      row.workpaper_name || '',
      row.field || row.target_field || '',
      locatorText(row),
      row.current_value || '',
      row.suggested_value || '',
      '',
    ].map(value => String(value).replace(/\t/g, ' ').replace(/\n/g, ' ')).join('\t'),
  ].join('\n');
}

function actionCell(row) {
  if (!rowNeedsAction(row)) return '<span class="muted">无需处理</span>';
  const key = esc(rowKey(row));
  return `
    <div class="row-action-stack">
      <button class="secondary" type="button" data-rule-viz-action="pending_confirm" data-rule-viz-key="${key}">待确认</button>
      <button class="secondary" type="button" data-rule-viz-action="skipped" data-rule-viz-key="${key}">暂跳过</button>
      <button class="secondary" type="button" data-rule-viz-action="copy_template" data-rule-viz-key="${key}">复制修正</button>
    </div>
  `;
}

function renderRows() {
  const rows = filteredRows();
  $('ruleVisualizationCount').textContent = `${rows.length} 条`;
  $('ruleVisualizationRows').innerHTML = rows.map(row => `
    <tr>
      <td>${esc(row.category || '')}</td>
      <td><strong>${esc(row.workpaper_code || '')}</strong><div class="muted">${esc(row.workpaper_name || '')}</div></td>
      <td><strong>${esc(row.rule_id || '')}</strong><div class="muted">${esc(shortText(row.rule_name || '', 80))}</div></td>
      <td>${esc(row.field || row.target_field || '')}</td>
      <td title="${esc(locatorText(row))}">${esc(shortText(locatorText(row), 120))}</td>
      <td>${esc(row.fill_source || '')}<div class="muted">${esc(shortText(row.match_logic || '', 100))}</div></td>
      <td title="${esc(row.current_value || '')}">${esc(shortText(row.current_value || '', 80))}</td>
      <td title="${esc(row.suggested_value || '')}">${esc(shortText(row.suggested_value || '', 100))}</td>
      <td>${tag(statusLabel(row.value_source || 'rule'), tone(row.value_source))}${row.manual_correction_status ? `<div>${tag(row.manual_correction_status === 'approved' ? '已批准' : row.manual_correction_status, row.manual_correction_status === 'approved' ? 'green' : 'amber')}</div>` : ''}</td>
      <td>${tag(statusLabel(row.verification_status || 'not_verified'), tone(row.verification_status))}${localActionTag(row)}<div class="muted">${esc(shortText(row.verification_message || '', 90))}</div></td>
      <td title="${esc(row.conflict_message || row.warning || '')}">${row.conflict_message || row.warning ? `<span class="conflict-icon">!</span> ${esc(shortText(row.conflict_message || row.warning || '', 120))}` : '<span class="muted">无</span>'}</td>
      <td title="${esc(row.manual_correction || '')}">${esc(shortText(row.manual_correction || '', 90))}</td>
      <td>${actionCell(row)}</td>
    </tr>
  `).join('') || '<tr><td colspan="13" class="empty">没有符合筛选条件的规则位置</td></tr>';
}

function renderBClassFillRows(data) {
  if (!$('ruleVisualizationBClassRows')) return;
  const rows = bClassFillRows(data);
  const workpapers = new Set(rows.map(row => row.workpaper_code).filter(Boolean));
  $('ruleVisualizationBClassSource').textContent = data?.project_name
    ? `${PROJECT_MASTER_SOURCE}；当前项目：${data.project_name}。`
    : `${PROJECT_MASTER_SOURCE}。请选择项目后查看 B 类底稿填充内容。`;
  $('ruleVisualizationBClassCount').textContent = `${rows.length} 个填充位置${workpapers.size ? ` / ${workpapers.size} 份底稿` : ''}`;
  $('ruleVisualizationBClassRows').innerHTML = rows.map(row => `
    <tr>
      <td><strong>${esc(row.workpaper_code || '')}</strong><div class="muted">${esc(row.workpaper_name || '')}</div></td>
      <td>${esc(row.sheet || '-')}</td>
      <td title="${esc(targetText(row))}">${esc(shortText(targetText(row) || '-', 120))}</td>
      <td>${esc(row.field || row.target_field || '-')}</td>
      <td title="${esc(fillText(row))}">${esc(shortText(fillText(row) || '待规则生成/人工确认', 160))}</td>
      <td>${esc(sourceText(row) || '规则生成')}<div class="muted">${esc(shortText(row.rule_id || row.rule_name || '', 90))}</div></td>
      <td>${tag(statusLabel(row.verification_status || 'not_verified'), tone(row.verification_status))}<div class="muted">${esc(shortText(row.verification_message || row.warning || '', 80))}</div></td>
    </tr>
  `).join('') || '<tr><td colspan="7" class="empty">当前项目暂无 B 类底稿填充规则。</td></tr>';
}

function renderEvidenceDetails(data) {
  const details = data?.evidence_rule_details || {};
  const blocks = ['C21-1', 'A27', 'B22A'].map(key => {
    const item = details[key] || {};
    if (key === 'B22A') {
      return `
        <div class="detail-card evidence-rule-card">
          <span>${esc(key)}</span><strong>${esc(item.status || '')}</strong>
          <div class="muted">${esc((item.warnings || []).join('；'))}</div>
          <div class="evidence-control-list">${(item.controls || []).map(control => `
            <div>${tag(control.control_code, control.judgment?.includes('模板无行') ? 'amber' : 'blue')} ${esc(control.judgment || '')}</div>
          `).join('')}</div>
        </div>
      `;
    }
    return `
      <div class="detail-card evidence-rule-card">
        <span>${esc(key)}</span><strong>${esc(item.status || '')}</strong>
        <div class="muted">${esc(item.source || '')}</div>
        <div>${esc(shortText(item.logic || '', 220))}</div>
      </div>
    `;
  }).join('');
  $('ruleVisualizationEvidence').innerHTML = blocks;
}

function failureAction(status) {
  return {
    failed: '查看冲突提示，确认采用规则值、人工修正或标记待确认。',
    missing_locator: '检查模板行、页签、单元格或段落定位；必要时补充人工修正。',
    not_supported: '暂按人工填写或测试副本验证处理，不要直接写真实底稿。',
    not_verified: '先运行测试副本验证或导出配置清单，确认后再推进。',
    skipped: '检查是否缺少证据、模板不适用或规则被采样跳过。',
    blocked: '先处理阻塞原因，再重新生成预览计划。',
  }[status] || '查看验证消息后人工判断下一步。';
}

function renderFailureActions(data) {
  if (!$('ruleVisualizationFailureActions')) return;
  const rows = data?.rows || [];
  const buckets = new Map();
  rows.forEach(row => {
    const status = row.verification_status || 'not_verified';
    if (!['failed', 'missing_locator', 'not_supported', 'not_verified', 'skipped', 'blocked'].includes(status)) return;
    if (!buckets.has(status)) buckets.set(status, []);
    buckets.get(status).push(row);
  });
  if (!buckets.size) {
    $('ruleVisualizationFailureActions').innerHTML = '<div class="empty">暂无需要处理的失败或待验证项</div>';
    return;
  }
  $('ruleVisualizationFailureActions').innerHTML = Array.from(buckets.entries()).map(([status, items]) => {
    const workpapers = Array.from(new Set(items.map(item => item.workpaper_code).filter(Boolean))).slice(0, 6);
    const sample = items.find(item => item.verification_message || item.conflict_message || item.warning) || items[0];
    return `
      <div class="failure-action-card">
        <div>${tag(statusLabel(status), tone(status))}<strong>${esc(items.length)} 项</strong></div>
        <p>${esc(failureAction(status))}</p>
        <span>影响底稿：${workpapers.length ? esc(workpapers.join('、')) : '未识别'}</span>
        <small>${esc(shortText(sample?.verification_message || sample?.conflict_message || sample?.warning || '暂无详细消息', 160))}</small>
      </div>
    `;
  }).join('');
}

export function renderRuleVisualization() {
  const data = state.ruleVisualization || {};
  renderSummary(data);
  renderFilters(data);
  renderBClassFillRows(data);
  renderRows();
  renderEvidenceDetails(data);
  renderFailureActions(data);
}

export async function loadRuleVisualization({silent = false} = {}) {
  const pid = activeProjectId();
  if (!pid) {
    state.ruleVisualization = {rows: [], summary: {}};
    renderRuleVisualization();
    return;
  }
  try {
    if (!silent) setStatus('填写规则加载中');
    state.ruleVisualization = await request(`/api/projects/${pid}/autofill-rule-visualization`);
    renderRuleVisualization();
    if (!silent) setStatus('就绪');
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

function filenameFromDisposition(disposition) {
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition || '');
  if (encoded?.[1]) return decodeURIComponent(encoded[1]);
  const plain = /filename="?([^"]+)"?/i.exec(disposition || '');
  return plain?.[1] || '底稿填写规则可视化.xlsx';
}

async function exportRuleVisualization() {
  const pid = activeProjectId();
  if (!pid) {
    setStatus('请先选择项目后再导出');
    return;
  }
  try {
    setStatus('正在导出填写规则');
    const res = await fetch(`${api}/api/projects/${pid}/autofill-rule-visualization/export`, {headers: authHeaders()});
    if (!res.ok) throw new Error(await res.text());
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filenameFromDisposition(res.headers.get('Content-Disposition'));
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setStatus('填写规则导出完成');
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

async function copyRuleCorrectionTemplate(row) {
  const text = correctionTemplate(row);
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    textarea.remove();
  }
  setStatus('已复制人工修正模板，可粘贴到修正导入表');
}

async function handleRuleRowAction(action, key) {
  const row = (state.ruleVisualization?.rows || []).find(item => rowKey(item) === key);
  if (!row) return setStatus('未找到该规则行，请刷新后重试');
  if (action === 'copy_template') {
    await copyRuleCorrectionTemplate(row);
    return;
  }
  const payload = {
    rule_id: row.rule_id || '',
    workpaper_code: row.workpaper_code || '',
    workpaper_name: row.workpaper_name || '',
    target_field: row.field || row.target_field || '',
    locator: locatorText(row),
    action_status: action,
    source_verification_status: row.verification_status || '',
    conflict_message: row.conflict_message || row.warning || '',
  };
  try {
    const result = await request(`/api/projects/${activeProjectId()}/autofill-rule-actions`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    row.action = result.action;
    row.action_status = result.action?.action_status || action;
    row.action_note = result.action?.action_note || '';
    row.action_updated_at = result.action?.updated_at || '';
    row.action_updated_by_user_id = result.action?.updated_by_user_id || null;
    delete localRuleActions[key];
    saveLocalRuleActions();
    renderRows();
    setStatus(action === 'pending_confirm' ? '已同步为团队待确认' : '已同步为团队暂跳过');
  } catch (err) {
    localRuleActions[key] = {
      status: action,
      updated_at: new Date().toISOString(),
      rule_id: row.rule_id || '',
      workpaper_code: row.workpaper_code || '',
      field: row.field || row.target_field || '',
      local_unsynced: true,
    };
    saveLocalRuleActions();
    renderRows();
    setStatus(`后端不可用，已本地标记但本地未同步：${err.message}`);
  }
}

export function bindRuleVisualization() {
  $('refreshRuleVisualizationBtn').addEventListener('click', () => loadRuleVisualization());
  $('exportRuleVisualizationBtn').addEventListener('click', exportRuleVisualization);
  ['ruleVisualizationCategoryFilter', 'ruleVisualizationWorkpaperFilter', 'ruleVisualizationStatusFilter', 'ruleVisualizationSourceFilter'].forEach(id => {
    $(id).addEventListener('change', renderRuleVisualization);
  });
  $('ruleVisualizationRows').addEventListener('click', async (event) => {
    const button = event.target.closest('[data-rule-viz-action]');
    if (!button) return;
    try {
      await handleRuleRowAction(button.dataset.ruleVizAction, button.dataset.ruleVizKey);
    } catch (err) {
      setStatus('错误：' + err.message);
    }
  });
}
