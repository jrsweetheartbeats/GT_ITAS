import { request } from '../api.js?v=20260816a';
import { state } from '../state.js?v=20260816a';
import { $, esc, setStatus, tag } from '../utils.js?v=20260630b';


function validationHtml(validation) {
  if (!validation || !Object.keys(validation).length) return '<span class="muted">尚未校验</span>';
  const errors = (validation.errors || []).map(item => `<li>${esc(item)}</li>`).join('');
  const warnings = (validation.warnings || []).map(item => `<li>${esc(item)}</li>`).join('');
  return `
    <div class="practice-validation ${validation.passed ? 'passed' : 'failed'}">
      <strong>${validation.passed ? '静态校验通过' : '静态校验未通过'}</strong>
      ${errors ? `<ul>${errors}</ul>` : ''}
      ${warnings ? `<ul class="warnings">${warnings}</ul>` : ''}
      <small>校验不会连接或执行SQL；表、字段、数据与业务口径仍须人工复核。</small>
    </div>`;
}

function queryResultHtml(result) {
  if (!result) return '';
  const columns = result.columns || [];
  const rows = result.rows || [];
  return `
    <div class="practice-validation passed">
      <strong>查询成功：${esc(result.rowCount || 0)} 行 · ${esc(result.durationMs || 0)} ms</strong>
      <small>${result.limitApplied ? `系统已自动添加 LIMIT ${esc(result.rowLimit)}` : `结果上限 ${esc(result.rowLimit)} 行`}${result.truncated ? '；结果已截断' : ''}</small>
      <details><summary>查看实际执行 SQL</summary><pre>${esc(result.executedSql || '')}</pre></details>
    </div>
    <div class="table-wrap"><table class="practice-result-table">
      <thead><tr>${columns.map(item => `<th>${esc(item)}</th>`).join('')}</tr></thead>
      <tbody>${rows.map(row => `<tr>${row.map(value => `<td>${esc(value ?? 'NULL')}</td>`).join('')}</tr>`).join('') || `<tr><td colspan="${Math.max(columns.length, 1)}" class="empty">查询结果为空</td></tr>`}</tbody>
    </table></div>`;
}

function statusLabel(value) {
  const labels = {draft: '草稿', submitted: '已提交', reviewed: '已批阅'};
  const colors = {draft: 'amber', submitted: 'blue', reviewed: 'green'};
  return tag(labels[value] || value || '未开始', colors[value] || 'amber');
}

export function renderLearningWeeks() {
  const list = $('learningWeekList');
  if (!list) return;
  list.innerHTML = (state.learningWeeks || []).map(week => {
    const active = Number(state.selectedLearningWeekId) === Number(week.id);
    const percent = week.questionCount ? Math.round(week.completedCount * 100 / week.questionCount) : 0;
    return `<button type="button" class="learning-week-card ${active ? 'active' : ''}" data-learning-week="${week.id}">
      <span>第${week.weekNo}周</span><strong>${esc(week.title)}</strong>
      <small>${week.completedCount}/${week.questionCount} 已提交 · ${percent}%</small>
    </button>`;
  }).join('') || '<div class="empty">暂无课程</div>';
}

export function renderLearningDetail() {
  const detail = $('learningDetail');
  if (!detail) return;
  const week = state.learningWeek;
  if (!week) {
    detail.innerHTML = '<div class="empty">请选择学习周</div>';
    return;
  }
  const guideUrl = String(week.learningMarkdown || '').replace(/^.*?(\/static\/\S+).*$/, '$1');
  const courseware = (week.courseware || []).map(item => `<a class="courseware-link" href="${esc(item.url)}" target="_blank" rel="noopener"><i class="ti ti-presentation"></i><span>${esc(item.title)}</span></a>`).join('');
  const questions = (week.questions || []).map(question => {
    const submission = question.latestSubmission || {};
    const isSql = question.questionType === 'sql';
    const queryEnabled = isSql && question.validationRules?.query_enabled === true;
    const defaultLimit = Number(question.validationRules?.default_limit || 50);
    return `<article class="practice-question" data-question-card="${question.id}">
      <div class="practice-question-head">
        <div><span class="practice-code">${esc(question.code)}</span><strong>${esc(question.title)}</strong></div>
        <div>${statusLabel(submission.status)} <span class="muted">${question.points}分</span></div>
      </div>
      <p>${esc(question.prompt)}</p>
      ${isSql ? `<label>SQL<textarea class="practice-sql" spellcheck="false" placeholder="输入一条只读SQL${queryEnabled ? `；未写LIMIT时默认限制${defaultLimit}行` : ''}">${esc(submission.sqlText || '')}</textarea></label>` : ''}
      <label>${isSql ? '口径、核对或补充说明' : '答案'}<textarea class="practice-answer" placeholder="填写口径、核对过程和结论边界">${esc(submission.answerText || '')}</textarea></label>
      <div class="practice-actions">
        ${isSql ? `<button type="button" class="secondary" data-practice-validate="${question.id}"><i class="ti ti-shield-check"></i> 校验SQL</button>` : ''}
        ${queryEnabled ? `<button type="button" class="secondary" data-practice-execute="${question.id}"><i class="ti ti-player-play"></i> 运行查询</button>` : ''}
        <button type="button" class="secondary" data-practice-save="${question.id}"><i class="ti ti-device-floppy"></i> 保存草稿</button>
        <button type="button" data-practice-submit="${question.id}"><i class="ti ti-send"></i> 正式提交</button>
      </div>
      <div data-practice-result="${question.id}">${validationHtml(submission.validation)}</div>
      <div data-practice-query-result="${question.id}"></div>
      ${submission.feedback ? `<div class="practice-feedback"><strong>复核意见</strong><p>${esc(submission.feedback)}</p><span>得分：${submission.score ?? '-'}/${question.points}</span></div>` : ''}
    </article>`;
  }).join('');
  detail.innerHTML = `
    <div class="learning-hero">
      <div><span>第${week.weekNo}周</span><h2>${esc(week.title)}</h2><p>${esc(week.summary)}</p></div>
      ${guideUrl.startsWith('/static/') ? `<a class="button-link" href="${esc(guideUrl)}" target="_blank" rel="noopener"><i class="ti ti-notes"></i> 打开本周学习指导</a>` : ''}
    </div>
    <div class="courseware-grid">${courseware}</div>
    <div class="practice-notice"><strong>查询边界</strong>：先执行只读、单语句、数据库范围和题目规则校验；开放查询的题目可读取 IMC、YUHU 或 SOHO，未写 LIMIT 时默认添加 LIMIT 50，具体以题目配置为准。</div>
    <div class="practice-list">${questions || '<div class="empty">本周暂无题目</div>'}</div>`;
}

export async function loadLearning({weekId = null, silent = false} = {}) {
  try {
    state.learningWeeks = await request('/api/learning/weeks');
    const selected = Number(weekId || state.selectedLearningWeekId || state.learningWeeks[0]?.id || 0);
    state.selectedLearningWeekId = selected || null;
    state.learningWeek = selected ? await request(`/api/learning/weeks/${selected}`) : null;
    renderLearningWeeks();
    renderLearningDetail();
    if (state.learningWeek?.canReview) await loadReviewSubmissions();
    else $('learningReviewPanel')?.classList.add('hidden');
  } catch (err) {
    if (!silent) setStatus('学习刷题加载失败：' + err.message);
  }
}

async function loadReviewSubmissions() {
  const panel = $('learningReviewPanel');
  const rowsBox = $('learningReviewRows');
  if (!panel || !rowsBox || !state.selectedLearningWeekId) return;
  const rows = await request(`/api/learning/submissions?weekId=${state.selectedLearningWeekId}`);
  panel.classList.remove('hidden');
  rowsBox.innerHTML = rows.filter(row => ['submitted', 'reviewed'].includes(row.status)).map(row => `<tr>
    <td>${esc(row.displayName || row.username)}</td><td>${esc(row.questionCode)}</td><td>第${row.attemptNo}次</td>
    <td>${statusLabel(row.status)}</td><td>${row.score ?? '-'}</td>
    <td><button type="button" class="secondary" data-practice-review="${row.id}" data-practice-max="${esc(state.learningWeek.questions.find(item => item.id === row.questionId)?.points || 100)}">批阅</button></td>
  </tr>`).join('') || '<tr><td colspan="6" class="empty">暂无待批阅提交</td></tr>';
}

function payloadFor(questionId) {
  const card = document.querySelector(`[data-question-card="${questionId}"]`);
  return {
    sql_text: card?.querySelector('.practice-sql')?.value || '',
    answer_text: card?.querySelector('.practice-answer')?.value || '',
  };
}

export function bindLearning() {
  $('learningWeekList')?.addEventListener('click', async event => {
    const button = event.target.closest('[data-learning-week]');
    if (!button) return;
    setStatus('正在加载本周题目');
    await loadLearning({weekId: Number(button.dataset.learningWeek)});
    setStatus('就绪');
  });
  $('learningDetail')?.addEventListener('click', async event => {
    const validateButton = event.target.closest('[data-practice-validate]');
    const executeButton = event.target.closest('[data-practice-execute]');
    const saveButton = event.target.closest('[data-practice-save]');
    const submitButton = event.target.closest('[data-practice-submit]');
    const questionId = Number(validateButton?.dataset.practiceValidate || executeButton?.dataset.practiceExecute || saveButton?.dataset.practiceSave || submitButton?.dataset.practiceSubmit || 0);
    if (!questionId) return;
    const payload = payloadFor(questionId);
    try {
      if (validateButton) {
        const validation = await request(`/api/learning/questions/${questionId}/validate`, {method: 'POST', body: JSON.stringify({sql_text: payload.sql_text})});
        document.querySelector(`[data-practice-result="${questionId}"]`).innerHTML = validationHtml(validation);
        setStatus(validation.passed ? 'SQL静态校验通过' : 'SQL静态校验未通过');
        return;
      }
      if (executeButton) {
        setStatus('正在运行只读查询');
        const result = await request(`/api/learning/questions/${questionId}/execute`, {method: 'POST', body: JSON.stringify({sql_text: payload.sql_text})});
        document.querySelector(`[data-practice-query-result="${questionId}"]`).innerHTML = queryResultHtml(result);
        setStatus(`查询完成：${result.rowCount || 0} 行`);
        return;
      }
      if (saveButton) {
        await request(`/api/learning/questions/${questionId}/submission`, {method: 'PUT', body: JSON.stringify(payload)});
        setStatus('草稿已保存');
      } else if (submitButton) {
        const result = await request(`/api/learning/questions/${questionId}/submit`, {method: 'POST', body: JSON.stringify(payload)});
        setStatus(result.submitted ? '作业已正式提交' : '校验未通过，已保留为草稿');
      }
      await loadLearning({weekId: state.selectedLearningWeekId, silent: true});
    } catch (err) { setStatus('错误：' + err.message); }
  });
  $('learningReviewRows')?.addEventListener('click', async event => {
    const button = event.target.closest('[data-practice-review]');
    if (!button) return;
    const max = Number(button.dataset.practiceMax || 100);
    const scoreValue = window.prompt(`请输入得分（0-${max}）`);
    if (scoreValue === null) return;
    const feedback = window.prompt('请输入复核意见或订正要求') ?? '';
    try {
      await request(`/api/learning/submissions/${button.dataset.practiceReview}/review`, {method: 'PATCH', body: JSON.stringify({score: Number(scoreValue), feedback})});
      await loadReviewSubmissions();
      setStatus('批阅已保存');
    } catch (err) { setStatus('错误：' + err.message); }
  });
}
