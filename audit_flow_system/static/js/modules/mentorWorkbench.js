import { request } from '../api.js?v=20260920-state12';
import { $, esc, setStatus, tag } from '../utils.js?v=20260630b';

let workbench = null;
let selectedStudentPlanId = null;
let submissionDetail = null;
let assessmentDetail = null;
let blockerDetail = null;

function selectedStudent() {
  return (workbench?.students || []).find(item => Number(item.planId) === Number(selectedStudentPlanId)) || null;
}

function renderStudentSelector() {
  const students = workbench?.students || [];
  return `<label class="mentor-student-select">选择学员<select id="mentorStudentSelect"><option value="">请选择学员</option>${students.map(student => `<option value="${student.planId}" ${Number(student.planId) === Number(selectedStudentPlanId) ? 'selected' : ''}>${esc(student.employeeName)} · 待Review ${student.pendingReview || 0} · 活跃度 ${student.activityScore || 0}</option>`).join('')}</select></label>`;
}

function renderStudentTasks() {
  const student = selectedStudent();
  if (!student) return '<div class="empty">点击上方学员查看其全部任务与待 Review 作业。</div>';
  const status = task => task.isReviewPending ? tag('待Review', 'amber') : tag(task.status === 'completed' ? '完成' : (task.status || '未开始'), task.status === 'completed' ? 'green' : '');
  return `<div class="mentor-task-list">${(student.tasks || []).map(task => `<div class="mentor-task-item"><div><strong>${esc(task.taskCode)} · ${esc(task.title)}</strong><small>截止 ${esc(String(task.dueDate || '—').slice(0, 10))}${task.submittedAt ? ` · 提交 ${esc(String(task.submittedAt).slice(0, 16))}` : ''}</small></div>${status(task)}${task.isReviewPending ? `<button type="button" data-mentor-action="review" data-mentor-id="${task.latestSubmissionId || ''}" data-mentor-plan="${student.planId}">打开并 Review</button>` : ''}</div>`).join('') || '<div class="empty">该学员暂无任务。</div>'}</div>`;
}

function renderActions() {
  const student = selectedStudent();
  if (!student) return '<div class="empty">请先选择学员，再查看需要处理的作业。</div>';
  const items = (workbench?.actionItems || []).filter(item => Number(item.planId) === Number(student.planId) && ['review', 'overdue'].includes(item.type));
  const labels = {review: '打开并 Review', overdue: '查看逾期作业'};
  return `<div class="mentor-action-list">${items.map(item => `<button type="button" class="mentor-action-item mentor-action-${esc(item.type)}" data-mentor-action="${item.type}" data-mentor-id="${item.id}" data-mentor-plan="${item.planId}"><span class="mentor-action-kind">${esc(labels[item.type])}</span><strong>${esc(item.title || '培养作业')}</strong><small>${item.createdAt ? `提交于 ${esc(String(item.createdAt).slice(0,16))}` : `截止 ${esc(String(item.dueDate || '—').slice(0,10))}`}</small></button>`).join('') || '<div class="empty">该学员当前没有待处理作业。</div>'}</div>`;
}

function renderSubmission() {
  if (!submissionDetail) return '';
  const task = submissionDetail.task;
  const submissions = submissionDetail.submissions || [];
  const reviewForm = submissions.length ? `<form id="mentorReviewForm" class="mentor-review-form"><label>Review结论<select name="result"><option value="passed">通过</option><option value="revision_required">要求修改</option></select></label><label>Review comments<textarea name="comments" required placeholder="请写明结论依据或具体改进要求"></textarea></label><label>评分 <span class="muted">满分 100</span><input name="score" type="text" inputmode="numeric" pattern="[0-9]*" placeholder="请输入 0–100"></label><button type="submit">保存 Review</button></form>` : '<div class="empty">该作业尚未提交，暂不能 Review。请跟进学员完成在线作业。</div>';
  return `<div class="mentor-detail-panel"><div class="mentor-detail-head"><div><span class="muted">${esc(submissionDetail.employee.name)}</span><h3>${esc(task.title)}</h3></div><button type="button" class="secondary" data-mentor-close-detail>关闭</button></div><div class="mentor-requirement-grid"><div><span>任务要求</span><p>${esc(task.instructions || task.description || '')}</p></div><div><span>完成标准</span><p>${esc(task.completionCriteria || '')}</p></div></div><div class="mentor-version-list">${submissions.map(item => `<div class="mentor-version"><div><strong>V${item.version}</strong><span>${esc(String(item.submittedAt || '').slice(0,16))} · ${esc(item.submissionType)}</span></div><div class="mentor-self-check">已完成 ${Object.keys(item.selfCheckAnswers || {}).length} 道在线题目</div>${(item.reviews || []).map(review => `<div class="mentor-review-history">${tag(review.result === 'passed' ? '通过' : '要求修改', review.result === 'passed' ? 'green' : 'amber')} ${esc(review.comments || '')}</div>`).join('')}</div>`).join('')}</div>${reviewForm}</div>`;
}

function render() {
  const box = $('developmentContent');
  if (!box || !workbench) return;
  const selected = selectedStudent();
  const actionCount = selected ? (workbench.actionItems || []).filter(item => Number(item.planId) === Number(selected.planId) && ['review', 'overdue'].includes(item.type)).length : 0;
  box.innerHTML = `<div class="mentor-workbench-head"><div><div class="training-eyebrow">导师入口</div><h2>Mentor 指挥台</h2><p class="muted">选择学员后查看其任务与待处理作业；点击“打开并 Review”进入作业详情。</p></div><button type="button" class="secondary" data-mentor-refresh>刷新</button></div><section class="mentor-section mentor-student-picker"><div class="mentor-section-head"><h3>学员列表</h3></div>${renderStudentSelector()}</section>${selected ? `<section class="mentor-section"><div class="mentor-section-head"><h3>${esc(selected.employeeName)}的任务</h3><span class="muted">${(selected.tasks || []).length} 项</span></div>${renderStudentTasks()}</section><section class="mentor-section"><div class="mentor-section-head"><h3>需要我处理的作业</h3><span class="muted">${actionCount} 项</span></div>${renderActions()}</section>` : '<section class="mentor-section"><div class="empty">尚未选择学员。</div></section>'}${renderSubmission()}`;
}

export async function loadMentorWorkbench() {
  try {
    setStatus('加载 Mentor 指挥台');
    workbench = await request('/api/development/mentor-workbench');
    if (selectedStudentPlanId && !(workbench.students || []).some(item => Number(item.planId) === Number(selectedStudentPlanId))) selectedStudentPlanId = null;
    submissionDetail = null; assessmentDetail = null; blockerDetail = null;
    render(); setStatus('Mentor 指挥台已加载');
  } catch (error) {
    setStatus(`错误：${error.message}`);
    const box = $('developmentContent'); if (box) box.innerHTML = `<div class="empty">Mentor 指挥台加载失败：${esc(error.message)}</div>`;
  }
}

export function bindMentorWorkbench() {
  const box = $('developmentContent');
  if (!box) return;
  box.addEventListener('click', async event => {
    if (event.target.closest('[data-mentor-refresh]')) { await loadMentorWorkbench(); return; }
    if (event.target.closest('[data-mentor-close-detail]')) { submissionDetail = null; render(); return; }
    const studentButton = event.target.closest('[data-mentor-student]');
    if (studentButton) { selectedStudentPlanId = Number(studentButton.dataset.mentorStudent); submissionDetail = null; render(); return; }
    const action = event.target.closest('[data-mentor-action]');
    if (!action) return;
    try {
      selectedStudentPlanId = Number(action.dataset.mentorPlan) || selectedStudentPlanId;
      if (action.dataset.mentorAction === 'review') {
        submissionDetail = await request(`/api/development/mentor/submissions/${action.dataset.mentorId}`);
        render();
        requestAnimationFrame(() => document.querySelector('.mentor-detail-panel')?.scrollIntoView({behavior: 'smooth', block: 'start'}));
      } else if (action.dataset.mentorAction === 'blocker') {
        setStatus('请先在学员任务中查看关联任务；卡点处理入口正在整理。');
      } else if (action.dataset.mentorAction === 'overdue') {
        submissionDetail = await request(`/api/development/mentor/tasks/${action.dataset.mentorId}`);
        render();
        requestAnimationFrame(() => document.querySelector('.mentor-detail-panel')?.scrollIntoView({behavior: 'smooth', block: 'start'}));
      }
    } catch (error) { setStatus(`打开 Review 失败：${error.message}`); }
  });
  box.addEventListener('change', event => {
    const select = event.target.closest('#mentorStudentSelect');
    if (!select) return;
    selectedStudentPlanId = select.value ? Number(select.value) : null;
    submissionDetail = null;
    render();
  });
  box.addEventListener('submit', async event => {
    if (event.target.id !== 'mentorReviewForm') return;
    event.preventDefault();
    const form = event.target;
    try {
      const latest = submissionDetail.submissions[submissionDetail.submissions.length - 1];
      await request(`/api/development/submissions/${latest.id}/review`, {method: 'POST', body: JSON.stringify({result: form.result.value, comments: form.comments.value, score: form.score.value ? Number(form.score.value) : null})});
      await loadMentorWorkbench();
      setStatus('Review 已保存');
    } catch (error) { setStatus(`保存 Review 失败：${error.message}`); }
  });
}
