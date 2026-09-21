const tokenKey = 'audit_flow_token';
const params = new URLSearchParams(location.search);
const taskId = Number(params.get('task') || '');
const statusBox = document.getElementById('status');
const viewer = document.getElementById('viewer');
const saveTimers = new Map();

function token() {
  return localStorage.getItem(tokenKey) || '';
}

function setStatus(message, isError = false) {
  statusBox.textContent = message;
  statusBox.classList.toggle('hidden', !message);
  statusBox.style.color = isError ? '#b91c1c' : '';
}

async function api(path, options = {}) {
  const headers = {Authorization: `Bearer ${token()}`, ...(options.headers || {})};
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {...options, headers});
  if (response.status === 401) throw new Error('登录已失效，请回到 ITAS 重新登录后再打开课件');
  if (!response.ok) {
    let detail = await response.text();
    try { detail = JSON.parse(detail).detail || detail; } catch {}
    throw new Error(typeof detail === 'string' ? detail : '请求失败');
  }
  const type = response.headers.get('content-type') || '';
  if (type.includes('application/json')) return response.json();
  return response.text();
}

function chapterMeta(heading) {
  return {
    key: heading.getAttribute('data-chapter-key') || '',
    module: heading.getAttribute('data-chapter-module') || '课件笔记',
    title: heading.textContent.trim(),
  };
}

function splitChapters(main) {
  const nodes = [...main.childNodes];
  const chapters = [];
  let current = null;
  const start = (heading) => {
    current = {heading, nodes: [], ...chapterMeta(heading)};
    chapters.push(current);
  };
  for (const node of nodes) {
    if (node.nodeType === Node.ELEMENT_NODE && node.tagName === 'H2') {
      start(node);
      continue;
    }
    if (!current) continue;
    current.nodes.push(node);
  }
  return chapters.filter(item => item.key);
}

function renderChapter(chapter, saved) {
  const body = document.createElement('div');
  body.className = 'chapter-body';
  body.append(chapter.heading.cloneNode(true));
  for (const node of chapter.nodes) body.append(node.cloneNode(true));
  const aside = document.createElement('aside');
  aside.className = 'chapter-note';
  aside.innerHTML = `<label>${chapter.module} · 学习笔记</label><textarea data-chapter-key="${chapter.key}" placeholder="在这里记录这一章的要点、判断口径和待确认问题…">${saved}</textarea><small data-note-status="${chapter.key}">输入后自动保存</small>`;
  const wrap = document.createElement('section');
  wrap.className = 'chapter';
  wrap.append(body, aside);
  return wrap;
}

function scheduleSave(task, textarea) {
  const key = textarea.dataset.chapterKey;
  const status = viewer.querySelector(`[data-note-status="${key}"]`);
  if (status) {
    status.textContent = '正在保存…';
    status.className = '';
  }
  clearTimeout(saveTimers.get(key));
  saveTimers.set(key, setTimeout(async () => {
    try {
      await api(`/api/development/tasks/${task}/courseware-notes`, {
        method: 'PUT',
        body: JSON.stringify({chapterKey: key, content: textarea.value}),
      });
      if (status) {
        status.textContent = '已自动保存';
        status.className = 'saved';
      }
    } catch (error) {
      if (status) {
        status.textContent = error.message;
        status.className = 'error';
      }
    }
  }, 500));
}

async function boot() {
  if (!taskId) { setStatus('缺少任务编号', true); return; }
  if (!token()) { setStatus('未登录，请先打开 ITAS 登录后再进入课件', true); return; }
  try {
    const [html, notePayload] = await Promise.all([
      api(`/api/development/tasks/${taskId}/courseware`),
      api(`/api/development/tasks/${taskId}/courseware-notes`),
    ]);
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const main = doc.querySelector('main');
    if (!main) throw new Error('课件内容为空');
    const notes = Object.fromEntries((notePayload.notes || []).map(item => [item.key, item.content || '']));
    const head = document.createElement('header');
    head.className = 'viewer-head';
    const meta = main.querySelector('.meta');
    const title = main.querySelector('h1');
    const toc = main.querySelector('.toc');
    if (meta) head.append(meta);
    if (title) head.append(title);
    viewer.innerHTML = '';
    viewer.append(head);
    if (toc) viewer.append(toc);
    for (const chapter of splitChapters(main)) viewer.append(renderChapter(chapter, notes[chapter.key] || ''));
    document.title = `${title?.textContent || '学习课件'}｜学习课件`;
    viewer.classList.remove('hidden');
    setStatus('');
    viewer.addEventListener('input', event => {
      const textarea = event.target.closest('textarea[data-chapter-key]');
      if (textarea) scheduleSave(taskId, textarea);
    });
  } catch (error) {
    setStatus(error.message, true);
  }
}

boot();
