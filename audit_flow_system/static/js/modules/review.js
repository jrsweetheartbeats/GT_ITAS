import { api, authHeaders, request } from '../api.js?v=20260630a';
import { state } from '../state.js?v=20260630a';
import { $, activeProjectId, esc, planRowClass, setStatus, statusClass, tag } from '../utils.js?v=20260630a';

let refreshProjectScoped = async () => {};

export function autofillScopeParam() {
  const scope = $('autofillScope')?.value || '';
  return scope ? `?scope=${encodeURIComponent(scope)}` : '';
}

export function renderAutofillSummary(data) {
  const summary = data.summary || {};
  const unchangedSkipped = (summary.unchanged || 0) + (summary.skipped || 0);
  const manualCount = (summary.manual_correction_approved || 0) + (summary.manual_correction_conflict || 0);
  $('autofillSummary').innerHTML = `
    <div class="mini-stat"><span>建议</span><strong>${esc(data.suggestion_count || 0)}</strong></div>
    <div class="mini-stat"><span>计划</span><strong>${esc(summary.planned || 0)}</strong></div>
    <div class="mini-stat"><span>变更</span><strong>${esc(summary.changed || 0)}</strong></div>
    <div class="mini-stat"><span>不变/跳过</span><strong>${esc(unchangedSkipped)}</strong></div>
    <div class="mini-stat"><span>阻塞</span><strong>${esc(summary.blocked || 0)}</strong></div>
    <div class="mini-stat"><span>人工修正</span><strong>${esc(manualCount)}</strong></div>
  `;
}

function planSourceTag(p) {
  if (p.value_source === 'manual_correction_approved') return tag('已批准人工修正', 'green');
  if (p.value_source === 'manual_correction_conflict') return tag('人工修正冲突', 'red');
  return tag('自动规则', 'blue');
}

export function renderPlanRows(plan) {
  $('planRows').innerHTML = plan.map(p => `
    <tr class="${planRowClass(p.status)}">
      <td>${esc(p.rule_id)}</td>
      <td title="${esc(p.workbook_path || '')}">${esc((p.workbook_path || '').split('/').slice(-2).join('/'))}</td>
      <td>${esc(p.sheet_name)}</td>
      <td>${esc(p.field)}</td>
      <td>${esc(p.cell)}</td>
      <td>${tag(p.status, statusClass(p.status))}</td>
      <td>${planSourceTag(p)}${p.manual_correction_id ? `<div class="muted">#${esc(p.manual_correction_id)}</div>` : ''}</td>
      <td>${esc(p.new_value || '')}</td>
      <td>${esc(p.message || '')}</td>
    </tr>
  `).join('') || '<tr><td colspan="9" class="empty">暂无写入计划</td></tr>';
}

export function renderAutofillRuns() {
  $('autofillRunRows').innerHTML = state.autofillRuns.map(r => `
    <tr>
      <td>${esc(r.id)}</td>
      <td>${tag(r.apply ? '写回' : '预览', r.apply ? 'green' : 'blue')}</td>
      <td>${esc(r.scope || '全部')}</td>
      <td>${esc(r.suggestion_count)}</td>
      <td>${esc(r.plan_count)}</td>
      <td>${esc(r.changed_count)}</td>
      <td>${tag(r.blocked_count, r.blocked_count ? 'red' : 'green')}</td>
      <td>${esc(r.created_at || '')}</td>
      <td><button class="secondary" data-autofill-run-items="${esc(r.id)}">明细</button></td>
    </tr>
  `).join('') || '<tr><td colspan="9" class="empty">暂无自动填写记录</td></tr>';
}

export function renderRuns() {
  const rows = state.runs.map(r => `
    <tr>
      <td>${r.id}</td>
      <td>${tag(r.status, statusClass(r.status))}</td>
      <td>${r.finding_count ?? ''}</td>
      <td>${esc(r.summary || '')}</td>
      <td><button class="secondary" data-run-findings="${esc(r.id)}">查看</button></td>
    </tr>
  `).join('') || '<tr><td colspan="5" class="empty">暂无复核任务</td></tr>';
  $('reviewRows').innerHTML = rows;
  if ($('recentRuns')) {
    $('recentRuns').innerHTML = state.runs.slice(0, 8).map(r => `
      <tr><td>${r.id}</td><td>${tag(r.status, statusClass(r.status))}</td><td>${esc(r.summary || '')}</td><td>${esc(r.finished_at || '')}</td></tr>
    `).join('') || '<tr><td colspan="4" class="empty">暂无复核任务</td></tr>';
  }
}

async function loadFindings(runId) {
  try {
    const rows = await request(`/api/review-runs/${runId}/findings`);
    $('findingRows').innerHTML = rows.map(f => `
      <tr><td>${esc(f.issue_no || f.rule_code)}</td><td>${tag(f.severity, statusClass(f.severity))}</td><td>${f.c22_related ? tag('C22', 'blue') : tag('非C22', 'green')}</td><td>${esc(f.target)}</td><td>${esc(f.issue)}</td><td>${esc(f.evidence)}</td><td>${esc(f.recommendation || '')}</td></tr>
    `).join('') || '<tr><td colspan="7" class="empty">无复核问题</td></tr>';
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

async function downloadFindingTemplate() {
  const pid = activeProjectId();
  if (!pid) return setStatus('请先选择项目');
  const response = await fetch(`${api}/api/projects/${pid}/review-findings/import-template`, {headers: authHeaders()});
  if (!response.ok) throw new Error(await response.text());
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = 'ITAS_review_findings_template.xlsx';
  anchor.click();
  URL.revokeObjectURL(url);
  setStatus('已下载标准问题清单模板');
}

async function importFindingWorkbook() {
  const pid = activeProjectId();
  const input = $('reviewFindingImportFile');
  const file = input?.files?.[0];
  if (!pid) return setStatus('请先选择项目');
  if (!file) return setStatus('请先选择问题清单文件');
  const form = new FormData();
  form.append('file', file);
  const result = await request(`/api/projects/${pid}/review-findings/import`, {method: 'POST', body: form});
  $('reviewImportSummary').textContent = `导入完成：新增 ${result.created} 项，更新 ${result.updated} 项，共 ${result.rows} 行。`;
  input.value = '';
  await refreshProjectScoped();
  setStatus('标准问题清单已导入');
}

async function loadRedactedReviewPreview() {
  const pid = activeProjectId();
  if (!pid) return setStatus('请先选择项目');
  try {
    const data = await request(`/api/projects/${pid}/llm-review/redacted-preview?maxChars=1800`);
    const stats = data.redaction_stats || {};
    const statLine = Object.entries(stats).map(([key, count]) => `${key}: ${count}`).join('；') || '未命中敏感字段';
    $('redactedReviewPreview').innerHTML = `
      <div class="detail-view">
        <div class="subtle-note">脱敏已启用。命中统计：${esc(statLine)}</div>
        ${(data.items || []).map(item => `
          <div class="sheet-preview-section">
            <h4>${esc(item.code || '')} ${esc(item.name || '')}</h4>
            <pre>${esc(item.redacted_text || '该底稿暂无可预览文本')}</pre>
          </div>
        `).join('') || '<div class="empty">暂无可预览底稿文本。</div>'}
      </div>
    `;
    setStatus('LLM脱敏预览已生成');
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

async function loadSuggestions() {
  const pid = activeProjectId();
  if (!pid) return setStatus('请先选择项目');
  try {
    const data = await request(`/api/projects/${pid}/autofill-suggestions${autofillScopeParam()}`);
    $('suggestionSummary').textContent = `已基于 ${data.attachment_count} 个附件生成 ${data.suggestion_count} 条建议；管理员字段范围已过滤 ${data.scope_filtered_count || 0} 条。`;
    renderAutofillSummary({suggestion_count: data.suggestion_count, summary: {}});
    $('suggestionRows').innerHTML = data.suggestions.map(s => `
      <tr>
        <td><strong>${esc(s.rule_id)}</strong><div class="muted">${esc(s.name || '')}</div></td>
        <td>${tag(s.scope, s.scope === 'C22' ? 'blue' : 'green')}</td>
        <td>${esc(s.sheet || s.workpaper || '')}</td>
        <td>${esc((s.targets || []).map(t => t.field || t.locator || '').filter(Boolean).join('、'))}</td>
        <td>${esc(s.suggested_content || '')}</td>
        <td>${esc((s.missing_required_evidence || []).join('、'))}</td>
      </tr>
    `).join('') || '<tr><td colspan="6" class="empty">当前附件未匹配到规则</td></tr>';
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

async function loadAutofillPlan() {
  const pid = activeProjectId();
  if (!pid) return setStatus('请先选择项目');
  try {
    const data = await request(`/api/projects/${pid}/autofill-plan`, {
      method: 'POST',
      body: JSON.stringify({apply: false, scope: $('autofillScope').value || null})
    });
    $('suggestionSummary').textContent = `写入预览：计划 ${data.summary.planned}，不变 ${data.summary.unchanged}，跳过 ${data.summary.skipped}，阻塞 ${data.summary.blocked}，管理员字段范围过滤 ${data.summary.scope_filtered || 0}，已批准人工修正 ${data.summary.manual_correction_approved || 0}。当前仅预览，不写真实底稿。`;
    renderAutofillSummary(data);
    renderPlanRows(data.plan);
    await loadAutofillRuns();
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

async function applyAutofillPlan() {
  setStatus('真实底稿写回当前禁用；请使用预览或测试副本验证。');
}

async function loadAutofillRuns() {
  const pid = activeProjectId();
  if (!pid) return setStatus('请先选择项目');
  state.autofillRuns = await request(`/api/autofill-runs?projectId=${pid}`);
  renderAutofillRuns();
}

async function loadAutofillRunItems(runId) {
  try {
    const rows = await request(`/api/autofill-runs/${runId}/items`);
    renderPlanRows(rows);
    $('suggestionSummary').textContent = `已加载自动填写记录 #${runId} 的 ${rows.length} 条明细。`;
    setStatus('就绪');
  } catch (err) {
    setStatus('错误：' + err.message);
  }
}

export async function runReview(useExternal, reviewEngine = 'rules') {
  const pid = activeProjectId();
  if (!pid) return setStatus('请先选择项目');
  setStatus('复核中');
  const run = await request('/api/review-runs', {
    method: 'POST',
    body: JSON.stringify({project_id: pid, use_external_rules: useExternal, review_engine: reviewEngine})
  });
  $('reviewSummary').textContent = run.summary;
  await refreshProjectScoped();
  await loadFindings(run.id);
  setStatus('就绪');
}

export function bindReview(options) {
  refreshProjectScoped = options.refreshProjectScoped;

  $('dashRunReview')?.addEventListener('click', () => runReview(false));
  $('runReviewBtn').addEventListener('click', () => runReview($('externalRules').checked));
  $('runDeepSeekReviewBtn')?.addEventListener('click', () => runReview(false, 'deepseek').catch(err => setStatus('错误：' + err.message)));
  $('loadRedactedReviewPreviewBtn')?.addEventListener('click', loadRedactedReviewPreview);
  $('downloadReviewFindingTemplateBtn')?.addEventListener('click', () => downloadFindingTemplate().catch(err => setStatus('错误：' + err.message)));
  $('importReviewFindingBtn')?.addEventListener('click', () => importFindingWorkbook().catch(err => setStatus('错误：' + err.message)));
  $('loadSuggestionsBtn').addEventListener('click', loadSuggestions);
  $('loadPlanBtn').addEventListener('click', loadAutofillPlan);
  $('applyPlanBtn').addEventListener('click', applyAutofillPlan);
  $('refreshAutofillRunsBtn').addEventListener('click', loadAutofillRuns);
  $('reviewRows').addEventListener('click', (event) => {
    const button = event.target.closest('[data-run-findings]');
    if (button) loadFindings(Number(button.dataset.runFindings));
  });
  $('autofillRunRows').addEventListener('click', (event) => {
    const button = event.target.closest('[data-autofill-run-items]');
    if (button) loadAutofillRunItems(Number(button.dataset.autofillRunItems));
  });
  $('autofillScope').addEventListener('change', () => {
    $('suggestionRows').innerHTML = '<tr><td colspan="6" class="empty">筛选已改变，请重新生成建议</td></tr>';
    $('planRows').innerHTML = '<tr><td colspan="9" class="empty">筛选已改变，请重新预览写入计划</td></tr>';
    renderAutofillSummary({suggestion_count: 0, summary: {}});
  });

  window.loadFindings = loadFindings;
  window.loadAutofillRunItems = loadAutofillRunItems;
}
