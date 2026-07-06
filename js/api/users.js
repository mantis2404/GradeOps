/**
 * api/users.js — User management operations.
 */

import { getAuthHeaders } from './auth.js';

// If running on Vercel or production, use relative paths. For dev (port 3000), use localhost:8000
const API_BASE = (window.location.port === '3000' || window.location.hostname === 'localhost') 
  ? 'http://localhost:8000' 
  : '';

function mapUserUIProperties(u) {
  return {
    ...u,
    avatar: (u.name || '??').substring(0, 2).toUpperCase(),
    color: u.role === 'instructor' ? '#E1F5EE' : '#E6F1FB',
    tc: u.role === 'instructor' ? '#0F6E56' : '#185FA5'
  };
}

export async function getUsers() {
  const res = await fetch(`${API_BASE}/auth/users`, {
    headers: getAuthHeaders()
  });

  if (!res.ok) {
    if (res.status === 401) {
      const { logout } = await import('./auth.js');
      logout();
      window.location.reload(); // Force redirect to login
    }
    let msg = 'Failed to fetch users';
    try {
      const err = await res.json();
      msg = err.detail || msg;
    } catch (e) {}
    throw new Error(msg);
  }
  
  const users = await res.json();
  return users.map(mapUserUIProperties);
}

export async function getCourseMembers(courseId) {
  const res = await fetch(`${API_BASE}/metadata/courses/id/${courseId}/members`, {
    headers: getAuthHeaders()
  });

  if (!res.ok) {
    let msg = 'Failed to fetch course members';
    try {
      const err = await res.json();
      msg = err.detail || msg;
    } catch (e) {}
    throw new Error(msg);
  }
  
  const members = await res.json();
  return members.map(mapUserUIProperties);
}

export async function addCourseMember(courseId, { userId, role }) {
  const res = await fetch(`${API_BASE}/metadata/courses/id/${courseId}/members`, {
    method: 'POST',
    headers: {
      ...getAuthHeaders(),
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ user_id: userId, role })
  });

  if (!res.ok) {
    let msg = 'Failed to add member to course';
    try {
      const err = await res.json();
      msg = err.detail || msg;
    } catch (e) {}
    throw new Error(msg);
  }

  return res.json();
}

export async function toggleCourseMemberRole(courseId, userId) {
  const res = await fetch(`${API_BASE}/metadata/courses/id/${courseId}/members/${userId}/toggle-role`, {
    method: 'POST',
    headers: getAuthHeaders()
  });

  if (!res.ok) {
    let msg = 'Failed to update member role';
    try {
      const err = await res.json();
      msg = err.detail || msg;
    } catch (e) {}
    throw new Error(msg);
  }

  return res.json();
}

export async function removeCourseMember(courseId, userId) {
  const res = await fetch(`${API_BASE}/metadata/courses/id/${courseId}/members/${userId}`, {
    method: 'DELETE',
    headers: getAuthHeaders()
  });

  if (!res.ok) {
    let msg = 'Failed to remove member from course';
    try {
      const err = await res.json();
      msg = err.detail || msg;
    } catch (e) {}
    throw new Error(msg);
  }

  return res.json();
}
