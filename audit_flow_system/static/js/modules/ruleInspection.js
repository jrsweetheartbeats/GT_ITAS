import { api, authHeaders, request } from '../api.js?v=20260920-state12';
import { state } from '../state.js?v=20260920-state12';
import { $, activeProjectId, esc, setStatus, tag } from '../utils.js?v=20260630a';

const STATUS_LABELS = {
  ready: '可用',
  missing_target: '缺目标',
  missing_locator: '缺定位',
  missing_evidence: '缺证据',
  conflict: '冲突',
  disabled: '停用',
  not_checked: '未检查'
};

const CORRECTION_STATUS_LABELS = {
  draft: '待确认',
  reviewed: '已复核',
  approved: '已批准',
  rejected: '已驳回',
  applied: '已应用'
};

const IMPORT_STATUS_LABELS = {
  pending: '等待中',
  running: '导入处理中',
  completed: '已完成',
  failed: '失败'
};

let importPollTimer = null;

function statusTone(status) {
  if (status === 'ready') return 'green';
  if (status === 'conflict' || status === 'missing_target') return 'red';
  if (status === 'missing_locator' || status === 'missing_evidence' || status === 'disabled') return 'amber';
  return 'blue';
}

function correctionStatusTone(status, conflict = '') {
  if (conflict) return 'red';
  if (status === 'approved' || status === 'applied') return 'green';
  if (status === 'rejected') return 'red';
  if (status === 'reviewed') return 'amber';
  return 'blue';
}

function importStatusTone(status) {
  if (status === 'completed') return 'green';
  if (status === 'failed') return 'red';
  if (status === 'running') return 'amber';
  return 'blue';
}

function shortText(value, limit = 120) {
  const text = String(value || '');
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

function formatDateTime(value) {
  if (!value) return '';
  return String(value).replace('T', ' ').slice(0, 19);
}

function optionRows(rows, valueKey, labelKey, currentValue) {
  const seen = new Set();
  const options = ['<option value="">全部</option>'];
  rows.forEach(row => {
    const value = String(row[valueKey] || '');
    if (!value || seen.has(value)) return;
    seen.add(value);
    const label = String(row[labelKey] || value);
    options.push(`<option value="${esc(value)}" ${currentValue === value ? 'selected' : ''}>${esc(label)}</option>`);
  });
  return options.join('');
}

function ruleChecks(rule) {
  return rule.validation?.checks || {};
}

function isDefinitionReady(rule) {
  const checks = ruleChecks(rule);
  return Boolean(
    checks.enabled !== false &&
    checks.has_target &&
    checks.has_locator &&
    checks.has_evidence &&
    checks.has_content_template
  );
}

function definitionSummary(rules) {
  return rules.reduce((acc, rule) => {
    const checks = ruleChecks(rule);
    if (isDefinitionReady(rule)) acc.ready += 1;
    if (checks.has_target === false) acc.missingTarget += 1;
    if (checks.has_locator === false) acc.missingLocator += 1;
    if (checks.has_evidence === false) acc.missingEvidenceConfig += 1;
    if (checks.has_content_template === false) acc.missingTemplate += 1;
    if (checks.enabled === false) acc.disabled += 1;
    return acc;
  }, {ready: 0, missingTarget: 0, missingLocator: 0, missingEvidenceConfig: 0, missingTemplate: 0, disabled: 0});
}

function projectEvidenceSummary(rules) {
  return rules.reduce((acc, rule) => {
    const validation = rule.project_validation || {};
    const missing = validation.missing_required_evidence || rule.missing_required_evidence || [];
    if (missing.length) acc.missingEvidence += 1;
    if (validation.matched_workpaper_count === 0 || rule.status === 'missing_target') acc.missingTarget += 1;
    if (rule.status === 'ready') acc.ready += 1;
    return acc;
  }, {ready: 0, missingEvidence: 0, missingTarget: 0});
}

function renderSummary(data) {
  const definition = data?.definition_summary || {};
  const project = data?.project_summary || {};
  const projectContext = data?.project_context || null;
  const attachmentCount = projectContext ? projectContext.attachment_count : null;
  const definitionGapCount = (definition.missing_target || 0) + (definition.missing_locator || 0) + (definition.missing_evidence || 0) + (definition.conflict || 0);
  const correctionSummary = data?.manual_corrections?.summary || {};
  $('ruleInspectionSummary').innerHTML = `
    <div class="mini-stat"><span>规则总数</span><strong>${esc(definition.total_rules || data?.summary?.total_rules || 0)}</strong></div>
    <div class="mini-stat"><span>定义可用</span><strong>${esc(definition.ready || 0)}</strong></div>
    <div class="mini-stat"><span>定义缺口</span><strong>${esc(definitionGapCount)}</strong></div>
    <div class="mini-stat"><span>项目附件</span><strong>${esc(attachmentCount === null ? '-' : attachmentCount)}</strong></div>
    <div class="mini-stat"><span>项目缺证据</span><strong>${esc(project.missing_evidence || 0)}</strong></div>
    <div class="mini-stat"><span>项目可执行</span><strong>${esc(project.ready || 0)}</strong></div>
    <div class="mini-stat"><span>人工修正</span><strong>${esc(correctionSummary.total || 0)}</strong></div>
  `;
  const activeProject = state.projects.find(item => item.id === activeProjectId());
  const mode = $('ruleInspectionMode').value;
  const noAttachmentNote = attachmentCount === 0
    ? ' 当前项目未登记附件/资料，因此证据匹配会显示缺失；这不代表规则定义全部错误。'
    : '';
  const context = projectContext
    ? `当前项目：${activeProject ? activeProject.name : `#${activeProjectId()}`}；已登记底稿 ${projectContext.workpaper_count} 份，附件 ${projectContext.attachment_count} 个。${noAttachmentNote}`
    : `规则库版本：${data?.version || '未标明'}；当前为全局规则定义检查，项目状态为未检查。`;
  $('ruleInspectionContext').textContent = mode === 'project' && !activeProjectId()
    ? '未选择项目，已显示全局规则定义检查。'
    : context;
}

function renderFilters(data) {
  const rules = data?.rules || [];
  const currentScope = $('ruleScopeFilter').value;
  const currentStage = $('ruleStageFilter').value;
  const currentWorkpaper = $('ruleWorkpaperFilter').value;
  $('ruleScopeFilter').innerHTML = optionRows(rules, 'scope', 'scope', currentScope);
  $('ruleStageFilter').innerHTML = optionRows(rules, 'stage', 'stage', currentStage);
  $('ruleWorkpaperFilter').innerHTML = optionRows(
    rules.map(rule => ({
      workpaper_code: rule.workpaper_code,
      workpaper_label: `${rule.workpaper_code || ''} ${rule.workpaper_name || ''}`.trim()
    })),
    'workpaper_code',
    'workpaper_label',
    currentWorkpaper
  );
}

function currentStatusLayer() {
  return $('ruleStatusLayer')?.value || 'project_status';
}

function filteredRules() {
  const data = state.ruleInspection || {};
  const status = $('ruleStatusFilter').value;
  const statusLayer = currentStatusLayer();
  const scope = $('ruleScopeFilter').value;
  const stage = $('ruleStageFilter').value;
  const workpaper = $('ruleWorkpaperFilter').value;
  return (data.rules || []).filter(rule => {
    if (status && (rule[statusLayer] || rule.status) !== status) return false;
    if (scope && rule.scope !== scope) return false;
    if (stage && rule.stage !== stage) return false;
    if (workpaper && rule.workpaper_code !== workpaper) return false;
    return true;
  });
}

function targetSummary(rule) {
  return (rule.targets || [])
    .map(target => target.target_field || target.field || '')
    .filter(Boolean)
    .join('、');
}

function locatorSummary(rule) {
  return (rule.targets || [])
    .map(target => target.locator_display || target.locator || target.target_cell || '')
    .filter(Boolean)
    .join('、');
}

function renderGapSummary(data) {
  const definition = data?.definition_summary || {};
  const project = data?.project_summary || {};
  const attachmentCount = data?.project_context?.attachment_count;
  $('ruleGapSummary').innerHTML = `
    <div><strong>规则定义状态</strong></div>
    <div>定义可用：${esc(definition.ready || 0)}</div>
    <div>缺 target：${esc(definition.missing_target || 0)}</div>
    <div>缺 locator：${esc(definition.missing_locator || 0)}</div>
    <div>缺 evidence 配置：${esc(definition.missing_evidence || 0)}</div>
    <div style="margin-top:8px"><strong>项目证据状态</strong></div>
    <div>当前附件：${esc(attachmentCount ?? '-')}</div>
    <div>项目可执行：${esc(project.ready || 0)}</div>
    <div>项目缺证据：${esc(project.missing_evidence || 0)}</div>
    <div>项目未匹配底稿：${esc(project.missing_target || 0)}</div>
    ${attachmentCount === 0 ? '<div class="subtle-note" style="margin-top:8px">当前项目未登记附件/资料，项目缺证据主要来自项目证据缺失，不代表规则定义全部错误。</div>' : ''}
  `;
}

function coverageTone(row) {
  if (row.coverage_status === 'covered' || row.coverage_status === 'writable') return 'green';
  if (row.coverage_status === 'writable_with_gap' || row.coverage_status === 'missing_rule_priority') return 'amber';
  return row.covered ? 'blue' : 'red';
}

function coverageRows(data) {
  const matrix = data?.coverage_matrix || {};
  return [...(matrix.B || []), ...(matrix.C || []), ...(matrix.A || [])];
}

function renderCoverageMatrix(data) {
  const rows = coverageRows(data);
  const tbody = $('ruleCoverageMatrix');
  if (!tbody) return;
  tbody.innerHTML = rows.map(row => `
    <tr>
      <td>${esc(row.class || '')}</td>
      <td><strong>${esc(row.workpaper_code || '')}</strong><div class="muted">${esc(row.workpaper_name || '')}</div></td>
      <td>${esc(row.rule_count || 0)}</td>
      <td>${tag(row.definition_ready ? 'ready' : row.covered ? '需补定义' : '缺规则', row.definition_ready ? 'green' : row.covered ? 'amber' : 'red')}</td>
      <td>${row.project_present === null ? tag('not_checked', 'blue') : tag(row.project_ready ? 'ready' : row.project_present ? '待证据' : '缺底稿', row.project_ready ? 'green' : 'amber')}</td>
      <td>${tag(row.write_level || row.coverage_status || '', coverageTone(row))}</td>
      <td>${esc(row.note || '')}</td>
    </tr>
  `).join('') || '<tr><td colspan="7" class="empty">暂无覆盖矩阵</td></tr>';
}

function renderTemplateScan(data) {
  const scan = data?.template_scan;
  const summaryEl = $('templateRuleSummary');
  const tbody = $('templateRuleMatrix');
  if (!summaryEl || !tbody) return;
  if (!scan) {
    summaryEl.textContent = '全局模式不扫描项目底稿模板';
    tbody.innerHTML = '<tr><td colspan="6" class="empty">请选择项目模式后扫描项目底稿模板</td></tr>';
    return;
  }
  const summary = scan.summary || {};
  summaryEl.textContent = `已扫描 ${summary.scanned_workpaper_count || 0}/${summary.workpaper_count || 0} 份，候选 ${summary.candidate_rule_count || 0} 条`;
  const rows = (scan.by_code || []).slice().sort((a, b) => String(a.code || '').localeCompare(String(b.code || '')));
  tbody.innerHTML = rows.map(row => `
    <tr>
      <td><strong>${esc(row.code || '')}</strong><div class="muted">${esc(row.name || '')}</div></td>
      <td>${esc(row.field_count || 0)}</td>
      <td>${esc(row.table_count || 0)}</td>
      <td>${esc(row.procedure_count || 0)}</td>
      <td>${esc(row.candidate_rule_count || 0)}</td>
      <td>${row.errors?.length ? tag('需检查', 'amber') : tag('已识别', 'green')}</td>
    </tr>
  `).join('') || '<tr><td colspan="6" class="empty">暂无模板识别结果</td></tr>';
}

function renderManualCorrections(data) {
  const box = $('ruleCorrectionRows');
  const summaryEl = $('ruleCorrectionSummary');
  if (!box || !summaryEl) return;
  const manual = data?.manual_corrections || {};
  const summary = manual.summary || {};
  const rows = [...(manual.groups?.formal || []), ...(manual.groups?.candidate || [])];
  summaryEl.textContent = `共 ${summary.total || 0} 条；正式 ${summary.formal || 0}，候选 ${summary.candidate || 0}，冲突 ${summary.conflict || 0}`;
  box.innerHTML = rows.slice(0, 80).map(item => `
    <tr>
      <td>${tag(item.rule_kind === 'formal' ? '正式规则' : '候选规则', item.rule_kind === 'formal' ? 'blue' : 'amber')}</td>
      <td><strong>${esc(item.workpaper_code || '')}</strong><div class="muted">${esc(item.workpaper_name || '')}</div></td>
      <td>${esc(item.target_field || item.rule_id || '')}<div class="muted">${esc(shortText(item.locator || item.sheet_or_section || '', 90))}</div></td>
      <td title="${esc(item.manual_correction || '')}">${esc(shortText(item.manual_correction || '', 120))}</td>
      <td>${tag(CORRECTION_STATUS_LABELS[item.status] || item.status || '待确认', correctionStatusTone(item.status, item.conflict_message))}</td>
      <td>${esc(shortText(item.conflict_message || '无', 120))}</td>
      <td>${renderCorrectionActions(item)}</td>
    </tr>
  `).join('') || '<tr><td colspan="7" class="empty">暂无人工修正 overlay。可先导出规则，在“人工修正”列填写后导入。</td></tr>';
}

function renderCorrectionActions(item) {
  if (!state.me?.is_admin) return '';
  if (item.status === 'approved') return '<span class="muted">已批准</span>';
  if (item.status === 'rejected') return '<span class="muted">已驳回</span>';
  return `
    <span class="actions">
      <button class="secondary" type="button" data-correction-action="approve" data-correction-id="${esc(item.id)}">批准</button>
      <button class="danger" type="button" data-correction-action="reject" data-correction-id="${esc(item.id)}">驳回</button>
    </span>
  `;
}

function renderImportBatches() {
  const rowsEl = $('ruleImportRows');
  const summaryEl = $('ruleImportSummary');
  if (!rowsEl || !summaryEl) return;
  const rows = state.ruleCorrectionImports || [];
  const active = rows.find(item => ['pending', 'running'].includes(item.status));
  summaryEl.textContent = active
    ? `导入处理中：${active.processed_rows || 0}/${active.total_rows || 0}`
    : rows.length ? `最近 ${rows.length} 个批次` : '暂无批次';
  rowsEl.innerHTML = rows.map(item => `
    <tr>
      <td title="${esc(item.filename || '')}">${esc(shortText(item.filename || '', 80))}</td>
      <td>${tag(IMPORT_STATUS_LABELS[item.status] || item.status || '', importStatusTone(item.status))}</td>
      <td>${esc(item.processed_rows || 0)} / ${esc(item.total_rows || 0)}</td>
      <td>${esc(item.created_count || 0)}</td>
      <td>${esc(item.updated_count || 0)}</td>
      <td>${esc(item.conflict_count || 0)}</td>
      <td>${esc(item.error_count || 0)}${item.error_message ? `<div class="muted">${esc(shortText(item.error_message, 80))}</div>` : ''}</td>
      <td>${esc(formatDateTime(item.created_at))}<div class="muted">${esc(formatDateTime(item.completed_at))}</div></td>
    </tr>
  `).join('') || '<tr><td colspan="8" class="empty">暂无导入批次</td></tr>';
}

function selectVisibleRule(rows) {
  if (!rows.length) {
    state.selectedRuleInspectionId = null;
    return null;
  }
  const selected = rows.find(rule => rule.rule_id === state.selectedRuleInspectionId);
  if (selected) return selected;
  state.selectedRuleInspectionId = rows[0].rule_id;
  return rows[0];
}

function renderRuleRows() {
  const rows = filteredRules();
  const selected = selectVisibleRule(rows);
  $('ruleListCount').textContent = `${rows.length} 条`;
  $('ruleInspectionRows').innerHTML = rows.map(rule => `
    <tr class="selectable-row ${rule.rule_id === state.selectedRuleInspectionId ? 'selected-row' : ''}" data-rule-inspection-id="${esc(rule.rule_id)}">
      <td><strong>${esc(rule.rule_id)}</strong><div class="muted">${esc(rule.name || '')}</div></td>
      <td>${esc(rule.workpaper_code || '')}<div class="muted">${esc(rule.workpaper_name || rule.workpaper || '')}</div></td>
      <td>${esc(rule.stage || '')}<div class="muted">${esc(rule.sheet || rule.section || '')}</div></td>
      <td title="${esc(targetSummary(rule))}">${esc(shortText(targetSummary(rule), 90))}</td>
      <td title="${esc(locatorSummary(rule))}">${esc(shortText(locatorSummary(rule), 90))}</td>
      <td>${tag(STATUS_LABELS[rule.definition_status] || rule.definition_status, statusTone(rule.definition_status))}</td>
      <td>${tag(STATUS_LABELS[rule.project_status] || rule.project_status, statusTone(rule.project_status))}</td>
    </tr>
  `).join('') || '<tr><td colspan="7" class="empty">没有符合筛选条件的规则</td></tr>';
  renderRuleDetail(selected);
}

function listBlock(items) {
  if (!items || !items.length) return '<div class="muted">无</div>';
  return `<ul class="rule-detail-list">${items.map(item => `<li>${esc(item)}</li>`).join('')}</ul>`;
}

function evidenceBlock(rule) {
  const requirements = rule.evidence_requirements || [];
  if (!requirements.length) return '<div class="muted">未配置证据来源</div>';
  return requirements.map(item => `
    <div class="rule-evidence-line">
      ${tag(item.required ? '必需' : '可选', item.required ? 'amber' : 'blue')}
      <strong>${esc(item.name || '未命名证据')}</strong>
      <div class="muted">${esc((item.any_keywords || []).join('、') || '未配置关键词')}</div>
    </div>
  `).join('');
}

function projectEvidenceBlock(rule) {
  const matches = rule.evidence_matches || [];
  if (!matches.length) return '<div class="muted">当前为全局规则检查，未结合项目附件。</div>';
  return matches.map(item => `
    <div class="rule-evidence-line">
      ${tag(item.matched ? '已匹配' : '未匹配', item.matched ? 'green' : item.required ? 'red' : 'amber')}
      <strong>${esc(item.name || '')}</strong>
      <div class="muted">${esc(item.attachment_count || 0)} 个附件：${esc((item.attachments || []).map(att => att.index_no || att.title || att.file_path).filter(Boolean).join('、') || '无')}</div>
    </div>
  `).join('');
}

function targetTable(rule) {
  const rows = rule.targets || [];
  if (!rows.length) return '<div class="muted">未配置填写目标</div>';
  return `
    <div class="table-wrap rule-detail-table">
      <table>
        <thead><tr><th>目标字段</th><th>单元格</th><th>定位方式</th><th>locator / 表头 / 标签</th><th>状态</th></tr></thead>
        <tbody>
          ${rows.map(target => `
            <tr>
              <td>${esc(target.target_field || target.field || '')}</td>
              <td>${esc(target.target_cell || target.cell || '')}</td>
              <td>${esc(target.locator_method || '')}</td>
              <td>${esc(target.locator_display || target.locator || '')}</td>
              <td>${tag(target.status || rule.status, statusTone(target.status || rule.status))}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function matchedWorkpapers(rule) {
  const rows = rule.matched_workpapers || [];
  if (!rows.length) return '<div class="muted">未结合项目，或当前项目未匹配到底稿。</div>';
  return rows.map(item => `
    <div class="rule-evidence-line">
      <strong>${esc(item.code || '')} ${esc(item.name || '')}</strong>
      <div class="muted">${esc(item.stage || '')} ${esc(item.file_path || '')}</div>
    </div>
  `).join('');
}

function templateCandidates(rule) {
  const code = rule?.workpaper_code || '';
  const scan = state.ruleInspection?.template_scan;
  if (!code || !scan) return '<div class="muted">当前模式未提供模板识别结果。</div>';
  const workpapers = (scan.workpapers || []).filter(item => item.code === code);
  if (!workpapers.length) return '<div class="muted">未扫描到该底稿模板。</div>';
  const candidates = workpapers.flatMap(item => (item.candidate_rules || []).map(candidate => ({...candidate, source_workpaper: `${item.code} ${item.name}`})));
  if (!candidates.length) return '<div class="muted">该底稿未识别出候选填写规则。</div>';
  return `
    <div class="table-wrap rule-detail-table">
      <table>
        <thead><tr><th>类型</th><th>标签/程序</th><th>位置</th><th>写入方式</th><th>来源推断</th><th>置信度</th></tr></thead>
        <tbody>
          ${candidates.slice(0, 40).map(item => `
            <tr>
              <td>${esc(item.rule_type || '')}</td>
              <td title="${esc(item.procedure_text || item.label || '')}">${esc(shortText(item.label || item.procedure_text || '', 80))}</td>
              <td>${esc(item.location || '')}</td>
              <td>${esc(item.write_mode || '')}</td>
              <td>${esc(item.source_guess || '')}</td>
              <td>${tag(item.manual_correction_status ? `修正 ${item.manual_correction_status}` : item.confidence || '', item.manual_correction_conflict ? 'red' : item.manual_correction_status ? 'blue' : item.confidence === 'high' ? 'green' : item.confidence === 'medium' ? 'amber' : 'blue')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
    ${candidates.length > 40 ? `<div class="muted">仅显示前 40 条候选规则，共 ${esc(candidates.length)} 条。</div>` : ''}
  `;
}

function manualCorrectionBlock(rule) {
  const rows = rule.manual_corrections || [];
  if (!rows.length) return '<div class="muted">无人工修正 overlay</div>';
  return `
    <div class="table-wrap rule-detail-table">
      <table>
        <thead><tr><th>目标字段</th><th>定位</th><th>人工修正</th><th>状态</th><th>冲突提示</th></tr></thead>
        <tbody>
          ${rows.map(item => `
            <tr>
              <td>${esc(item.target_field || '')}</td>
              <td>${esc(shortText(item.locator || item.sheet_or_section || '', 90))}</td>
              <td>${esc(item.manual_correction || '')}</td>
              <td>${tag(item.status || 'draft', item.conflict_message ? 'red' : 'blue')}</td>
              <td>${esc(item.conflict_message || '无')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function renderRuleDetail(rule) {
  if (!rule) {
    $('ruleInspectionDetail').innerHTML = '<div class="empty">请选择一条规则</div>';
    return;
  }
  const definitionStatus = rule.definition_status || (isDefinitionReady(rule) ? 'ready' : rule.status);
  const projectStatus = rule.project_status || rule.project_validation?.status || rule.status;
  $('ruleInspectionDetail').innerHTML = `
    <div class="rule-detail-title">
      <div>
        <h3>${esc(rule.rule_id)} / ${esc(rule.name || '')}</h3>
        <div class="muted">${esc(rule.workpaper_code || '')} ${esc(rule.workpaper_name || '')}</div>
      </div>
      <div class="actions">${tag(`定义 ${definitionStatus}`, statusTone(definitionStatus))}${tag(`项目 ${projectStatus}`, statusTone(projectStatus))}</div>
    </div>
    <div class="detail-grid">
      <div class="detail-card"><span>适用底稿</span><strong>${esc(rule.workpaper_code || '')}</strong><div class="muted">${esc(rule.workpaper_name || '')}</div></div>
      <div class="detail-card"><span>阶段</span><strong>${esc(rule.stage || '')}</strong><div class="muted">${esc(rule.scope || '')}</div></div>
      <div class="detail-card"><span>sheet / 章节</span><strong>${esc(rule.sheet || rule.section || '')}</strong></div>
      <div class="detail-card"><span>填充来源</span><strong>${esc(rule.source_type || '')}</strong></div>
      <div class="detail-card"><span>证据类型</span><strong>${esc((rule.evidence_requirements || []).map(item => item.evidence_type).filter(Boolean).join('、') || '未配置')}</strong></div>
      <div class="detail-card"><span>规则定义状态</span><strong>${esc(definitionStatus)}</strong><div class="muted">项目状态：${esc(projectStatus)}</div></div>
    </div>
    <div class="rule-detail-section">
      <h3>人工修正 overlay</h3>
      ${manualCorrectionBlock(rule)}
    </div>
    <div class="rule-detail-section">
      <h3>填写目标</h3>
      ${targetTable(rule)}
    </div>
    <div class="rule-detail-section">
      <h3>定位逻辑</h3>
      <div>${esc(rule.locator || '未配置 locator')}</div>
      <div class="muted">${esc((rule.targets || []).map(target => target.write_mode ? `${target.target_field}: ${target.write_mode}` : '').filter(Boolean).join('；'))}</div>
    </div>
    <div class="rule-detail-section">
      <h3>来源证据</h3>
      ${evidenceBlock(rule)}
    </div>
    <div class="rule-detail-section">
      <h3>内容生成模板</h3>
      <div class="rule-template-text">${esc(rule.content_template || '未配置模板')}</div>
    </div>
    <div class="rule-detail-section">
      <h3>匹配逻辑</h3>
      <div>${esc(rule.matching_logic || '')}</div>
    </div>
    <div class="rule-detail-section">
      <h3>写入前校验</h3>
      ${listBlock(rule.validation?.pre_write || [])}
    </div>
    <div class="rule-detail-section">
      <h3>写入后验证</h3>
      ${listBlock(rule.validation?.post_write || [])}
    </div>
    <div class="rule-detail-section">
      <h3>定义缺口</h3>
      ${listBlock(rule.definition_gaps || [])}
    </div>
    <div class="rule-detail-section">
      <h3>项目缺口</h3>
      ${listBlock(rule.project_gaps || [])}
    </div>
    <div class="rule-detail-section">
      <h3>项目级匹配结果</h3>
      ${matchedWorkpapers(rule)}
      <div class="rule-project-evidence">${projectEvidenceBlock(rule)}</div>
    </div>
    <div class="rule-detail-section">
      <h3>模板识别候选规则</h3>
      ${templateCandidates(rule)}
    </div>
  `;
}

function filenameFromDisposition(disposition) {
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition || '');
  if (encoded?.[1]) return decodeURIComponent(encoded[1]);
  const plain = /filename="?([^"]+)"?/i.exec(disposition || '');
  return plain?.[1] || '底稿填写规则.xlsx';
}

async function exportRuleInspection() {
  const mode = $('ruleInspectionMode')?.value || 'project';
  const pid = activeProjectId();
  if (mode !== 'project' || !pid) {
    setStatus('请先选择项目后再导出规则');
    return;
  }
  try {
    setStatus('正在导出底稿规则');
    const res = await fetch(`${api}/api/projects/${pid}/autofill-rule-inspection/export`, {
      headers: authHeaders()
    });
    if (!res.ok) {
      let detail = await res.text();
      try { detail = JSON.parse(detail).detail || detail; } catch {}
      throw new Error(detail || '导出失败');
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filenameFromDisposition(res.headers.get('Content-Disposition'));
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setStatus('规则导出完成');
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

async function loadCorrectionImports() {
  const mode = $('ruleInspectionMode')?.value || 'project';
  const pid = activeProjectId();
  if (mode !== 'project' || !pid) {
    state.ruleCorrectionImports = [];
    renderImportBatches();
    return [];
  }
  const data = await request(`/api/projects/${pid}/autofill-rule-inspection/imports`);
  state.ruleCorrectionImports = data.imports || [];
  renderImportBatches();
  return state.ruleCorrectionImports;
}

function stopImportPolling() {
  if (importPollTimer) {
    clearTimeout(importPollTimer);
    importPollTimer = null;
  }
}

async function pollImportBatch(batchId) {
  stopImportPolling();
  const pid = activeProjectId();
  if (!pid || !batchId) return;
  try {
    const batch = await request(`/api/projects/${pid}/autofill-rule-inspection/imports/${batchId}`);
    state.ruleCorrectionImports = [
      batch,
      ...(state.ruleCorrectionImports || []).filter(item => item.id !== batch.id)
    ].slice(0, 20);
    renderImportBatches();
    if (batch.status === 'completed') {
      setStatus(`人工修正导入完成：新增 ${batch.created_count || 0}，更新 ${batch.updated_count || 0}，冲突 ${batch.conflict_count || 0}，错误 ${batch.error_count || 0}`);
      await loadCorrectionImports();
      await loadRuleInspection({silent: true});
      return;
    }
    if (batch.status === 'failed') {
      setStatus(`人工修正导入失败：${batch.error_message || '后台任务异常'}`);
      await loadCorrectionImports();
      return;
    }
    setStatus(`人工修正导入处理中：${batch.processed_rows || 0}/${batch.total_rows || 0}`);
    importPollTimer = setTimeout(() => pollImportBatch(batchId), 1500);
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

async function importRuleCorrections(file) {
  const mode = $('ruleInspectionMode')?.value || 'project';
  const pid = activeProjectId();
  if (mode !== 'project' || !pid) {
    setStatus('请先选择项目后再导入人工修正');
    return;
  }
  if (!file) return;
  const form = new FormData();
  form.append('file', file);
  try {
    setStatus('正在提交人工修正导入');
    const result = await request(`/api/projects/${pid}/autofill-rule-inspection/import-corrections`, {
      method: 'POST',
      body: form
    });
    if (result.batch_id) {
      state.ruleCorrectionImports = [
        {id: result.batch_id, filename: result.filename || file.name, status: result.status || 'pending'},
        ...(state.ruleCorrectionImports || []).filter(item => item.id !== result.batch_id)
      ].slice(0, 20);
      renderImportBatches();
      setStatus('人工修正导入处理中');
      await pollImportBatch(result.batch_id);
    } else {
      setStatus(`人工修正导入完成：新增 ${result.created || 0}，更新 ${result.updated || 0}，冲突 ${result.conflict || 0}，错误 ${result.errors || 0}`);
      await loadRuleInspection({silent: true});
    }
  } catch (err) {
    setStatus('错误：' + err.message);
  } finally {
    $('ruleCorrectionFile').value = '';
  }
}

export function renderRuleInspection() {
  const data = state.ruleInspection;
  renderSummary(data);
  renderFilters(data);
  renderGapSummary(data);
  renderManualCorrections(data);
  renderImportBatches();
  renderCoverageMatrix(data);
  renderTemplateScan(data);
  renderRuleRows();
}

export async function loadRuleInspection({silent = false} = {}) {
  const mode = $('ruleInspectionMode')?.value || 'project';
  const pid = activeProjectId();
  const path = mode === 'project' && pid
    ? `/api/projects/${pid}/autofill-rule-inspection`
    : '/api/autofill-rule-inspection';
  try {
    if (!silent) setStatus('规则检查加载中');
    state.ruleInspection = await request(path);
    if (mode === 'project' && pid) {
      try { await loadCorrectionImports(); } catch {}
    } else {
      state.ruleCorrectionImports = [];
    }
    renderRuleInspection();
    if (!silent) setStatus('就绪');
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

async function decideCorrection(correctionId, action) {
  const pid = activeProjectId();
  if (!pid || !correctionId) return;
  try {
    await request(`/api/projects/${pid}/autofill-rule-inspection/corrections/${correctionId}/${action}`, {method: 'POST'});
    setStatus(action === 'approve' ? '人工修正已批准' : '人工修正已驳回');
    await loadRuleInspection({silent: true});
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

export function bindRuleInspection() {
  $('exportRuleInspectionBtn').addEventListener('click', exportRuleInspection);
  $('importRuleCorrectionsBtn').addEventListener('click', () => $('ruleCorrectionFile').click());
  $('ruleCorrectionFile').addEventListener('change', event => importRuleCorrections(event.target.files?.[0]));
  $('refreshRuleInspectionBtn').addEventListener('click', () => loadRuleInspection());
  $('ruleInspectionMode').addEventListener('change', () => loadRuleInspection());
  ['ruleStatusLayer', 'ruleStatusFilter', 'ruleScopeFilter', 'ruleStageFilter', 'ruleWorkpaperFilter'].forEach(id => {
    $(id).addEventListener('change', renderRuleInspection);
  });
  $('ruleInspectionRows').addEventListener('click', event => {
    const row = event.target.closest('[data-rule-inspection-id]');
    if (!row) return;
    state.selectedRuleInspectionId = row.dataset.ruleInspectionId;
    renderRuleRows();
  });
  $('ruleCorrectionRows').addEventListener('click', event => {
    const button = event.target.closest('[data-correction-action]');
    if (!button) return;
    decideCorrection(button.dataset.correctionId, button.dataset.correctionAction);
  });
}
