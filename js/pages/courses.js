/**
 * pages/courses.js — Manage courses and set the active course context.
 */

import { getCourses, createCourse, deleteCourse } from '../api/courses.js';
import { showToast } from '../components/toast.js';
import { store } from '../state.js';

export async function render(container) {
  let courses = [];
  try {
    courses = await getCourses();
    // Default to first course if none selected
    if (!store.selectedCourseId && courses.length > 0) {
      store.selectedCourseId = courses[0].id;
    }
  } catch (err) {
    console.warn('Failed to fetch courses:', err);
  }

  container.innerHTML = `
    <div class="page-header">
      <div class="page-header-left">
        <h1 class="page-title">Course Manager</h1>
        <p class="page-sub">Manage your courses and select the active workspace</p>
      </div>
    </div>

    <div class="grid2">
      <!-- Existing courses -->
      <div class="card" style="${courses.length ? 'padding:0;overflow:hidden' : ''}">
        <div style="padding:16px 18px 14px">
          <div class="card-title" style="margin:0">Your courses</div>
        </div>
        ${courses.length
          ? courses.map(c => courseRow(c)).join('')
          : `<div class="empty"><i class="ti ti-book" aria-hidden="true"></i><p>No courses added yet</p><small>Add one using the form →</small></div>`}
      </div>

      <!-- New course form -->
      <div class="card">
        <div class="card-title">Add new course</div>
        <div class="form-group">
          <label class="form-label" for="course-name">Course name</label>
          <input type="text" id="course-name" placeholder="e.g. Algorithms & Complexity">
        </div>
        <div class="form-group">
          <label class="form-label" for="course-code">Course code</label>
          <input type="text" id="course-code" placeholder="e.g. CS 301">
        </div>
        <button class="btn btn-primary" style="width:100%" id="save-course-btn">
          Create course
        </button>
      </div>
    </div>`;

  bindEvents(container);
  // Also update header immediately on render to ensure it's in sync
  await updateHeader();
}

function bindEvents(container) {
  container.querySelector('#save-course-btn').addEventListener('click', async () => {
    const name = container.querySelector('#course-name')?.value?.trim();
    const code = container.querySelector('#course-code')?.value?.trim();
    if (!name || !code) { showToast('Enter both name and code', 'error'); return; }
    
    const btn = container.querySelector('#save-course-btn');
    btn.disabled = true;
    try {
      const course = await createCourse({ name, code });
      if (!store.selectedCourseId) {
        store.selectedCourseId = course.id;
        localStorage.setItem('selectedCourseId', course.id);
      }
      showToast('Course created');
      await updateHeader();
      render(container);
    } catch (err) {
      showToast('Failed to create course', 'error');
      btn.disabled = false;
    }
  });

  container.querySelectorAll('[data-select-course]').forEach(btn => {
    btn.addEventListener('click', async () => {
      store.selectedCourseId = btn.dataset.selectCourse;
      localStorage.setItem('selectedCourseId', btn.dataset.selectCourse);
      showToast('Active course updated');
      window.location.reload();
    });
  });

  container.querySelectorAll('[data-delete-course]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const courseId = btn.dataset.deleteCourse;
      if (!confirm('Are you sure you want to delete this course?')) return;
      
      try {
        await deleteCourse(courseId);
        showToast('Course deleted');
        if (store.selectedCourseId === courseId) {
          store.selectedCourseId = null;
          window.location.reload();
        } else {
          render(container);
        }
      } catch (err) {
        showToast('Failed to delete course', 'error');
      }
    });
  });
}

export async function updateHeader() {
  const courses = await getCourses();
  const activeCourse = courses.find(c => c.id === store.selectedCourseId);
  const label = document.getElementById('course-label');
  if (label) {
    if (activeCourse) {
      label.textContent = `${activeCourse.code} — ${activeCourse.name}${store.role === 'ta' ? ' | TA View' : ''}`;
    } else {
      label.textContent = 'Select a Course';
    }
  }
}

function courseRow(c) {
  const isSelected = store.selectedCourseId === c.id;
  return `
    <div class="row-item" style="${isSelected ? 'background:var(--brand-tint)' : ''}">
      <div class="row-icon blue"><i class="ti ti-book" aria-hidden="true"></i></div>
      <div class="row-info">
        <div class="row-name">${c.code} — ${c.name}</div>
        <div class="row-meta">ID: ${c.id}</div>
      </div>
      <div class="row-actions">
        ${isSelected 
          ? `<span class="badge badge-green">Active</span>`
          : `<button class="btn btn-sm" data-select-course="${c.id}">Select</button>`
        }
        <button class="btn btn-sm btn-outline-danger" data-delete-course="${c.id}" title="Delete course" style="margin-left: 8px; color: var(--danger); border-color: var(--danger);">
          <i class="ti ti-trash" aria-hidden="true"></i>
        </button>
      </div>
    </div>`;
}
