import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { candidateAPI, interviewAPI, WS_BASE } from '../services/api';
import toast from 'react-hot-toast';
import {
  Loader2, Users, Eye, ArrowLeft, RefreshCw, BarChart3,
  CheckCircle, Clock, AlertTriangle, FileText, XCircle, Timer,
  Video, VideoOff, Monitor, X, Shield, UserX, MonitorX, Copy, LogOut,
  ChevronLeft, ChevronRight, LayoutGrid, Maximize2, Minimize2,
} from 'lucide-react';

// Imports and WebRTC definitions removed in favor of Agora Monitor Dashboard

export default function LiveInterview() {
  const { sessionId } = useParams();
  const [session, setSession] = useState(null);
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedCandidate, setSelectedCandidate] = useState(null);
  const [candidateReport, setCandidateReport] = useState(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('candidates'); // 'candidates' | 'duplicates' | 'gallery'
  const [duplicateQuestions, setDuplicateQuestions] = useState(null);
  const [duplicatesLoading, setDuplicatesLoading] = useState(false);
  const [endingSession, setEndingSession] = useState(false);
  const [showEndConfirm, setShowEndConfirm] = useState(false);

  // Removed state and sync effects for legacy LiveInterview streams

  const loadData = async (showRefresh = false) => {
    if (showRefresh) setRefreshing(true);
    try {
      const [sRes, pRes] = await Promise.all([
        interviewAPI.getSession(sessionId),
        candidateAPI.getSessionProgress(sessionId),
      ]);
      setSession(sRes.data);
      setCandidates(pRes.data);
    } catch (err) {
      toast.error('Failed to load session data');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const loadDuplicates = async () => {
    setDuplicatesLoading(true);
    try {
      const res = await candidateAPI.getDuplicateQuestions(sessionId);
      setDuplicateQuestions(res.data);
    } catch (err) {
      toast.error('Failed to load duplicate questions');
    } finally {
      setDuplicatesLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    loadDuplicates();
    const interval = setInterval(() => { loadData(); loadDuplicates(); }, 10000);
    return () => clearInterval(interval);
  }, [sessionId]);

  // Legacy WebSocket and WebRTC stream logic removed


  const viewReport = async (candidateToken) => {
    setReportLoading(true);
    try {
      const res = await candidateAPI.getReport(candidateToken);
      setCandidateReport(res.data);
      setSelectedCandidate(candidateToken);
    } catch (err) {
      toast.error('Report not available yet');
    } finally {
      setReportLoading(false);
    }
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case 'completed':
        return <CheckCircle size={16} className="text-green-500" />;
      case 'in_progress':
        return <Clock size={16} className="text-blue-500 animate-pulse" />;
      case 'failed':
        return <XCircle size={16} className="text-red-500" />;
      default:
        return <AlertTriangle size={16} className="text-yellow-500" />;
    }
  };

  const getStatusBadge = (status) => {
    const styles = {
      completed: 'bg-green-100 text-green-700',
      in_progress: 'bg-blue-100 text-blue-700',
      invited: 'bg-yellow-100 text-yellow-700',
      failed: 'bg-red-100 text-red-700',
    };
    return styles[status] || 'bg-gray-100 text-gray-700';
  };

  const getStatusLabel = (status) => {
    const labels = {
      completed: 'Completed',
      in_progress: 'In Progress',
      invited: 'Invited',
      failed: 'Failed',
    };
    return labels[status] || status;
  };

  const getScoreColor = (score) => {
    if (score >= 70) return 'text-green-600';
    if (score >= 40) return 'text-yellow-600';
    return 'text-red-600';
  };

  const formatTimeRemaining = (timeStatus) => {
    if (!timeStatus) return null;
    const mins = Math.floor(timeStatus.remaining_seconds / 60);
    const secs = timeStatus.remaining_seconds % 60;
    return `${mins}:${String(secs).padStart(2, '0')}`;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <Loader2 className="animate-spin text-primary-500" size={40} />
      </div>
    );
  }

  // ── Report Detail View ─────────────────
  if (selectedCandidate && candidateReport) {
    const rpt = candidateReport;
    const roundSummary = rpt.round_summary;

    return (
      <div className="max-w-5xl mx-auto px-4 py-8">
        <button
          onClick={() => { setSelectedCandidate(null); setCandidateReport(null); }}
          className="flex items-center space-x-2 text-gray-600 hover:text-gray-900 mb-6"
        >
          <ArrowLeft size={18} />
          <span>Back to Monitor</span>
        </button>

        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 mb-6">
          <h1 className="text-2xl font-bold text-gray-900 mb-1">
            {rpt.candidate_name}'s Report
          </h1>
          <p className="text-gray-500">
            {rpt.job_role} • {rpt.candidate_email} • {rpt.total_questions} questions
          </p>
        </div>

        {/* Recommendation */}
        {rpt.recommendation && (
          <div className={`rounded-xl p-5 mb-6 border flex items-start space-x-3 ${rpt.recommendation === 'Selected'
              ? 'bg-green-50 border-green-200'
              : rpt.recommendation.startsWith('Maybe')
                ? 'bg-yellow-50 border-yellow-200'
                : 'bg-red-50 border-red-200'
            }`}>
            {rpt.recommendation === 'Selected' ? (
              <CheckCircle size={22} className="text-green-600 flex-shrink-0 mt-0.5" />
            ) : rpt.recommendation.startsWith('Maybe') ? (
              <AlertTriangle size={22} className="text-yellow-600 flex-shrink-0 mt-0.5" />
            ) : (
              <XCircle size={22} className="text-red-600 flex-shrink-0 mt-0.5" />
            )}
            <div>
              <p className={`font-semibold ${rpt.recommendation === 'Selected' ? 'text-green-800'
                  : rpt.recommendation.startsWith('Maybe') ? 'text-yellow-800' : 'text-red-800'
                }`}>
                Recommendation: {rpt.recommendation}
              </p>
              {rpt.confidence_analysis && (
                <p className="text-sm text-gray-600 mt-1">{rpt.confidence_analysis}</p>
              )}
            </div>
          </div>
        )}

        {/* Round Summary */}
        {roundSummary && (
          <div className="grid grid-cols-3 gap-4 mb-6">
            <div className="bg-white rounded-xl border border-gray-100 p-4 text-center">
              <div className={`text-2xl font-bold ${getScoreColor(roundSummary.technical?.score || 0)}`}>
                {Math.round(roundSummary.technical?.score || 0)}%
              </div>
              <div className="text-xs text-gray-500 mt-1">Technical ({roundSummary.technical?.questions_asked || 0}Q)</div>
              {roundSummary.technical?.passed ? (
                <span className="text-xs text-green-600 font-medium">✓ Passed</span>
              ) : (
                <span className="text-xs text-red-600 font-medium">✗ Below cutoff</span>
              )}
            </div>
            <div className="bg-white rounded-xl border border-gray-100 p-4 text-center">
              <div className={`text-2xl font-bold ${roundSummary.hr?.questions_asked > 0 ? getScoreColor(roundSummary.hr?.score || 0) : 'text-gray-300'
                }`}>
                {roundSummary.hr?.questions_asked > 0 ? `${Math.round(roundSummary.hr?.score || 0)}%` : '—'}
              </div>
              <div className="text-xs text-gray-500 mt-1">
                HR ({roundSummary.hr?.questions_asked || 0}Q)
              </div>
              {roundSummary.hr?.questions_asked > 0 ? (
                roundSummary.hr?.passed ? (
                  <span className="text-xs text-green-600 font-medium">✓ Passed</span>
                ) : (
                  <span className="text-xs text-red-600 font-medium">✗ Below cutoff</span>
                )
              ) : (
                <span className="text-xs text-gray-400">Not reached</span>
              )}
            </div>
            <div className="bg-white rounded-xl border border-gray-100 p-4 text-center">
              <div className={`text-2xl font-bold ${getScoreColor(rpt.overall_score || 0)}`}>
                {Math.round(rpt.overall_score || 0)}%
              </div>
              <div className="text-xs text-gray-500 mt-1">Overall</div>
            </div>
          </div>
        )}

        {/* Detailed Scores */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
          {[
            { label: 'Content', value: rpt.overall_scores?.content_score },
            { label: 'Keywords', value: rpt.overall_scores?.keyword_score },
            { label: 'Depth', value: rpt.overall_scores?.depth_score },
            { label: 'Communication', value: rpt.overall_scores?.communication_score },
            { label: 'Confidence', value: rpt.overall_scores?.confidence_score },
          ].map((s) => (
            <div key={s.label} className="bg-white rounded-xl border border-gray-100 p-4 text-center">
              <div className={`text-2xl font-bold ${getScoreColor(s.value || 0)}`}>
                {Math.round(s.value || 0)}%
              </div>
              <div className="text-xs text-gray-500 mt-1">{s.label}</div>
            </div>
          ))}
        </div>

        {/* Communication & Confidence Feedback */}
        {(rpt.communication_feedback || rpt.confidence_analysis) && (
          <div className="grid md:grid-cols-2 gap-6 mb-6">
            {rpt.communication_feedback && (
              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <h3 className="font-semibold text-blue-700 mb-3">🗣️ Communication</h3>
                <p className="text-sm text-gray-700">{rpt.communication_feedback}</p>
              </div>
            )}
            {rpt.confidence_analysis && (
              <div className="bg-white rounded-xl border border-gray-100 p-6">
                <h3 className="font-semibold text-purple-700 mb-3">🎯 Confidence</h3>
                <p className="text-sm text-gray-700">{rpt.confidence_analysis}</p>
              </div>
            )}
          </div>
        )}

        {/* Strengths & Weaknesses */}
        <div className="grid md:grid-cols-2 gap-6 mb-6">
          <div className="bg-white rounded-xl border border-gray-100 p-6">
            <h3 className="font-semibold text-green-700 mb-3">✅ Strengths</h3>
            <ul className="space-y-2">
              {rpt.strengths?.map((s, i) => (
                <li key={i} className="text-sm text-gray-700 flex items-start space-x-2">
                  <span className="text-green-500 mt-0.5">•</span>
                  <span>{s}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="bg-white rounded-xl border border-gray-100 p-6">
            <h3 className="font-semibold text-red-700 mb-3">⚠️ Areas for Improvement</h3>
            <ul className="space-y-2">
              {rpt.weaknesses?.map((w, i) => (
                <li key={i} className="text-sm text-gray-700 flex items-start space-x-2">
                  <span className="text-red-500 mt-0.5">•</span>
                  <span>{w}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* Question Breakdown */}
        <div className="bg-white rounded-xl border border-gray-100 p-6">
          <h3 className="font-semibold text-gray-900 mb-4">Question-by-Question Breakdown</h3>
          <div className="space-y-4">
            {rpt.question_evaluations?.map((qe, i) => (
              <div key={i} className="border border-gray-100 rounded-lg p-4">
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center space-x-2">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${qe.round === 'HR' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'
                      }`}>
                      {qe.round || 'Technical'}
                    </span>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${qe.difficulty === 'hard' ? 'bg-red-100 text-red-700'
                        : qe.difficulty === 'easy' ? 'bg-green-100 text-green-700'
                          : 'bg-yellow-100 text-yellow-700'
                      }`}>
                      {qe.difficulty || 'medium'}
                    </span>
                    <p className="text-sm font-medium text-gray-900">Q{i + 1}: {qe.question}</p>
                  </div>
                  <div className="flex items-center space-x-2 flex-shrink-0">
                    {qe.answer_strength && (
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${qe.answer_strength === 'strong' ? 'bg-green-100 text-green-700'
                          : qe.answer_strength === 'moderate' ? 'bg-yellow-100 text-yellow-700'
                            : 'bg-red-100 text-red-700'
                        }`}>
                        {qe.answer_strength}
                      </span>
                    )}
                    <span className={`text-sm font-bold ${getScoreColor(qe.scores?.overall_score || 0)}`}>
                      {Math.round(qe.scores?.overall_score || 0)}%
                    </span>
                  </div>
                </div>
                <p className="text-sm text-gray-600 mb-2"><strong>Answer:</strong> {qe.answer}</p>
                {qe.feedback && (
                  <p className="text-xs text-gray-500 bg-gray-50 rounded p-2">{qe.feedback}</p>
                )}
                {/* Per-question scores */}
                <div className="grid grid-cols-5 gap-2 mt-2">
                  {[
                    { label: 'Content', value: qe.scores?.content_score },
                    { label: 'Keywords', value: qe.scores?.keyword_score },
                    { label: 'Depth', value: qe.scores?.depth_score },
                    { label: 'Comm.', value: qe.scores?.communication_score },
                    { label: 'Confidence', value: qe.scores?.confidence_score },
                  ].map((s) => (
                    <div key={s.label} className="bg-gray-50 rounded p-1.5 text-center">
                      <div className={`text-xs font-bold ${getScoreColor(s.value || 0)}`}>{Math.round(s.value || 0)}%</div>
                      <div className="text-[9px] text-gray-400">{s.label}</div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // ── Main Monitor View ──────────────────
  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center space-x-4">
          <Link
            to={`/hr/session/${sessionId}`}
            className="p-2 hover:bg-gray-100 rounded-lg transition"
          >
            <ArrowLeft size={20} className="text-gray-600" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900 flex items-center space-x-2">
              <Eye size={24} className="text-primary-500" />
              <span>Interview Monitor</span>
            </h1>
            <p className="text-gray-500">{session?.job_role} • {session?.company_name}</p>
          </div>
        </div>
        <div className="flex items-center space-x-3">
          <Link
            to={`/hr/agora-monitor/${sessionId}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center space-x-2 px-4 py-2 bg-green-50 hover:bg-green-100 text-green-700 rounded-lg text-sm font-semibold transition"
          >
            <Video size={16} />
            <span>Open AI Live Monitor</span>
          </Link>
          <button
            onClick={() => loadData(true)}
            disabled={refreshing}
            className="flex items-center space-x-2 px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg text-sm font-medium text-gray-700 transition"
          >
            <RefreshCw size={16} className={refreshing ? 'animate-spin' : ''} />
            <span>Refresh</span>
          </button>
          <button
            onClick={() => setShowEndConfirm(true)}
            className="flex items-center space-x-1.5 px-4 py-2 rounded-lg text-sm font-semibold bg-red-50 text-red-600 hover:bg-red-100 transition"
            title="End Session"
          >
            <LogOut size={16} />
            <span>End Session</span>
          </button>
        </div>
      </div>

      {/* End Session Confirmation Modal */}
      {showEndConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-2xl border border-gray-200 p-8 max-w-md w-full mx-4">
            <div className="text-center">
              <div className="w-14 h-14 rounded-full bg-red-100 flex items-center justify-center mx-auto mb-4">
                <LogOut className="text-red-600" size={28} />
              </div>
              <h3 className="text-xl font-bold text-gray-900 mb-2">End Session?</h3>
              <p className="text-gray-500 text-sm mb-6">
                This will end the interview session and force-complete all in-progress candidate interviews. This action cannot be undone.
              </p>
              <div className="flex gap-3">
                <button
                  onClick={() => setShowEndConfirm(false)}
                  className="flex-1 px-4 py-2.5 rounded-xl border-2 border-gray-200 text-gray-700 font-semibold hover:bg-gray-50 transition"
                  disabled={endingSession}
                >
                  Cancel
                </button>
                <button
                  onClick={async () => {
                    setEndingSession(true);
                    try {
                      await interviewAPI.endSession(sessionId);
                      toast.success('Session ended successfully');
                      setShowEndConfirm(false);
                      loadData();
                    } catch (err) {
                      toast.error('Failed to end session');
                    } finally {
                      setEndingSession(false);
                    }
                  }}
                  disabled={endingSession}
                  className="flex-1 px-4 py-2.5 rounded-xl bg-red-600 text-white font-semibold hover:bg-red-700 transition flex items-center justify-center gap-2 disabled:opacity-50"
                >
                  {endingSession ? <Loader2 size={16} className="animate-spin" /> : <LogOut size={16} />}
                  {endingSession ? 'Ending...' : 'End Session'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Info banner */}
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-6 flex items-start space-x-3">
        <Eye size={20} className="text-blue-600 flex-shrink-0 mt-0.5" />
        <div className="text-sm text-blue-800">
          <p className="font-semibold mb-1">AI is conducting two-round interviews</p>
          <p>Candidates start with Technical questions ({session?.technical_cutoff || 70}% cutoff), then proceed to HR questions. This dashboard auto-refreshes every 10 seconds. View each candidate's round, time remaining, and scores in real-time.</p>
        </div>
      </div>

  {/* Legacy Live Feed Panel removed in favor of Agora Dashboard */}

      {/* Summary stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-8">
        {[
          { label: 'Total', value: candidates.length, icon: Users, color: 'text-gray-700' },
          { label: 'In Progress', value: candidates.filter(c => c.status === 'in_progress').length, icon: Clock, color: 'text-blue-600' },
          { label: 'Completed', value: candidates.filter(c => c.status === 'completed').length, icon: CheckCircle, color: 'text-green-600' },
          { label: 'Failed Cutoff', value: candidates.filter(c => c.status === 'failed' || c.termination_reason).length, icon: XCircle, color: 'text-red-600' },
          {
            label: 'Avg Score',
            value: candidates.filter(c => c.avg_scores?.overall_score > 0).length > 0
              ? Math.round(
                candidates
                  .filter(c => c.avg_scores?.overall_score > 0)
                  .reduce((sum, c) => sum + c.avg_scores.overall_score, 0) /
                candidates.filter(c => c.avg_scores?.overall_score > 0).length
              ) + '%'
              : '—',
            icon: BarChart3,
            color: 'text-purple-600',
          },
        ].map((stat) => (
          <div key={stat.label} className="bg-white rounded-xl border border-gray-100 p-5">
            <div className="flex items-center space-x-3">
              <stat.icon size={20} className={stat.color} />
              <div>
                <div className={`text-xl font-bold ${stat.color}`}>{stat.value}</div>
                <div className="text-xs text-gray-500">{stat.label}</div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Tabs: Candidates | Duplicate Questions */}
      <div className="flex items-center space-x-1 mb-6 bg-gray-100 rounded-xl p-1 w-fit">
        <button
          onClick={() => setActiveTab('candidates')}
          className={`px-5 py-2.5 rounded-lg text-sm font-semibold transition-all ${activeTab === 'candidates'
              ? 'bg-white text-gray-900 shadow-sm'
              : 'text-gray-500 hover:text-gray-700'
            }`}
        >
          <span className="flex items-center gap-2"><Users size={15} /> Candidates ({candidates.length})</span>
        </button>
        <button
          onClick={() => setActiveTab('duplicates')}
          className={`px-5 py-2.5 rounded-lg text-sm font-semibold transition-all ${activeTab === 'duplicates'
              ? 'bg-white text-gray-900 shadow-sm'
              : 'text-gray-500 hover:text-gray-700'
            }`}
        >
          <span className="flex items-center gap-2">
            <Copy size={15} />
            Duplicate Questions
            {duplicateQuestions && duplicateQuestions.total_duplicate_questions > 0 && (
              <span className="ml-1 bg-red-100 text-red-700 text-xs px-2 py-0.5 rounded-full font-bold">
                {duplicateQuestions.total_duplicate_questions}
              </span>
            )}
          </span>
        </button>
      </div>

      {/* ── Duplicate Questions Tab ─────────────── */}
      {activeTab === 'duplicates' && (
        <div className="space-y-4">
          {duplicatesLoading ? (
            <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-12 text-center">
              <Loader2 className="animate-spin text-primary-500 mx-auto mb-3" size={32} />
              <p className="text-gray-400 text-sm">Loading duplicate questions...</p>
            </div>
          ) : !duplicateQuestions || duplicateQuestions.total_duplicate_questions === 0 ? (
            <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-12 text-center">
              <CheckCircle size={48} className="mx-auto text-green-300 mb-4" />
              <h2 className="text-lg font-semibold text-gray-700 mb-2">No Duplicate Questions</h2>
              <p className="text-gray-400 text-sm">All candidates received unique questions in this session.</p>
            </div>
          ) : (
            <>
              <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-start space-x-3">
                <AlertTriangle size={20} className="text-amber-600 flex-shrink-0 mt-0.5" />
                <div className="text-sm text-amber-800">
                  <p className="font-semibold mb-1">{duplicateQuestions.total_duplicate_questions} duplicate question(s) detected</p>
                  <p>The following questions were asked to multiple candidates in this session. This may affect fairness if candidates can share answers.</p>
                </div>
              </div>
              {duplicateQuestions.duplicates.map((dup, idx) => (
                <div key={idx} className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
                  <div className="flex items-start justify-between mb-4">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="bg-red-100 text-red-700 text-xs px-2.5 py-1 rounded-full font-semibold">
                          Asked to {dup.candidate_count} candidates
                        </span>
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${dup.candidates[0]?.round === 'HR' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'
                          }`}>
                          {dup.candidates[0]?.round || 'Technical'}
                        </span>
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${dup.candidates[0]?.difficulty === 'hard' ? 'bg-red-100 text-red-700'
                            : dup.candidates[0]?.difficulty === 'easy' ? 'bg-green-100 text-green-700'
                              : 'bg-yellow-100 text-yellow-700'
                          }`}>
                          {dup.candidates[0]?.difficulty || 'medium'}
                        </span>
                      </div>
                      <p className="text-gray-900 font-medium text-sm leading-relaxed">
                        "{dup.question}"
                      </p>
                    </div>
                  </div>
                  <div className="border-t border-gray-100 pt-3">
                    <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Candidates who received this question:</p>
                    <div className="flex flex-wrap gap-2">
                      {dup.candidates.map((c, cIdx) => (
                        <div key={cIdx} className="flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-2">
                          <div className="w-6 h-6 rounded-full bg-primary-100 flex items-center justify-center text-primary-700 text-xs font-bold">
                            {c.candidate_name?.[0]?.toUpperCase() || '?'}
                          </div>
                          <div>
                            <span className="text-sm font-medium text-gray-800">{c.candidate_name}</span>
                            <span className="text-xs text-gray-400 ml-2">{c.candidate_email}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
      )}

      {/* ── Candidates Tab ─────────────────────── */}
      {activeTab === 'candidates' && (<>
        {/* Candidate list */}
        {candidates.length === 0 ? (
          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-12 text-center">
            <Users size={48} className="mx-auto text-gray-300 mb-4" />
            <h2 className="text-lg font-semibold text-gray-700 mb-2">No candidates have started yet</h2>
            <p className="text-gray-400 text-sm">Candidates will appear here once they begin their AI interview.</p>
          </div>
        ) : (
          <div className="space-y-4">
            {candidates.map((c) => (
              <div
                key={c.candidate_email || c.session_id}
                className="bg-white rounded-xl border border-gray-100 shadow-sm p-6 hover:shadow-md transition"
              >
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                  {/* Candidate info */}
                  <div className="flex items-center space-x-4">
                    <div className="w-10 h-10 rounded-full bg-primary-100 flex items-center justify-center text-primary-700 font-bold">
                      {c.candidate_name?.[0]?.toUpperCase() || '?'}
                    </div>
                    <div>
                      <h3 className="font-semibold text-gray-900">{c.candidate_name || 'Not started'}</h3>
                      <p className="text-sm text-gray-500">{c.candidate_email}</p>
                    </div>
                  </div>

                  {/* Round, Time, Progress & Scores */}
                  <div className="flex items-center space-x-6">
                    {/* Current Round Badge */}
                    {c.status === 'in_progress' && (
                      <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${c.current_round === 'HR' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'
                        }`}>
                        {c.current_round || 'Technical'}
                      </span>
                    )}

                    {/* Time Remaining */}
                    {c.status === 'in_progress' && c.time_status && (
                      <div className="flex items-center space-x-1.5 text-sm">
                        <Timer size={14} className={c.time_status.remaining_seconds < 120 ? 'text-red-500' : 'text-gray-400'} />
                        <span className={`font-mono font-medium ${c.time_status.remaining_seconds < 120 ? 'text-red-600' : 'text-gray-600'}`}>
                          {formatTimeRemaining(c.time_status)}
                        </span>
                      </div>
                    )}

                    {/* Questions Answered */}
                    <div className="text-center">
                      <div className="text-lg font-bold text-gray-700">{c.answered}</div>
                      <div className="text-[10px] text-gray-400">Answered</div>
                    </div>

                    {/* Round Scores */}
                    <div className="hidden md:flex items-center space-x-4">
                      <div className="text-center">
                        <div className={`text-lg font-bold ${getScoreColor(c.technical_score || c.avg_scores?.overall_score || 0)}`}>
                          {c.technical_score ? Math.round(c.technical_score) + '%' : c.avg_scores?.overall_score > 0 ? Math.round(c.avg_scores.overall_score) + '%' : '—'}
                        </div>
                        <div className="text-[10px] text-gray-400">Tech</div>
                      </div>
                      {c.hr_score != null && (
                        <div className="text-center">
                          <div className={`text-lg font-bold ${getScoreColor(c.hr_score)}`}>
                            {Math.round(c.hr_score)}%
                          </div>
                          <div className="text-[10px] text-gray-400">HR</div>
                        </div>
                      )}
                    </div>

                    {/* Status badge */}
                    <div className="flex items-center space-x-2">
                      {getStatusIcon(c.status)}
                      <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${getStatusBadge(c.status)}`}>
                        {getStatusLabel(c.status)}
                      </span>
                    </div>

                    {/* View Report button */}
                    {(c.status === 'completed' || c.status === 'failed') && (
                      <button
                        onClick={() => viewReport(c.candidate_token)}
                        disabled={reportLoading}
                        className="flex items-center space-x-1 px-3 py-1.5 bg-primary-50 text-primary-700 rounded-lg text-sm font-medium hover:bg-primary-100 transition"
                      >
                        <FileText size={14} />
                        <span>Report</span>
                      </button>
                    )}

                    {/* Watch Live button */}
                    {c.status === 'in_progress' && (
                      <Link
                        to={`/hr/agora-monitor/${sessionId}?focus=${c.candidate_token}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center space-x-1 px-3 py-1.5 rounded-lg text-sm font-medium transition bg-green-50 text-green-700 hover:bg-green-100"
                      >
                        <Video size={14} />
                        <span>Watch Live</span>
                      </Link>
                    )}
                  </div>
                </div>

                {/* Current question (for in-progress candidates) */}
                {c.status === 'in_progress' && c.current_question && (
                  <div className="mt-4 bg-gray-50 rounded-lg p-3 text-sm">
                    <span className="text-gray-500 font-medium">Current Question: </span>
                    <span className="text-gray-700">{c.current_question}</span>
                  </div>
                )}

                {/* Termination reason (for failed candidates) */}
                {c.termination_reason && (
                  <div className="mt-3 flex items-center space-x-2 text-xs">
                    <AlertTriangle size={14} className="text-red-500" />
                    <span className="text-red-600 font-medium">Termination Reason:</span>
                    <span className="text-gray-600">{c.termination_reason}</span>
                  </div>
                )}

                {/* Latest evaluation (for in-progress candidates) */}
                {c.status === 'in_progress' && c.latest_evaluation && (
                  <div className="mt-3 flex items-center space-x-4 text-xs text-gray-500">
                    <span>Last answer:</span>
                    <span className={`font-semibold ${getScoreColor(c.latest_evaluation.overall_score)}`}>
                      {Math.round(c.latest_evaluation.overall_score)}% overall
                    </span>
                    {c.latest_evaluation.answer_strength && (
                      <span className={`px-2 py-0.5 rounded-full font-medium ${c.latest_evaluation.answer_strength === 'strong' ? 'bg-green-100 text-green-700'
                          : c.latest_evaluation.answer_strength === 'moderate' ? 'bg-yellow-100 text-yellow-700'
                            : 'bg-red-100 text-red-700'
                        }`}>
                        {c.latest_evaluation.answer_strength}
                      </span>
                    )}
                    {c.latest_evaluation.feedback && (
                      <span className="text-gray-400 truncate max-w-md">{c.latest_evaluation.feedback}</span>
                    )}
                  </div>
                )}

                {/* Proctoring Stats */}
                {c.proctoring && (c.proctoring.gaze_violations > 0 || c.proctoring.multi_person_alerts > 0 || c.proctoring.tab_switches > 0) && (
                  <div className="mt-3 flex items-center flex-wrap gap-3 text-xs">
                    <div className="flex items-center space-x-1 text-gray-500">
                      <Shield size={12} className="text-cyan-600" />
                      <span className="font-medium">Proctoring:</span>
                    </div>
                    {c.proctoring.gaze_violations > 0 && (
                      <span className={`flex items-center gap-1 px-2 py-0.5 rounded-full font-medium ${c.proctoring.gaze_violations < 5 ? 'bg-yellow-100 text-yellow-700' : 'bg-red-100 text-red-700'}`}>
                        <Eye size={10} /> Gaze: {c.proctoring.gaze_violations}
                      </span>
                    )}
                    {c.proctoring.multi_person_alerts > 0 && (
                      <span className="flex items-center gap-1 px-2 py-0.5 rounded-full font-medium bg-red-100 text-red-700">
                        <UserX size={10} /> Multi-Person: {c.proctoring.multi_person_alerts}
                      </span>
                    )}
                    {c.proctoring.tab_switches > 0 && (
                      <span className={`flex items-center gap-1 px-2 py-0.5 rounded-full font-medium ${c.proctoring.tab_switches < 3 ? 'bg-yellow-100 text-yellow-700' : 'bg-red-100 text-red-700'}`}>
                        <MonitorX size={10} /> Tabs: {c.proctoring.tab_switches}
                      </span>
                    )}
                    {(() => {
                      const p = c.proctoring;
                      const score = Math.max(0, 100 - ((p.gaze_violations || 0) * 3) - ((p.multi_person_alerts || 0) * 15) - ((p.tab_switches || 0) * 10) - ((p.total_away_time_sec || 0) * 0.5));
                      return (
                        <span className={`px-2 py-0.5 rounded-full font-bold ${score >= 80 ? 'bg-green-100 text-green-700' : score >= 50 ? 'bg-yellow-100 text-yellow-700' : 'bg-red-100 text-red-700'}`}>
                          Integrity: {Math.round(score)}%
                        </span>
                      );
                    })()}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </>)}

      {/* Legacy Gallery Logic removed */}
    </div>
  );
}
