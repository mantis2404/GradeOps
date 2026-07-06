/**
 * pages/exams.js — Manage all uploaded exam batches.
 *
 * The download button fetches GET /pipeline/{exam_id}/export/csv from the
 * FastAPI backend and triggers a browser download. If the gradebook is not
 * ready yet (exam still processing) a toast is shown instead.
 */

import { getExams, deleteExam } from '../api/exams.js';
import { navigate } from '../router.js';
import { showToast } from '../components/toast.js';
import { store } from '../state.js';
import { getCourses } from '../api/courses.js';
import { getAuthHeaders } from '../api/auth.js';

// Use the current origin as the API base if we're not on the default dev port (3000)
const API_BASE = window.location.port === '3000' ? 'http://localhost:8000' : '';

const STATUS_BADGE = { 
  graded: 'badge-green', 
  complete: 'badge-green', 
  processing: 'badge-amber', 
  awaiting_review: 'badge-amber',
  pending: 'badge-gray' 
};
const STATUS_LABEL = { 
  graded: 'Graded', 
  complete: 'Graded',
  processing: 'In progress', 
  awaiting_review: 'In review',
  pending: 'Pending' 
};

export async function render(container) {
  const [exams, courses] = await Promise.all([getExams(), getCourses()]);
  
  const activeCourse = courses.find(c => c.id === store.selectedCourseId);
  const filteredExams = store.selectedCourseId 
    ? exams.filter(e => e.courseId === store.selectedCourseId || e.course_id === store.selectedCourseId)
    : exams;

  container.innerHTML = `
    <div class="page-header">
      <div class="page-header-left">
        <h1 class="page-title">Exams</h1>
        <p class="page-sub">
          ${activeCourse ? `Viewing exams for <strong>${activeCourse.code}</strong>` : `${exams.length} batch${exams.length !== 1 ? 'es' : ''} uploaded`}
        </p>
      </div>
      <div style="display:flex; gap:8px">
        ${store.selectedCourseId ? `<button class="btn" id="btn-show-all">Show all</button>` : ''}
        <button class="btn btn-primary" id="btn-upload-new">
          <i class="ti ti-upload" aria-hidden="true"></i> Upload exam
        </button>
      </div>
    </div>

    <div class="card" style="padding:0;overflow:hidden">
      <table>
        <thead>
          <tr>
            <th>Exam</th>
            <th>Students</th>
            <th style="min-width:120px">TA progress</th>
            <th>Rubric</th>
            <th>Status</th>
            <th>Uploaded</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          ${filteredExams.length
            ? filteredExams.map(e => examRow(e)).join('')
            : `<tr><td colspan="7"><div class="empty"><i class="ti ti-files" aria-hidden="true"></i><p>No exams for this course</p><small>Upload your first exam to get started.</small></div></td></tr>`}
        </tbody>
      </table>
    </div>`;

  container.querySelector('#btn-upload-new').addEventListener('click', () => navigate('upload'));
  container.querySelector('#btn-show-all')?.addEventListener('click', () => {
    store.selectedCourseId = null;
    render(container);
  });

  // ── Delete buttons ──────────────────────────────────────────────────────────
  container.querySelectorAll('[data-delete-exam]').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!confirm('Remove this exam? This cannot be undone.')) return;
      await deleteExam(btn.dataset.deleteExam);
      showToast('Exam removed');
      render(container);
    });
  });

  // ── Download / export buttons ───────────────────────────────────────────────
  container.querySelectorAll('[data-download-exam]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const examId = btn.dataset.downloadExam;
      const examStatus = btn.dataset.examStatus;

      if (examStatus !== 'graded' && examStatus !== 'complete') {
        showToast('Gradebook not ready — complete all TA reviews first', 'error');
        return;
      }

      try {
        btn.disabled = true;
        btn.innerHTML = '<i class="ti ti-loader-2 ti-spin" aria-hidden="true"></i>';

        const res = await fetch(`${API_BASE}/pipeline/${examId}/export/csv`, {
          headers: getAuthHeaders()
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(err.detail ?? 'Export failed');
        }

        // Trigger browser download
        const blob = await res.blob();
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href     = url;
        a.download = `gradebook_${examId}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        showToast('CSV downloaded ✓');
      } catch (err) {
        showToast(err.message ?? 'Download failed', 'error');
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="ti ti-download" aria-hidden="true"></i>';
      }
    });
  });
}

function examRow(e) {
  const pct    = e.students ? Math.round(e.reviewed / e.students * 100) : 0;
  const rubric = e.rubric
    ? `<span class="badge badge-blue" style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${e.rubric}</span>`
    : `<span style="font-size:var(--text-xs);color:var(--neutral-400)">—</span>`;

  const isGraded = e.status === 'graded' || e.status === 'complete';
  const downloadTitle = isGraded ? 'Download grades CSV' : 'Complete reviews first';
  const downloadStyle = !isGraded ? 'opacity:0.4;cursor:not-allowed' : '';

  return `
    <tr>
      <td>
        <div style="font-weight:500;color:var(--neutral-900)">${e.name}</div>
        <div style="font-size:var(--text-xs);color:var(--neutral-400);margin-top:1px">${e.course}</div>
      </td>
      <td>${e.students}</td>
      <td>
        <div style="font-size:var(--text-xs);color:var(--neutral-600);margin-bottom:5px">${e.reviewed} / ${e.students}</div>
        <div class="progress" style="width:90px"><div class="progress-bar" style="width:${pct}%"></div></div>
      </td>
      <td>${rubric}</td>
      <td><span class="badge ${STATUS_BADGE[e.status] ?? 'badge-gray'}">${STATUS_LABEL[e.status] ?? e.status}</span></td>
      <td style="color:var(--neutral-400);font-size:var(--text-xs)">${e.uploaded}</td>
      <td>
        <div style="display:flex;gap:6px">
          <button class="btn btn-sm btn-icon"
                  data-download-exam="${e.id}"
                  data-exam-status="${e.status}"
                  title="${downloadTitle}"
                  style="${downloadStyle}">
            <i class="ti ti-download" aria-hidden="true"></i>
          </button>
          <button class="btn btn-sm btn-icon btn-danger" data-delete-exam="${e.id}" title="Remove exam">
            <i class="ti ti-trash" aria-hidden="true"></i>
          </button>
        </div>
      </td>
    </tr>`;
}
