import axios from 'axios';

// In production, VITE_API_URL should be set to the Render backend URL (e.g. https://your-backend.onrender.com/api)
// In development, Vite proxy handles /api → localhost:8000
const API_BASE = import.meta.env.VITE_API_URL || '/api';

// WebSocket base URL: in production, point to the backend service directly
// VITE_WS_URL should be like wss://ai-interview-backend.onrender.com
export const WS_BASE = import.meta.env.VITE_WS_URL || '';

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
});

// Attach JWT token to every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Auto-logout on 401
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      window.location.href = '/login';
    }
    return Promise.reject(err);
  }
);

// ── Auth ─────────────────────────────────────────────
export const authAPI = {
  register: (data) => api.post('/auth/register', data),
  login: (data) => api.post('/auth/login', data),
  getMe: () => api.get('/auth/me'),
  updateProfile: (data) => api.put('/auth/profile', data),
  deleteAccount: () => api.delete('/auth/account'),
};

// ── Mock Interview ───────────────────────────────────
export const mockAPI = {
  start: (data) => api.post('/mock-interview/start', data),
  submitAnswer: (sessionId, data) => api.post(`/mock-interview/${sessionId}/answer`, data),
  getReport: (sessionId) => api.get(`/mock-interview/${sessionId}/report`),
  getReportPDF: (sessionId) =>
    api.get(`/mock-interview/${sessionId}/report/pdf`, { responseType: 'blob' }),
  history: () => api.get('/mock-interview/history/me'),
  checkTime: (sessionId) => api.get(`/mock-interview/${sessionId}/time`),
  endInterview: (sessionId) => api.post(`/mock-interview/${sessionId}/end`),
  // Practice mode live metrics
  getPracticeMetrics: (sessionId, answerText, videoFrame) => api.post(`/mock-interview/${sessionId}/practice/metrics`, { partial_text: answerText || '', video_frame: videoFrame || null }),
  getPracticeSummary: (sessionId) => api.get(`/mock-interview/${sessionId}/practice/summary`),
  // Proctoring
  logViolation: (sessionId, data) => api.post(`/mock-interview/${sessionId}/proctoring/violation`, data),
  getProctoringSummary: (sessionId) => api.get(`/mock-interview/${sessionId}/proctoring/summary`),
  registerFace: (sessionId, videoFrame) => api.post(`/mock-interview/${sessionId}/proctoring/register-face`, { video_frame: videoFrame }),
  getIntegrityReport: (sessionId) => api.get(`/mock-interview/${sessionId}/proctoring/integrity-report`),
};

// ── Practice Mode ────────────────────────────────────
export const practiceAPI = {
  getTopics: () => api.get('/practice/topics'),
  startSession: (data) => api.post('/practice/start', data),
  getQuestion: (sessionId) => api.get(`/practice/${sessionId}/question`),
  updateMetrics: (sessionId) => api.post(`/practice/${sessionId}/metrics`),
  submitAnswer: (sessionId, data) => api.post(`/practice/${sessionId}/answer`, data),
  endSession: (sessionId) => api.post(`/practice/${sessionId}/end`),
  getStatus: (sessionId) => api.get(`/practice/${sessionId}/status`),
  history: () => api.get('/practice/history/me'),
};

// ── Analytics (Explainability / Fairness / Roadmap) ──
export const analyticsAPI = {
  explain: (data) => api.post('/analytics/explain', data),
  auditFairness: (data) => api.post('/analytics/fairness/audit', data),
  getFairnessReport: (params) => api.get('/analytics/fairness/report', { params }),
  getFairnessDrift: (params) => api.get('/analytics/fairness/drift', { params }),
  generateRoadmap: (data) => api.post('/analytics/roadmap', data),
  updateProgress: (data) => api.post('/analytics/roadmap/progress', data),
};

// ── Data Collection (GitHub / LinkedIn / Resume) ─────
export const dataCollectionAPI = {
  analyzeGithub: (url) => api.post('/data-collection/analyze-github', null, { params: { github_url: url } }),
  analyzeLinkedin: (url) => api.post('/data-collection/analyze-linkedin', null, { params: { linkedin_url: url } }),
  uploadResume: (file) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/data-collection/upload-resume', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  getProfile: () => api.get('/data-collection/profile'),
  buildFullProfile: (data) => api.post('/data-collection/build-full-profile', null, { params: data }),
};

// ── HR Interview Sessions ────────────────────────────
export const interviewAPI = {
  createSession: (data) => api.post('/interviews/sessions', data),
  listSessions: () => api.get('/interviews/sessions'),
  getSession: (id) => api.get(`/interviews/sessions/${id}`),
  deleteSession: (id) => api.delete(`/interviews/sessions/${id}`),
  endSession: (id) => api.post(`/interviews/sessions/${id}/end`),
  inviteCandidates: (sessionId, emails) =>
    api.post(`/interviews/sessions/${sessionId}/invite`, { emails }),
  listCandidates: (sessionId) =>
    api.get(`/interviews/sessions/${sessionId}/candidates`),
};

// ── Candidate AI Interview (token-based, no auth) ────
export const candidateAPI = {
  getInfo: (token) => api.get(`/candidate-interview/${token}/info`),
  start: (token, data) => api.post(`/candidate-interview/${token}/start`, data),
  submitAnswer: (token, data) => api.post(`/candidate-interview/${token}/answer`, data),
  getReport: (token) => api.get(`/candidate-interview/${token}/report`),
  getReportPDF: (token) => api.get(`/candidate-interview/${token}/report/pdf`, { responseType: 'blob' }),
  getSessionProgress: (sessionId) => api.get(`/candidate-interview/session/${sessionId}/progress`),
  getDuplicateQuestions: (sessionId) => api.get(`/candidate-interview/session/${sessionId}/duplicate-questions`),
  getPublicUrl: () => api.get('/candidate-interview/public-url'),
  checkTime: (token) => api.get(`/candidate-interview/${token}/time`),
  endInterview: (token) => api.post(`/candidate-interview/${token}/end`),
  // Proctoring
  logViolation: (token, data) => api.post(`/candidate-interview/${token}/proctoring/violation`, data),
  getProctoringSummary: (token) => api.get(`/candidate-interview/${token}/proctoring/summary`),
  analyzeFrame: (token, videoFrame) => api.post(`/candidate-interview/${token}/proctoring/analyze`, { video_frame: videoFrame || null }),
  registerFace: (token, videoFrame) => api.post(`/candidate-interview/${token}/proctoring/register-face`, { video_frame: videoFrame }),
  getIntegrityReport: (token) => api.get(`/candidate-interview/${token}/proctoring/integrity-report`),
};

export default api;
