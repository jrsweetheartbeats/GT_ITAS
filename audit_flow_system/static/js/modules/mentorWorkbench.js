import { request } from '../api.js?v=20260630a';
import { $, esc, setStatus, tag } from '../utils.js?v=20260630b';

let workbench = null;
let submissionDetail = null;
let assessmentDetail = null;
let blockerDetail = null;

function renderStudentCards() {
  return `<div class="mentor-student-grid">${(workbench?.students || []).map(student => `<button type="button" class="mentor-student-card" data-mentor-assessment="${student.planId}"><div><strong>${esc(student.employeeName || '未命名学员')}</strong><span>第${student.currentWeekNo || '—'}周 · ${esc(student.period)}</span></div><div class="mentor-student-metrics"><span>完成率 <b>${student.completionRate}%</b></span><span>逾期 <b>${student.overdueTasks}</b></span><span>待Review <b>${student.pendingReview}</b></span><span>Blocked <b>${student.blocked}</b></span></div></button>`).join('') || '<div class="empty">暂无直属学员培养计划</div>'}</div>`;
}

function renderActions() {
  const labels = {review: '待Review作业', blocker: '待处理卡点', overdue: '逾期重要作业', assessment: '月底待评分'};
  return `<div class="mentor-action-list">${(workbench?.actionItems || []).map(item => `<button type="button" class="mentor-action-item mentor-action-${esc(item.type)}" data-mentor-action="${item.type}" data-mentor-id="${item.id}" data-mentor-plan="${item.planId}"><span class="mentor-action-kind">${esc(labels[item.type] || item.type)}</span><strong>${esc(item.employeeName || '')} · ${esc(item.title || '培养事项')}</strong><small>${item.dueDate ? `截止 ${esc(String(item.dueDate).slice(0,10))}` : item.createdAt ? `提交于 ${esc(String(item.createdAt).slice(0,10))}` : ''}</small></button>`).join('') || '<div class="empty">当前没有需要介入的事项。</div>'}</div>`;
}

function renderSubmission() {
  if (!submissionDetail) return '';
  const task = submissionDetail.task;
  return `<div class="mentor-detail-panel"><div class="mentor-detail-head"><div><span class="muted">${esc(submissionDetail.employee.name)}</span><h3>${esc(task.title)}</h3></div><button type="button" class="secondary" data-mentor-close-detail>关闭</button></div><div class="mentor-requirement-grid"><div><span>任务要求</span><p>${esc(task.instructions || task.description || '')}</p></div><div><span>完成标准</span><p>${esc(task.completionCriteria || '')}</p></div><div><span>提交要求</span><p>${esc(task.submissionRequirements || '')}</p></div></div><div class="mentor-version-list">${(submissionDetail.submissions || []).map(item => `<div class="mentor-version"><div><strong>V${item.version}</strong><span>${esc(String(item.submittedAt || '').slice(0,16))} · ${esc(item.submissionType)}</span></div><div class="mentor-submission-content">${esc(item.content || '')}${item.attachment ? `<a href="${esc(item.attachment)}" target="_blank" rel="noopener">查看附件/链接</a>` : ''}</div><div class="mentor-self-check">自检：${Object.values(item.selfCheckAnswers || {}).filter(Boolean).length} 项已完成</div>${(item.reviews || []).map(review => `<div class="mentor-review-history">${tag(review.result === 'passed' ? '通过' : '要求修改', review.result === 'passed' ? 'green' : 'amber')} ${esc(review.comments || '')}</div>`).join('')}</div>`).join('')}</div><form id="mentorReviewForm" class="mentor-review-form"><label>Review结论<select name="result"><option value="passed">通过</option><option value="revision_required">要求修改</option></select></label><label>Review comments<textarea name="comments" required placeholder="要求修改时必须填写具体改进要求"></textarea></label><label>评分<input name="score" type="number" min="0" max="100"></label><button type="submit">保存Review</button></form></div>`;
}

function renderAssessment() {
  if (!assessmentDetail) return '';
  const assessment = assessmentDetail.assessment;
  return `<div class="mentor-detail-panel"><div class="mentor-detail-head"><div><span class="muted">${esc(assessmentDetail.plan.employeeName)} · ${esc(assessmentDetail.plan.period)}</span><h3>月度评价</h3></div><button type="button" class="secondary" data-mentor-close-detail>关闭</button></div><form id="mentorAssessmentForm" class="mentor-assessment-form">${(assessment.dimensions || []).map(item => `<div class="mentor-score-row"><label>${esc(item.name)} <span>权重 ${item.weight}%</span><input name="score_${esc(item.code)}" type="number" min="0" max="100" step="0.1" value="${item.score ?? ''}" required></label><input name="comment_${esc(item.code)}" placeholder="该维度评价（可选）" value="${esc(item.comments || '')}"></div>`).join('')}<label>导师评价<textarea name="mentorEvaluation" placeholder="总结本月表现"></textarea></label><label>下阶段建议<textarea name="nextStageSuggestion" placeholder="系统会根据thresholds提供建议，可编辑"></textarea></label><div class="actions"><button type="submit">保存月度评价</button><button type="button" class="secondary" data-mentor-copy="json">复制给 ChatGPT（JSON）</button><button type="button" class="secondary" data-mentor-copy="markdown">复制给 ChatGPT（Markdown）</button></div></form>${assessment.totalScore != null ? `<div class="mentor-total-score">当前总分：<strong>${assessment.totalScore}</strong></div>` : ''}</div>`;
}

function renderBlocker() {
  if (!blockerDetail) return '';
  return `<div class="mentor-detail-panel"><div class="mentor-detail-head"><div><span class="muted">${esc(blockerDetail.employeeName)} · ${esc(blockerDetail.blockerType)}</span><h3>卡点详情</h3></div><button type="button" class="secondary" data-mentor-close-detail>关闭</button></div><div class="mentor-blocker-analysis">${[['problem','具体问题'],['confirmedFacts','已确认事实'],['materialsChecked','已看材料'],['initialJudgment','初步判断'],['attemptedSolutions','已尝试方案'],['missingInformation','缺少资料或验证'],['mentorQuestion','希望导师判断']].map(([key,label]) => `<div><strong>${label}</strong><p>${esc(blockerDetail[key] || '')}</p></div>`).join('')}</div><form id="mentorBlockerForm" class="mentor-review-form"><label>处理动作<select name="action"><option value="continue_self_processing">继续自行处理</option><option value="resolved">已解决</option></select></label><label>导师回复<textarea name="mentorResponse" required placeholder="请给出下一步要求或解决说明"></textarea></label><button type="submit">保存处理结果</button></form></div>`;
}

function render() {
  const box = $('developmentContent');
  if (!box || !workbench) return;
  box.innerHTML = `<div class="mentor-workbench-head"><div><div class="training-eyebrow">Mentor 工作台</div><h2>我的学员</h2><p class="muted">只处理待Review、卡点、逾期重要作业和月底评分。</p></div><button type="button" class="secondary" data-mentor-refresh><i class="ti ti-refresh"></i> 刷新</button></div>${renderStudentCards()}<div class="mentor-section"><div class="mentor-section-head"><h3>需要我处理</h3><span class="muted">${workbench.actionItems?.length || 0} 项</span></div>${renderActions()}</div>${renderSubmission()}${renderBlocker()}${renderAssessment()}`;
}

export async function loadMentorWorkbench() {
  try { setStatus('加载导师工作台'); workbench = await request('/api/development/mentor-workbench'); submissionDetail = null; blockerDetail = null; assessmentDetail = null; render(); setStatus('导师工作台已加载'); }
  catch (error) { setStatus(`错误：${error.message}`); const box = $('developmentContent'); if (box) box.innerHTML = `<div class="empty">导师工作台加载失败：${esc(error.message)}</div>`; }
}

async function loadAssessment(planId) {
  assessmentDetail = await request(`/api/development/mentor/plans/${planId}/assessment`); submissionDetail = null; render();
}

export function bindMentorWorkbench() {
  const box = $('developmentContent');
  if (!box) return;
  box.addEventListener('click', async event => {
    if (event.target.closest('[data-mentor-refresh]')) { await loadMentorWorkbench(); return; }
    if (event.target.closest('[data-mentor-close-detail]')) { submissionDetail = null; blockerDetail = null; assessmentDetail = null; render(); return; }
    const assessmentButton = event.target.closest('[data-mentor-assessment]');
    if (assessmentButton) { await loadAssessment(Number(assessmentButton.dataset.mentorAssessment)); return; }
    const action = event.target.closest('[data-mentor-action]');
    if (action?.dataset.mentorAction === 'review') { submissionDetail = await request(`/api/development/mentor/submissions/${action.dataset.mentorId}`); assessmentDetail = null; render(); return; }
    if (action?.dataset.mentorAction === 'blocker') { blockerDetail = await request(`/api/development/blockers/${action.dataset.mentorId}`); submissionDetail = null; assessmentDetail = null; render(); return; }
    if (action?.dataset.mentorAction === 'assessment') { await loadAssessment(Number(action.dataset.mentorPlan)); return; }
  });
  box.addEventListener('submit', async event => {
    if (event.target.id === 'mentorReviewForm') {
      event.preventDefault(); const form = event.target;
      try { const latest = submissionDetail.submissions[submissionDetail.submissions.length - 1]; await request(`/api/development/submissions/${latest.id}/review`, {method:'POST', body: JSON.stringify({result: form.result.value, comments: form.comments.value, score: form.score.value ? Number(form.score.value) : null})}); await loadMentorWorkbench(); }
      catch (error) { setStatus(`错误：${error.message}`); }
    }
    if (event.target.id === 'mentorAssessmentForm') {
      event.preventDefault(); const form = event.target; const dimensions = {}; const dimensionComments = {};
      (assessmentDetail.assessment.dimensions || []).forEach(item => { dimensions[item.code] = Number(form[`score_${item.code}`].value); dimensionComments[item.code] = form[`comment_${item.code}`].value; });
      try { await request(`/api/development/mentor/plans/${assessmentDetail.plan.id}/assessment`, {method:'PUT', body: JSON.stringify({dimensions, dimensionComments, mentorEvaluation: form.mentorEvaluation.value, nextStageSuggestion: form.nextStageSuggestion.value})}); await loadMentorWorkbench(); }
      catch (error) { setStatus(`错误：${error.message}`); }
    }
    if (event.target.id === 'mentorBlockerForm') {
      event.preventDefault(); const form = event.target;
      try { await request(`/api/development/blockers/${blockerDetail.id}/respond`, {method:'PATCH', body: JSON.stringify({action: form.action.value, mentorResponse: form.mentorResponse.value})}); await loadMentorWorkbench(); }
      catch (error) { setStatus(`错误：${error.message}`); }
    }
  });
  box.addEventListener('click', async event => {
    const copy = event.target.closest('[data-mentor-copy]');
    if (!copy || !assessmentDetail) return;
    try { const data = await request(`/api/development/mentor/plans/${assessmentDetail.plan.id}/assessment/export?format=${copy.dataset.mentorCopy}`); await navigator.clipboard.writeText(data.content); setStatus('已复制，可粘贴给 ChatGPT'); }
    catch (error) { setStatus(`错误：${error.message}`); }
  });
}
