/**
 * state.js — Central in-memory data store.
 *
 * This is the ONLY place where raw data lives.
 * Pages interact with data exclusively through js/api/* functions.
 * When you connect a real backend, replace the api/* internals — this file stays.
 */

export const store = {
  role: localStorage.getItem('role') || 'instructor',
  page: 'dashboard',
  token: localStorage.getItem('token') || null,
  user: JSON.parse(localStorage.getItem('user')) || null,

  // Tracks the exam currently being graded by the live pipeline.
  // Set by upload.js after POST /pipeline/start, read by ta-review.js.
  activeExamId: null,

  // The currently active course context
  selectedCourseId: localStorage.getItem('selectedCourseId') || null,

  users: [],
  exams: [],
  rubrics: [],
  pendingReviews: [],
};

/** Simulates network latency. Replace with real fetch() in api/* files when deploying. */
export const delay = (ms = 80) => new Promise(resolve => setTimeout(resolve, ms));
