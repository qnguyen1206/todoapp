/* ── State ──────────────────────────────────────────────────────── */
let allTasks      = [];
let sortKey       = 'due_date';
let sortAsc       = true;
let calYear       = new Date().getFullYear();
let calMonth      = new Date().getMonth() + 1;  // 1-based
let aiModels      = [];
let use24Hour     = true;
let selectedAiModelSetting = '';
let activeAiModelChoice = '';
let savedAiModels = [];
let attestationInfo = null;
let attestationLoaded = false;
let currentNotesFull = '';
const NOTES_PREVIEW_LIMIT = 500;
let zdrEnabled = false;
let zdrModels = [];

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
async function api(method, path, body, timeoutMs = 20000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const opts = { method, headers: { 'Content-Type': 'application/json' }, signal: ctrl.signal };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const r = await fetch(path, opts);
    return await r.json();
  } catch (e) {
    if (e.name === 'AbortError') throw new Error('Request timed out. Please try again.');
    throw new Error('Network error. Please check your connection and try again.');
  } finally {
    clearTimeout(timer);
  }
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

/* ── Trust Modal ─────────────────────────────────────────── */
function openTrustModal() {
    document.getElementById("trust-modal").style.display = "flex";
}

function closeTrustModal() {
    document.getElementById("trust-modal").style.display = "none";
}

document.getElementById("trust-modal").addEventListener("click", function(e) {
    if (e.target === this) {
        closeTrustModal();
    }
});

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
    const color = t.color || '';
    return `<tr class="${color}">
      <td class="task-name-cell" onclick="showNotes('${id}')">${title}</td>
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

async function clearAllTasks() {
  if (!confirm('Clear all tasks in the Tasks tab? Daily tasks will be kept.')) return;
  await api('POST', '/api/tasks/clear');
  loadTasks();
}

function showNotes(id, title, notes) {
  const task = allTasks.find(t => String(t.task_id) === String(id));
  const safeTitle = task?.title || title || 'Task Notes';
  currentNotesFull = task?.notes || notes || 'No notes';

  const isLong = currentNotesFull.length > NOTES_PREVIEW_LIMIT;
  const preview = isLong
    ? `${currentNotesFull.slice(0, NOTES_PREVIEW_LIMIT)}\n\n[... truncated ...]`
    : currentNotesFull;

  document.getElementById('notes-title').textContent = safeTitle;
  document.getElementById('notes-body').textContent  = preview || 'No notes';
  const readMoreBtn = document.getElementById('notes-read-more');
  if (readMoreBtn) {
    readMoreBtn.style.display = isLong ? 'inline-flex' : 'none';
  }
  document.getElementById('notes-modal').style.display = 'flex';
}

function openFullNotes() {
  document.getElementById('notes-full-body').textContent = currentNotesFull || 'No notes';
  document.getElementById('notes-full-modal').style.display = 'flex';
}

function closeFullNotes() {
  document.getElementById('notes-full-modal').style.display = 'none';
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
  list.innerHTML = tasks.map(t => {
    const safeId = encodeURIComponent(String(t.id ?? ''));
    return `
    <li class="daily-item ${t.done ? 'done' : ''}">
      <input type="checkbox" class="daily-check" ${t.done ? 'checked' : ''}
             onchange="toggleDaily('${safeId}')"/>
      <span class="daily-title">${escHtml(t.title)}</span>
      <button class="btn btn-sm btn-danger" onclick="deleteDaily('${safeId}')">✗</button>
    </li>`;
  }).join('');
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

async function clearAllDaily() {
  if (!confirm('Clear all daily tasks in the Daily tab? Regular tasks will be kept.')) return;
  await api('POST', '/api/daily/clear');
  loadDaily();
}

/* ══════════════════════════════════════════════════════════════════
   AI ASSISTANT
══════════════════════════════════════════════════════════════════ */
async function initAI() {
  const statusBox = document.getElementById('ai-status');
  statusBox.textContent = 'Checking…';
  if (!attestationLoaded) loadAttestation();
  if (!selectedAiModelSetting && savedAiModels.length === 0) {
    try {
      const s = await api('GET', '/api/settings');
      selectedAiModelSetting = (s.settings?.phala_ai_model || '').trim();
      savedAiModels = Array.isArray(s.settings?.phala_ai_models)
        ? s.settings.phala_ai_models.map(m => String(m || '').trim()).filter(Boolean)
        : [];
    } catch {}
  }

  aiModels = [];
  try {
    const h = await api('GET', '/api/ai/health');
    const ok = ['ok', 'success', 'healthy'].includes(String(h?.status || '').toLowerCase());
    if (ok) {
      statusBox.textContent = selectedAiModelSetting
        ? `✓ AI service online\nDefault model: ${selectedAiModelSetting}`
        : '✓ AI service online';
    } else {
      const msg = h?.message ? `\n${h.message}` : '';
      statusBox.textContent = `⚠ AI service reported an issue${msg}`;
    }

    try {
      const m = await api('GET', '/api/ai/models');
      aiModels = Array.isArray(m?.models) ? m.models : [];
    } catch {
      aiModels = [];
    }
  } catch {
    statusBox.textContent = '✗ AI service unreachable';
    aiModels = [];
  }

  document.getElementById('zdr-toggle').checked = zdrEnabled;
  document.getElementById('zdr-help-text').style.display = zdrEnabled ? 'block' : 'none';
  await rebuildModelSelect();

  // Initial greeting
  const chat = document.getElementById('ai-chat');
  if (!chat.dataset.greeted) {
    appendAIMessage('bot', "Hello! I'm your task assistant. Ask me anything about your tasks or productivity.");
    chat.dataset.greeted = '1';
  }
}

async function loadAttestation() {
  const box = document.getElementById('ai-attestation');
  if (!box) return;
  box.innerHTML = 'Verifying enclave…';
  try {
    const d = await api('GET', '/api/ai/attestation', undefined, 15000);
    if (d.status !== 'success') {
      attestationInfo = null;
      box.innerHTML = `<div class="attn-row attn-bad">⚠ Attestation unavailable${d.message ? `: ${escHtml(d.message)}` : ''}</div>`;
      attestationLoaded = true;
      return;
    }

    attestationInfo = d;
    const staleAfter = d.stale_after ? new Date(d.stale_after) : null;
    const fresh = staleAfter ? staleAfter.getTime() > Date.now() : null;
    const freshText = staleAfter
      ? (fresh ? `fresh (until ${staleAfter.toLocaleString()})` : 'STALE')
      : 'not reported by gateway';
    const workloadText = d.workload_id ? `${escHtml(d.workload_id.slice(0, 16))}…` : 'not reported by gateway';

    box.innerHTML = `
      <div class="attn-row attn-good">✓ TEE attested (${escHtml(d.tee_type || 'unknown')})</div>
      <div class="attn-row">Workload: <code>${workloadText}</code></div>
      <div class="attn-row ${fresh === false ? 'attn-bad' : ''}">Freshness: ${escHtml(freshText)}</div>
      <button class="btn btn-sm attn-details-btn" onclick="openAttestationDetails()">View Full Details</button>
    `;
  } catch (e) {
    attestationInfo = null;
    box.innerHTML = `<div class="attn-row attn-bad">⚠ ${escHtml(e.message)}</div>`;
  }
  attestationLoaded = true;
}

function openAttestationDetails() {
  const body = document.getElementById('attestation-details-body');
  if (!attestationInfo) {
    body.innerHTML = '<p class="empty-msg">No attestation data available.</p>';
  } else {
    const d = attestationInfo;
    const prov = d.source_provenance || {};
    const row = (label, value) =>
      `<div class="detail-row"><span class="detail-label">${escHtml(label)}</span><code class="detail-value">${value ? escHtml(String(value)) : '<span class="detail-empty">not reported</span>'}</code></div>`;

    body.innerHTML = `
      ${row('API Version', d.api_version)}
      ${row('Nonce', d.nonce)}
      ${row('TEE Type', d.tee_type)}
      ${row('Workload ID', d.workload_id)}
      ${row('Workload Keyset Digest', d.workload_keyset_digest)}
      ${row('Stale After', d.stale_after)}
      <div class="detail-section-title">Source Provenance</div>
      ${row('Repo URL', prov.repo_url)}
      ${row('Repo Commit', prov.repo_commit)}
      ${row('Image Digest', prov.image_digest)}
      ${row('Image Provenance', prov.image_provenance)}
    `;
  }
  document.getElementById('attestation-details-modal').style.display = 'flex';
}

function closeAttestationDetails() {
  document.getElementById('attestation-details-modal').style.display = 'none';
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeModal();
    document.getElementById('notes-modal').style.display = 'none';
    closeFullNotes();
    closeAttestationDetails();
  }
});

async function verifyReceipt(receiptId, metaEl) {
  try {
    const d = await api('GET', `/api/ai/receipt/${encodeURIComponent(receiptId)}`, undefined, 15000);
    if (d.status === 'success') {
      const badge = d.verified ? '✓ verified' : '⚠ unverified';
      metaEl.textContent = `Receipt: ${receiptId} · ${badge}${d.model_id ? ` · ${d.model_id}` : ''}`;
      metaEl.classList.toggle('receipt-verified', !!d.verified);
      metaEl.classList.toggle('receipt-unverified', !d.verified);
    } else {
      metaEl.textContent = `Receipt: ${receiptId}`;
    }
  } catch {
    metaEl.textContent = `Receipt: ${receiptId}`;
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


function appendAIBotResponse(text, payload) {
  const chat = document.getElementById('ai-chat');
  const div = document.createElement('div');
  div.className = 'ai-msg bot';

  const body = document.createElement('div');
  body.className = 'ai-text';
  body.textContent = text || '(no response)';
  div.appendChild(body);


  const receiptId = payload?.receipt_id || '';
  if (receiptId) {
    const meta = document.createElement('div');
    meta.className = 'ai-receipt';
    meta.textContent = `Receipt: ${receiptId} · checking…`;
    div.appendChild(meta);
    verifyReceipt(receiptId, meta);
  }

  if (payload?.zdr) {
    const badge = document.createElement('div');
    badge.className = 'ai-zdr-badge';
    badge.textContent = 'Zero Data Retention';
    div.appendChild(badge);
  }

  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

async function sendAI() {
  const input = document.getElementById('ai-input');
  const prompt = input.value.trim();
  if (!prompt) return;

  const selectedModel = document.getElementById('ai-model-select').value;
  if (zdrEnabled && !selectedModel) {
    alert('Select a Zero Data Retention model first.');
    return;
  }

  appendAIMessage('user', prompt);
  input.value = '';
  const thinking = appendAIMessage('bot thinking', '…thinking…');

  try {
    const d = await api('POST', '/api/ai/chat', { prompt, model: selectedModel, zdr: zdrEnabled }, 120000);
    thinking.remove();
    d.status === 'success'
      ? appendAIBotResponse(d.response || '(no response)', d)
      : appendAIBotResponse(`⚠ ${d.message || 'Unknown AI error'}`, d);
  } catch (e) {
    thinking.remove();
    appendAIBotResponse(`✗ Error: ${e.message}`, {});
  }
}

document.getElementById('ai-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendAI(); }
});

async function onZdrToggle() {
  zdrEnabled = document.getElementById('zdr-toggle').checked;
  document.getElementById('zdr-help-text').style.display = zdrEnabled ? 'block' : 'none';
  await rebuildModelSelect();
}

async function loadZdrModels() {
  try {
    const d = await api('GET', '/api/ai/models/zdr', undefined, 15000);
    zdrModels = (d.status === 'success' && Array.isArray(d.models)) ? d.models : [];
  } catch {
    zdrModels = [];
  }
}

async function rebuildModelSelect() {
  const sel = document.getElementById('ai-model-select');

  if (zdrEnabled) {
    sel.disabled = true;
    sel.innerHTML = '<option value="">Loading ZDR models…</option>';
    await loadZdrModels();
    sel.disabled = false;

    if (!zdrModels.length) {
      sel.innerHTML = '<option value="">No ZDR models available</option>';
      activeAiModelChoice = '';
      return;
    }
    sel.innerHTML = zdrModels.map(m => `<option value="${escHtml(m)}">${escHtml(m)}</option>`).join('');
    sel.value = zdrModels.includes(activeAiModelChoice) ? activeAiModelChoice : zdrModels[0];
    activeAiModelChoice = sel.value;
    sel.onchange = () => { activeAiModelChoice = sel.value; };
    return;
  }

  const modelSet = new Set(aiModels.map(m => String(m || '').trim()).filter(Boolean));
  for (const m of savedAiModels) modelSet.add(m);
  if (selectedAiModelSetting) modelSet.add(selectedAiModelSetting);
  const modelOptions = Array.from(modelSet);

  const defaultLabel = selectedAiModelSetting
    ? `Use default (${selectedAiModelSetting})`
    : 'Use configured model';

  sel.innerHTML = `<option value="">${escHtml(defaultLabel)}</option>` +
    modelOptions.map(m => `<option value="${escHtml(m)}">${escHtml(m)}</option>`).join('');

  if (activeAiModelChoice && modelOptions.includes(activeAiModelChoice)) {
    sel.value = activeAiModelChoice;
  } else if (selectedAiModelSetting && modelOptions.includes(selectedAiModelSetting)) {
    sel.value = selectedAiModelSetting;
    activeAiModelChoice = selectedAiModelSetting;
  } else {
    sel.value = '';
    activeAiModelChoice = '';
  }
  sel.onchange = () => { activeAiModelChoice = sel.value; };
}

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
  selectedAiModelSetting = (s.phala_ai_model || '').trim();
  savedAiModels = Array.isArray(s.phala_ai_models)
    ? s.phala_ai_models.map(m => String(m || '').trim()).filter(Boolean)
    : [];
  document.getElementById('setting-24h').checked = use24Hour;
  document.getElementById('setting-uid').textContent = s.web_user_id ?? '–';
  const aiInput = document.getElementById('setting-ai-model');
  if (aiInput) aiInput.value = '';
  renderSavedAiModelList();
}

async function saveSetting(key, value) {
  if (key === 'use_24_hour') use24Hour = value;
  await api('POST', '/api/settings', { [key]: value });
}

async function addAiModelSetting() {
  const input = document.getElementById('setting-ai-model');
  if (!input) return;
  const model = input.value.trim();
  if (!model) return;

  if (!savedAiModels.includes(model)) {
    savedAiModels.push(model);
    await saveSetting('phala_ai_models', savedAiModels);
  }

  // If no default is set yet, use the first added model as default.
  if (!selectedAiModelSetting) {
    selectedAiModelSetting = model;
    activeAiModelChoice = model;
    await saveSetting('phala_ai_model', model);
  }

  input.value = '';
  renderSavedAiModelList();
  await initAI();
}

async function setDefaultAiModel(model) {
  selectedAiModelSetting = String(model || '').trim();
  activeAiModelChoice = selectedAiModelSetting;
  await saveSetting('phala_ai_model', selectedAiModelSetting);
  renderSavedAiModelList();
  await initAI();
}

async function removeAiModelSetting(model) {
  const target = String(model || '').trim();
  if (!target) return;

  savedAiModels = savedAiModels.filter(m => m !== target);
  await saveSetting('phala_ai_models', savedAiModels);

  if (selectedAiModelSetting === target) {
    selectedAiModelSetting = savedAiModels[0] || '';
    activeAiModelChoice = selectedAiModelSetting;
    await saveSetting('phala_ai_model', selectedAiModelSetting);
  }

  renderSavedAiModelList();
  await initAI();
}

function renderSavedAiModelList() {
  const list = document.getElementById('saved-model-list');
  if (!list) return;

  if (!savedAiModels.length) {
    list.innerHTML = '<div class="empty-msg" style="padding:10px 0;">No saved models yet.</div>';
    return;
  }

  list.innerHTML = savedAiModels.map(model => {
    const isDefault = model === selectedAiModelSetting;
    const displayModel = escHtml(model);
    const encodedModel = encodeURIComponent(model);
    return `
      <div class="saved-model-item">
        <code class="saved-model-name">${displayModel}</code>
        <div class="saved-model-actions">
          <button class="btn btn-sm ${isDefault ? 'btn-primary' : ''}" onclick="setDefaultAiModel(decodeURIComponent('${encodedModel}'))">
            ${isDefault ? 'Default' : 'Set Default'}
          </button>
          <button class="btn btn-sm btn-danger" onclick="removeAiModelSetting(decodeURIComponent('${encodedModel}'))">Remove</button>
        </div>
      </div>`;
  }).join('');
}

async function checkHealth() {
  const out = document.getElementById('health-output');
  out.textContent = 'Checking…';
  try {
    const data = await api('GET', '/api/health/all');
    const services = data.services ?? {};
    const labels = {
      web_ui: 'Web UI',
      backend: 'Backend Storage',
      ai_inference: 'AI Inference',
      task_sync: 'Task Sync',
      scheduler: 'Scheduler',
    };

    const order = ['web_ui', 'backend', 'ai_inference', 'task_sync', 'scheduler'];
    const lines = [];
    const overallClass = data.overall_ok ? 'ok' : 'degraded';
    const overallText = data.overall_ok ? 'Overall: OK' : 'Overall: DEGRADED';
    lines.push(`<div class="overall ${overallClass}">${escHtml(overallText)}</div>`);

    for (const key of order) {
      const svc = services[key] || {};
      const name = labels[key] || key;
      const status = svc.status || 'unknown';
      const code = svc.code || 0;
      const badge = svc.ok ? 'OK' : 'ERROR';
      const badgeClass = svc.ok ? 'ok' : 'error';
      const detail = svc.message ? ` - ${svc.message}` : '';
      lines.push(
        `<div class="health-row">` +
          `<span class="service-name">${escHtml(name)}:</span>` +
          `<span class="status-badge ${badgeClass}">${escHtml(badge)}</span>` +
          `<span class="status-detail">(${escHtml(status)}, HTTP ${escHtml(code)})${escHtml(detail)}</span>` +
        `</div>`
      );
    }

    out.innerHTML = lines.join('');
  } catch (e) {
    out.textContent = `Health check failed: ${e?.message || e}`;
  }
}

/* ── Keyboard shortcuts ─────────────────────────────────────────── */
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeModal();
    document.getElementById('notes-modal').style.display = 'none';
    closeFullNotes();
  }
});

/* ── Boot ───────────────────────────────────────────────────────── */
loadTasks();
loadCharacter();
