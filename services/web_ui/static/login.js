let isRegisterMode = false;

function showError(msg) {
  const el = document.getElementById('login-error');
  el.textContent = msg;
  el.style.display = 'block';
}
function clearError() {
  document.getElementById('login-error').style.display = 'none';
}

document.getElementById('toggle-mode').addEventListener('click', (e) => {
  e.preventDefault();
  isRegisterMode = !isRegisterMode;
  document.getElementById('submit-btn').textContent = isRegisterMode ? 'Create Account' : 'Sign In';
  document.getElementById('login-subtitle').textContent = isRegisterMode
    ? 'Create an account to sync your tasks' : 'Sign in to sync your tasks';
  document.getElementById('toggle-text').textContent = isRegisterMode
    ? 'Already have an account?' : "Don't have an account?";
  document.getElementById('toggle-mode').textContent = isRegisterMode ? 'Sign in' : 'Create one';
  document.getElementById('display-name-group').style.display = isRegisterMode ? 'block' : 'none';
  document.getElementById('f-password').autocomplete = isRegisterMode ? 'new-password' : 'current-password';
  clearError();
});

document.getElementById('auth-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  clearError();
  const email = document.getElementById('f-email').value.trim();
  const password = document.getElementById('f-password').value;
  const submitBtn = document.getElementById('submit-btn');
  submitBtn.disabled = true;
  try {
    const endpoint = isRegisterMode ? '/api/auth/register' : '/api/auth/login';
    const body = { email, password };
    if (isRegisterMode) body.display_name = document.getElementById('f-display-name').value.trim();

    const resp = await fetch(endpoint, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (resp.ok && data.status === 'success') window.location.href = '/';
    else if (data.status === 'verification_required') openVerifyModal(email);
    else showError(data.message || 'Something went wrong. Please try again.');
  } catch {
    showError('Network error. Please check your connection and try again.');
  } finally {
    submitBtn.disabled = false;
  }
});

let verificationEmail = '';
function openVerifyModal(email) {
  verificationEmail = email;
  document.getElementById('verify-modal').style.display = 'flex';
  document.getElementById('verify-code').focus();
  document.getElementById('verify-status').textContent = 'Check your inbox for the verification code.';
}
function closeVerifyModal() { document.getElementById('verify-modal').style.display = 'none'; }
async function verifyEmail() {
  const code = document.getElementById('verify-code').value.trim();
  const status = document.getElementById('verify-status');
  const verifyBtn = document.getElementById('verify-btn');
  if (!/^\d{6}$/.test(code)) { status.textContent = 'Enter the six-digit code.'; return; }
  verifyBtn.disabled = true;
  verifyBtn.textContent = 'Verifying...';
  status.textContent = 'Checking your code...';
  try {
    const resp = await fetch('/api/auth/verify-email', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({email: verificationEmail, code}) });
    const data = await resp.json().catch(() => ({}));
    if (resp.ok && data.status === 'success') {
      status.textContent = 'Email verified. Signing you in...';
      window.location.assign('/');
      return;
    }
    status.textContent = data.message || `Verification failed (${resp.status}).`;
  } catch {
    status.textContent = 'Network error. Please try again.';
  } finally {
    verifyBtn.disabled = false;
    verifyBtn.textContent = 'Verify';
  }
}

document.getElementById('verify-btn').addEventListener('click', verifyEmail);
document.getElementById('verify-code').addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    verifyEmail();
  }
});

document.getElementById('forgot-link').addEventListener('click', (e) => {
  e.preventDefault();
  document.getElementById('reset-modal').style.display = 'flex';
  document.getElementById('reset-request-view').style.display = 'block';
  document.getElementById('reset-confirm-view').style.display = 'none';
  document.getElementById('reset-status').textContent = '';
  document.getElementById('reset-email').value = document.getElementById('f-email').value.trim();
});
function closeResetModal() { document.getElementById('reset-modal').style.display = 'none'; }

async function requestReset() {
  const email = document.getElementById('reset-email').value.trim();
  const statusEl = document.getElementById('reset-status');
  if (!email) { statusEl.textContent = 'Enter your email first.'; return; }
  statusEl.textContent = 'Sending…';
  try {
    const resp = await fetch('/api/auth/password-reset/request', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email }),
    });
    const data = await resp.json();
    statusEl.textContent = data.message || 'If that email exists, a reset link has been sent.';
  } catch { statusEl.textContent = 'Network error. Please try again.'; }
}

// Arriving via emailed reset link: /login?token=...
(function checkResetToken() {
  const token = new URLSearchParams(window.location.search).get('token');
  if (!token) return;
  document.getElementById('reset-modal').style.display = 'flex';
  document.getElementById('reset-request-view').style.display = 'none';
  document.getElementById('reset-confirm-view').style.display = 'block';
  document.getElementById('reset-confirm-view').dataset.token = token;
})();

async function confirmReset() {
  const token = document.getElementById('reset-confirm-view').dataset.token;
  const password = document.getElementById('reset-new-password').value;
  const statusEl = document.getElementById('reset-status');
  if (password.length < 8) { statusEl.textContent = 'Password must be at least 8 characters.'; return; }
  statusEl.textContent = 'Saving…';
  try {
    const resp = await fetch('/api/auth/password-reset/confirm', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, password }),
    });
    const data = await resp.json();
    if (resp.ok && data.status === 'success') {
      statusEl.textContent = 'Password updated! You can sign in now.';
      setTimeout(closeResetModal, 1500);
    } else statusEl.textContent = data.message || 'Could not reset password.';
  } catch { statusEl.textContent = 'Network error. Please try again.'; }
}
