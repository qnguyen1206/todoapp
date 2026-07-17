/* ── State ──────────────────────────────────────────────────────── */
let allTasks      = [];
let sortKey       = 'due_date';
let sortAsc       = true;
let calYear       = new Date().getFullYear();
let calMonth      = new Date().getMonth() + 1;  // 1-based
let aiModels      = [];
let use24Hour     = true;

/* ── Tab Switching ─────────────────────────────────────────────── */
document.querySelectorAll('.tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(s => s.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');

    if (btn.dataset.tab === 'tasks')    loadTasks();
    if (btn.dataset.tab === 'daily')    loadDaily();
    if (btn.dataset.tab === 'ai')       initAI();
    if (btn.dataset.tab === 'calendar') renderCalendar();
    if (btn.dataset.tab === 'weekly')   loadWeekly();
    if (btn.dataset.tab === 'settings') loadSettings();
  });
});

/* ── Helpers ───────────────────────────────────────────────────── */
async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  return r.json();
}

function fmtTime(t) {
  if (!t || t === '' || t === '--:--') return '–';
  if (!use24Hour) {
    const [h, m] = t.split(':').map(Number);
    const ampm = h >= 12 ? 'PM' : 'AM';
    return `${h % 12 || 12}:${String(m).padStart(2,'0')} ${ampm}`;
  }
  return t;
}

function priorityPill(p) {
  return `<span class="priority-pill p${p}">${p}</span>`;
}

function escHtml(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;')
                        .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* ── Character / Stats ─────────────────────────────────────────── */
async function loadCharacter() {
  try {
    const d = await api('GET', '/api/character');
    document.getElementById('level-badge').textContent = `Lv ${d.level ?? 0}`;
    document.getElementById('xp-badge').textContent    = `XP ${d.xp_current}/${d.xp_needed}`;
  } catch {}
}

/* ══════════════════════════════════════════════════════════════════
   TASK LIST
══════════════════════════════════════════════════════════════════ */
async function loadTasks() {
  document.getElementById('task-tbody').innerHTML =
    '<tr><td colspan="5" class="empty-msg">Loading…</td></tr>';
  try {
    const data = await api('GET', '/api/tasks');
    allTasks = data.tasks ?? [];
    renderTasks();
    document.getElementById('remaining-badge').textContent = `Tasks: ${allTasks.filter(t => !t.completed).length}`;
    loadCharacter();
  } catch (e) {
    document.getElementById('task-tbody').innerHTML =
      `<tr><td colspan="5" class="empty-msg">Error: ${escHtml(e.message)}</td></tr>`;
  }
}

function sortTasks(key) {
  if (sortKey === key) sortAsc = !sortAsc;
  else { sortKey = key; sortAsc = true; }
  renderTasks();
}

function renderTasks() {
  const tbody = document.getElementById('task-tbody');
  const tasks = [...allTasks].filter(t => !t.completed);

  tasks.sort((a, b) => {
    let va = a[sortKey] ?? '', vb = b[sortKey] ?? '';
    if (sortKey === 'priority') { va = +va; vb = +vb; }
    if (sortKey === 'due_date') {
      const toTs = s => { try { const p = s.split('-'); return new Date(+p[2],+p[0]-1,+p[1]).getTime(); } catch { return 0; }};
      va = toTs(va); vb = toTs(vb);
    }
    return sortAsc ? (va > vb ? 1 : va < vb ? -1 : 0) : (va < vb ? 1 : va > vb ? -1 : 0);
  });

  if (!tasks.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-msg">No tasks — add one above!</td></tr>';
    return;
  }

  tbody.innerHTML = tasks.map(t => {
    const id    = escHtml(t.task_id);
    const title = escHtml(t.title);
    const notes = escHtml(t.notes);
    const color = t.color || '';
    return `<tr class="${color}">
      <td class="task-name-cell" onclick="showNotes('${id}','${title}','${notes}')">${title}</td>
      <td>${escHtml(t.due_date)}</td>
      <td>${fmtTime(t.due_time)}</td>
      <td>${priorityPill(t.priority)}</td>
      <td class="actions-cell">
        <button class="btn btn-sm btn-primary" onclick="finishTask('${id}')">✓ Finish</button>
        <button class="btn btn-sm" onclick="openEditTask('${id}')">✎ Edit</button>
        <button class="btn btn-sm btn-danger" onclick="deleteTask('${id}')">✗ Delete</button>
      </td>
    </tr>`;
  }).join('');
}

async function finishTask(id) {
  await api('POST', `/api/tasks/${id}/complete`);
  loadTasks();
}

async function deleteTask(id) {
  if (!confirm('Delete this task?')) return;
  await api('DELETE', `/api/tasks/${id}`);
  loadTasks();
}

function showNotes(id, title, notes) {
  document.getElementById('notes-title').textContent = title;
  document.getElementById('notes-body').textContent  = notes || 'No notes';
  document.getElementById('notes-modal').style.display = 'flex';
}

/* ── Task Modal ─────────────────────────────────────────────────── */
function openAddTask() {
  document.getElementById('modal-title').textContent = 'Add Task';
  document.getElementById('edit-task-id').value = '';
  ['f-title','f-date','f-time','f-notes'].forEach(id => document.getElementById(id).value = '');
  document.getElementById('f-priority').value = '3';
  document.getElementById('task-modal').style.display = 'flex';
  setTimeout(() => document.getElementById('f-title').focus(), 50);
}

function openEditTask(id) {
  const t = allTasks.find(t => t.task_id === id);
  if (!t) return;
  document.getElementById('modal-title').textContent = 'Edit Task';
  document.getElementById('edit-task-id').value  = id;
  document.getElementById('f-title').value        = t.title    || '';
  document.getElementById('f-date').value         = t.due_date || '';
  document.getElementById('f-time').value         = t.due_time || '';
  document.getElementById('f-priority').value     = t.priority || '3';
  document.getElementById('f-notes').value        = t.notes    || '';
  document.getElementById('task-modal').style.display = 'flex';
}

function closeModal() {
  document.getElementById('task-modal').style.display = 'none';
}

async function saveTask() {
  const id       = document.getElementById('edit-task-id').value;
  const title    = document.getElementById('f-title').value.trim();
  const due_date = document.getElementById('f-date').value.trim();
  const due_time = document.getElementById('f-time').value.trim();
  const priority = document.getElementById('f-priority').value;
  const notes    = document.getElementById('f-notes').value.trim() || 'No notes';

  if (!title) { alert('Task name is required.'); return; }
  if (!due_date) { alert('Due date is required (MM-DD-YYYY).'); return; }

  if (id) {
    await api('PUT', `/api/tasks/${id}`, { title, due_date, due_time, priority, notes });
  } else {
    await api('POST', '/api/tasks', { title, due_date, due_time, priority, notes });
  }
  closeModal();
  loadTasks();
}

/* ══════════════════════════════════════════════════════════════════
   DAILY TASKS
══════════════════════════════════════════════════════════════════ */
async function loadDaily() {
  const list = document.getElementById('daily-list');
  list.innerHTML = '<li class="empty-msg">Loading…</li>';
  const data = await api('GET', '/api/daily');
  const tasks = data.tasks ?? [];
  if (!tasks.length) {
    list.innerHTML = '<li class="empty-msg">No daily tasks yet.</li>';
    return;
  }
  list.innerHTML = tasks.map(t => `
    <li class="daily-item ${t.done ? 'done' : ''}">
      <input type="checkbox" class="daily-check" ${t.done ? 'checked' : ''}
             onchange="toggleDaily(${t.id})"/>
      <span class="daily-title">${escHtml(t.title)}</span>
      <button class="btn btn-sm btn-danger" onclick="deleteDaily(${t.id})">✗</button>
    </li>`).join('');
}

async function addDailyTask() {
  const input = document.getElementById('daily-input');
  const title = input.value.trim();
  if (!title) return;
  await api('POST', '/api/daily', { title });
  input.value = '';
  loadDaily();
}
document.getElementById('daily-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') addDailyTask();
});

async function toggleDaily(id) {
  await api('POST', `/api/daily/${id}/toggle`);
  loadDaily();
}

async function deleteDaily(id) {
  await api('DELETE', `/api/daily/${id}`);
  loadDaily();
}

/* ══════════════════════════════════════════════════════════════════
   AI ASSISTANT
══════════════════════════════════════════════════════════════════ */
async function initAI() {
  const statusBox = document.getElementById('ai-status');
  statusBox.textContent = 'Checking…';
  try {
    const h = await api('GET', '/api/ai/health');
    const ollama = h.ollama ?? {};
    if (ollama.available) {
      statusBox.textContent = `✓ Ollama online\nModel: ${ollama.default_model}`;
      aiModels = ollama.models ?? [];
    } else {
      statusBox.textContent = '⚠ Ollama not running.\nPull a model via CVM exec.';
      aiModels = [];
    }
  } catch {
    statusBox.textContent = '✗ AI service unreachable';
    aiModels = [];
  }

  const sel = document.getElementById('ai-model-select');
  sel.innerHTML = '<option value="">Default</option>' +
    aiModels.map(m => `<option value="${escHtml(m)}">${escHtml(m)}</option>`).join('');

  // Initial greeting
  const chat = document.getElementById('ai-chat');
  if (!chat.dataset.greeted) {
    appendAIMessage('bot', "Hello! I'm your task assistant. Ask me anything about your tasks or productivity.");
    chat.dataset.greeted = '1';
  }
}

function appendAIMessage(role, text) {
  const chat = document.getElementById('ai-chat');
  const div  = document.createElement('div');
  div.className = `ai-msg ${role}`;
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

async function sendAI() {
  const input = document.getElementById('ai-input');
  const prompt = input.value.trim();
  if (!prompt) return;
  const model = document.getElementById('ai-model-select').value;

  appendAIMessage('user', prompt);
  input.value = '';

  const thinking = appendAIMessage('bot thinking', '…thinking…');

  try {
    const d = await api('POST', '/api/ai/chat', { prompt, model });
    thinking.remove();
    if (d.status === 'success') {
      appendAIMessage('bot', d.response || '(no response)');
    } else {
      appendAIMessage('bot', `⚠ ${d.message}`);
    }
  } catch (e) {
    thinking.remove();
    appendAIMessage('bot', `✗ Error: ${e.message}`);
  }
}

document.getElementById('ai-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendAI(); }
});

/* ══════════════════════════════════════════════════════════════════
   CALENDAR
══════════════════════════════════════════════════════════════════ */
const MONTHS = ['January','February','March','April','May','June',
                'July','August','September','October','November','December'];
const DAYS   = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

async function renderCalendar() {
  document.getElementById('cal-title').textContent = `${MONTHS[calMonth-1]} ${calYear}`;
  const data = await api('GET', `/api/calendar/${calYear}/${calMonth}`);
  const byDay = data.tasks_by_day ?? {};

  const today = new Date();
  const firstDay = new Date(calYear, calMonth - 1, 1);
  const lastDay  = new Date(calYear, calMonth, 0).getDate();
  // Mon=0 … Sun=6
  let startDow = (firstDay.getDay() + 6) % 7;

  let html = DAYS.map(d => `<div class="cal-header">${d}</div>`).join('');

  // Blank cells before first day
  for (let i = 0; i < startDow; i++) html += '<div class="cal-cell other-month"></div>';

  for (let day = 1; day <= lastDay; day++) {
    const isToday = today.getFullYear() === calYear && today.getMonth()+1 === calMonth && today.getDate() === day;
    const tasks = byDay[String(day)] ?? [];
    const dots  = tasks.slice(0, 4).map(t =>
      `<div class="cal-dot ${t.color||'normal'}">${escHtml(t.title)}</div>`).join('');
    html += `<div class="cal-cell${isToday?' today-cell':''}">
               <div class="cal-day">${day}</div>${dots}</div>`;
  }

  document.getElementById('calendar-grid').innerHTML = html;
}

function calPrev() { calMonth--; if (calMonth < 1) { calMonth = 12; calYear--; } renderCalendar(); }
function calNext() { calMonth++; if (calMonth > 12) { calMonth = 1;  calYear++; } renderCalendar(); }

/* ══════════════════════════════════════════════════════════════════
   WEEKLY
══════════════════════════════════════════════════════════════════ */
async function loadWeekly() {
  const data = await api('GET', '/api/weekly');
  const week = data.week ?? {};
  const days = data.week_days ?? [];
  const dates = data.week_dates ?? [];
  const today = new Date();
  const todayStr = `${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}-${today.getFullYear()}`;

  const grid = document.getElementById('weekly-grid');
  grid.innerHTML = dates.map((date, i) => {
    const isToday = date === todayStr;
    const tasks   = week[date] ?? [];
    const taskHtml = tasks.map(t =>
      `<div class="weekly-task ${t.color||'normal'}">${escHtml(t.title)}</div>`).join('');
    return `<div class="weekly-day${isToday?' today-col':''}">
              <div class="weekly-day-header">${escHtml(days[i])}</div>
              ${taskHtml || '<span style="color:#bbb;font-size:11px">No tasks</span>'}
            </div>`;
  }).join('');
}

/* ══════════════════════════════════════════════════════════════════
   SETTINGS
══════════════════════════════════════════════════════════════════ */
async function loadSettings() {
  const d = await api('GET', '/api/settings');
  const s = d.settings ?? {};
  use24Hour = s.use_24_hour !== false;
  document.getElementById('setting-24h').checked = use24Hour;
  document.getElementById('setting-uid').textContent = s.web_user_id ?? '–';
}

async function saveSetting(key, value) {
  if (key === 'use_24_hour') use24Hour = value;
  await api('POST', '/api/settings', { [key]: value });
}

async function checkHealth() {
  const out = document.getElementById('health-output');
  out.textContent = 'Checking…';
  const endpoints = [
    ['/api/ai/health', 'AI Inference'],
    ['/health', 'Web UI'],
  ];
  const results = await Promise.allSettled(endpoints.map(([path]) => api('GET', path)));
  out.textContent = endpoints.map(([_, name], i) => {
    const r = results[i];
    if (r.status === 'fulfilled') {
      return `${name}: ${r.value.status ?? 'ok'}`;
    }
    return `${name}: ERROR – ${r.reason}`;
  }).join('\n');
}

/* ── Keyboard shortcuts ─────────────────────────────────────────── */
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeModal();
    document.getElementById('notes-modal').style.display = 'none';
  }
});

/* ── Boot ───────────────────────────────────────────────────────── */
loadTasks();
loadCharacter();
