/* ── State ──────────────────────────────────────────────────────── */
let allTasks      = [];
let sortKey       = 'due_date';
let sortAsc       = true;
let calYear       = new Date().getFullYear();
let calMonth      = new Date().getMonth() + 1;  // 1-based
let use24Hour     = true;
let selectedAiModelSetting = '';
let activeAiModelChoice = '';
let attestationInfo = null;
let attestationLoaded = false;
let currentNotesFull = '';
const NOTES_PREVIEW_LIMIT = 500;
let zdrEnabled = false;
let zdrModels = [];
let visionModels = [];
let attachedImageDataUrl = null;
let modelCatalog = [];
let toolsEnabled = true;
let streamEnabled = false;
let conversationHistory = [];
let currentMeetingProposal = null;
let bulkParsedTasks = [];
const selectedTaskIds = new Set();
const snoozedMeetingProposals = new Set();
const MAX_HISTORY_MESSAGES = 20; // ~10 exchanges; trims oldest first

async function checkMeetingProposals() {
  if (currentMeetingProposal || document.getElementById('meeting-proposal-modal').style.display === 'flex') return;
  try {
    const data = await api('GET', '/api/integrations/meetings');
    const proposal = (data.proposals || []).find(item => !snoozedMeetingProposals.has(String(item.id)));
    if (proposal) showMeetingProposal(proposal);
  } catch (_) {}
}

function showMeetingProposal(proposal) {
  currentMeetingProposal = proposal;
  const start = new Date(proposal.start_at);
  const pad = value => String(value).padStart(2, '0');
  document.getElementById('meeting-proposal-id').value = proposal.id;
  document.getElementById('meeting-title').value = proposal.title || 'Meeting';
  document.getElementById('meeting-date').value = `${pad(start.getMonth() + 1)}-${pad(start.getDate())}-${start.getFullYear()}`;
  document.getElementById('meeting-time').value = timeForTaskInput(`${pad(start.getHours())}:${pad(start.getMinutes())}`);
  document.getElementById('meeting-organizer').value = proposal.organizer || '';
  document.getElementById('meeting-link').value = proposal.meeting_link || '';
  const end = proposal.end_at ? new Date(proposal.end_at).toLocaleString() : '';
  const details = [proposal.notes || '', end ? `Ends: ${end}` : '', proposal.meeting_link ? `Join: ${proposal.meeting_link}` : ''].filter(Boolean);
  document.getElementById('meeting-notes').value = details.join('\n');
  document.getElementById('meeting-proposal-error').style.display = 'none';
  document.getElementById('meeting-proposal-modal').style.display = 'flex';
}

function closeMeetingProposal() {
  if (currentMeetingProposal) snoozedMeetingProposals.add(String(currentMeetingProposal.id));
  currentMeetingProposal = null;
  document.getElementById('meeting-proposal-modal').style.display = 'none';
}

async function acceptMeetingProposal() {
  if (!currentMeetingProposal) return;
  const error = document.getElementById('meeting-proposal-error');
  const title = document.getElementById('meeting-title').value.trim();
  const due_date = document.getElementById('meeting-date').value.trim();
  const due_time = normalizeDueTime(document.getElementById('meeting-time').value.trim());
  if (!title || !isValidDueDate(due_date) || !due_time) {
    error.textContent = 'Enter a valid title, date, and start time.';
    error.style.display = 'block';
    return;
  }
  try {
    await api('POST', '/api/tasks', {
      title, due_date, due_time, priority: '2',
      notes: document.getElementById('meeting-notes').value.trim() || 'Meeting imported from email',
      reminder: {email_enabled: false, sms_enabled: false, minutes_before: 15,
                 timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'},
    });
    await api('PATCH', `/api/integrations/meetings/${encodeURIComponent(currentMeetingProposal.id)}`, {decision: 'accepted'});
    currentMeetingProposal = null;
    document.getElementById('meeting-proposal-modal').style.display = 'none';
    await loadTasks();
    checkMeetingProposals();
  } catch (exception) {
    error.textContent = exception.message;
    error.style.display = 'block';
  }
}

async function ignoreMeetingProposal() {
  if (!currentMeetingProposal) return;
  const proposalId = currentMeetingProposal.id;
  try {
    await api('PATCH', `/api/integrations/meetings/${encodeURIComponent(proposalId)}`, {decision: 'ignored'});
    currentMeetingProposal = null;
    document.getElementById('meeting-proposal-modal').style.display = 'none';
    checkMeetingProposals();
  } catch (exception) {
    const error = document.getElementById('meeting-proposal-error');
    error.textContent = exception.message;
    error.style.display = 'block';
  }
}

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
    if (btn.dataset.tab === 'settings') {
      loadSettings();
      checkHealth();
    }
  });
});

/* ── Helpers ───────────────────────────────────────────────────── */
async function api(method, path, body, timeoutMs = 20000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const opts = { method, headers: { 'Content-Type': 'application/json' }, signal: ctrl.signal };
    if (method.toUpperCase() === 'GET') opts.cache = 'no-store';
    if (body !== undefined) opts.body = JSON.stringify(body);
    const r = await fetch(path, opts);
    const text = await r.text();
    let data;
    try { data = text ? JSON.parse(text) : {}; }
    catch { data = { status: 'error', message: text || `Server returned HTTP ${r.status}` }; }
    if (!r.ok) {
      const error = new Error(data.message || `Request failed (HTTP ${r.status})`);
      error.isApiError = true;
      throw error;
    }
    return data;
  } catch (e) {
    if (e.name === 'AbortError') throw new Error('Request timed out. Please try again.');
    if (e.isApiError) throw e;
    throw new Error('Network error. Please check your connection and try again.');
  } finally {
    clearTimeout(timer);
  }
}

function fmtTime(t) {
  if (!t || t === '' || t === '--:--') return '–';
  const normalized = normalizeDueTime(t);
  if (normalized === null) return String(t);
  if (use24Hour) return normalized;
  const [hourText, minute] = normalized.split(':');
  const hour = Number(hourText);
  return `${hour % 12 || 12}:${minute} ${hour >= 12 ? 'PM' : 'AM'}`;
}

function normalizeDueTime(value) {
  const raw = String(value || '').trim().toUpperCase();
  if (!raw) return '';
  let match = raw.match(/^(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM)$/);
  if (match) {
    let hour = Number(match[1]);
    const minute = Number(match[2]);
    if (hour < 1 || hour > 12 || minute > 59) return null;
    if (match[3] === 'AM') hour = hour === 12 ? 0 : hour;
    else hour = hour === 12 ? 12 : hour + 12;
    return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
  }
  match = raw.match(/^(\d{1,2}):(\d{2})(?::\d{2})?$/);
  if (!match || Number(match[1]) > 23 || Number(match[2]) > 59) return null;
  return `${String(Number(match[1])).padStart(2, '0')}:${match[2]}`;
}

function timeForTaskInput(value) {
  const normalized = normalizeDueTime(value);
  if (!normalized) return value || '';
  if (use24Hour) return normalized;
  const [hourText, minute] = normalized.split(':');
  const hour = Number(hourText);
  return `${hour % 12 || 12}:${minute} ${hour >= 12 ? 'PM' : 'AM'}`;
}

function configureTaskTimeInput() {
  const input = document.getElementById('f-time');
  const label = document.getElementById('f-time-label');
  if (!input || !label) return;
  const normalized = normalizeDueTime(input.value);
  if (normalized !== null) input.value = timeForTaskInput(normalized);
  label.textContent = use24Hour ? 'Due Time (24-hour HH:MM)' : 'Due Time (12-hour HH:MM AM/PM)';
  input.placeholder = use24Hour ? '09:00' : '9:00 AM';
}

function isValidDueDate(value) {
  const match = String(value).match(/^(\d{2})-(\d{2})-(\d{4})$/);
  if (!match) return false;
  const month = Number(match[1]), day = Number(match[2]), year = Number(match[3]);
  const parsed = new Date(year, month - 1, day);
  return parsed.getFullYear() === year && parsed.getMonth() === month - 1 && parsed.getDate() === day;
}

function formatDueDateTyping(value) {
  const digits = String(value).replace(/\D/g, '').slice(0, 8);
  if (digits.length <= 2) return digits;
  if (digits.length <= 4) return `${digits.slice(0, 2)}-${digits.slice(2)}`;
  return `${digits.slice(0, 2)}-${digits.slice(2, 4)}-${digits.slice(4)}`;
}

function priorityPill(p) {
  return `<span class="priority-pill p${p}">${p}</span>`;
}

function escHtml(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;')
                        .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function modelLabel(m) {
  const badges = [];
  if (m.is_tee) badges.push('TEE');
  if ((m.input_modalities || []).includes('image')) badges.push('Vision');
  return badges.length ? `${m.id} (${badges.join(', ')})` : m.id;
}

function currentModelEntry() {
  const selectedId = document.getElementById('ai-model-select').value || selectedAiModelSetting;
  const pool = zdrEnabled ? zdrModels : modelCatalog;
  return pool.find(m => m.id === selectedId) || null;
}

async function loadModelCatalog(refresh = false) {
  try {
    const d = await api('GET', `/api/ai/models${refresh ? '?refresh=true' : ''}`, undefined, 15000);
    modelCatalog = (d.status === 'success' && Array.isArray(d.models)) ? d.models : [];
    if (!selectedAiModelSetting && d.default_model) selectedAiModelSetting = d.default_model;
  } catch {
    modelCatalog = [];
  }
}

async function refreshModelCatalog() {
  await loadModelCatalog(true);
  await rebuildModelSelect();
}

function onFeatureToggle() {
  toolsEnabled = document.getElementById('tools-toggle').checked;
  streamEnabled = document.getElementById('stream-toggle').checked;
  if (toolsEnabled && streamEnabled) {
    streamEnabled = false;
    document.getElementById('stream-toggle').checked = false;
    alert('Streaming is disabled while task tools are on — tool calls need the full response to run.');
  }
}

function onFormatChange() {
  const val = document.getElementById('format-select').value;
  document.getElementById('format-custom-input').style.display = val === 'other' ? 'block' : 'none';
}

function buildResponseFormat() {
  const val = document.getElementById('format-select').value;
  if (val === 'normal') return null;
  if (val === 'json') {
    return { type: 'json_schema', json_schema: { name: 'output', strict: false, schema: { type: 'object', additionalProperties: true } } };
  }
  const raw = document.getElementById('format-custom-input').value.trim();
  if (!raw) return null;
  try {
    const schema = JSON.parse(raw);
    return { type: 'json_schema', json_schema: { name: 'custom_output', strict: true, schema } };
  } catch {
    alert('Custom output format must be valid JSON (a JSON Schema object).');
    return undefined;
  }
}

function updateFeatureAvailability() {
  const entry = currentModelEntry();
  const params = (entry && entry.supported_parameters) || [];
  const supportsTools = params.includes('tools');
  const supportsFormat = params.includes('response_format');

  document.getElementById('tools-toggle').closest('.ai-feature-row').style.display = supportsTools ? 'flex' : 'none';
  if (!supportsTools) { toolsEnabled = false; document.getElementById('tools-toggle').checked = false; }

  document.getElementById('format-select').closest('.form-group').style.display = supportsFormat ? 'block' : 'none';
  if (!supportsFormat) {
    document.getElementById('format-select').value = 'normal';
    onFormatChange();
  }
}

function buildUserContent(prompt, imageDataUrl) {
  if (!imageDataUrl) return prompt;
  return [
    { type: 'text', text: prompt || 'What is in this image?' },
    { type: 'image_url', image_url: { url: imageDataUrl } },
  ];
}

function trimHistory() {
  if (conversationHistory.length > MAX_HISTORY_MESSAGES) {
    conversationHistory = conversationHistory.slice(-MAX_HISTORY_MESSAGES);
  }
}

// Non-vision models can't accept image_url blocks — degrade old images to a
// text note instead of dropping the turn or sending something that'll 400.
function sanitizeHistoryForModel(history, supportsImage) {
  if (supportsImage) return history;
  return history.map(m => {
    if (Array.isArray(m.content)) {
      const textPart = m.content.find(p => p.type === 'text');
      const hadImage = m.content.some(p => p.type === 'image_url');
      return {
        role: m.role,
        content: (textPart?.text || '') + (hadImage ? '\n[an image was attached here — not visible to this model]' : ''),
      };
    }
    return m;
  });
}

function clearConversation() {
  conversationHistory = [];
  const chat = document.getElementById('ai-chat');
  chat.innerHTML = '';
  chat.dataset.greeted = '';
  appendAIMessage('bot', "Conversation cleared. Ask me anything about your tasks or productivity.");
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
    '<tr><td colspan="6" class="empty-msg">Loading…</td></tr>';
  try {
    const data = await api('GET', '/api/tasks');
    allTasks = data.tasks ?? [];
    const availableIds = new Set(allTasks.filter(task => !task.completed).map(task => String(task.task_id)));
    [...selectedTaskIds].forEach(id => { if (!availableIds.has(id)) selectedTaskIds.delete(id); });
    renderTasks();
    updateTaskSelectionUI(allTasks.filter(task => !task.completed));
    document.getElementById('remaining-badge').textContent = `Tasks: ${allTasks.filter(t => !t.completed).length}`;
    loadCharacter();
  } catch (e) {
    document.getElementById('task-tbody').innerHTML =
      `<tr><td colspan="6" class="empty-msg">Error: ${escHtml(e.message)}</td></tr>`;
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
    tbody.innerHTML = '<tr><td colspan="6" class="empty-msg">No tasks — add one above!</td></tr>';
    return;
  }

  tbody.innerHTML = tasks.map(t => {
    const id    = escHtml(t.task_id);
    const title = escHtml(t.title);
    const color = t.color || '';
    return `<tr class="${color} ${selectedTaskIds.has(String(t.task_id)) ? 'selected' : ''}">
      <td class="select-cell"><input class="task-select" data-task-id="${id}" type="checkbox" aria-label="Select ${title}" ${selectedTaskIds.has(String(t.task_id)) ? 'checked' : ''} onchange="toggleTaskSelection('${id}', this.checked)"/></td>
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
  updateTaskSelectionUI(tasks);
}

function visibleTaskIds() {
  return allTasks.filter(task => !task.completed).map(task => String(task.task_id));
}

function checkedTaskIds() {
  return [...document.querySelectorAll('#task-tbody .task-select:checked')]
    .map(checkbox => String(checkbox.dataset.taskId));
}

function syncTaskSelectionFromDOM() {
  const taskIds = checkedTaskIds();
  selectedTaskIds.clear();
  taskIds.forEach(taskId => selectedTaskIds.add(taskId));
  updateTaskSelectionUI();
  return taskIds;
}

function updateTaskSelectionUI(visibleTasks = allTasks.filter(task => !task.completed)) {
  const visibleIds = visibleTasks.map(task => String(task.task_id));
  const selectedVisible = visibleIds.filter(id => selectedTaskIds.has(id)).length;
  const count = checkedTaskIds().length;
  document.getElementById('task-bulk-actions').hidden = count === 0;
  document.getElementById('task-selection-count').textContent = visibleIds.length
    ? `${count ? 'Selected' : 'Select tasks below'} (${count} selected)`
    : 'No tasks available to select';
  const selectAll = document.getElementById('select-all-tasks');
  selectAll.checked = visibleIds.length > 0 && selectedVisible === visibleIds.length;
  selectAll.indeterminate = selectedVisible > 0 && selectedVisible < visibleIds.length;
}

function toggleTaskSelection(taskId, selected) {
  const id = String(taskId);
  if (selected) selectedTaskIds.add(id);
  else selectedTaskIds.delete(id);
  renderTasks();
}

function toggleAllVisibleTasks(selected) {
  visibleTaskIds().forEach(id => selected ? selectedTaskIds.add(id) : selectedTaskIds.delete(id));
  renderTasks();
}

function clearTaskSelection() {
  selectedTaskIds.clear();
  renderTasks();
}

function setBulkActionsBusy(busy) {
  document.querySelectorAll('#task-bulk-actions button').forEach(button => { button.disabled = busy; });
}

async function finishSelectedTasks() {
  const taskIds = syncTaskSelectionFromDOM();
  if (!taskIds.length) { alert('Select at least one task first.'); return; }
  setBulkActionsBusy(true);
  try {
    const result = await api('POST', '/api/tasks/bulk/complete', {task_ids: taskIds}, 120000);
    selectedTaskIds.clear();
    await loadTasks();
    alert(`Finished ${result.updated ?? taskIds.length} ${taskIds.length === 1 ? 'task' : 'tasks'}.${result.warning ? `\n${result.warning}` : ''}`);
  } catch (error) {
    alert(`Could not finish selected tasks: ${error.message}`);
  } finally {
    setBulkActionsBusy(false);
  }
}

async function deleteSelectedTasks() {
  const taskIds = syncTaskSelectionFromDOM();
  if (!taskIds.length) { alert('Select at least one task first.'); return; }
  if (!confirm(`Delete ${taskIds.length} selected ${taskIds.length === 1 ? 'task' : 'tasks'}? This cannot be undone.`)) return;
  setBulkActionsBusy(true);
  try {
    const result = await api('POST', '/api/tasks/bulk/delete', {task_ids: taskIds}, 120000);
    selectedTaskIds.clear();
    await loadTasks();
    alert(`Deleted ${result.deleted ?? taskIds.length} ${taskIds.length === 1 ? 'task' : 'tasks'}.`);
  } catch (error) {
    alert(`Could not delete selected tasks: ${error.message}`);
  } finally {
    setBulkActionsBusy(false);
  }
}

function configureBulkEditInputs() {
  ['date', 'time', 'priority', 'notes'].forEach(field => {
    document.getElementById(`bulk-edit-${field}`).disabled = !document.getElementById(`bulk-edit-${field}-enabled`).checked;
  });
}

function openBulkEditModal() {
  const selectedIds = syncTaskSelectionFromDOM();
  if (!selectedIds.length) { alert('Select at least one task first.'); return; }
  ['date', 'time', 'priority', 'notes'].forEach(field => {
    document.getElementById(`bulk-edit-${field}-enabled`).checked = false;
  });
  document.getElementById('bulk-edit-date').value = '';
  document.getElementById('bulk-edit-time').value = '';
  document.getElementById('bulk-edit-time').placeholder = use24Hour
    ? 'HH:MM, or leave empty to remove the time'
    : 'HH:MM AM/PM, or leave empty to remove the time';
  document.getElementById('bulk-edit-priority').value = '3';
  document.getElementById('bulk-edit-notes').value = '';
  document.getElementById('bulk-edit-summary').textContent = `Editing ${selectedIds.length} selected ${selectedIds.length === 1 ? 'task' : 'tasks'}.`;
  document.getElementById('bulk-edit-error').style.display = 'none';
  configureBulkEditInputs();
  document.getElementById('bulk-edit-modal').style.display = 'flex';
}

function closeBulkEditModal() {
  document.getElementById('bulk-edit-modal').style.display = 'none';
}

async function saveBulkTaskEdits() {
  const error = document.getElementById('bulk-edit-error');
  const changes = {};
  if (document.getElementById('bulk-edit-date-enabled').checked) {
    const value = document.getElementById('bulk-edit-date').value;
    if (!value) {
      error.textContent = 'Choose a due date.';
      error.style.display = 'block';
      return;
    }
    const [year, month, day] = value.split('-');
    changes.due_date = `${month}-${day}-${year}`;
  }
  if (document.getElementById('bulk-edit-time-enabled').checked) {
    const value = document.getElementById('bulk-edit-time').value.trim();
    const normalized = normalizeDueTime(value);
    if (normalized === null) {
      error.textContent = use24Hour ? 'Enter time as HH:MM.' : 'Enter time as HH:MM AM/PM.';
      error.style.display = 'block';
      return;
    }
    changes.due_time = normalized;
  }
  if (document.getElementById('bulk-edit-priority-enabled').checked) {
    changes.priority = document.getElementById('bulk-edit-priority').value;
  }
  if (document.getElementById('bulk-edit-notes-enabled').checked) {
    changes.notes = document.getElementById('bulk-edit-notes').value.trim() || 'No notes';
  }
  if (!Object.keys(changes).length) {
    error.textContent = 'Check at least one field to change.';
    error.style.display = 'block';
    return;
  }

  const taskIds = [...selectedTaskIds];
  const saveButton = document.getElementById('bulk-edit-save');
  saveButton.disabled = true;
  error.style.display = 'none';
  try {
    const result = await api('POST', '/api/tasks/bulk/edit', {task_ids: taskIds, changes}, 120000);
    closeBulkEditModal();
    selectedTaskIds.clear();
    await loadTasks();
    alert(`Updated ${result.updated ?? taskIds.length} ${taskIds.length === 1 ? 'task' : 'tasks'}.`);
  } catch (exception) {
    error.textContent = exception.message;
    error.style.display = 'block';
  } finally {
    saveButton.disabled = false;
  }
}

const finishingTaskIds = new Set();

async function finishTask(id) {
  if (finishingTaskIds.has(id)) return;
  const task = allTasks.find(item => String(item.task_id) === String(id));
  if (!task) return;

  finishingTaskIds.add(id);
  task.completed = true;
  renderTasks();
  document.getElementById('remaining-badge').textContent = `Tasks: ${allTasks.filter(item => !item.completed).length}`;

  try {
    await api('POST', `/api/tasks/${encodeURIComponent(id)}/complete`);
    loadCharacter();
  } catch (error) {
    task.completed = false;
    renderTasks();
    document.getElementById('remaining-badge').textContent = `Tasks: ${allTasks.filter(item => !item.completed).length}`;
    alert(`Could not finish task: ${error.message}`);
  } finally {
    finishingTaskIds.delete(id);
  }
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
const BULK_WEEKDAYS = {sunday: 0, monday: 1, tuesday: 2, wednesday: 3, thursday: 4, friday: 5, saturday: 6};
const BULK_MONTHS = {
  jan: 0, january: 0, feb: 1, february: 1, mar: 2, march: 2, apr: 3, april: 3,
  may: 4, jun: 5, june: 5, jul: 6, july: 6, aug: 7, august: 7,
  sep: 8, sept: 8, september: 8, oct: 9, october: 9, nov: 10, november: 10,
  dec: 11, december: 11,
};

function taskDateFromLocal(date) {
  const pad = value => String(value).padStart(2, '0');
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())}-${date.getFullYear()}`;
}

function validBulkDate(year, month, day) {
  const date = new Date(year, month, day);
  return date.getFullYear() === year && date.getMonth() === month && date.getDate() === day ? date : null;
}

function parseBulkDateValue(raw, baseDate = new Date()) {
  const value = String(raw || '').trim().toLowerCase();
  const base = new Date(baseDate.getFullYear(), baseDate.getMonth(), baseDate.getDate());
  if (!value) return null;
  if (value === 'today') return taskDateFromLocal(base);
  if (value === 'tomorrow') {
    base.setDate(base.getDate() + 1);
    return taskDateFromLocal(base);
  }

  let match = value.match(/^(next\s+)?(sunday|monday|tuesday|wednesday|thursday|friday|saturday)$/);
  if (match) {
    let offset = (BULK_WEEKDAYS[match[2]] - base.getDay() + 7) % 7;
    if (match[1] && offset === 0) offset = 7;
    base.setDate(base.getDate() + offset);
    return taskDateFromLocal(base);
  }

  match = value.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (match) {
    const date = validBulkDate(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    return date ? taskDateFromLocal(date) : null;
  }
  match = value.match(/^(\d{1,2})[\/-](\d{1,2})[\/-](\d{4})$/);
  if (match) {
    const date = validBulkDate(Number(match[3]), Number(match[1]) - 1, Number(match[2]));
    return date ? taskDateFromLocal(date) : null;
  }
  match = value.match(/^([a-z]+)\s+(\d{1,2})(?:,?\s+(\d{4}))?$/);
  if (match && Object.prototype.hasOwnProperty.call(BULK_MONTHS, match[1])) {
    let year = match[3] ? Number(match[3]) : base.getFullYear();
    let date = validBulkDate(year, BULK_MONTHS[match[1]], Number(match[2]));
    if (date && !match[3] && date < base) date = validBulkDate(year + 1, BULK_MONTHS[match[1]], Number(match[2]));
    return date ? taskDateFromLocal(date) : null;
  }
  return null;
}

function normalizeBulkTime(raw) {
  let value = String(raw || '').trim();
  if (!value) return '';
  value = value.replace(/^(\d{1,2})\s*(am|pm)$/i, '$1:00 $2');
  return normalizeDueTime(value);
}

function parseBulkTaskLine(originalLine, lineNumber, defaults) {
  let text = String(originalLine || '').replace(/^\s*(?:[-*\u2022]\s+|\d+[.)]\s+|\[[ xX]\]\s*)/, '').trim();
  const result = {line: lineNumber, title: '', due_date: defaults.due_date, due_time: '', priority: defaults.priority, notes: 'No notes', valid: false, error: ''};
  if (!text) return {...result, error: 'Empty line'};

  if (text.includes('|')) {
    const fields = text.split('|').map(field => field.trim());
    result.title = fields[0] || '';
    if (fields[1]) {
      result.due_date = parseBulkDateValue(fields[1]);
      if (!result.due_date) result.error = 'Invalid date';
    }
    if (fields[2]) {
      result.due_time = normalizeBulkTime(fields[2]);
      if (result.due_time === null) result.error = result.error || 'Invalid time';
    }
    if (fields[3]) {
      const priority = Number(fields[3].replace(/^(?:p|priority\s*)/i, ''));
      if (Number.isInteger(priority) && priority >= 1 && priority <= 5) result.priority = String(priority);
      else result.error = result.error || 'Priority must be 1-5';
    }
    const notes = fields.slice(4).join(' | ').trim();
    if (notes) result.notes = notes;
  } else {
    const notesMatch = text.match(/\s+notes?\s*:\s*(.+)$/i);
    if (notesMatch) {
      result.notes = notesMatch[1].trim() || 'No notes';
      text = text.slice(0, notesMatch.index).trim();
    }

    const priorityMatch = text.match(/(?:^|\s)(?:p|priority\s*)([1-5])\b/i);
    if (priorityMatch) {
      result.priority = priorityMatch[1];
      text = `${text.slice(0, priorityMatch.index)} ${text.slice(priorityMatch.index + priorityMatch[0].length)}`.trim();
    }

    const datePatterns = [
      /\b\d{4}-\d{1,2}-\d{1,2}\b/i,
      /\b\d{1,2}[\/-]\d{1,2}[\/-]\d{4}\b/i,
      /\b(?:today|tomorrow)\b/i,
      /\b(?:next\s+)?(?:sunday|monday|tuesday|wednesday|thursday|friday|saturday)\b/i,
      /\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}(?:,?\s+\d{4})?\b/i,
    ];
    const dateMatch = datePatterns.map(pattern => text.match(pattern)).find(Boolean);
    if (dateMatch) {
      result.due_date = parseBulkDateValue(dateMatch[0]);
      if (!result.due_date) result.error = 'Invalid date';
      text = `${text.slice(0, dateMatch.index)} ${text.slice(dateMatch.index + dateMatch[0].length)}`.trim();
    }

    const timeMatch = text.match(/\b(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)|(?:[01]?\d|2[0-3]):[0-5]\d)\b/i);
    if (timeMatch) {
      result.due_time = normalizeBulkTime(timeMatch[1]);
      if (result.due_time === null) result.error = result.error || 'Invalid time';
      text = `${text.slice(0, timeMatch.index)} ${text.slice(timeMatch.index + timeMatch[0].length)}`.trim();
    }
    result.title = text.replace(/[,:;\u2013\u2014-]+\s*$/, '').replace(/\b(?:due|on|at)\s*$/i, '').trim();
  }

  if (!result.title) result.error = result.error || 'Task name is missing';
  if (!result.due_date || !isValidDueDate(result.due_date)) result.error = result.error || 'A valid due date is required';
  result.valid = !result.error;
  return result;
}

function parseBulkTasks() {
  const dateInput = document.getElementById('bulk-default-date').value;
  const defaults = {
    due_date: dateInput ? parseBulkDateValue(dateInput) : taskDateFromLocal(new Date()),
    priority: document.getElementById('bulk-default-priority').value || '3',
  };
  bulkParsedTasks = document.getElementById('bulk-task-input').value.split(/\r?\n/)
    .map((line, index) => ({line, index: index + 1})).filter(item => item.line.trim())
    .map(item => parseBulkTaskLine(item.line, item.index, defaults));
  return bulkParsedTasks;
}

function renderBulkTaskPreview() {
  const tasks = parseBulkTasks();
  const preview = document.getElementById('bulk-task-preview');
  const error = document.getElementById('bulk-task-error');
  const button = document.getElementById('bulk-add-button');
  if (!tasks.length) {
    preview.innerHTML = '<div class="empty-msg">Enter tasks above to preview them before saving.</div>';
    error.style.display = 'none';
    button.disabled = true;
    button.textContent = 'Add Tasks';
    return;
  }
  const invalidCount = tasks.filter(task => !task.valid).length;
  preview.innerHTML = `<table class="bulk-preview-table"><thead><tr><th>Line</th><th>Task</th><th>Date</th><th>Time</th><th>Priority</th><th>Check</th></tr></thead><tbody>${tasks.map(task => `
    <tr class="${task.valid ? '' : 'invalid'}"><td>${task.line}</td><td>${escHtml(task.title || 'â€”')}</td><td>${escHtml(task.due_date || 'â€”')}</td><td>${escHtml(task.due_time ? fmtTime(task.due_time) : 'No time')}</td><td>${escHtml(task.priority)}</td><td>${task.valid ? 'Ready' : escHtml(task.error)}</td></tr>`).join('')}</tbody></table>`;
  error.textContent = invalidCount ? `${invalidCount} ${invalidCount === 1 ? 'line needs' : 'lines need'} attention. Nothing will be saved until every line is valid.` : '';
  error.style.display = invalidCount ? 'block' : 'none';
  button.disabled = invalidCount > 0;
  button.textContent = `Add ${tasks.length} ${tasks.length === 1 ? 'Task' : 'Tasks'}`;
}

function openBulkTaskModal() {
  const now = new Date();
  const pad = value => String(value).padStart(2, '0');
  document.getElementById('bulk-default-date').value = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  document.getElementById('bulk-default-priority').value = '3';
  document.getElementById('bulk-task-input').value = '';
  document.getElementById('bulk-task-error').style.display = 'none';
  bulkParsedTasks = [];
  renderBulkTaskPreview();
  document.getElementById('bulk-task-modal').style.display = 'flex';
  setTimeout(() => document.getElementById('bulk-task-input').focus(), 50);
}

function closeBulkTaskModal() {
  document.getElementById('bulk-task-modal').style.display = 'none';
}

async function saveBulkTasks() {
  const tasks = parseBulkTasks();
  renderBulkTaskPreview();
  if (!tasks.length || tasks.some(task => !task.valid)) return;
  const button = document.getElementById('bulk-add-button');
  const error = document.getElementById('bulk-task-error');
  button.disabled = true;
  button.textContent = `Adding ${tasks.length}...`;
  try {
    const data = await api('POST', '/api/tasks/bulk', {tasks: tasks.map(({title, due_date, due_time, priority, notes}) => ({title, due_date, due_time, priority, notes}))}, 120000);
    closeBulkTaskModal();
    await loadTasks();
    alert(`Added ${data.added ?? tasks.length} ${tasks.length === 1 ? 'task' : 'tasks'}.`);
  } catch (exception) {
    error.textContent = exception.message;
    error.style.display = 'block';
  } finally {
    button.disabled = false;
    renderBulkTaskPreview();
  }
}

document.getElementById('bulk-task-input').addEventListener('input', renderBulkTaskPreview);
document.getElementById('bulk-default-date').addEventListener('change', renderBulkTaskPreview);
document.getElementById('bulk-default-priority').addEventListener('change', renderBulkTaskPreview);

function openAddTask() {
  document.getElementById('modal-title').textContent = 'Add Task';
  document.getElementById('edit-task-id').value = '';
  ['f-title','f-date','f-time','f-notes'].forEach(id => document.getElementById(id).value = '');
  document.getElementById('f-priority').value = '3';
  document.getElementById('f-reminder-email-enabled').checked = false;
  document.getElementById('f-reminder-email').value = '';
  document.getElementById('f-reminder-sms-enabled').checked = false;
  document.getElementById('f-reminder-phone').value = '';
  document.getElementById('f-reminder-minutes').value = '15';
  configureReminderInputs();
  configureTaskTimeInput();
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
  document.getElementById('f-time').value         = timeForTaskInput(t.due_time || '');
  document.getElementById('f-priority').value     = t.priority || '3';
  document.getElementById('f-notes').value        = t.notes    || '';
  document.getElementById('f-reminder-email-enabled').checked = Boolean(t.reminder_email_enabled);
  document.getElementById('f-reminder-email').value = t.reminder_email || '';
  document.getElementById('f-reminder-sms-enabled').checked = Boolean(t.reminder_sms_enabled);
  document.getElementById('f-reminder-phone').value = t.reminder_phone || '';
  document.getElementById('f-reminder-minutes').value = String(t.reminder_minutes_before ?? 15);
  configureReminderInputs();
  document.getElementById('task-modal').style.display = 'flex';
}

function configureReminderInputs() {
  const emailEnabled = document.getElementById('f-reminder-email-enabled').checked;
  const smsEnabled = document.getElementById('f-reminder-sms-enabled').checked;
  document.getElementById('f-reminder-email').disabled = !emailEnabled;
  document.getElementById('f-reminder-phone').disabled = !smsEnabled;
}

function closeModal() {
  document.getElementById('task-modal').style.display = 'none';
}

async function saveTask() {
  const id       = document.getElementById('edit-task-id').value;
  const title    = document.getElementById('f-title').value.trim();
  const due_date = document.getElementById('f-date').value.trim();
  const dueTimeInput = document.getElementById('f-time').value.trim();
  const due_time = normalizeDueTime(dueTimeInput);
  const priority = document.getElementById('f-priority').value;
  const notes    = document.getElementById('f-notes').value.trim() || 'No notes';
  const emailEnabled = document.getElementById('f-reminder-email-enabled').checked;
  const reminderEmail = document.getElementById('f-reminder-email').value.trim();
  const smsEnabled = document.getElementById('f-reminder-sms-enabled').checked;
  const reminderPhone = document.getElementById('f-reminder-phone').value.trim();
  const reminder = {
    email_enabled: emailEnabled,
    email: reminderEmail,
    sms_enabled: smsEnabled,
    phone: reminderPhone,
    minutes_before: Number(document.getElementById('f-reminder-minutes').value),
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
  };

  if (!title) { alert('Task name is required.'); return; }
  if (!due_date) { alert('Due date is required (MM-DD-YYYY).'); return; }
  if (!isValidDueDate(due_date)) { alert('Enter a valid due date in MM-DD-YYYY format.'); return; }
  if (due_time === null) {
    alert(use24Hour ? 'Enter time as HH:MM (for example, 09:30 or 17:30).' : 'Enter time as HH:MM AM/PM (for example, 9:30 AM or 5:30 PM).');
    return;
  }
  if ((emailEnabled || smsEnabled) && !due_time) {
    alert('A due time is required when reminders are enabled.');
    return;
  }
  if (emailEnabled && !document.getElementById('f-reminder-email').checkValidity()) {
    alert('Enter a valid reminder email address.');
    return;
  }
  if (smsEnabled && !/^\+[1-9]\d{7,14}$/.test(reminderPhone.replace(/[\s().-]/g, ''))) {
    alert('Enter the phone number in international format, such as +15551234567.');
    return;
  }

  if (id) {
    await api('PUT', `/api/tasks/${id}`, { title, due_date, due_time, priority, notes, reminder });
  } else {
    await api('POST', '/api/tasks', { title, due_date, due_time, priority, notes, reminder });
  }
  closeModal();
  loadTasks();
}

const taskDateInput = document.getElementById('f-date');
const nativeTaskDatePicker = document.getElementById('f-date-picker');
taskDateInput.addEventListener('input', () => {
  taskDateInput.value = formatDueDateTyping(taskDateInput.value);
});
taskDateInput.addEventListener('blur', () => {
  taskDateInput.setCustomValidity(taskDateInput.value && !isValidDueDate(taskDateInput.value)
    ? 'Enter a valid date in MM-DD-YYYY format.' : '');
});
nativeTaskDatePicker.addEventListener('change', () => {
  if (!nativeTaskDatePicker.value) return;
  const [year, month, day] = nativeTaskDatePicker.value.split('-');
  taskDateInput.value = `${month}-${day}-${year}`;
  taskDateInput.setCustomValidity('');
});
document.getElementById('f-date-picker-btn').addEventListener('click', () => {
  if (isValidDueDate(taskDateInput.value)) {
    const [month, day, year] = taskDateInput.value.split('-');
    nativeTaskDatePicker.value = `${year}-${month}-${day}`;
  }
  if (typeof nativeTaskDatePicker.showPicker === 'function') nativeTaskDatePicker.showPicker();
  else nativeTaskDatePicker.click();
});

/* ══════════════════════════════════════════════════════════════════
   DAILY TASKS
══════════════════════════════════════════════════════════════════ */
async function loadDaily() {
  const list = document.getElementById('daily-list');
  list.innerHTML = '<div class="empty-msg">Loading...</div>';
  const now = new Date();
  const day = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][now.getDay()];
  const localDate = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
  const data = await api('GET', `/api/daily?day=${day}&date=${localDate}`);
  const tasks = data.tasks ?? [];
  window.currentDailyTasks = tasks;
  if (!tasks.length) {
    list.innerHTML = '<div class="empty-msg">No daily task schedules yet.</div>';
    return;
  }
  const header = '<div class="daily-item daily-header"><span></span><span>Repeats</span><span>Time</span><span>Task</span><span>Status</span><span>Actions</span></div>';
  list.innerHTML = header + tasks.map(t => {
    const safeId = encodeURIComponent(String(t.id ?? ''));
    const status = dailyTaskStatus(t);
    const time = formatDailyScheduleTimes(t);
    const recurrence = formatDailyRecurrence(t.days || []);
    return `
    <div class="daily-item ${t.done ? 'done' : ''} ${status.className}">
      <input type="checkbox" class="daily-check" ${t.done ? 'checked' : ''}
             onchange="toggleDaily('${safeId}')"/>
      <span class="daily-days" title="${escHtml(recurrence)}">${escHtml(recurrence)}</span>
      <span class="daily-time" title="${escHtml(time)}">${escHtml(time)}</span>
      <span class="daily-title">${escHtml(t.title)}</span>
      <span class="daily-status">${escHtml(status.label)}</span>
      <span class="daily-actions">
        ${t.notes ? `<button class="btn btn-sm" onclick="openDailyNotes('${safeId}')">Notes</button>` : ''}
        ${t.source === 'remote' ? `<button class="btn btn-sm" onclick="openDailyModal('${safeId}')">Edit</button>` : ''}
        <button class="btn btn-sm btn-danger" onclick="deleteDaily('${safeId}')">Delete</button>
      </span>
    </div>`;
  }).join('');
}

function formatDailyRecurrence(days) {
  const order = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const fullNames = {Mon: 'Monday', Tue: 'Tuesday', Wed: 'Wednesday', Thu: 'Thursday',
                     Fri: 'Friday', Sat: 'Saturday', Sun: 'Sunday'};
  const selected = order.filter(day => days.includes(day));
  const key = selected.join(',');
  if (selected.length === 7) return 'Every day';
  if (key === 'Mon,Tue,Wed,Thu,Fri') return 'Every weekday';
  if (key === 'Sat,Sun') return 'Every weekend';
  if (selected.length === 1) return `Every ${fullNames[selected[0]]}`;
  if (selected.length === 6) {
    const missing = order.find(day => !selected.includes(day));
    return `Every day except ${fullNames[missing]}`;
  }
  if (!selected.length) return 'No days selected';
  const names = selected.map(day => selected.length <= 2 ? fullNames[day] : day);
  return `Every ${names.length === 2 ? names.join(' & ') : `${names.slice(0, -1).join(', ')} & ${names.at(-1)}`}`;
}

function formatDailyScheduleTimes(task) {
  const schedules = Array.isArray(task.schedules) && task.schedules.length
    ? task.schedules
    : [{days: task.days || [], start_time: task.start_time || '', end_time: task.end_time || ''}];
  const formatRange = schedule => schedule.end_time
    ? `${fmtTime(schedule.start_time)} - ${fmtTime(schedule.end_time)}`
    : fmtTime(schedule.start_time);
  if (schedules.length === 1) return formatRange(schedules[0]);
  return schedules.map(schedule => `${(schedule.days || []).join(', ')}: ${formatRange(schedule)}`).join('; ');
}

function dailyTaskStatus(task) {
  if (task.done) return {label: 'Completed', className: 'completed'};
  if (task.scheduled_today === false) return {label: 'Not Today', className: 'not-today'};
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  const toMinutes = value => {
    const normalized = normalizeDueTime(value);
    if (!normalized) return 0;
    const [hour, minute] = normalized.split(':').map(Number);
    return hour * 60 + minute;
  };
  const start = toMinutes(task.start_time);
  const end = task.end_time ? toMinutes(task.end_time) : start;
  const deadline = end === 0 ? 1439 : end;
  if (minutes > deadline) return {label: 'Overdue', className: 'overdue'};
  if (task.end_time && minutes >= start && minutes <= deadline) return {label: 'In Progress', className: 'in-progress'};
  return {label: 'Pending', className: 'pending'};
}

function configureDailyTimeInputs() {
  document.getElementById('daily-start-label').textContent = use24Hour ? 'Start Time * (HH:MM)' : 'Start Time * (HH:MM AM/PM)';
  document.getElementById('daily-end-label').textContent = use24Hour ? 'End Time (optional, HH:MM)' : 'End Time (optional, HH:MM AM/PM)';
  document.getElementById('daily-start').placeholder = use24Hour ? '09:00' : '9:00 AM';
  document.getElementById('daily-end').placeholder = use24Hour ? '10:00' : '10:00 AM';
  document.querySelectorAll('.daily-day-start').forEach(input => { input.placeholder = use24Hour ? '09:00' : '9:00 AM'; });
  document.querySelectorAll('.daily-day-end').forEach(input => { input.placeholder = use24Hour ? '10:00' : '10:00 AM'; });
}

let dailyScheduleDrafts = {};

function selectedDailyDays() {
  return [...document.querySelectorAll('input[name="daily-day"]:checked')].map(box => box.value);
}

function captureDailyScheduleDrafts() {
  document.querySelectorAll('.daily-day-time-row').forEach(row => {
    dailyScheduleDrafts[row.dataset.day] = {
      start_time: row.querySelector('.daily-day-start').value,
      end_time: row.querySelector('.daily-day-end').value,
    };
  });
}

function renderDailyDayTimeRows() {
  const container = document.getElementById('daily-day-times');
  const custom = document.getElementById('daily-custom-times').checked;
  captureDailyScheduleDrafts();
  container.hidden = !custom;
  document.getElementById('daily-default-times').hidden = custom;
  if (!custom) return;

  const fallbackStart = document.getElementById('daily-start').value || timeForTaskInput('09:00');
  const fallbackEnd = document.getElementById('daily-end').value;
  const fullNames = {Mon: 'Monday', Tue: 'Tuesday', Wed: 'Wednesday', Thu: 'Thursday',
                     Fri: 'Friday', Sat: 'Saturday', Sun: 'Sunday'};
  container.innerHTML = selectedDailyDays().map(day => {
    const draft = dailyScheduleDrafts[day] || {start_time: fallbackStart, end_time: fallbackEnd};
    dailyScheduleDrafts[day] = draft;
    return `<div class="daily-day-time-row" data-day="${day}">
      <strong>${fullNames[day]}</strong>
      <label>Start *<input class="input daily-day-start" type="text" value="${escHtml(draft.start_time)}"/></label>
      <label>End (optional)<input class="input daily-day-end" type="text" value="${escHtml(draft.end_time)}"/></label>
    </div>`;
  }).join('');
  configureDailyTimeInputs();
}

function toggleDailyCustomTimes() {
  renderDailyDayTimeRows();
}

function configureDailyReminderInputs() {
  document.getElementById('daily-reminder-email').disabled = !document.getElementById('daily-reminder-email-enabled').checked;
  document.getElementById('daily-reminder-phone').disabled = !document.getElementById('daily-reminder-sms-enabled').checked;
}

function openDailyNotes(encodedId) {
  const id = decodeURIComponent(encodedId);
  const task = (window.currentDailyTasks || []).find(item => String(item.id) === id);
  if (task) showNotes(id, task.title, task.notes || 'No notes');
}

function openDailyModal(encodedId = '') {
  const id = encodedId ? decodeURIComponent(encodedId) : '';
  const task = id ? (window.currentDailyTasks || []).find(item => String(item.id) === id) : null;
  document.getElementById('daily-modal-title').textContent = task ? 'Edit Daily Task' : 'Add Daily Task';
  document.getElementById('edit-daily-id').value = id;
  document.getElementById('daily-title').value = task?.title || '';
  document.getElementById('daily-start').value = timeForTaskInput(task?.start_time || '09:00');
  document.getElementById('daily-end').value = task?.end_time ? timeForTaskInput(task.end_time) : '';
  const schedules = Array.isArray(task?.schedules) && task.schedules.length
    ? task.schedules
    : [{days: task?.days || [], start_time: task?.start_time || '09:00', end_time: task?.end_time || ''}];
  dailyScheduleDrafts = {};
  document.getElementById('daily-day-times').innerHTML = '';
  schedules.forEach(schedule => (schedule.days || []).forEach(day => {
    dailyScheduleDrafts[day] = {
      start_time: timeForTaskInput(schedule.start_time || '09:00'),
      end_time: schedule.end_time ? timeForTaskInput(schedule.end_time) : '',
    };
  }));
  document.getElementById('daily-custom-times').checked = schedules.length > 1;
  document.getElementById('daily-notes').value = task?.notes || '';
  document.getElementById('daily-reminder-email-enabled').checked = Boolean(task?.reminder_email_enabled);
  document.getElementById('daily-reminder-email').value = task?.reminder_email || '';
  document.getElementById('daily-reminder-sms-enabled').checked = Boolean(task?.reminder_sms_enabled);
  document.getElementById('daily-reminder-phone').value = task?.reminder_phone || '';
  document.getElementById('daily-reminder-minutes').value = String(task?.reminder_minutes_before ?? 15);
  document.querySelectorAll('input[name="daily-day"]').forEach(box => { box.checked = task ? task.days.includes(box.value) : true; });
  document.getElementById('daily-form-error').style.display = 'none';
  configureDailyTimeInputs();
  renderDailyDayTimeRows();
  configureDailyReminderInputs();
  document.getElementById('daily-modal').style.display = 'flex';
  document.getElementById('daily-title').focus();
}

function closeDailyModal() { document.getElementById('daily-modal').style.display = 'none'; }

async function saveDailyTask() {
  const id = document.getElementById('edit-daily-id').value;
  const title = document.getElementById('daily-title').value.trim();
  const days = selectedDailyDays();
  const customTimes = document.getElementById('daily-custom-times').checked;
  let start_time = normalizeDueTime(document.getElementById('daily-start').value);
  let endInput = document.getElementById('daily-end').value.trim();
  let end_time = endInput ? normalizeDueTime(endInput) : '';
  let schedules = [];
  let scheduleError = '';
  if (customTimes) {
    captureDailyScheduleDrafts();
    schedules = days.map(day => {
      const draft = dailyScheduleDrafts[day] || {};
      const normalizedStart = normalizeDueTime(draft.start_time);
      const rawEnd = String(draft.end_time || '').trim();
      const normalizedEnd = rawEnd ? normalizeDueTime(rawEnd) : '';
      if (!normalizedStart) scheduleError = `${day} needs a valid start time.`;
      else if (rawEnd && !normalizedEnd) scheduleError = `${day} needs a valid end time or a blank end time.`;
      return {days: [day], start_time: normalizedStart || '', end_time: normalizedEnd || ''};
    });
    if (schedules.length) {
      start_time = schedules[0].start_time;
      end_time = schedules[0].end_time;
    }
  } else {
    schedules = [{days, start_time: start_time || '', end_time: end_time || ''}];
  }
  const notes = document.getElementById('daily-notes').value.trim();
  const emailEnabled = document.getElementById('daily-reminder-email-enabled').checked;
  const smsEnabled = document.getElementById('daily-reminder-sms-enabled').checked;
  const reminderEmail = document.getElementById('daily-reminder-email').value.trim();
  const reminderPhone = document.getElementById('daily-reminder-phone').value.trim();
  const reminder = {email_enabled: emailEnabled, email: reminderEmail, sms_enabled: smsEnabled,
    phone: reminderPhone, minutes_before: Number(document.getElementById('daily-reminder-minutes').value),
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'};
  const error = document.getElementById('daily-form-error');
  let message = '';
  if (!title) message = 'Task name is required.';
  else if (!days.length) message = 'Select at least one day.';
  else if (scheduleError) message = scheduleError;
  else if (!start_time) message = 'Enter a valid start time.';
  else if (!customTimes && endInput && !end_time) message = 'Enter a valid end time or leave it blank.';
  else if (emailEnabled && !document.getElementById('daily-reminder-email').checkValidity()) message = 'Enter a valid reminder email address.';
  else if (smsEnabled && !/^\+[1-9]\d{7,14}$/.test(reminderPhone.replace(/[\s().-]/g, ''))) message = 'Enter the phone number in international format, such as +15551234567.';
  if (message) { error.textContent = message; error.style.display = 'block'; return; }
  try {
    const result = await api(id ? 'PUT' : 'POST', id ? `/api/daily/${encodeURIComponent(id)}` : '/api/daily',
      {title, days, start_time, end_time, schedules, notes, reminder});
    if (result.status === 'partial') {
      closeDailyModal();
      await loadDaily();
      alert(result.message || 'The schedule was saved, but part of the reminder setup failed.');
      return;
    }
    if (result.status !== 'success') throw new Error(result.message || 'Could not save daily task.');
    closeDailyModal();
    loadDaily();
  } catch (e) { error.textContent = e.message; error.style.display = 'block'; }
}

async function toggleDaily(id) {
  const now = new Date();
  const localDate = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
  await api('POST', `/api/daily/${id}/toggle`, {date: localDate});
  loadDaily();
}

async function deleteDaily(id) {
  if (!confirm('Delete this daily task?')) return;
  await api('DELETE', `/api/daily/${id}`);
  loadDaily();
}

async function clearAllDaily() {
  if (!confirm('Clear all daily tasks shown for today? Regular tasks and schedules for other days will be kept.')) return;
  const now = new Date();
  const day = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][now.getDay()];
  const localDate = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
  await api('POST', '/api/daily/clear', {day, date: localDate});
  loadDaily();
}

/* ══════════════════════════════════════════════════════════════════
   AI ASSISTANT
══════════════════════════════════════════════════════════════════ */
async function initAI() {
  const statusBox = document.getElementById('ai-status');
  statusBox.textContent = 'Checking…';
  if (!attestationLoaded) loadAttestation();

  if (!selectedAiModelSetting) {
    try {
      const s = await api('GET', '/api/settings');
      selectedAiModelSetting = (s.settings?.phala_ai_model || '').trim();
    } catch {}
  }

  try {
    const h = await api('GET', '/api/ai/health');
    const ok = ['ok', 'success', 'healthy'].includes(String(h?.status || '').toLowerCase());
    statusBox.textContent = ok
      ? (selectedAiModelSetting ? `✓ AI service online\nDefault model: ${selectedAiModelSetting}` : '✓ AI service online')
      : `⚠ AI service reported an issue${h?.message ? `\n${h.message}` : ''}`;
  } catch {
    statusBox.textContent = '✗ AI service unreachable';
  }

  if (!modelCatalog.length) await loadModelCatalog();

  document.getElementById('zdr-toggle').checked = zdrEnabled;
  document.getElementById('zdr-help-text').style.display = zdrEnabled ? 'block' : 'none';
  await rebuildModelSelect();

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
    closeBulkTaskModal();
    closeBulkEditModal();
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
  if (!prompt && !attachedImageDataUrl) return;

  const selectedModel = document.getElementById('ai-model-select').value;
  if (zdrEnabled && !selectedModel) { alert('Select a Zero Data Retention model first.'); return; }

  const entry = currentModelEntry();
  const supportsImage = !!entry && (entry.input_modalities || []).includes('image');
  if (attachedImageDataUrl && !supportsImage) {
    alert('Select a vision-capable model before sending an image.');
    return;
  }

  const responseFormat = buildResponseFormat();
  if (responseFormat === undefined) return;

  appendAIMessage('user', prompt || '(image)');
  input.value = '';
  const imageToSend = attachedImageDataUrl;
  removeAttachedImage();

  const userTurn = { role: 'user', content: buildUserContent(prompt, imageToSend) };
  conversationHistory.push(userTurn);
  trimHistory();

  const historyForRequest = sanitizeHistoryForModel(conversationHistory.slice(0, -1), supportsImage);

  if (toolsEnabled && !imageToSend) {
    const thinking = appendAIMessage('bot thinking', '…thinking…');
    try {
      const localNow = new Date();
      const localDay = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][localNow.getDay()];
      const localDate = `${localNow.getFullYear()}-${String(localNow.getMonth()+1).padStart(2,'0')}-${String(localNow.getDate()).padStart(2,'0')}`;
      const localTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
      const d = await api('POST', '/api/ai/chat/tools', {
        prompt, model: selectedModel, zdr: zdrEnabled, history: historyForRequest,
        local_date: localDate, local_day: localDay, local_timezone: localTimezone,
      }, 300000);
      thinking.remove();
      if (d.status === 'success') {
        appendAIBotResponse(d.response || '(no response)', d);
        conversationHistory.push({ role: 'assistant', content: d.response || '' });
        if (d.tasks_changed) await loadTasks();
        if (d.daily_tasks_changed) await loadDaily();
      } else {
        appendAIBotResponse(`⚠ ${d.message || 'Unknown AI error'}`, d);
        conversationHistory.pop(); // don't keep a turn that failed
      }
    } catch (e) {
      thinking.remove();
      appendAIBotResponse(`✗ Error: ${e.message}`, {});
      conversationHistory.pop();
    }
    return;
  }

  if (streamEnabled) {
    await sendAIStreaming(prompt, selectedModel, imageToSend, responseFormat, historyForRequest);
    return;
  }

  const thinking = appendAIMessage('bot thinking', '…thinking…');
  try {
    const d = await api('POST', '/api/ai/chat', {
      prompt, model: selectedModel, zdr: zdrEnabled, image_url: imageToSend || '',
      response_format: responseFormat || undefined, history: historyForRequest,
    }, 120000);
    thinking.remove();
    if (d.status === 'success') {
      appendAIBotResponse(d.response || '(no response)', d);
      conversationHistory.push({ role: 'assistant', content: d.response || '' });
    } else {
      appendAIBotResponse(`⚠ ${d.message || 'Unknown AI error'}`, d);
      conversationHistory.pop();
    }
  } catch (e) {
    thinking.remove();
    appendAIBotResponse(`✗ Error: ${e.message}`, {});
    conversationHistory.pop();
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
      updateAttachButtonVisibility();
      return;
    }
    sel.innerHTML = zdrModels.map(m => `<option value="${escHtml(m.id)}">${escHtml(modelLabel(m))}</option>`).join('');
    sel.value = zdrModels.some(m => m.id === activeAiModelChoice) ? activeAiModelChoice : zdrModels[0].id;
    activeAiModelChoice = sel.value;
    sel.onchange = () => { activeAiModelChoice = sel.value; updateAttachButtonVisibility(); };
    updateAttachButtonVisibility();
    return;
  }

  const defaultLabel = selectedAiModelSetting ? `Use default (${selectedAiModelSetting})` : 'Use configured model';
  sel.innerHTML = `<option value="">${escHtml(defaultLabel)}</option>` +
    modelCatalog.map(m => `<option value="${escHtml(m.id)}">${escHtml(modelLabel(m))}</option>`).join('');

  if (activeAiModelChoice && modelCatalog.some(m => m.id === activeAiModelChoice)) {
    sel.value = activeAiModelChoice;
  } else if (selectedAiModelSetting && modelCatalog.some(m => m.id === selectedAiModelSetting)) {
    sel.value = selectedAiModelSetting;
    activeAiModelChoice = selectedAiModelSetting;
  } else {
    sel.value = '';
    activeAiModelChoice = '';
  }
  sel.onchange = () => { activeAiModelChoice = sel.value; updateAttachButtonVisibility(); };
  updateAttachButtonVisibility();
}

function onImageSelected(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    attachedImageDataUrl = reader.result;
    document.getElementById('image-attach-thumb').src = attachedImageDataUrl;
    document.getElementById('image-attach-preview').style.display = 'flex';
    checkVisionCompatibility();
  };
  reader.readAsDataURL(file);
  event.target.value = '';
}

function removeAttachedImage() {
  attachedImageDataUrl = null;
  document.getElementById('image-attach-preview').style.display = 'none';
  checkVisionCompatibility();
}

function updateAttachButtonVisibility() {
  const entry = currentModelEntry();
  const supportsImage = !!entry && (entry.input_modalities || []).includes('image');
  const attachBtn = document.getElementById('image-attach-btn');
  if (attachBtn) attachBtn.style.display = supportsImage ? 'inline-flex' : 'none';
  if (!supportsImage && attachedImageDataUrl) removeAttachedImage();
  checkVisionCompatibility();
  updateFeatureAvailability();
}

function checkVisionCompatibility() {
  const warning = document.getElementById('vision-warning');
  const sendBtn = document.getElementById('ai-send-btn');
  if (!attachedImageDataUrl) {
    warning.style.display = 'none';
    sendBtn.disabled = false;
    return;
  }
  const entry = currentModelEntry();
  const supported = entry && (entry.input_modalities || []).includes('image');
  if (!supported) {
    const pool = zdrEnabled ? zdrModels : modelCatalog;
    const visionIds = pool.filter(m => (m.input_modalities || []).includes('image')).map(m => m.id);
    warning.textContent = entry
      ? `⚠ "${entry.id}" doesn't support image analysis. Choose one of: ${visionIds.join(', ') || 'no vision models available'}.`
      : `⚠ Select a vision-capable model to analyze images: ${visionIds.join(', ') || 'none available'}.`;
    warning.style.display = 'block';
    sendBtn.disabled = true;
  } else {
    warning.style.display = 'none';
    sendBtn.disabled = false;
  }
}

async function sendAIStreaming(prompt, selectedModel, imageToSend, responseFormat, history) {
  const chat = document.getElementById('ai-chat');
  const div = document.createElement('div');
  div.className = 'ai-msg bot';
  const body = document.createElement('div');
  body.className = 'ai-text';
  div.appendChild(body);
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;

  let receiptId = '', full = '';
  try {
    const resp = await fetch('/api/ai/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt, model: selectedModel, zdr: zdrEnabled, image_url: imageToSend || '',
        response_format: responseFormat || undefined, history,
      }),
    });
    if (!resp.ok || !resp.body) {
      let msg = 'Stream request failed';
      try { const j = await resp.json(); msg = j.message || msg; } catch {}
      body.textContent = `⚠ ${msg}`;
      conversationHistory.pop();
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split('\n\n');
      buffer = events.pop() ?? '';
      for (const evt of events) {
        for (const line of evt.split('\n').filter(Boolean)) {
          if (!line.startsWith('data:')) continue;
          const dataStr = line.slice(5).trim();
          if (dataStr === '[DONE]') continue;
          try {
            const parsed = JSON.parse(dataStr);
            if (parsed.receipt_id) { receiptId = parsed.receipt_id; continue; }
            const delta = parsed.choices?.[0]?.delta?.content;
            if (delta) { full += delta; body.textContent = full; chat.scrollTop = chat.scrollHeight; }
          } catch {}
        }
      }
    }

    if (!full) {
      body.textContent = '(no response)';
      conversationHistory.pop();
    } else {
      conversationHistory.push({ role: 'assistant', content: full });
    }
    if (receiptId) {
      const meta = document.createElement('div');
      meta.className = 'ai-receipt';
      meta.textContent = `Receipt: ${receiptId} · checking…`;
      div.appendChild(meta);
      verifyReceipt(receiptId, meta);
    }
  } catch (e) {
    body.textContent = `✗ Error: ${e.message}`;
    conversationHistory.pop();
  }
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
    const dots  = tasks.map(t => {
      const time = t.due_time ? `${fmtTime(t.due_time)} ` : '';
      const marker = t.type === 'daily' ? '&#8635; ' : '';
      return `<div class="cal-dot ${t.color||'normal'}" title="${escHtml(t.title)}">${marker}${escHtml(time + t.title)}</div>`;
    }).join('');
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
function weeklyStartSlot(value) {
  const normalized = normalizeDueTime(value);
  if (!normalized) return null;
  const [hour, minute] = normalized.split(':').map(Number);
  return Math.max(0, Math.min(95, Math.floor((hour * 60 + minute) / 15)));
}

function weeklyEndSlot(value, startSlot) {
  const normalized = normalizeDueTime(value);
  if (!normalized) return null;
  const [hour, minute] = normalized.split(':').map(Number);
  const totalMinutes = hour * 60 + minute;

  // An event ending at midnight belongs at the boundary after 23:45,
  // not at the first slot of the same day. Round other end times upward
  // so 23:59 and partial quarter-hours include their entire final slot.
  if (totalMinutes === 0 && startSlot > 0) return 96;
  const slot = Math.max(1, Math.min(96, Math.ceil(totalMinutes / 15)));
  return slot <= startSlot ? 96 : slot;
}

async function loadWeekly(scrollToCurrentTime = true) {
  const now = new Date();
  const localDate = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
  const data = await api('GET', `/api/weekly?date=${localDate}`);
  const week = data.week ?? {};
  const days = data.week_days ?? [];
  const dates = data.week_dates ?? [];
  const today = now;
  const todayStr = `${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}-${today.getFullYear()}`;

  const grid = document.getElementById('weekly-grid');
  const unscheduled = document.getElementById('weekly-unscheduled');
  const layoutOverlaps = tasks => {
    const events = tasks.filter(task => task.due_time).map(task => {
      const start = weeklyStartSlot(task.due_time);
      const requestedEnd = weeklyEndSlot(task.end_time, start);
      return {...task, _start: start, _end: requestedEnd !== null ? requestedEnd : Math.min(96, start + 1)};
    }).filter(event => event._start !== null).sort((a, b) => a._start - b._start || a._end - b._end);

    let group = [];
    let groupEnd = -1;
    const finishGroup = () => {
      if (!group.length) return;
      const laneEnds = [];
      group.forEach(event => {
        let lane = laneEnds.findIndex(end => end <= event._start);
        if (lane < 0) lane = laneEnds.length;
        laneEnds[lane] = event._end;
        event._lane = lane;
      });
      group.forEach(event => { event._laneCount = laneEnds.length; });
    };

    events.forEach(event => {
      if (group.length && event._start >= groupEnd) {
        finishGroup();
        group = [];
        groupEnd = -1;
      }
      group.push(event);
      groupEnd = Math.max(groupEnd, event._end);
    });
    finishGroup();
    return events;
  };

  const dateOnlyGroups = dates.map((date, index) => ({
    day: days[index],
    tasks: (week[date] ?? []).filter(task => !normalizeDueTime(task.due_time)),
  })).filter(group => group.tasks.length);
  const dateOnlyCount = dateOnlyGroups.reduce((count, group) => count + group.tasks.length, 0);

  if (dateOnlyCount) {
    unscheduled.hidden = false;
    unscheduled.innerHTML = `
      <div class="weekly-unscheduled-heading">
        <strong>No due time</strong>
        <span>${dateOnlyCount} date-only ${dateOnlyCount === 1 ? 'task' : 'tasks'}</span>
      </div>
      <div class="weekly-unscheduled-days">
        ${dateOnlyGroups.map(group => `
          <section class="weekly-unscheduled-day">
            <strong>${escHtml(group.day)}</strong>
            <div class="weekly-unscheduled-tasks">
              ${group.tasks.map(task => `<span class="weekly-all-day-task ${task.color || 'normal'}" title="${escHtml(task.title)}">${escHtml(task.title)}</span>`).join('')}
            </div>
          </section>
        `).join('')}
      </div>`;
  } else {
    unscheduled.hidden = true;
    unscheduled.innerHTML = '';
  }

  let html = '<div class="weekly-corner">Time</div>';
  dates.forEach((date, i) => {
    html += `<div class="weekly-day-header${date === todayStr ? ' today-col' : ''}" style="grid-column:${i + 2};grid-row:1">
      <strong>${escHtml(days[i])}</strong>
    </div>`;
  });

  for (let slot = 0; slot < 96; slot++) {
    const hour = Math.floor(slot / 4);
    const minute = (slot % 4) * 15;
    const rawTime = `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
    const isCurrentSlot = slot === now.getHours() * 4 + Math.floor(now.getMinutes() / 15);
    html += `<div class="weekly-time-label${isCurrentSlot ? ' current-time-label' : ''}" data-slot="${slot}" style="grid-column:1;grid-row:${slot + 2}">${escHtml(fmtTime(rawTime))}</div>`;
    for (let dayIndex = 0; dayIndex < 7; dayIndex++) {
      const isToday = dates[dayIndex] === todayStr;
      html += `<div class="weekly-slot${isToday ? ' today-slot' : ''}${isToday && isCurrentSlot ? ' current-time-slot' : ''}${slot % 4 === 0 ? ' hour-line' : ''}" data-slot="${slot}" data-date="${dates[dayIndex]}" style="grid-column:${dayIndex + 2};grid-row:${slot + 2}"></div>`;
    }
  }

  dates.forEach((date, dayIndex) => {
    layoutOverlaps(week[date] ?? []).forEach(task => {
      const start = task._start;
      const span = task._end - task._start;
      const endLabel = task.end_time ? ` - ${fmtTime(task.end_time)}` : '';
      const marker = task.type === 'daily' ? '&#8635; ' : '';
      const laneWidth = 100 / task._laneCount;
      const laneLeft = laneWidth * task._lane;
      html += `<div class="weekly-event ${task.color || 'normal'}" style="grid-column:${dayIndex + 2};grid-row:${start + 2} / span ${span};--event-width:${laneWidth}%;--event-left:${laneLeft}%" title="${escHtml(task.title)}">
        <span class="weekly-event-time">${escHtml(fmtTime(task.due_time) + endLabel)}</span>
        <span>${marker}${escHtml(task.title)}</span>
      </div>`;
    });
  });

  grid.innerHTML = html;

  const currentSlot = now.getHours() * 4 + Math.floor(now.getMinutes() / 15);
  const currentCell = grid.querySelector(`.weekly-time-label[data-slot="${currentSlot}"]`);
  if (scrollToCurrentTime && currentCell) currentCell.scrollIntoView({block: 'center'});
}

function refreshWeeklyTimeMarker() {
  const grid = document.getElementById('weekly-grid');
  if (!grid || !document.getElementById('tab-weekly').classList.contains('active')) return;
  const now = new Date();
  const dateKey = `${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}-${now.getFullYear()}`;
  const slot = now.getHours() * 4 + Math.floor(now.getMinutes() / 15);
  const currentDaySlot = grid.querySelector(`.weekly-slot[data-date="${dateKey}"][data-slot="${slot}"]`);
  if (!currentDaySlot) {
    loadWeekly();
    return;
  }
  grid.querySelectorAll('.current-time-slot').forEach(element => element.classList.remove('current-time-slot'));
  grid.querySelectorAll('.current-time-label').forEach(element => element.classList.remove('current-time-label'));
  currentDaySlot.classList.add('current-time-slot');
  grid.querySelector(`.weekly-time-label[data-slot="${slot}"]`)?.classList.add('current-time-label');
}

/* ══════════════════════════════════════════════════════════════════
   SETTINGS
══════════════════════════════════════════════════════════════════ */
async function loadSettings() {
  const d = await api('GET', '/api/settings');
  const s = d.settings ?? {};
  use24Hour = s.use_24_hour !== false;
  selectedAiModelSetting = (s.phala_ai_model || '').trim();
  document.getElementById('setting-24h').checked = use24Hour;
  configureTaskTimeInput();
  configureDailyTimeInputs();
  if (allTasks.length) renderTasks();
  document.getElementById('setting-uid').textContent = s.web_user_id ?? '–';
  if (!modelCatalog.length) await loadModelCatalog();
  renderDefaultModelSelect();
}

function renderDefaultModelSelect() {
  const sel = document.getElementById('setting-default-model');
  if (!sel) return;
  if (!modelCatalog.length) {
    sel.innerHTML = '<option value="">No models available</option>';
    return;
  }
  sel.innerHTML = modelCatalog.map(m =>
    `<option value="${escHtml(m.id)}" ${m.id === selectedAiModelSetting ? 'selected' : ''}>${escHtml(modelLabel(m))}</option>`
  ).join('');
}

async function saveDefaultModel() {
  const sel = document.getElementById('setting-default-model');
  const model = sel.value;
  if (!model) return;
  selectedAiModelSetting = model;
  activeAiModelChoice = model;
  await saveSetting('phala_ai_model', model);
}

async function saveSetting(key, value) {
  if (key === 'use_24_hour') {
    use24Hour = value;
    configureTaskTimeInput();
    configureDailyTimeInputs();
    renderTasks();
  }
  await api('POST', '/api/settings', { [key]: value });
}

async function checkHealth() {
  const out = document.getElementById('health-output');
  const button = document.getElementById('health-check-btn');
  const checked = document.getElementById('health-last-checked');
  button.disabled = true;
  button.textContent = 'Checking...';
  out.innerHTML = '<div class="health-empty health-checking">Checking all services...</div>';
  try {
    const data = await api('GET', '/api/health/all');
    const services = data.services ?? {};
    const labels = {
      web_ui: 'Web UI',
      backend: 'Backend Storage',
      postgres: 'PostgreSQL Database',
      ai_inference: 'AI Inference',
      task_sync: 'Task Sync',
      scheduler: 'Scheduler',
      openclaw: 'OpenClaw',
    };

    const order = ['web_ui', 'backend', 'postgres', 'ai_inference', 'task_sync', 'scheduler', 'openclaw'];
    const cards = [];
    const overallClass = data.overall_ok ? 'ok' : 'degraded';
    const overallText = data.overall_ok ? 'All systems operational' : 'One or more services need attention';

    for (const key of order) {
      const svc = services[key] || {};
      const name = labels[key] || key;
      const status = svc.status || 'unknown';
      const code = svc.code || 0;
      const badge = svc.ok ? 'Healthy' : 'Unavailable';
      const badgeClass = svc.ok ? 'ok' : 'error';
      const latency = Number.isFinite(Number(svc.latency_ms)) ? `${Number(svc.latency_ms)} ms` : 'Not measured';
      const response = code ? `HTTP ${code}` : 'No response';
      const message = svc.message || (svc.ok ? 'Service responded normally' : 'Service did not report a healthy status');
      cards.push(
        `<div class="health-service ${badgeClass}">` +
          `<div class="health-service-heading">` +
            `<span class="service-name">${escHtml(name)}</span>` +
            `<span class="status-badge ${badgeClass}">${escHtml(badge)}</span>` +
          `</div>` +
          `<div class="health-service-meta">${escHtml(response)} · ${escHtml(latency)} · ${escHtml(status)}</div>` +
          `<div class="status-detail">${escHtml(message)}</div>` +
        `</div>`
      );
    }

    out.innerHTML =
      `<div class="overall ${overallClass}">${escHtml(overallText)}</div>` +
      `<div class="health-grid">${cards.join('')}</div>`;
    const timestamp = data.timestamp ? new Date(data.timestamp) : new Date();
    checked.textContent = `Last checked ${Number.isNaN(timestamp.getTime()) ? 'just now' : timestamp.toLocaleString()}`;
  } catch (e) {
    out.innerHTML = `<div class="overall degraded">Health check failed</div>` +
      `<div class="health-empty health-error">${escHtml(e?.message || e)}</div>`;
    checked.textContent = 'Last check failed';
  } finally {
    button.disabled = false;
    button.textContent = 'Check Again';
  }
}

/* ── Keyboard shortcuts ─────────────────────────────────────────── */
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeModal();
    closeBulkTaskModal();
    closeBulkEditModal();
    closeDailyModal();
    document.getElementById('notes-modal').style.display = 'none';
    closeFullNotes();
  }
});

/* ── Boot ───────────────────────────────────────────────────────── */
loadTasks();
loadCharacter();
loadSettings();
checkMeetingProposals();
setInterval(checkMeetingProposals, 30000);
setInterval(() => {
  if (document.getElementById('tab-daily').classList.contains('active')) loadDaily();
}, 60000);
setInterval(() => {
  if (document.getElementById('tab-calendar').classList.contains('active')) renderCalendar();
  if (document.getElementById('tab-weekly').classList.contains('active')) loadWeekly(false);
}, 60000);
setInterval(refreshWeeklyTimeMarker, 60000);
