import { api, authHeaders, request } from '../api.js?v=20260630a';
import { $, esc, setStatus, tag } from '../utils.js?v=20260630b';

let plans = [];
let selectedPlanId = null;
let overview = null;
let view = 'tasks';
let selectedTaskId = null;
let learnerData = null;
let learnerMode = false;
let blockerFormOpen = false;
let taskDetail = null;
let personalHandbookUrl = null;
let selectedLearnerBatchId = null;
let assignmentWindowOpen = false;
let assignmentQuizFeedback = [];
let assignmentSubmissionResult = null;
let developmentViewRequestSeq = 0;

const STATUS_LABELS = {
  not_started: '未开始', in_progress: '进行中', submitted: '待Review',
  needs_revision: '修改中', completed: '完成', blocked: 'Blocked',
};
const TASK_TYPE_LABELS = { learning: '学习', quiz: '理解题', practice: '练习', project: '项目实操', assignment: '作业', self_check: '自检', review: '导师Review' };
const TRAINING_MANAGER_ROLES = new Set(['admin', 'partner', 'quality', 'director', 'senior_manager', 'manager']);

function canSelectTrainingPlan() {
  return Boolean(state.me?.is_admin || TRAINING_MANAGER_ROLES.has(state.me?.role_code));
}

function beginDevelopmentViewRequest() {
  developmentViewRequestSeq += 1;
  return developmentViewRequestSeq;
}

function isCurrentDevelopmentViewRequest(requestSeq) {
  return requestSeq === developmentViewRequestSeq;
}

function dateValue(value) {
  if (!value) return null;
  const [year, month, day] = String(value).slice(0, 10).split('-').map(Number);
  return new Date(year, month - 1, day);
}

function dateText(value) {
  return value ? String(value).slice(0, 10) : '—';
}

function dayDiff(a, b) {
  return Math.round((a.getTime() - b.getTime()) / 86400000);
}

function daysBetween(start, end) {
  const result = [];
  for (let current = new Date(start); current <= end; current.setDate(current.getDate() + 1)) result.push(new Date(current));
  return result;
}

function statusLabel(status) { return STATUS_LABELS[status] || status || '未开始'; }

function taskStatusClass(task) {
  if (task.locked || task.blockedByPrerequisite) return 'training-status-not-started';
  if (task.isBlocked || task.status === 'blocked') return 'training-status-blocked';
  if (task.isReviewPending || task.status === 'submitted') return 'training-status-review';
  if (task.status === 'needs_revision') return 'training-status-revision';
  if (task.status === 'completed') return 'training-status-completed';
  if (task.status === 'in_progress') return 'training-status-progress';
  return 'training-status-not-started';
}

function renderMetric(label, value, tone = '') {
  return `<div class="training-metric ${tone}"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
}

function renderLearnerTask(task) {
  const status = task.locked || task.blockedByPrerequisite ? '前置任务未完成' : statusLabel(task.status);
  const statusClass = task.blockedByPrerequisite ? 'training-status-not-started' : taskStatusClass(task);
  const actionLabel = task.submissionRequired ? '进入作业' : '学习内容';
  const questionHint = task.submissionRequired && Number(task.questionCount || 0) > 0
    ? `<span>含 ${esc(task.questionCount)} 道题</span>` : '';
  return `<div class="my-training-task ${task.isOverdue ? 'overdue' : ''}"><div class="my-training-task-main"><div class="my-training-task-title"><strong>${esc(task.title)}</strong><span>${esc(TASK_TYPE_LABELS[task.taskType] || task.taskType || '任务')}</span></div><div class="my-training-task-meta"><span>预计 ${esc(task.estimatedHours ?? '—')} 小时</span><span>截止 ${esc(dateText(task.dueDate))}</span>${questionHint}</div></div><div class="my-training-task-state">${tag(status, statusClass)}${task.submissionRequired && !task.hasSubmission ? tag('未提交', 'amber') : ''}</div><button type="button" class="secondary" data-training-task="${task.id}">${actionLabel}</button></div>`;
}

function renderBatchCard(batch) {
  const progress = batch.progress || { completed: 0, total: 0 };
  const due = (batch.tasks || []).filter(task => task.submissionRequired && !task.hasSubmission).length;
  const progressRate = progress.total ? Math.round(progress.completed / progress.total * 100) : 0;
  return `<button type="button" class="training-batch-card" data-training-batch="${batch.id}"><div class="training-batch-card-head"><span>第 ${esc(batch.batchNo)} 批</span>${tag(`${progress.completed} / ${progress.total} 已完成`, progress.completed === progress.total && progress.total ? 'green' : 'blue')}</div><strong>${esc(batch.title)}</strong><p>${esc(batch.objective || '暂无批次目标')}</p><div class="training-batch-card-meta"><span>${esc(dateText(batch.startDate))} — ${esc(dateText(batch.endDate))}</span><span>${due ? `${due} 项待提交` : '无待提交作业'}</span></div><div class="progress"><i style="width:${progressRate}%"></i></div></button>`;
}

function renderLearnerBatch(batch) {
  const tasks = batch.tasks || [];
  const pending = tasks.filter(task => task.submissionRequired && !task.hasSubmission);
  const required = tasks.filter(task => task.submissionRequired);
  const feedback = tasks.filter(task => task.latestReview);
  return `<div class="my-training-batch-head"><button type="button" class="secondary" data-training-batch-back><i class="ti ti-arrow-left"></i> 返回学习批次</button><div><span class="training-eyebrow">第 ${esc(batch.batchNo)} 批学习计划</span><h3>${esc(batch.title)}</h3><p>${esc(batch.objective || '暂无批次目标')}</p><span class="muted">${esc(dateText(batch.startDate))} — ${esc(dateText(batch.endDate))} · 预期成果：${esc(batch.expectedDeliverable || '—')}</span></div></div>
    <div class="my-training-section"><div class="my-training-section-head"><h3>本批学习任务</h3><span class="muted">仅显示第 ${esc(batch.batchNo)} 批任务</span></div><div class="my-training-task-list">${tasks.map(renderLearnerTask).join('') || '<div class="empty">本批暂未配置学习任务。</div>'}</div>${!taskDetail?.submissionRequired ? renderTaskLoopDetail() : ''}</div>
    <div class="my-training-section"><div class="my-training-section-head"><h3>本批必须提交</h3><span class="muted">${pending.length} 项待提交</span></div><div class="my-training-submit-list">${required.map(task => `<div class="my-training-submit-item"><div><strong>${esc(task.submissionTitle || task.title)}</strong><span>截止：${esc(dateText(task.dueDate))}</span></div>${tag(task.hasSubmission ? '已提交' : '未提交', task.hasSubmission ? 'green' : 'amber')}<button type="button" class="secondary" data-training-task="${task.id}">进入作业</button></div>`).join('') || '<div class="empty">本批没有必须提交的作业。</div>'}</div></div>
    <div class="my-training-two-col"><div class="my-training-section"><div class="my-training-section-head"><h3>导师反馈</h3></div><div class="my-training-feedback-list">${feedback.map(task => `<button type="button" class="my-training-feedback" data-training-task="${task.id}"><span>${esc(task.title)}</span>${tag(task.latestReview.result === 'passed' ? '已通过' : '待修改', task.latestReview.result === 'passed' ? 'green' : 'amber')}<small>${esc(task.latestReview.comments || '')}</small></button>`).join('') || '<div class="empty">本批暂无导师反馈。</div>'}</div></div><div class="my-training-section"><div class="my-training-section-head"><h3>卡点</h3><button type="button" class="secondary" data-training-open-blocker>提交卡点</button></div><div class="my-training-blocker-list">${(learnerData.blockers || []).map(item => `<div class="my-training-blocker"><strong>${esc(item.problem)}</strong><span>${tag(item.status, 'amber')}</span><small>${esc(item.mentorResponse || '等待导师回复')}</small></div>`).join('') || '<div class="empty">当前没有 Blocked 卡点。</div>'}</div>${blockerFormOpen ? renderBlockerForm() : ''}</div></div>${renderAssignmentWindow()}`;
}

function renderLearner() {
  const box = $('developmentContent');
  if (!box) return;
  if (!learnerData?.plan) { box.innerHTML = '<div class="empty">暂无个人培养计划</div>'; return; }
  const batches = learnerData.batches || [];
  const selectedBatch = batches.find(batch => Number(batch.id) === Number(selectedLearnerBatchId));
  const metrics = learnerData.metrics || { completed: 0, total: 0, completionRate: 0 };
  box.innerHTML = `<div class="my-training-head"><div><div class="training-eyebrow">我的培养</div><h2>${esc(learnerData.employee.name)}</h2><div class="muted">${esc(learnerData.plan.title)} · ${esc(dateText(learnerData.plan.startDate))} — ${esc(dateText(learnerData.plan.endDate))}</div></div><button type="button" class="secondary" data-training-refresh><i class="ti ti-refresh"></i> 刷新</button></div>
    ${selectedBatch ? renderLearnerBatch(selectedBatch) : `<section class="my-training-section training-batch-home"><div class="my-training-section-head"><div><h3>学习批次</h3><span class="muted">选择一个批次后查看对应学习任务和作业</span></div><strong>${metrics.completionRate}%</strong></div><div class="training-batch-grid">${batches.map(renderBatchCard).join('') || '<div class="empty">暂无学习批次。</div>'}</div></section>${personalHandbookUrl ? `<section class="my-training-section personal-handbook"><div class="my-training-section-head"><div><h3>第 1 个月个人培养手册</h3><span class="muted">风险原理、操作步骤、练习作业与月末评价标准</span></div></div><iframe class="training-personal-handbook" src="${personalHandbookUrl}" title="${esc(learnerData.employee.name)}的个人培养手册"></iframe></section>` : ''}<div class="my-training-section my-training-month"><div class="my-training-section-head"><h3>本月进度</h3><strong>${metrics.completionRate}%</strong></div><div class="progress progress-large"><i style="width:${metrics.completionRate}%"></i></div><span class="muted">已完成 ${metrics.completed} / ${metrics.total} 个任务</span></div>`}`;
}

function renderBlockerForm() {
  const selectedBatch = (learnerData.batches || []).find(batch => Number(batch.id) === Number(selectedLearnerBatchId));
  const tasks = selectedBatch?.tasks || learnerData.tasks || [];
  const fields = [['problem','我现在要解决的具体问题是什么？'],['confirmedFacts','我已经确认了哪些事实？'],['materialsChecked','我已经看过哪些材料？'],['initialJudgment','我的初步判断是什么？'],['attemptedSolutions','我已经尝试过哪些方案？'],['missingInformation','目前还缺什么资料或验证？'],['mentorQuestion','我希望导师帮我判断什么？']];
  return `<form class="my-training-blocker-form" id="myTrainingBlockerForm"><label>关联任务<select name="taskId" required>${tasks.map(task => `<option value="${task.id}">${esc(task.title)}</option>`).join('')}</select></label>${fields.map(([name, label]) => `<label>${esc(label)}<textarea name="${name}" required></textarea></label>`).join('')}<label>卡点类型<select name="blockerType"><option value="general">一般问题</option><option value="method">方法理解</option><option value="evidence">证据不足</option><option value="judgment">判断困难</option><option value="data">资料或数据</option></select></label><div class="actions"><button type="button" class="secondary" data-training-close-blocker>取消</button><button type="submit">提交卡点</button></div></form>`;
}

function renderGlobalRadar(data) {
  const students = data.students || [];
  const actions = data.actionItems || [];
  const pendingReview = actions.filter(item => item.type === 'review').length;
  const blocked = actions.filter(item => item.type === 'blocker').length;
  const overdue = actions.filter(item => item.type === 'overdue').length;
  return `<div class="development-subview-head"><div><div class="training-eyebrow">IT审计成长舱</div><h2>全局雷达</h2><p class="muted">汇总全部学员的活跃任务、待 Review、卡点和逾期事项。</p></div><button type="button" data-open-mentor-workbench>进入 Mentor 指挥台</button></div><div class="training-metrics">${renderMetric('学员', students.length)}${renderMetric('待Review', pendingReview, 'attention')}${renderMetric('卡点', blocked, 'risk')}${renderMetric('逾期事项', overdue, 'attention')}</div><section class="mentor-section"><div class="mentor-section-head"><h3>学员活跃度</h3><span class="muted">按待 Review、卡点、逾期与进行中任务排序</span></div><div class="mentor-student-grid">${students.map(student => `<button type="button" class="mentor-student-card" data-open-mentor-workbench><div><strong>${esc(student.employeeName)}</strong><span>活跃任务 ${student.activeTasks || 0} · 待Review ${student.pendingReview || 0}</span></div><div class="mentor-student-metrics"><span>完成率 <b>${student.completionRate}%</b></span><span>逾期 <b>${student.overdueTasks}</b></span><span>卡点 <b>${student.blocked}</b></span><span>活跃度 <b>${student.activityScore || 0}</b></span></div></button>`).join('') || '<div class="empty">暂无培养计划。</div>'}</div></section><section class="mentor-section"><div class="mentor-section-head"><h3>优先事项</h3><span class="muted">${actions.length} 项</span></div><div class="mentor-action-list">${actions.slice(0, 12).map(item => `<button type="button" class="mentor-action-item" data-open-mentor-workbench><span class="mentor-action-kind">${esc(item.type === 'review' ? '待Review' : item.type === 'blocker' ? '卡点' : item.type === 'overdue' ? '逾期' : '月度评分')}</span><strong>${esc(item.employeeName || '')} · ${esc(item.title || '')}</strong><small>${item.createdAt ? `提交于 ${esc(String(item.createdAt).slice(0,16))}` : item.dueDate ? `截止 ${esc(String(item.dueDate).slice(0,10))}` : ''}</small></button>`).join('') || '<div class="empty">当前没有需要导师处理的事项。</div>'}</div></section>`;
}


const LEGACY_VIEW_META = {
  people: {title: '审计学员档案', endpoint: '/api/development/employees'},
  plans: {title: '成长路线', endpoint: '/api/development/plans'},
  learning: {title: '训练与案例', endpoint: '/api/development/dashboard'},
  issues: {title: 'Review问题库', endpoint: '/api/development/issues'},
  monthly: {title: '月度复盘记录', endpoint: '/api/development/dashboard'},
};

async function loadLegacyView(viewName) {
  const meta = LEGACY_VIEW_META[viewName];
  if (!meta) return;
  try {
    setStatus(`加载${meta.title}`);
    const data = await request(meta.endpoint);
    learnerMode = false;
    taskDetail = null;
    overview = null;
    const box = $('developmentContent');
    const rows = Array.isArray(data) ? data : (data.team || data.actionItems || []);
    const fmt = value => Array.isArray(value) ? `${value.length} 项` : (value && typeof value === 'object' ? '已配置' : String(value ?? '—'));
    let content = '';
    if (viewName === 'people') {
      content = `<div class="development-card-grid">${rows.map(row => `<article class="development-info-card"><div class="development-card-title"><strong>${esc(row.name || '未命名成员')}</strong>${tag(row.status || 'active', 'green')}</div><p class="muted">${esc(row.currentRole || '执行成员')}</p><div class="development-card-meta"><span>当前重点：${esc(row.currentFocus || '未设置')}</span><span>能力维度：${Object.keys(row.competencies || {}).length} 项</span></div></article>`).join('') || '<div class="empty">暂无成员档案</div>'}</div>`;
    } else if (viewName === 'plans') {
      content = `<div class="development-card-grid">${rows.map(row => `<article class="development-info-card"><div class="development-card-title"><strong>${esc(row.title || '未命名路线')}</strong>${tag(row.status || 'draft')}</div><p class="muted">${esc(row.employeeName || '成员未关联')} · ${esc(row.planType || '')}</p><div class="development-card-meta"><span>月度节点：${Array.isArray(row.months) ? row.months.length : 0}</span><span>周期：${esc(row.startsOn || '—')} — ${esc(row.endsOn || '—')}</span></div></article>`).join('') || '<div class="empty">暂无成长路线</div>'}</div>`;
    } else {
      const summary = data.summary || {};
      content = `<div class="summary-strip development-summary-cards">${Object.entries(summary).slice(0, 6).map(([key,value]) => `<div class="mini-stat"><span>${esc(key)}</span><strong>${esc(fmt(value))}</strong></div>`).join('')}</div><div class="development-card-grid">${rows.slice(0, 12).map(row => `<article class="development-info-card"><div class="development-card-title"><strong>${esc(row.employee?.name || row.employeeName || row.title || '培养记录')}</strong>${row.progress != null ? `<b>${esc(row.progress)}%</b>` : tag(row.status || '记录')}</div><p class="muted">${esc(row.risk || row.description || row.period || '持续跟踪中')}</p><div class="development-card-meta"><span>完成：${esc(row.taskCompleted ?? row.completionRate ?? '—')}</span><span>Review：${esc(row.pendingReview ?? row.pendingReviewCount ?? '—')}</span></div></article>`).join('') || '<div class="empty">暂无记录</div>'}</div>`;
    }
    box.innerHTML = `<div class="development-subview-head"><div><div class="training-eyebrow">IT审计成长舱</div><h2>${esc(meta.title)}</h2><p class="muted">这里保留现有培养数据视图，点击页签即可切换。</p></div><button type="button" class="secondary" data-development-refresh="${esc(viewName)}">刷新</button></div>${content}`;
    setStatus(`${meta.title}已加载`);
  } catch (error) {
    setStatus(`错误：${error.message}`);
    const box = $('developmentContent');
    if (box) box.innerHTML = `<div class="empty">${esc(meta.title)}加载失败：${esc(error.message)}</div>`;
  }
}

function renderSubmissionForm(task, questions) {
  if (!questions.length) return `<div class="empty">本作业尚未配置在线题目，请联系导师补充课程练习。</div>`;
  return `<form class="training-submission-form" id="trainingSubmissionForm"><fieldset><legend>课件知识选择题（全部答对才算过关）</legend>${questions.map(renderTaskQuestion).join('')}</fieldset><button type="submit">提交并判题</button></form>`;
}

function renderLearningMaterial(item) {
  const privateCourseware = /^\/api\/development\/tasks\/\d+\/courseware$/.test(item.url || '');
  const title = item.url ? (privateCourseware ? `<button type="button" class="link-button" data-training-open-courseware="${esc(item.url)}">${esc(item.title)}</button>` : `<a href="${esc(item.url)}" target="_blank" rel="noopener">${esc(item.title)}</a>`) : esc(item.title);
  return `<div class="training-material-item"><div><strong>${title}</strong><span>${esc(item.type)} · ${esc(item.description || '')}</span></div><button type="button" class="${item.read ? 'secondary' : ''}" data-training-material-read="${item.id}">${item.read ? '已阅读' : '标记已阅读'}</button></div>`;
}

function renderLearningMaterials(materials) {
  if (!materials?.length) return '<div class="empty">暂无学习材料</div>';
  const groups = [
    { scope: 'common', title: '通用课程', hint: '适合全体 IT 审计学员复用的基础能力课程。' },
    { scope: 'personal', title: '个人课程', hint: '围绕你当前任务、能力短板和项目安排配置。' },
  ];
  return groups.map(group => {
    const items = materials.filter(item => (item.courseScope || 'personal') === group.scope);
    if (!items.length) return '';
    return `<section class="training-material-group"><div class="training-material-group-head"><strong>${group.title}</strong><span>${group.hint}</span></div><div class="training-material-list">${items.map(renderLearningMaterial).join('')}</div></section>`;
  }).join('');
}

function renderLearningCompletion(task) {
  if (task.submissionRequired) return '';
  if (task.status === 'completed') return `<div class="training-learning-complete">${tag('学习任务已完成', 'green')}</div>`;
  const unread = Number(task.unreadMaterialCount || 0);
  if (unread) return `<div class="training-learning-complete"><span class="muted">请先阅读并标记剩余 ${unread} 项学习材料，再完成本任务。</span></div>`;
  return `<div class="training-learning-complete"><button type="button" data-training-complete-learning="${task.id}">完成学习任务</button></div>`;
}

function renderTaskLoopDetail() {
  const task = taskDetail;
  if (!task) return '';
  const questions = task.selfCheckQuestions || [];
  const relatedSubmission = task.relatedSubmissionTask;
  return `<aside class="training-task-loop-detail"><div class="training-detail-head"><div><h3>${esc(task.title)}</h3></div><button type="button" class="secondary" data-training-close-detail>关闭</button></div>
    <div class="training-task-loop-grid"><div><span class="muted">任务目标</span><p>${esc(task.description || '暂无任务说明')}</p></div><div><span class="muted">预计耗时 / 截止</span><p>${esc(task.estimatedHours ?? '—')} 小时 · ${esc(dateText(task.dueDate))}</p></div><div><span class="muted">完成标准</span><p>${esc(task.completionCriteria || '未设置')}</p></div><div><span class="muted">为什么要学</span><p>${esc(task.purpose || task.description || '未设置')}</p></div></div>
    <div class="training-detail-section"><strong>学习材料</strong>${renderLearningMaterials(task.materials || [])}<p class="muted">完成阅读后，请逐项标记已阅读，再点击“完成学习任务”解锁后续作业。</p>${renderLearningCompletion(task)}</div>
    <div class="training-detail-section"><strong>学习笔记</strong><form id="trainingTaskNoteForm"><textarea name="content" placeholder="记录关键概念、判断依据、易错点和待确认问题…">${esc(task.note || '')}</textarea><div class="actions"><button type="submit" class="secondary">保存笔记</button></div></form></div>
    <div class="training-detail-section"><strong>学习与执行步骤</strong><p>${esc(task.instructions || '未设置')}</p><p class="muted">请按步骤阅读材料、完成每道选择题，再提交任务。全部答对后系统才会判定本日任务过关。</p></div>
    ${task.submissionRequired ? `<div class="training-detail-section"><strong>作业提交</strong><p>${esc(task.submissionTitle || task.title)}<br>${esc(task.submissionRequirements || '请按任务要求提交')}</p><p class="muted">允许形式：${esc(task.submissionType || '文本 / 文件 / 链接')}；${questions.length ? `本作业含 ${questions.length} 道必答题。` : '本作业不含自检题。'}</p>${task.locked ? `<div class="empty">前置任务尚未完成，完成${(task.prerequisites || []).map(item => `「${esc(item.title)}」`).join('、')}后解锁。<div class="actions">${(task.prerequisites || []).map(item => `<button type="button" data-training-task="${item.id}">进入前置任务</button>`).join('')}</div></div>` : renderSubmissionForm(task, questions)}</div>` : `<div class="training-detail-section"><strong>作业提交</strong><p class="muted">这是学习/练习任务，不单独提交作业。</p>${relatedSubmission ? `<div class="practice-notice"><strong>下一步</strong>：请进入「${esc(relatedSubmission.title)}」完成 ${esc(relatedSubmission.questionCount || 0)} 道题并提交作业。<div class="actions"><button type="button" data-training-task="${relatedSubmission.id}">进入本周正式作业</button></div></div>` : '<p class="muted">本周尚未配置需要提交的正式作业。</p>'}</div>`}
    <div class="training-detail-section"><strong>提交历史</strong><div class="training-submission-history">${(task.submissions || []).map(item => `<div class="training-submission-version"><div><strong>V${item.version}</strong><span>${esc(dateText(item.submittedAt))} · ${esc(item.submissionType)}</span></div>${tag(item.status, item.status === 'passed' ? 'green' : item.status === 'revision_required' ? 'amber' : '')}<div class="training-submission-reviews">${(item.reviews || []).map(review => `<p>${review.result === 'passed' ? '通过' : '要求修改'}：${esc(review.comments || '无评语')}</p>`).join('')}</div></div>`).join('') || '<div class="empty">尚未提交。</div>'}</div></div>
  </aside>`;
}

function renderAssignmentWindow() {
  const task = taskDetail;
  if (!assignmentWindowOpen || !task?.submissionRequired) return '';
  const questions = task.selfCheckQuestions || [];
  return `<div class="training-assignment-backdrop" role="presentation"><section class="training-assignment-window" role="dialog" aria-modal="true" aria-label="作业窗口"><div class="training-detail-head"><div><span class="training-eyebrow">作业窗口</span><h3>${esc(task.submissionTitle || task.title)}</h3><p class="muted">${questions.length} 道课件知识选择题，全部答对后方可提交。</p></div><button type="button" class="secondary" data-training-close-assignment>关闭</button></div><div class="training-assignment-body"><div class="training-detail-section"><strong>作业要求</strong><p>${esc(task.submissionRequirements || task.instructions || '请按任务要求完成作业。')}</p></div><div class="training-detail-section"><strong>关联课程</strong>${renderLearningMaterials(task.materials || [])}</div>${renderQuizFeedback()}${assignmentSubmissionResult ? renderAssignmentSubmissionResult() : (task.locked ? `<div class="empty">前置任务尚未完成，完成${(task.prerequisites || []).map(item => `「${esc(item.title)}」`).join('、')}后解锁。<div class="actions">${(task.prerequisites || []).map(item => `<button type="button" data-training-task="${item.id}">进入前置任务</button>`).join('')}</div></div>` : renderSubmissionForm(task, questions))}</div></section></div>`;
}

function renderQuizFeedback() {
  if (!assignmentQuizFeedback.length) return '';
  const statusLabel = item => item.status === 'correct' ? '回答正确' : (item.status === 'missing' ? '尚未作答' : '回答不正确');
  return `<section class="training-quiz-feedback"><strong>逐题结果与解析</strong>${assignmentQuizFeedback.map(item => `<article class="training-quiz-feedback-${esc(item.status || 'incorrect')}"><b>${esc(item.prompt)}</b><span>${statusLabel(item)}</span><p>你的答案：${esc(Array.isArray(item.submittedAnswer) ? item.submittedAnswer.join('、') : item.submittedAnswer || '未作答')}</p><p>正确答案：${esc(Array.isArray(item.correctAnswer) ? item.correctAnswer.join('、') : item.correctAnswer || '—')}</p><p>${esc(item.explanation || '')}</p></article>`).join('')}</section>`;
}

function renderAssignmentSubmissionResult() {
  return `<section class="training-quiz-success"><strong>作业提交成功</strong><p>${esc(assignmentSubmissionResult)}</p><p class="muted">提交记录已更新，可关闭窗口返回本批学习计划。</p><div class="actions"><button type="button" data-training-close-assignment>关闭</button></div></section>`;
}

function renderTaskDetail(task) {
  if (!task) return '<div class="training-task-detail empty">点击任务查看详情</div>';
  return `<aside class="training-task-detail">
    <div class="training-detail-head"><div><span class="muted">${esc(task.taskCode)}</span><h3>${esc(task.title)}</h3></div><button type="button" class="secondary" data-training-close-detail>关闭</button></div>
    <div class="training-detail-grid"><div><span class="muted">状态</span><p>${task.locked ? tag('前置任务未完成', 'amber') : tag(statusLabel(task.status), taskStatusClass(task))}</p></div><div><span class="muted">截止日期</span><p>${esc(dateText(task.dueDate))}</p></div><div><span class="muted">提交</span><p>${task.submissionRequired ? (task.hasSubmission ? '已提交' : '待提交') : '无需提交'}</p></div><div><span class="muted">导师Review</span><p>${task.mentorReviewRequired ? (task.isReviewPending ? '待Review' : '需要Review') : '无需Review'}</p></div></div>
    <div class="training-detail-section"><strong>任务说明</strong><p>${esc(task.description || '暂无说明')}</p></div>
    <div class="training-detail-section"><strong>完成标准</strong><p>${esc(task.completionCriteria || '未设置')}</p></div>
    <div class="training-detail-section"><strong>执行要求</strong><p>${esc(task.instructions || '未设置')}</p></div>
    <div class="training-detail-section"><strong>学习材料</strong>${renderLearningMaterials(task.materials || [])}</div>
  </aside>`;
}

function renderTaskQuestion(question, index) {
  if (typeof question === 'string') {
    return `<article class="practice-question training-quiz-question"><div class="practice-question-head"><div><span class="practice-code">Q${index + 1}</span><strong>完成自检</strong></div><span class="muted">必做</span></div><div class="leetcode-description"><p>${esc(question)}</p></div><label class="training-self-check"><input type="checkbox" name="selfCheck_${index}" value="1">我已完成并确认</label></article>`;
  }
  const options = (question.options || []).map((option, optionIndex) => `<label class="training-quiz-option"><input type="radio" name="selfCheck_${index}" value="${esc(option)}" required><span class="training-quiz-option-key">${String.fromCharCode(65 + optionIndex)}</span><span>${esc(option)}</span></label>`).join('');
  return `<article class="practice-question training-quiz-question"><div class="practice-question-head"><div><span class="practice-code">Q${index + 1}</span><strong>${esc(question.prompt || '')}</strong></div><span class="muted">选择题 · 必须答对</span></div><div class="training-quiz-options">${options}</div></article>`;
}

function collectTaskQuestionAnswers(form) {
  const answers = {};
  form.querySelectorAll('[name^="selfCheck_"]').forEach(input => {
    const index = input.name.replace('selfCheck_', '');
    if (input.type === 'checkbox') answers[index] = input.checked;
    else if (input.type === 'radio') { if (input.checked) answers[index] = input.value; }
    else answers[index] = input.value;
  });
  return answers;
}

function renderTasks() {
  const tasks = overview?.tasks || [];
  const weeks = overview?.weeks || [];
  return `<div class="training-task-list">${weeks.map(week => `<div class="training-week-block">
    <div class="training-week-heading"><div><span class="muted">W${week.weekNo} · ${esc(dateText(week.startDate))} — ${esc(dateText(week.endDate))}</span><h3>${esc(week.title)}</h3></div><div class="training-week-objective">${esc(week.objective || '')}</div></div>
    <div class="table-wrap"><table><thead><tr><th>任务</th><th>排期</th><th>提交</th><th>Review</th><th>状态</th><th></th></tr></thead><tbody>${week.tasks.map(task => `<tr class="training-task-row ${task.id === selectedTaskId ? 'selected' : ''}" data-training-task="${task.id}"><td><strong>${esc(task.taskCode)}</strong><div>${esc(task.title)}</div></td><td>${esc(dateText(task.startDate))} — ${esc(dateText(task.dueDate))}</td><td>${task.submissionRequired ? (task.hasSubmission ? tag('已提交', 'green') : tag('待提交', 'amber')) : '<span class="muted">—</span>'}</td><td>${task.mentorReviewRequired ? (task.isReviewPending ? tag('待Review', 'amber') : '<span class="muted">需Review</span>') : '<span class="muted">—</span>'}</td><td>${tag(statusLabel(task.status), taskStatusClass(task))}</td><td><button class="secondary" type="button" data-training-task="${task.id}">详情</button></td></tr>`).join('') || '<tr><td colspan="6" class="empty">本周暂无任务</td></tr>'}</tbody></table></div>
  </div>`).join('') || '<div class="empty">暂无培养周</div>'}</div>${renderTaskDetail(tasks.find(task => task.id === selectedTaskId))}`;
}

function renderGantt() {
  if (!overview) return '<div class="empty">暂无培养计划</div>';
  const start = dateValue(overview.plan.startDate);
  const end = dateValue(overview.plan.endDate);
  if (!start || !end || end < start) return '<div class="empty">培养计划日期不完整，无法生成甘特图</div>';
  const days = daysBetween(start, end);
  const today = dateValue(overview.today);
  const todayIndex = today && today >= start && today <= end ? dayDiff(today, start) : -1;
  const columns = days.length;
  const dayHeader = days.map(day => `<div class="training-gantt-day ${day.getDay() === 0 || day.getDay() === 6 ? 'weekend' : ''}"><span>${day.getMonth() + 1}/${day.getDate()}</span><small>${['日','一','二','三','四','五','六'][day.getDay()]}</small></div>`).join('');
  const rows = (overview.weeks || []).map(week => `<div class="training-gantt-group"><div class="training-gantt-label training-gantt-week-label"><strong>W${week.weekNo}</strong><span>${esc(week.title)}</span></div><div class="training-gantt-track training-gantt-week-track" style="--gantt-columns:${columns}"><div class="training-gantt-week-band" style="grid-column:${Math.max(1, dayDiff(dateValue(week.startDate), start) + 1)} / ${Math.min(columns + 1, dayDiff(dateValue(week.endDate), start) + 2)}"></div>${todayIndex >= 0 ? `<i class="training-today-line" style="grid-column:${todayIndex + 1}"></i>` : ''}</div>${week.tasks.map(task => {
    const taskStart = dateValue(task.startDate) || dateValue(week.startDate);
    const taskEnd = dateValue(task.dueDate) || dateValue(week.endDate);
    const from = Math.max(0, dayDiff(taskStart, start));
    const to = Math.min(columns - 1, dayDiff(taskEnd, start));
    return `<div class="training-gantt-label training-gantt-task-label" data-training-task="${task.id}"><span>${esc(task.taskCode)}</span><strong>${esc(task.title)}</strong></div><div class="training-gantt-track" style="--gantt-columns:${columns}"><button type="button" class="training-gantt-bar ${taskStatusClass(task)}" style="grid-column:${from + 1} / ${Math.max(from + 2, to + 2)}" data-training-task="${task.id}" title="${esc(task.description || task.title)}"><span>${esc(statusLabel(task.status))}</span></button>${todayIndex >= 0 ? `<i class="training-today-line" style="grid-column:${todayIndex + 1}"></i>` : ''}</div>`;
  }).join('')}</div>`).join('');
  return `<div class="training-gantt-legend"><span><i class="training-legend-dot training-status-not-started"></i>未开始</span><span><i class="training-legend-dot training-status-progress"></i>进行中</span><span><i class="training-legend-dot training-status-review"></i>待Review</span><span><i class="training-legend-dot training-status-revision"></i>修改中</span><span><i class="training-legend-dot training-status-blocked"></i>Blocked</span><span><i class="training-legend-dot training-status-completed"></i>完成</span></div><div class="training-gantt-scroll"><div class="training-gantt" style="--gantt-columns:${columns}"><div class="training-gantt-label training-gantt-axis-label">Plan / Week / Task</div><div class="training-gantt-track training-gantt-axis" style="--gantt-columns:${columns}">${dayHeader}${todayIndex >= 0 ? `<i class="training-today-line" style="grid-column:${todayIndex + 1}"></i>` : ''}</div>${rows}</div></div><div class="training-gantt-note"><span class="training-today-key"></span> 今日：${esc(dateText(overview.today))}；Deadline 以任务条右端为准。点击任务查看详情，日期通过任务编辑调整。</div>${renderTaskDetail((overview.tasks || []).find(task => task.id === selectedTaskId))}`;
}

function render() {
  const box = $('developmentContent');
  if (!box) return;
  if (learnerMode) { renderLearner(); return; }
  if (!overview) { box.innerHTML = '<div class="empty">暂无已导入的培养计划</div>'; return; }
  const metrics = overview.metrics || {};
  const planPicker = canSelectTrainingPlan()
    ? `<label>培养计划<select id="trainingPlanSelect">${plans.map(plan => `<option value="${plan.id}" ${plan.id === selectedPlanId ? 'selected' : ''}>${esc(plan.employeeName)} · ${esc(plan.title)} · ${esc(plan.period)}</option>`).join('')}</select></label>`
    : `<span class="muted">当前培养计划：${esc(overview.plan.title || '我的培养计划')}</span>`;
  box.innerHTML = `<div class="training-plan-picker">${planPicker}<span class="muted">当前周：${overview.currentWeekNo ? `第${overview.currentWeekNo}周` : '不在计划周期内'}</span><button type="button" class="secondary" data-training-refresh><i class="ti ti-refresh"></i> 刷新</button></div>
    <div class="training-plan-hero"><div><div class="training-eyebrow">员工</div><h2>${esc(overview.employee.name)}</h2><div class="muted">${esc(overview.plan.title)} · ${esc(dateText(overview.plan.startDate))} — ${esc(dateText(overview.plan.endDate))}</div><p>${esc(overview.plan.overallGoal || '未设置整体目标')}</p></div><div class="training-plan-status">${tag(statusLabel(overview.plan.status), overview.plan.status === 'completed' ? 'green' : '')}</div></div>
    <div class="training-metrics">${renderMetric('总任务', metrics.totalTasks || 0)}${renderMetric('已完成', metrics.completed || 0, 'done')}${renderMetric('待提交', metrics.pendingSubmission || 0, 'attention')}${renderMetric('待Review', metrics.pendingReview || 0, 'attention')}${renderMetric('Blocked', metrics.blocked || 0, 'risk')}</div>
    <div class="training-view-switch"><button type="button" class="${view === 'tasks' ? 'active' : 'secondary'}" data-training-view="tasks"><i class="ti ti-list-check"></i> 任务视图</button><button type="button" class="${view === 'gantt' ? 'active' : 'secondary'}" data-training-view="gantt"><i class="ti ti-chart-gantt"></i> 甘特图</button></div>
    <div class="training-view-content">${view === 'tasks' ? renderTasks() : renderGantt()}</div>`;
  box.querySelector('#trainingPlanSelect')?.addEventListener('change', async event => { selectedPlanId = Number(event.target.value); await loadSelectedPlan(); });
}

export async function loadLearner() {
  const requestSeq = beginDevelopmentViewRequest();
  try {
    setStatus('加载我的培养');
    const data = await request('/api/development/my-training');
    if (!isCurrentDevelopmentViewRequest(requestSeq)) return;
    let handbookUrl = null;
    if (data?.plan) {
      const response = await fetch(`${api}/api/development/my-training/handbook`, {headers: authHeaders()});
      if (response.ok) handbookUrl = URL.createObjectURL(await response.blob());
    }
    if (!isCurrentDevelopmentViewRequest(requestSeq)) { if (handbookUrl) URL.revokeObjectURL(handbookUrl); return; }
    if (personalHandbookUrl) URL.revokeObjectURL(personalHandbookUrl);
    personalHandbookUrl = handbookUrl;
    learnerData = data;
    learnerMode = true;
    document.querySelectorAll('#developmentTabs [data-development-view]').forEach(button => button.classList.toggle('active', button.dataset.developmentView === 'mine'));
    render();
    setStatus('我的培养已加载');
  } catch (error) { if (isCurrentDevelopmentViewRequest(requestSeq)) setStatus(`错误：${error.message}`); }
}

async function loadTaskDetail(taskId) {
  try { setStatus('加载任务详情'); taskDetail = await request(`/api/development/tasks/${taskId}`); selectedTaskId = Number(taskId); assignmentWindowOpen = learnerMode && Boolean(taskDetail.submissionRequired); assignmentQuizFeedback = []; assignmentSubmissionResult = null; render(); setStatus('任务详情已加载'); }
  catch (error) { setStatus(`错误：${error.message}`); }
}

async function loadSelectedPlan({requestSeq = beginDevelopmentViewRequest()} = {}) {
  if (!selectedPlanId) { if (isCurrentDevelopmentViewRequest(requestSeq)) { overview = null; render(); } return; }
  try {
    setStatus('加载培养计划');
    const data = await request(`/api/development/training-plans/${selectedPlanId}/overview`);
    if (!isCurrentDevelopmentViewRequest(requestSeq)) return;
    overview = data;
    selectedTaskId = null;
    render();
    setStatus('培养计划已加载');
  } catch (error) { if (isCurrentDevelopmentViewRequest(requestSeq)) setStatus(`错误：${error.message}`); }
}

export async function loadDevelopmentOverview({silent = false} = {}) {
  if (!canSelectTrainingPlan()) { await loadLearner(); return; }
  const requestSeq = beginDevelopmentViewRequest();
  try {
    const radar = await request('/api/development/mentor-workbench');
    if (!isCurrentDevelopmentViewRequest(requestSeq)) return;
    learnerMode = false;
    overview = null;
    taskDetail = null;
    const box = $('developmentContent');
    if (box) box.innerHTML = renderGlobalRadar(radar);
    setStatus('全局雷达已加载');
  } catch (error) {
    if (!isCurrentDevelopmentViewRequest(requestSeq)) return;
    if (!silent) setStatus(`错误：${error.message}`);
    const box = $('developmentContent');
    if (box) box.innerHTML = `<div class="empty">全局雷达加载失败：${esc(error.message)}</div>`;
  }
}

export function bindDevelopmentOverview() {
  const box = $('developmentContent');
  if (!box) return;
  const tabs = $('developmentTabs');
  tabs?.addEventListener('click', async event => {
    const button = event.target.closest('[data-development-view]');
    if (!button) return;
    event.preventDefault();
    document.querySelectorAll('#developmentTabs [data-development-view]').forEach(item => item.classList.toggle('active', item === button));
    const viewName = button.dataset.developmentView;
    if (viewName === 'mine') await loadLearner();
    else if (viewName === 'mentor') await loadMentorWorkbenchView();
    else if (viewName === 'overview') await loadDevelopmentOverview();
    else if (LEGACY_VIEW_META[viewName]) await loadLegacyView(viewName);
  });
  box.addEventListener('click', async event => {
    const outerView = event.target.closest('[data-development-view]');
    if (outerView) {
      document.querySelectorAll('[data-development-view]').forEach(button => button.classList.toggle('active', button === outerView));
    if (outerView.dataset.developmentView === 'mine') await loadLearner();
      else if (LEGACY_VIEW_META[outerView.dataset.developmentView]) await loadLegacyView(outerView.dataset.developmentView);
      else if (outerView.dataset.developmentView === 'overview' || outerView.dataset.developmentView === 'plans') await loadDevelopmentOverview();
    return;
    }
    const mentorOpen = event.target.closest('[data-open-mentor-workbench]');
    if (mentorOpen) { await loadMentorWorkbenchView(); return; }
    const developmentRefresh = event.target.closest('[data-development-refresh]');
    if (developmentRefresh) { await loadLegacyView(developmentRefresh.dataset.developmentRefresh); return; }
    const viewButton = event.target.closest('[data-training-view]');
    if (viewButton) { view = viewButton.dataset.trainingView; render(); return; }
    if (event.target.closest('[data-training-refresh]')) { await (learnerMode ? loadLearner() : loadDevelopmentOverview()); return; }
    const batchButton = event.target.closest('[data-training-batch]');
    if (batchButton) { selectedLearnerBatchId = Number(batchButton.dataset.trainingBatch); selectedTaskId = null; taskDetail = null; render(); return; }
    if (event.target.closest('[data-training-batch-back]')) { selectedLearnerBatchId = null; selectedTaskId = null; taskDetail = null; render(); return; }
    if (event.target.closest('[data-training-close-assignment]')) { assignmentWindowOpen = false; assignmentQuizFeedback = []; assignmentSubmissionResult = null; selectedTaskId = null; taskDetail = null; render(); return; }
    if (event.target.closest('[data-training-close-detail]')) { selectedTaskId = null; taskDetail = null; render(); return; }
    const coursewareButton = event.target.closest('[data-training-open-courseware]');
    if (coursewareButton) {
      const coursewareWindow = window.open('', '_blank');
      if (!coursewareWindow) { setStatus('浏览器阻止了课程窗口，请允许本站点打开新窗口后重试。'); return; }
      coursewareWindow.opener = null;
      try {
        const response = await fetch(`${api}${coursewareButton.dataset.trainingOpenCourseware}`, {headers: authHeaders()});
        if (!response.ok) throw new Error('课程内容加载失败');
        const url = URL.createObjectURL(await response.blob());
        coursewareWindow.location.replace(url);
        window.setTimeout(() => URL.revokeObjectURL(url), 60000);
      } catch (error) { coursewareWindow.close(); setStatus(`打开课程失败：${error.message}`); }
      return;
    }
    const materialButton = event.target.closest('[data-training-material-read]');
    if (materialButton && taskDetail) {
      try { await request(`/api/development/tasks/${taskDetail.id}/materials/${materialButton.dataset.trainingMaterialRead}/read`, {method: 'POST', body: '{}'}); taskDetail = await request(`/api/development/tasks/${taskDetail.id}`); render(); }
      catch (error) { setStatus(`错误：${error.message}`); }
      return;
    }
    const completeLearningButton = event.target.closest('[data-training-complete-learning]');
    if (completeLearningButton && taskDetail) {
      try {
        await request(`/api/development/tasks/${completeLearningButton.dataset.trainingCompleteLearning}/complete-learning`, {method: 'POST', body: '{}'});
        assignmentWindowOpen = false;
        taskDetail = null;
        await loadLearner();
        setStatus('学习任务已完成，后续作业已解锁');
      } catch (error) { setStatus(`完成学习任务失败：${error.message}`); }
      return;
    }
    if (event.target.closest('[data-training-open-blocker]')) { blockerFormOpen = true; render(); return; }
    if (event.target.closest('[data-training-close-blocker]')) { blockerFormOpen = false; render(); return; }
    const taskButton = event.target.closest('[data-training-task]');
    if (taskButton) {
      if (learnerMode) await loadTaskDetail(Number(taskButton.dataset.trainingTask));
      else { selectedTaskId = Number(taskButton.dataset.trainingTask); render(); }
    }
  });
  box.addEventListener('submit', async event => {
    if (event.target.id === 'trainingTaskNoteForm') {
      event.preventDefault();
      if (!taskDetail) return;
      try {
        const content = event.target.elements.content.value;
        await request(`/api/development/tasks/${taskDetail.id}/note`, {method: 'PUT', body: JSON.stringify({content})});
        taskDetail.note = content;
        setStatus('学习笔记已保存');
      } catch (error) { setStatus(`保存笔记失败：${error.message}`); }
      return;
    }
    if (event.target.id === 'trainingSubmissionForm') {
      event.preventDefault();
      const form = event.target;
      const answers = collectTaskQuestionAnswers(form);
      try {
        const result = await request(`/api/development/tasks/${taskDetail.id}/submit`, {method: 'POST', body: JSON.stringify({selfCheckAnswers: answers})});
        assignmentQuizFeedback = result.questionFeedback || [];
        const quizResult = result.quiz ? `，答对 ${result.quiz.correctCount}/${result.quiz.total} 题` : '';
        assignmentSubmissionResult = `${result.message || '作业已提交'}${quizResult}${result.taskStatus === 'submitted' ? '，等待导师 Review。' : '，本任务已完成。'}`;
        taskDetail = await request(`/api/development/tasks/${taskDetail.id}`);
        await loadLearner();
        assignmentWindowOpen = true;
        render();
        setStatus(assignmentSubmissionResult);
      }
      catch (error) { assignmentSubmissionResult = null; assignmentQuizFeedback = error.detail?.questionFeedback || []; render(); setStatus(`错误：${error.message}`); }
      return;
    }
    if (event.target.id !== 'myTrainingBlockerForm') return;
    event.preventDefault();
    const form = event.target;
    const payload = Object.fromEntries(new FormData(form).entries());
    payload.taskId = Number(payload.taskId);
    try { await request('/api/development/my-training/blockers', {method: 'POST', body: JSON.stringify(payload)}); blockerFormOpen = false; await loadLearner(); }
    catch (error) { setStatus(`错误：${error.message}`); }
  });
}

async function loadMentorWorkbenchView() {
  const requestSeq = beginDevelopmentViewRequest();
  try {
    const module = await import('./mentorWorkbench.js?v=20260918-review-access3');
    if (!isCurrentDevelopmentViewRequest(requestSeq)) return;
    await module.loadMentorWorkbench();
  } catch (error) {
    if (isCurrentDevelopmentViewRequest(requestSeq)) setStatus(`错误：${error.message}`);
  }
}
