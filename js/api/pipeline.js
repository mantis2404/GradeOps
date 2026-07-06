/**
 * api/pipeline.js — All communication with the FastAPI grading pipeline.
 *
 * Base URL is http://localhost:8000 — the FastAPI server.
 * The frontend (served on port 3000) calls these functions; CORS is
 * pre-configured on the backend to allow this.
 */

import { getAuthHeaders } from './auth.js';

// If running on Vercel or production, use relative paths. For dev (port 3000), use localhost:8000
const API_BASE = (window.location.port === '3000' || window.location.hostname === 'localhost') 
  ? 'http://localhost:8000' 
  : '';

/**
 * Start the grading pipeline for an exam.
 *
 * @param {File}   pdfFile     - The uploaded PDF file object
 * @param {File}   rubricFile  - Optional uploaded rubric JSON file object
 * @param {string} examId      - Optional custom exam ID
 * @param {string} rubricId    - Optional ID of a saved rubric on the backend
 * @param {string} courseId    - Optional ID of a saved course on the backend
 * @param {string} name        - Optional custom exam name
 * @returns {{ exam_id: string, status: string }}
 */
export async function startPipeline(pdfFile, rubricFile = null, examId = null, rubricId = null, courseId = null, name = null) {
  const form = new FormData();
  form.append('pdf',    pdfFile);
  if (rubricFile) form.append('rubric', rubricFile);
  if (rubricId)   form.append('rubric_id', rubricId);
  if (courseId)   form.append('course_id', courseId);
  if (examId) form.append('exam_id', examId);
  if (name)   form.append('name', name);

  const res = await fetch(`${API_BASE}/pipeline/start`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: form,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? 'Failed to start pipeline');
  }

  return res.json(); // { exam_id, status }
}

/**
 * Poll the pipeline state for an exam.
 * Call this every 2–3 seconds while status === "processing".
 *
 * @param {string} examId
 * @returns {{
 *   exam_id:     string,
 *   status:      string,      // "processing" | "awaiting_review" | "complete" | "error"
 *   students:    object[],
 *   stats:       object,
 *   next_review: object|null, // the interrupt payload for the current student
 *   is_complete: boolean,
 *   error:       string|null
 * }}
 */
export async function getPipelineState(examId) {
  const res = await fetch(`${API_BASE}/pipeline/${examId}`, {
    headers: getAuthHeaders()
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? 'Failed to fetch pipeline state');
  }
  return res.json();
}

/**
 * Submit a TA decision (approve / override / escalate) for the current student.
 * This resumes the paused LangGraph pipeline.
 *
 * @param {string} examId
 * @param {'approve'|'override'|'escalate'} action
 * @param {number|null} score    - Required when action === 'override'
 * @param {string}      comment  - Optional override comment
 * @returns {{ exam_id, is_complete, next_review, stats }}
 */
export async function submitDecision(examId, action, score = null, comment = '') {
  const res = await fetch(`${API_BASE}/review/${examId}/decide`, {
    method:  'POST',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ action, score, comment }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? 'Failed to submit decision');
  }

  return res.json();
}
