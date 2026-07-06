/**
 * pages/users.js — Manage course members and permissions.
 */

import { getUsers, getCourseMembers, addCourseMember, toggleCourseMemberRole, removeCourseMember } from '../api/users.js';
import { showToast } from '../components/toast.js';
import { store } from '../state.js';

export async function render(container) {
  const courseId = store.selectedCourseId;

  if (!courseId) {
    container.innerHTML = `
      <div class="page-header">
        <div class="page-header-left">
          <h1 class="page-title">Team</h1>
          <p class="page-sub">Manage course members and permissions</p>
        </div>
      </div>
      <div class="card" style="text-align: center; padding: 40px;">
        <i class="ti ti-book-off" style="font-size: 48px; color: var(--neutral-400); margin-bottom: 16px; display: block;"></i>
        <h3>No Course Selected</h3>
        <p style="color: var(--neutral-600); margin-bottom: 20px;">Please select or create a course in the Course Manager to view and manage its team members.</p>
      </div>`;
    return;
  }

  let members = [];
  let globalUsers = [];
  try {
    members = await getCourseMembers(courseId);
    globalUsers = await getUsers();
  } catch (err) {
    showToast(err.message || 'Failed to load data', 'error');
  }

  const instructors = members.filter(u => u.role === 'instructor');
  const tas         = members.filter(u => u.role === 'ta');

  // Find users who are registered globally but not in the active course
  const assignableUsers = globalUsers.filter(gu => !members.some(cm => cm.id === gu.id));

  container.innerHTML = `
    <div class="page-header">
      <div class="page-header-left">
        <h1 class="page-title">Team</h1>
        <p class="page-sub">${instructors.length} instructor${instructors.length !== 1 ? 's' : ''} · ${tas.length} TA${tas.length !== 1 ? 's' : ''}</p>
      </div>
    </div>

    <div class="grid2">
      <!-- Members table -->
      <div class="card" style="padding:0;overflow:hidden">
        <div style="padding:16px 18px 14px">
          <div class="card-title" style="margin:0">Members</div>
        </div>
        <table>
          <thead><tr><th>Name</th><th>Role</th><th></th></tr></thead>
          <tbody>
            ${members.length > 0 
              ? members.map(u => userRow(u)).join('')
              : `<tr><td colspan="3" style="text-align:center; padding: 24px; color: var(--neutral-400);">No members in this course yet.</td></tr>`
            }
          </tbody>
        </table>
      </div>

      <!-- Add member form -->
      <div class="card">
        <div class="card-title">Add member to course</div>
        ${assignableUsers.length > 0 ? `
          <div class="form-group">
            <label class="form-label" for="add-member-user">Select registered user</label>
            <select id="add-member-user" style="width:100%; padding:8px; border-radius:var(--radius-sm); border:1px solid var(--neutral-200);">
              ${assignableUsers.map(u => `<option value="${u.id}">${u.name} (${u.email})</option>`).join('')}
            </select>
          </div>
          <div class="form-group">
            <label class="form-label" for="add-member-role">Role</label>
            <select id="add-member-role" style="width:100%; padding:8px; border-radius:var(--radius-sm); border:1px solid var(--neutral-200);">
              <option value="ta">Teaching Assistant (TA)</option>
              <option value="instructor">Instructor</option>
            </select>
          </div>
          <button class="btn btn-primary" style="width:100%" id="add-member-btn">
            <i class="ti ti-plus" aria-hidden="true"></i> Add to Course
          </button>
        ` : `
          <p style="color:var(--neutral-600); font-size:var(--text-sm); line-height: 1.5;">
            No other registered users are available to add. All registered users are already members of this course.
          </p>
          <p style="color:var(--neutral-400); font-size:var(--text-xs); margin-top: 10px;">
            To add new TAs or Instructors, they must first sign up / register an account on the platform.
          </p>
        `}
      </div>
    </div>`;

  bindEvents(container, courseId);
}

function bindEvents(container, courseId) {
  container.querySelectorAll('[data-toggle-role]').forEach(btn => {
    btn.addEventListener('click', async () => {
      try {
        await toggleCourseMemberRole(courseId, btn.dataset.toggleRole);
        showToast('Role updated');
        render(container);
      } catch (err) {
        showToast(err.message || 'Failed to update role', 'error');
      }
    });
  });

  container.querySelectorAll('[data-remove-user]').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!confirm('Remove this member from the course?')) return;
      try {
        await removeCourseMember(courseId, btn.dataset.removeUser);
        showToast('Member removed');
        render(container);
      } catch (err) {
        showToast(err.message || 'Failed to remove member', 'error');
      }
    });
  });

  const addBtn = container.querySelector('#add-member-btn');
  if (addBtn) {
    addBtn.addEventListener('click', async () => {
      const userId = container.querySelector('#add-member-user').value;
      const role   = container.querySelector('#add-member-role').value;
      
      addBtn.disabled = true;
      try {
        await addCourseMember(courseId, { userId, role });
        showToast('Member added successfully');
        render(container);
      } catch (err) {
        showToast(err.message || 'Failed to add member', 'error');
        addBtn.disabled = false;
      }
    });
  }
}

function userRow(u) {
  const isInstructor = u.role === 'instructor';
  return `
    <tr>
      <td>
        <div style="display:flex;align-items:center;gap:10px">
          <div class="avatar" style="background:${u.color};color:${u.tc}">${u.avatar}</div>
          <div>
            <div style="font-weight:500">${u.name}</div>
            <div style="font-size:var(--text-xs);color:var(--neutral-400)">${u.email}</div>
          </div>
        </div>
      </td>
      <td>
        <span class="badge ${isInstructor ? 'badge-green' : 'badge-blue'}">
          ${isInstructor ? 'Instructor' : 'TA'}
        </span>
      </td>
      <td>
        <div style="display:flex;gap:6px;justify-content:flex-end">
          <button class="btn btn-sm" data-toggle-role="${u.id}" title="Toggle role">
            <i class="ti ti-switch-horizontal" aria-hidden="true"></i>
          </button>
          <button class="btn btn-sm btn-icon btn-danger" data-remove-user="${u.id}" title="Remove">
            <i class="ti ti-trash" aria-hidden="true"></i>
          </button>
        </div>
      </td>
    </tr>`;
}
