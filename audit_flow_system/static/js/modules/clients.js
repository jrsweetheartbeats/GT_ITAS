import { request } from '../api.js?v=20260630a';
import { state } from '../state.js?v=20260630a';
import { $, cleanClientDescription, closeModal, esc, fillSelect, formData, openModal, setStatus, tag } from '../utils.js?v=20260816a';

export const clientIssueTabsExtension = {
  renderTabs(client) {
    return `<button type="button" class="secondary" data-client-action="issues" data-client-id="${esc(client.id)}">查看清单</button><button type="button" class="secondary" data-client-action="focus" data-client-id="${esc(client.id)}">引用建项</button>`;
  }
};

let refreshAll = async () => {};

const clientActions = {
  edit: (id) => editClient(id),
  contact: (id) => openClientContactModal(id),
  issues: (id) => openClientIssues(id),
  focus: (id) => openProjectWithClientIssues(id),
  delete: (id) => deleteClient(id)
};

export function renderClients() {
  fillSelect($('projectClientSelect'), state.clients, c => c.entity_name);
  fillSelect($('clientITSelect'), state.clients, c => c.entity_name);
  const issueCount = (client) => Number(state.clientIssuesByClient[client.id]?.issue_count || 0);
  $('clientRows').innerHTML = state.clients.map(c => `
    <tr>
      <td class="nowrap">#${esc(c.id)}</td>
      <td><strong>${esc(c.entity_name)}</strong><div class="muted">${esc(cleanClientDescription(c.description) || '行业未维护')}</div></td>
      <td>${tag(cleanClientDescription(c.description) || '未维护', cleanClientDescription(c.description) ? 'blue' : 'amber')}</td>
      <td>${(c.it_contacts || []).map(x => `<strong>${esc(x.name)}</strong> ${esc(x.title || '')}<div class="muted">${esc(x.phone || '')} ${esc(x.email || '')}</div>`).join('<br>') || '<span class="muted">暂无联系人</span>'}</td>
      <td><div>${tag('ITGC', 'blue')} ${tag('ITAC', 'green')} ${tag('资料清单', 'amber')}</div><div class="muted">按年度项目底稿和资料清单执行，具体程序以当前项目为准。</div></td>
      <td><div class="actions">${clientIssueTabsExtension.renderTabs(c)}${state.clientIssuesByClient[c.id] ? tag(issueCount(c) ? issueCount(c) + '项历史问题' : '暂无历史问题', issueCount(c) ? 'red' : 'green') : tag('点击查看', 'blue')}</div></td>
      <td class="actions">
        <button class="secondary" data-client-action="edit" data-client-id="${esc(c.id)}">编辑</button>
        <button class="secondary" data-client-action="contact" data-client-id="${esc(c.id)}">联系人</button>
        <button class="danger" data-client-action="delete" data-client-id="${esc(c.id)}">删除</button>
      </td>
    </tr>
  `).join('') || '<tr><td colspan="7" class="empty">暂无客户</td></tr>';
}

function setClientFormMode(client = null) {
  const form = $('clientForm');
  state.editingClientId = client ? client.id : null;
  $('clientFormTitle').textContent = client ? `编辑客户 #${client.id}` : '新增客户';
  $('clientSubmitBtn').textContent = client ? '保存修改' : '创建客户';
  openModal('clientModal');
  if (!client) {
    form.reset();
    return;
  }
  form.elements.entity_name.value = client.entity_name || '';
  form.elements.description.value = cleanClientDescription(client.description);
  if (form.elements.contact_name) form.elements.contact_name.value = '';
  if (form.elements.contact_title) form.elements.contact_title.value = '';
  if (form.elements.contact_phone) form.elements.contact_phone.value = '';
  if (form.elements.contact_email) form.elements.contact_email.value = '';
}

export function openNewClientForm() {
  state.editingClientId = null;
  $('clientForm').reset();
  $('clientFormTitle').textContent = '新增客户';
  $('clientSubmitBtn').textContent = '创建客户';
  openModal('clientModal');
}

export function openClientContactModal(clientId = null) {
  if (clientId) $('clientITSelect').value = clientId;
  openModal('clientContactModal');
}

function clientIssueData(clientId) {
  return state.clientIssuesByClient[clientId] || null;
}

function issueProjectYear(projectIssue) {
  const project = state.projects.find(item => Number(item.id) === Number(projectIssue.project_id));
  if (project?.audit_year) return String(project.audit_year);
  const matched = String(projectIssue.project_name || '').match(/20\d{2}/);
  return matched ? matched[0] : '未维护';
}

function issueTrend(data) {
  const counts = new Map();
  (data?.projects || []).forEach(project => {
    const year = issueProjectYear(project);
    counts.set(year, (counts.get(year) || 0) + (project.issues || []).length);
  });
  return Array.from(counts.entries()).sort(([a], [b]) => String(a).localeCompare(String(b)));
}

function renderIssueTrend(data) {
  const trend = issueTrend(data);
  if (!trend.length) return '<div class="empty">暂无历年趋势</div>';
  const max = Math.max(1, ...trend.map(([, count]) => count));
  return `
    <div class="issue-trend-bars">
      ${trend.map(([year, count]) => `<div class="issue-trend-bar"><span>${esc(year)}</span><strong style="--bar:${Math.max(6, Math.round(count / max * 100))}%"></strong><em>${esc(count)}</em></div>`).join('')}
    </div>
  `;
}

function renderClientIssuePanel() {
  const panel = $('clientIssuePanel');
  const tabs = $('clientIssueTabs');
  const content = $('clientIssueContent');
  if (!panel || !tabs || !content) return;

  const client = state.clients.find(row => row.id === state.selectedClientId);
  if (!client) {
    panel.classList.add('hidden');
    tabs.innerHTML = '';
    content.innerHTML = '';
    return;
  }

  panel.classList.remove('hidden');
  const data = clientIssueData(client.id);
  if (!data) {
    tabs.innerHTML = '';
    content.innerHTML = `<div class="empty">正在加载客户问题发现清单...</div>`;
    return;
  }

  const projects = Array.isArray(data.projects) ? data.projects : [];
  if (!projects.length) {
    tabs.innerHTML = '';
    content.innerHTML = `<div class="empty">该客户暂无可查看项目或 C21-1 底稿内容。</div>`;
    return;
  }

  if (!state.selectedClientIssueProjectId || !projects.some(p => p.project_id === state.selectedClientIssueProjectId)) {
    state.selectedClientIssueProjectId = projects[0].project_id;
  }
  const selectedProject = projects.find(p => p.project_id === state.selectedClientIssueProjectId);
  const rows = Array.isArray(selectedProject?.issues) ? selectedProject.issues : [];
  tabs.innerHTML = projects.map(project => `
    <button type="button" class="${project.project_id === state.selectedClientIssueProjectId ? 'active' : ''}" data-client-issue-project="${esc(project.project_id)}">
      ${esc(project.project_name || `项目 #${project.project_id}`)}
    </button>
  `).join('');

  const issueRows = rows.length
    ? rows.map(row => `
      <tr>
        <td>${esc(row.issue_no || row.row_no || '')}</td>
        <td><strong>${esc(row.title || '未命名问题')}</strong><div class="muted">${esc(row.description || '')}</div></td>
        <td>${esc(row.control_code || '')}</td>
        <td>${tag(row.severity || '未分级', row.severity === 'high' ? 'red' : row.severity === 'medium' ? 'amber' : 'blue')}</td>
        <td>${esc(row.owner || '')}</td>
        <td>${esc(row.status || '')}</td>
      </tr>
    `).join('')
    : '<tr><td colspan="6" class="empty">当前项目 C21-1 暂无问题发现记录。</td></tr>';

  const workpaperStatus = selectedProject.error
    ? `<div class="subtle-note">${esc(selectedProject.error)}</div>`
    : `<div class="muted">底稿：${esc(selectedProject.workpaper_code || '未识别')} ${esc(selectedProject.workpaper_name || '')}</div>`;

  content.innerHTML = `
    <h3>${esc(data.entity_name || client.entity_name)} / ${esc(selectedProject.project_name || '')} / C21-1</h3>
    <div class="detail-grid">
      <div class="detail-card"><span>项目数</span><strong>${esc(data.project_count || 0)}</strong></div>
      <div class="detail-card"><span>问题数</span><strong>${esc(data.issue_count || 0)}</strong></div>
      <div class="detail-card"><span>当前项目问题</span><strong>${esc(rows.length)}</strong></div>
    </div>
    <div class="history-box-head">
      <strong>历年问题趋势</strong>
      <button class="secondary" type="button" data-client-action="focus" data-client-id="${esc(client.id)}">引用为新项目重点关注</button>
    </div>
    ${renderIssueTrend(data)}
    ${workpaperStatus}
    <div class="table-wrap"><table><thead><tr><th>编号/行</th><th>问题</th><th>控制点</th><th>级别</th><th>责任人</th><th>状态</th></tr></thead><tbody>${issueRows}</tbody></table></div>
  `;
}

async function loadClientIssueProject(projectId) {
  state.selectedClientIssueProjectId = Number(projectId);
  renderClientIssuePanel();
}

async function openClientIssues(id) {
  state.selectedClientId = Number(id);
  state.selectedClientIssueProjectId = null;
  renderClientIssuePanel();
  try {
    state.clientIssuesByClient[id] = await request(`/api/clients/${id}/issues`);
    const firstProject = state.clientIssuesByClient[id].projects?.[0];
    if (firstProject) state.selectedClientIssueProjectId = firstProject.project_id;
    renderClientIssuePanel();
    setStatus('就绪');
  } catch (err) {
    state.clientIssuesByClient[id] = {id, entity_name: state.clients.find(c => c.id === id)?.entity_name || '', projects: [], issues: [], project_count: 0, issue_count: 0};
    renderClientIssuePanel();
    setStatus('错误：' + err.message);
  }
}

async function openProjectWithClientIssues(id) {
  if (!state.clientIssuesByClient[id]) {
    try {
      state.clientIssuesByClient[id] = await request(`/api/clients/${id}/issues`);
    } catch (err) {
      setStatus('错误：' + err.message);
      return;
    }
  }
  window.activateAppSection?.('projects');
  await window.openProjectFromClientIssues?.(id);
}

function editClient(id) {
  const client = state.clients.find(c => c.id === id);
  if (!client) return setStatus('客户不存在');
  setClientFormMode(client);
  window.activateAppSection?.('clients');
  setStatus(`正在编辑客户 #${id}`);
}

async function deleteClient(id) {
  if (!confirm('确认删除该客户信息？')) return;
  try {
    await request(`/api/clients/${id}`, {method: 'DELETE'});
    if (state.editingClientId === id) setClientFormMode(null);
    await refreshAll();
  } catch (err) { setStatus('错误：' + err.message); }
}

export function bindClients(options) {
  refreshAll = options.refreshAll;

  $('newClientBtn').addEventListener('click', openNewClientForm);
  $('refreshClientsBtn').addEventListener('click', refreshAll);
  $('cancelClientEditBtn').addEventListener('click', () => { state.editingClientId = null; closeModal('clientModal'); });
  $('clientRows').addEventListener('click', (event) => {
    const button = event.target.closest('[data-client-action]');
    if (!button) return;
    const action = clientActions[button.dataset.clientAction];
    if (action) action(Number(button.dataset.clientId));
  });
  $('clientIssueTabs').addEventListener('click', (event) => {
    const button = event.target.closest('[data-client-issue-project]');
    if (button) loadClientIssueProject(Number(button.dataset.clientIssueProject));
  });
  $('clientForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const data = formData(e.target);
      const contact = {
        name: data.contact_name || '',
        title: data.contact_title || '',
        phone: data.contact_phone || '',
        email: data.contact_email || '',
        department: '',
        responsibility: '企业对接人',
      };
      const clientData = {
        entity_name: data.entity_name || '',
        description: data.description || '',
        finance_director_name: '',
        finance_director_phone: '',
        finance_director_email: '',
      };
      let savedClient = null;
      if (state.editingClientId) {
        savedClient = await request(`/api/clients/${state.editingClientId}`, {method: 'PATCH', body: JSON.stringify(clientData)});
      } else {
        savedClient = await request('/api/clients', {method: 'POST', body: JSON.stringify(clientData)});
        if (savedClient?.id && contact.name) {
          await request(`/api/clients/${savedClient.id}/it-contacts`, {method: 'POST', body: JSON.stringify(contact)});
        }
      }
      closeModal('clientModal');
      state.editingClientId = null;
      await refreshAll();
    } catch (err) { setStatus('错误：' + err.message); }
  });
  $('clientITForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = formData(e.target);
    if (!data.client_id) return setStatus('请先选择客户');
    const clientId = data.client_id;
    delete data.client_id;
    try {
      await request(`/api/clients/${clientId}/it-contacts`, {method: 'POST', body: JSON.stringify(data)});
      e.target.reset();
      closeModal('clientContactModal');
      await refreshAll();
    } catch (err) { setStatus('错误：' + err.message); }
  });

  window.editClient = editClient;
  window.deleteClient = deleteClient;
  window.openClientContactModal = openClientContactModal;
}
