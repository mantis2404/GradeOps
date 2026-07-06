/**
 * pages/login.js — User login and registration.
 */

import { login, register } from '../api/auth.js';
import { showToast } from '../components/toast.js';
import { store } from '../state.js';

export async function render(container) {
  const isRegistering = store._isRegistering || false;

  container.innerHTML = `
    <div style="max-width:400px; margin: 80px auto;">
      <div class="card">
        <div class="card-title">${isRegistering ? 'Create an account' : 'Sign in to GradeFlow'}</div>
        <p class="page-sub" style="margin-bottom:24px">
          ${isRegistering ? 'Join the grading platform' : 'Welcome back! Please enter your details.'}
        </p>

        ${isRegistering ? `
          <div class="form-group">
            <label class="form-label" for="reg-name">Full Name</label>
            <input type="text" id="reg-name" placeholder="Prof. Jane Doe">
          </div>
        ` : ''}

        <div class="form-group">
          <label class="form-label" for="auth-email">Email address</label>
          <input type="email" id="auth-email" placeholder="you@university.edu">
        </div>

        <div class="form-group">
          <label class="form-label" for="auth-password">Password</label>
          <input type="password" id="auth-password" placeholder="••••••••">
        </div>

        ${isRegistering ? `
          <div class="form-group">
            <label class="form-label">Role</label>
            <select id="reg-role" class="form-label" style="width:100%; padding:8px; border-radius:var(--radius-sm); border:1px solid var(--neutral-200);">
              <option value="ta">Teaching Assistant (TA)</option>
              <option value="instructor">Instructor</option>
              <option value="admin">Central Admin</option>
            </select>
          </div>
        ` : ''}

        <button class="btn btn-primary" style="width:100%; margin-top:8px;" id="auth-submit-btn">
          ${isRegistering ? 'Register' : 'Sign in'}
        </button>

        <div style="margin-top:24px; text-align:center; font-size:var(--text-sm); color:var(--neutral-600);">
          ${isRegistering 
            ? 'Already have an account? <a href="#" id="toggle-auth-mode" style="color:var(--brand); font-weight:500;">Sign in</a>' 
            : 'Don\'t have an account? <a href="#" id="toggle-auth-mode" style="color:var(--brand); font-weight:500;">Create one</a>'}
        </div>
      </div>
    </div>`;

  bindEvents(container, isRegistering);
}

function bindEvents(container, isRegistering) {
  container.querySelector('#toggle-auth-mode').addEventListener('click', (e) => {
    e.preventDefault();
    store._isRegistering = !isRegistering;
    render(container);
  });

  container.querySelector('#auth-submit-btn').addEventListener('click', async () => {
    const email = container.querySelector('#auth-email').value.trim();
    const password = container.querySelector('#auth-password').value;
    
    if (!email || !password) {
      showToast('Please fill in all fields', 'error');
      return;
    }

    const btn = container.querySelector('#auth-submit-btn');
    btn.disabled = true;
    btn.textContent = isRegistering ? 'Registering...' : 'Signing in...';

    try {
      if (isRegistering) {
        const name = container.querySelector('#reg-name').value.trim();
        const role = container.querySelector('#reg-role').value;
        if (!name) { showToast('Name is required', 'error'); btn.disabled = false; return; }
        
        await register({ email, name, password, role });
        showToast('Account created! Please sign in.');
        store._isRegistering = false;
        render(container);
      } else {
        await login(email, password);
        showToast('Welcome back!');
        // Redirect to dashboard
        window.location.href = window.location.pathname; // Reload to refresh all state
      }
    } catch (err) {
      showToast(err.message, 'error');
      btn.disabled = false;
      btn.textContent = isRegistering ? 'Register' : 'Sign in';
    }
  });
}
