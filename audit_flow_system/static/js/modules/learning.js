import { request } from '../api.js?v=20260816a';
import { state } from '../state.js?v=20260816a';
import { $, esc, setStatus, tag } from '../utils.js?v=20260816a';

let learningLoadSequence = 0;


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

function displayTime(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 16);
  return date.toLocaleString('zh-CN', {hour12: false}).replace(/\//g, '-');
}

function calendarCells(attendance) {
  const start = String(attendance?.calendarStart || '');
  const end = String(attendance?.calendarEnd || '');
  if (!start || !end) return '';
  const counts = new Map((attendance.days || []).map(item => [item.date, Number(item.count || 0)]));
  const cursor = new Date(`${start}T00:00:00Z`);
  const last = new Date(`${end}T00:00:00Z`);
  const cells = Array.from({length: cursor.getUTCDay()}, () => '<span class="learning-day blank"></span>');
  while (cursor <= last) {
    const iso = cursor.toISOString().slice(0, 10);
    const count = counts.get(iso) || 0;
    const level = count === 0 ? 0 : count === 1 ? 1 : count <= 3 ? 2 : count <= 6 ? 3 : 4;
    cells.push(`<span class="learning-day level-${level}" title="${esc(iso)}：${count ? `登录 ${count} 次` : '未登录'}"></span>`);
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return cells.join('');
}

export function renderLearningDashboard() {
  const box = $('learningDashboard');
  if (!box) return;
  const dashboard = state.learningDashboard;
  if (!dashboard) {
    box.innerHTML = '<div class="empty">暂无学习统计</div>';
    return;
  }
  const summary = dashboard.submissionSummary || {};
  const attendance = dashboard.attendance || {};
  const ranking = dashboard.overallRanking || [];
  box.innerHTML = `
    <div class="learning-dashboard">
      <div class="learning-stat-grid">
        <div class="learning-stat"><span>正式提交</span><strong>${esc(summary.submissionCount || 0)}</strong></div>
        <div class="learning-stat danger"><span>校验错误</span><strong>${esc(summary.errorCount || 0)}</strong></div>
        <div class="learning-stat success"><span>提交成功</span><strong>${esc(summary.successCount || 0)}</strong></div>
        <div class="learning-stat"><span>已通过题目</span><strong>${esc(summary.solvedCount || 0)}</strong></div>
        <div class="learning-stat rank"><span>总排名</span><strong>${summary.rank ? `#${esc(summary.rank)}` : '-'}</strong></div>
      </div>
      <div class="learning-dashboard-grid">
        <div class="learning-activity-card">
          <div class="learning-card-head">
            <div><strong>每日登录打卡</strong><span>${attendance.checkedInToday ? '今日已打卡' : '今日未打卡'}</span></div>
            <div class="learning-streak"><b>${esc(attendance.currentStreak || 0)}</b> 天连续 · 最长 ${esc(attendance.longestStreak || 0)} 天</div>
          </div>
          <div class="learning-heatmap" aria-label="最近365天登录打卡记录">${calendarCells(attendance)}</div>
          <div class="learning-heatmap-note"><span>最近365天共打卡 ${esc(attendance.activeDayCount || 0)} 天</span><span>少 <i class="level-0"></i><i class="level-1"></i><i class="level-2"></i><i class="level-3"></i><i class="level-4"></i> 多</span></div>
        </div>
        <div class="learning-ranking-card">
          <div class="learning-card-head"><div><strong>总排名</strong><span>仅按成功完成的不同题目数排名</span></div></div>
          <div class="learning-overall-list">
            ${ranking.map(item => `<div class="learning-rank-row ${item.isCurrentUser ? 'current' : ''}"><b>#${esc(item.rank)}</b><span>${esc(item.displayName)}</span><strong>${esc(item.solvedCount)} 题</strong></div>`).join('') || '<div class="empty">暂无排名</div>'}
          </div>
        </div>
      </div>
    </div>`;
}

function questionRankingHtml(question) {
  const ranking = Array.isArray(question.ranking) ? question.ranking : [];
  const mine = question.myStats || {};
  const solvedCount = ranking.filter(item => Number(item.successCount || 0) > 0).length;
  return `
    <details class="practice-ranking" open>
      <summary><strong>本题排名</strong><span>成功 ${solvedCount} 人 · 我的排名 ${mine.rank ? `#${esc(mine.rank)}` : '未通过'} · 提交 ${esc(mine.submissionCount || 0)} / 错误 ${esc(mine.errorCount || 0)} / 成功 ${esc(mine.successCount || 0)}</span></summary>
      <div class="table-wrap"><table>
        <thead><tr><th>排名</th><th>姓名</th><th>提交</th><th>错误</th><th>成功</th><th>首次成功</th></tr></thead>
        <tbody>${ranking.map(item => `<tr class="${item.isCurrentUser ? 'current-ranking-row' : ''}">
          <td>${item.rank ? `#${esc(item.rank)}` : '未通过'}</td><td>${esc(item.displayName)}</td>
          <td>${esc(item.submissionCount || 0)}</td><td>${esc(item.errorCount || 0)}</td><td>${esc(item.successCount || 0)}</td><td>${esc(displayTime(item.firstSuccessAt))}</td>
        </tr>`).join('') || '<tr><td colspan="6" class="empty">暂时还没有人提交本题</td></tr>'}</tbody>
      </table></div>
    </details>`;
}

function statusLabel(value) {
  const labels = {draft: '草稿', submitted: '已提交', reviewed: '已批阅'};
  const colors = {draft: 'amber', submitted: 'blue', reviewed: 'green'};
  return tag(labels[value] || value || '未开始', colors[value] || 'amber');
}

function allLearningQuestions() {
  return (state.learningWeeks || []).flatMap(chapter => {
    const detail = state.learningWeekCache[Number(chapter.id)];
    return (detail?.questions || []).map(question => ({
      ...question,
      chapterId: Number(chapter.id),
      chapterNo: Number(chapter.weekNo),
      chapterTitle: chapter.title,
    }));
  });
}

function displayQuestionCode(code) {
  return String(code || '').replace(/^W(\d+)-Q(\d+)$/i, 'C$1-Q$2');
}

function questionDifficulty(question) {
  const configured = String(question.validationRules?.difficulty || '').toLowerCase();
  if (['easy', 'medium', 'hard'].includes(configured)) return configured;
  const keywords = (question.validationRules?.required_keywords || []).map(item => String(item).toLowerCase());
  const databases = question.validationRules?.allowed_databases || [];
  if (Number(question.points || 0) >= 100 || databases.length > 1 || question.chapterNo >= 6) return 'hard';
  if (question.chapterNo >= 3 || keywords.some(item => ['group', 'explain'].includes(item))) return 'medium';
  return 'easy';
}

function difficultyHtml(question) {
  const difficulty = questionDifficulty(question);
  const labels = {easy: '简单', medium: '中等', hard: '困难'};
  return `<span class="learning-difficulty ${difficulty}">${labels[difficulty]}</span>`;
}

function questionStatus(question) {
  const status = question.latestSubmission?.status;
  if (status === 'reviewed') return {label: '已批阅', className: 'reviewed'};
  if (status === 'submitted') return {label: '已提交', className: 'submitted'};
  if (status === 'draft') return {label: '草稿', className: 'draft'};
  return {label: '未开始', className: 'not-started'};
}

export function renderLearningCatalog() {
  const list = $('learningQuestionList');
  const chapterFilter = $('learningChapterFilter');
  if (!list || !chapterFilter) return;
  const previousChapter = String(state.learningChapterFilter || '');
  chapterFilter.innerHTML = '<option value="">全部章节</option>' + (state.learningWeeks || []).map(chapter =>
    `<option value="${chapter.id}">第${chapter.weekNo}章 · ${esc(chapter.title)}</option>`
  ).join('');
  chapterFilter.value = previousChapter;
  const search = String(state.learningQuestionSearch || '').trim().toLowerCase();
  const difficulty = String(state.learningDifficultyFilter || '');
  const questions = allLearningQuestions().filter(question => {
    const haystack = `${displayQuestionCode(question.code)} ${question.title} ${question.chapterTitle}`.toLowerCase();
    return (!search || haystack.includes(search))
      && (!difficulty || questionDifficulty(question) === difficulty)
      && (!previousChapter || Number(question.chapterId) === Number(previousChapter));
  });
  const total = allLearningQuestions().length;
  if ($('learningQuestionCount')) $('learningQuestionCount').textContent = `显示 ${questions.length} / ${total} 题`;
  list.innerHTML = `<div class="learning-question-table-head"><span>状态</span><span>题目</span><span>章节</span><span>类型</span><span>难度</span><span></span></div>
    <div class="learning-question-list">${questions.map(question => {
      const status = questionStatus(question);
      return `<button type="button" class="learning-question-row" data-learning-open-question="${question.id}">
        <span class="learning-question-status ${status.className}"><i></i>${status.label}</span>
        <span class="learning-question-title"><b>${esc(displayQuestionCode(question.code))}</b><strong>${esc(question.title)}</strong></span>
        <span class="learning-question-chapter">第${question.chapterNo}章 · ${esc(question.chapterTitle)}</span>
        <span class="learning-question-type">${question.questionType === 'sql' ? 'SQL' : '分析题'}</span>
        ${difficultyHtml(question)}
        <i class="ti ti-chevron-right learning-question-arrow"></i>
      </button>`;
    }).join('') || '<div class="empty">没有符合筛选条件的题目</div>'}</div>`;
}

function showLearningCatalog() {
  state.learningQuestionOpen = false;
  $('learningCatalog')?.classList.remove('hidden');
  $('learningDashboard')?.classList.remove('hidden');
  $('learningDetail')?.classList.add('hidden');
  $('learningReviewPanel')?.classList.add('hidden');
  if (/^#learning-question-\d+$/.test(location.hash)) history.replaceState(null, '', `${location.pathname}${location.search}`);
  renderLearningCatalog();
}

async function openLearningQuestion(questionId, {updateHistory = true} = {}) {
  const question = allLearningQuestions().find(item => Number(item.id) === Number(questionId));
  if (!question) return;
  state.learningQuestionOpen = true;
  state.selectedLearningWeekId = question.chapterId;
  state.selectedLearningQuestionId = Number(question.id);
  state.learningWeek = state.learningWeekCache[question.chapterId];
  $('learningCatalog')?.classList.add('hidden');
  $('learningDashboard')?.classList.add('hidden');
  $('learningDetail')?.classList.remove('hidden');
  if (updateHistory) history.replaceState(null, '', `#learning-question-${question.id}`);
  renderLearningDetail();
  if (state.learningWeek?.canReview) await loadReviewSubmissions();
  else $('learningReviewPanel')?.classList.add('hidden');
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
  const questions = week.questions || [];
  const selectedIndex = Math.max(0, questions.findIndex(item => Number(item.id) === Number(state.selectedLearningQuestionId)));
  const question = questions[selectedIndex] || null;
  if (!question) {
    detail.innerHTML = '<div class="empty">本章暂无题目</div>';
    return;
  }
  const submission = question.latestSubmission || {};
  const isSql = question.questionType === 'sql';
  const queryEnabled = isSql && question.validationRules?.query_enabled === true;
  const defaultLimit = Number(question.validationRules?.default_limit || 50);
  const tableHints = Array.isArray(question.validationRules?.table_hints) ? question.validationRules.table_hints : [];
  const catalogQuestions = allLearningQuestions();
  const catalogIndex = catalogQuestions.findIndex(item => Number(item.id) === Number(question.id));
  const previous = catalogQuestions[catalogIndex - 1];
  const next = catalogQuestions[catalogIndex + 1];
  const displayQuestion = {...question, chapterNo: Number(week.weekNo)};
  detail.innerHTML = `
    <div class="learning-problem-head">
      <div class="learning-problem-title">
        <button type="button" class="secondary learning-back-button" data-learning-back><i class="ti ti-arrow-left"></i> 返回题库</button>
        <span>第${week.weekNo}章 · ${esc(week.title)}</span><strong>${esc(displayQuestionCode(question.code))} ${esc(question.title)}</strong>
        ${difficultyHtml(displayQuestion)}
      </div>
      <div class="practice-actions">
        ${previous ? `<button type="button" class="secondary" data-learning-open-question="${previous.id}"><i class="ti ti-chevron-left"></i> 上一题</button>` : ''}
        ${next ? `<button type="button" class="secondary" data-learning-open-question="${next.id}">下一题 <i class="ti ti-chevron-right"></i></button>` : ''}
        ${guideUrl.startsWith('/static/') ? `<a class="button-link" href="${esc(guideUrl)}" target="_blank" rel="noopener"><i class="ti ti-notes"></i> 学习指导</a>` : ''}
      </div>
    </div>
    <div class="leetcode-question-layout" data-question-card="${question.id}">
      <section class="leetcode-problem-panel">
        <div class="practice-question-head"><div><span class="practice-code">${esc(displayQuestionCode(question.code))}</span><strong>${esc(question.title)}</strong></div><div>${statusLabel(submission.status)} <span class="muted">${question.points}分</span></div></div>
        <div class="leetcode-description"><h3>题目描述</h3><p>${esc(question.prompt)}</p></div>
        ${tableHints.length ? `<div class="practice-notice"><strong>查询表提示</strong>：${tableHints.map(esc).join('；')}</div>` : ''}
        <div class="practice-notice"><strong>${isSql ? '查询边界' : '作答要求'}</strong>：${isSql ? `只允许单条只读 SQL；${queryEnabled ? `未写 LIMIT 时默认添加 LIMIT ${defaultLimit}` : '按题目要求完成静态校验'}` : '填写完整分析、核对过程和结论边界'}。</div>
        ${questionRankingHtml(question)}
        <div class="courseware-grid compact">${courseware}</div>
      </section>
      <section class="leetcode-editor-panel">
        <div class="leetcode-editor-head"><strong>${isSql ? 'SQL 编辑器' : '答案编辑器'}</strong><span>自动保存前请点击“保存草稿”</span></div>
        ${isSql ? `<label>SQL<textarea class="practice-sql" spellcheck="false" placeholder="输入一条只读SQL${queryEnabled ? `；未写LIMIT时默认限制${defaultLimit}行` : ''}">${esc(submission.sqlText || '')}</textarea></label>` : ''}
        <label>${isSql ? '口径、核对或补充说明' : '答案'}<textarea class="practice-answer" placeholder="填写口径、核对过程和结论边界">${esc(submission.answerText || '')}</textarea></label>
        <div class="practice-actions editor-actions">
          ${isSql ? `<button type="button" class="secondary" data-practice-validate="${question.id}"><i class="ti ti-shield-check"></i> 校验SQL</button>` : ''}
          ${queryEnabled ? `<button type="button" class="secondary" data-practice-execute="${question.id}"><i class="ti ti-player-play"></i> 运行查询</button>` : ''}
          <button type="button" class="secondary" data-practice-save="${question.id}"><i class="ti ti-device-floppy"></i> 保存草稿</button>
          <button type="button" data-practice-submit="${question.id}"><i class="ti ti-send"></i> 正式提交</button>
        </div>
        <div data-practice-result="${question.id}">${validationHtml(submission.validation)}</div>
        <div data-practice-query-result="${question.id}"></div>
        ${submission.feedback ? `<div class="practice-feedback"><strong>复核意见</strong><p>${esc(submission.feedback)}</p><span>得分：${submission.score ?? '-'}/${question.points}</span></div>` : ''}
      </section>
    </div>`;
}

export async function loadLearning({weekId = null, silent = false, refresh = false} = {}) {
  const sequence = ++learningLoadSequence;
  try {
    if (refresh || !state.learningWeeks?.length || !state.learningDashboard) {
      const [weeks, dashboard] = await Promise.all([request('/api/learning/weeks'), request('/api/learning/dashboard')]);
      if (sequence !== learningLoadSequence) return;
      state.learningWeeks = weeks;
      state.learningDashboard = dashboard;
      if (refresh) state.learningWeekCache = {};
      renderLearningDashboard();
    }
    const missingChapters = (state.learningWeeks || []).filter(chapter => !state.learningWeekCache[Number(chapter.id)]);
    const chapterDetails = await Promise.all(missingChapters.map(chapter => request(`/api/learning/weeks/${chapter.id}`)));
    if (sequence !== learningLoadSequence) return;
    chapterDetails.forEach(detail => { state.learningWeekCache[Number(detail.id)] = detail; });
    const preferredChapter = Number(weekId || state.selectedLearningWeekId || state.learningWeeks[0]?.id || 0);
    state.selectedLearningWeekId = preferredChapter || null;
    state.learningWeek = state.learningWeekCache[preferredChapter] || null;
    const hashQuestion = Number(location.hash.match(/^#learning-question-(\d+)$/)?.[1] || 0);
    const preferredQuestion = hashQuestion || (state.learningQuestionOpen ? Number(state.selectedLearningQuestionId || 0) : 0);
    if (preferredQuestion && allLearningQuestions().some(item => Number(item.id) === preferredQuestion)) {
      await openLearningQuestion(preferredQuestion, {updateHistory: false});
    } else {
      showLearningCatalog();
    }
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
    <td>${esc(row.displayName || row.username)}</td><td>${esc(displayQuestionCode(row.questionCode))}</td><td>第${row.attemptNo}次</td>
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
  $('learningQuestionList')?.addEventListener('click', async event => {
    const button = event.target.closest('[data-learning-open-question]');
    if (button) await openLearningQuestion(Number(button.dataset.learningOpenQuestion));
  });
  $('learningQuestionSearch')?.addEventListener('input', event => {
    state.learningQuestionSearch = event.target.value;
    renderLearningCatalog();
  });
  $('learningChapterFilter')?.addEventListener('change', event => {
    state.learningChapterFilter = event.target.value;
    renderLearningCatalog();
  });
  $('learningDifficultyFilter')?.addEventListener('change', event => {
    state.learningDifficultyFilter = event.target.value;
    renderLearningCatalog();
  });
  $('learningDetail')?.addEventListener('click', async event => {
    if (event.target.closest('[data-learning-back]')) return showLearningCatalog();
    const questionButton = event.target.closest('[data-learning-open-question]');
    if (questionButton) return void await openLearningQuestion(Number(questionButton.dataset.learningOpenQuestion));
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
        const validationBox = document.querySelector(`[data-practice-result="${questionId}"]`);
        if (validationBox) validationBox.innerHTML = validationHtml(validation);
        setStatus(validation.passed ? 'SQL静态校验通过' : 'SQL静态校验未通过');
        return;
      }
      if (executeButton) {
        setStatus('正在运行只读查询');
        const result = await request(`/api/learning/questions/${questionId}/execute`, {method: 'POST', body: JSON.stringify({sql_text: payload.sql_text})});
        const queryResultBox = document.querySelector(`[data-practice-query-result="${questionId}"]`);
        if (queryResultBox) queryResultBox.innerHTML = queryResultHtml(result);
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
      await loadLearning({weekId: state.selectedLearningWeekId, silent: true, refresh: true});
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
