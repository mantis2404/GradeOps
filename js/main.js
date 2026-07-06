/**
 * main.js — Application entry point.
 *
 * Responsibilities:
 *  - Boot the app on DOMContentLoaded
 *  - Handle role switching (updates store + re-renders header + re-navigates)
 *  - Read initial page from URL query param
 */

import { store } from './state.js';
import { navigate } from './router.js';
import { getCourses } from './api/courses.js';
import { isAuthenticated, logout, verifySession } from './api/auth.js';
import { showToast } from './components/toast.js';

async function boot() {
  // 1. Verify if current session is actually valid
  if (isAuthenticated()) {
    const isValid = await verifySession();
    if (!isValid) {
      console.warn('[auth] Session invalid or expired. Logging out.');
      logout();
      window.location.reload();
      return;
    }
  }

  // 2. Read initial page from URL (supports deep-linking)
  const params  = new URL(window.location).searchParams;
  let initPage = params.get('page') ?? 'dashboard';

  if (!isAuthenticated()) {
    initPage = 'login';
  } else {
    // Determine active course and role for authenticated user
    try {
      const courses = await getCourses();
      if (courses.length > 0) {
        if (!store.selectedCourseId || !courses.some(c => c.id === store.selectedCourseId)) {
          store.selectedCourseId = courses[0].id;
          localStorage.setItem('selectedCourseId', courses[0].id);
        }
        const activeCourse = courses.find(c => c.id === store.selectedCourseId);
        
        let courseRole = 'ta';
        if (store.user?.role === 'admin') {
          // Central admin is allowed both roles; check localStorage first
          const savedRole = localStorage.getItem('role');
          courseRole = (savedRole === 'ta' || savedRole === 'instructor') ? savedRole : 'instructor';
        } else {
          // Standard users: course membership role
          const member = activeCourse?.members?.find(m => m.user_id === store.user?.id);
          if (member) courseRole = member.role;
        }
        
        // Update store and localStorage
        store.role = courseRole;
        localStorage.setItem('role', courseRole);
        
        // Adjust initial page if it violates new course role permissions
        const defaultPage = courseRole === 'instructor' ? 'dashboard' : 'ta-dashboard';
        const isInstructorPage = ['dashboard', 'upload', 'exams', 'rubrics', 'courses', 'users', 'reports'].includes(initPage);
        const isTAPage = ['ta-dashboard', 'ta-review', 'ta-approved', 'ta-exams'].includes(initPage);
        
        if (courseRole === 'ta' && isInstructorPage) {
          initPage = defaultPage;
        } else if (courseRole === 'instructor' && isTAPage) {
          // If a central admin switched to ta mode, let them stay, otherwise lock non-admins
          if (store.user?.role !== 'admin' && store.role !== 'ta') {
            initPage = defaultPage;
          }
        }
      } else {
        // No courses available
        store.selectedCourseId = null;
        localStorage.removeItem('selectedCourseId');
        if (store.user?.role === 'instructor' || store.user?.role === 'admin') {
          initPage = 'courses'; // redirect to course manager to add one
        } else {
          initPage = 'ta-dashboard'; // TA will see empty queue
        }
      }
    } catch (err) {
      console.error('Error resolving course role on boot:', err);
    }
  }

  await navigate(initPage);
  await updateDynamicHeader();
  bindGlobalEvents();
}

async function updateDynamicHeader() {
  const headerRight = document.querySelector('.header-right');
  const courseLabel = document.getElementById('course-label');
  
  if (!isAuthenticated()) {
    if (headerRight) headerRight.style.display = 'none';
    if (courseLabel) courseLabel.textContent = 'GradeOps';
    return;
  }

  if (headerRight) headerRight.style.display = 'flex';

  const user = store.user;
  const avatarEl = document.getElementById('user-avatar');
  if (avatarEl && user) {
    avatarEl.textContent        = user.name.substring(0, 2).toUpperCase();
    avatarEl.style.background   = '#E1F5EE';
    avatarEl.style.color        = '#0F6E56';
    avatarEl.title = `Logged in as ${user.name} (${store.role.toUpperCase()})`;
  }

  let courseRole = 'ta';
  if (courseLabel) {
    try {
      const courses = await getCourses();
      const activeCourse = courses.find(c => c.id === store.selectedCourseId) || courses[0];
      if (activeCourse) {
        if (!store.selectedCourseId) {
          store.selectedCourseId = activeCourse.id;
          localStorage.setItem('selectedCourseId', activeCourse.id);
        }
        
        if (store.user?.role === 'admin') {
          courseRole = 'admin';
        } else {
          const member = activeCourse.members?.find(m => m.user_id === store.user?.id);
          if (member) courseRole = member.role;
        }
        
        if (store.user?.role !== 'admin' && courseRole === 'ta' && store.role !== 'ta') {
          store.role = 'ta';
          localStorage.setItem('role', 'ta');
          navigate('ta-dashboard');
        }
        
        const suffix = store.role === 'ta' ? ' | TA View' : '';
        courseLabel.textContent = `${activeCourse.code} — ${activeCourse.name}${suffix}`;
      } else {
        courseLabel.textContent = 'GradeOps';
      }
    } catch (err) {
      courseLabel.textContent = 'GradeOps';
    }
  }

  // Show/hide role switcher based on course membership role
  const roleSwitch = document.querySelector('.role-switch');
  if (roleSwitch) {
    // ONLY global admin can access role switcher
    if (store.user?.role === 'admin') {
      roleSwitch.style.display = 'flex';
    } else {
      roleSwitch.style.display = 'none';
    }
  }

  // Set active role button
  document.getElementById('btn-instructor')?.classList.toggle('active', store.role === 'instructor');
  document.getElementById('btn-ta')?.classList.toggle('active',         store.role === 'ta');
}

function bindGlobalEvents() {
  document.getElementById('btn-instructor')?.addEventListener('click', () => switchRole('instructor'));
  document.getElementById('btn-ta')?.addEventListener('click',         () => switchRole('ta'));
  
  // Make avatar clickable to logout
  document.getElementById('user-avatar')?.addEventListener('click', () => {
    if (confirm('Do you want to logout?')) {
      logout();
      window.location.reload();
    }
  });
}

async function switchRole(role) {
  if (store.role === role) return; // No change needed

  if (store.user?.role !== 'admin') {
    showToast('Unauthorized: Only central admins can switch between roles', 'error');
    return;
  }

  store.role = role;
  localStorage.setItem('role', role);

  // Instant UI feedback for role buttons
  document.getElementById('btn-instructor')?.classList.toggle('active', role === 'instructor');
  document.getElementById('btn-ta')?.classList.toggle('active',         role === 'ta');

  // Trigger non-blocking header and nav updates
  updateDynamicHeader();

  // Instant navigation to the role's landing page
  const defaultPage = role === 'instructor' ? 'dashboard' : 'ta-dashboard';
  navigate(defaultPage);
}

document.addEventListener('DOMContentLoaded', boot);
