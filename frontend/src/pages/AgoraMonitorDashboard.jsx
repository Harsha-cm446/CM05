/**
 * AgoraMonitorDashboard — HR real-time monitoring dashboard.
 *
 * Routes to: /hr/agora-monitor/:sessionId
 *
 * Features:
 *   - Gallery view of all candidates
 *   - Focus view on click
 *   - Connection status bar
 *   - Debug log panel
 *   - Session info header
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import toast from 'react-hot-toast';
import {
  ArrowLeft, Users, LayoutGrid, Wifi, WifiOff, RefreshCw,
  Terminal, ChevronDown, ChevronUp, Shield, Loader2, AlertTriangle,
  Maximize2, Minimize2,
} from 'lucide-react';

import useAgora from '../hooks/useAgora';
import useToken from '../hooks/useToken';
import GalleryView from '../components/agora/GalleryView';
import FocusView from '../components/agora/FocusView';

// HR observer UID — fixed, high range to avoid collision with candidates
const HR_UID = 999;

export default function AgoraMonitorDashboard() {
  const { sessionId } = useParams();

  // ── Agora hooks ────────────────────────────────────
  const { candidates, connectionState, logs, joinAsHR, leave } = useAgora();
  const { getToken, loading: tokenLoading, error: tokenError } = useToken();

  // ── UI State ───────────────────────────────────────
  const [viewMode, setViewMode] = useState('gallery'); // 'gallery' | 'focus'
  const [selectedCandidate, setSelectedCandidate] = useState(null);
  const [showLogs, setShowLogs] = useState(false);
  const [joining, setJoining] = useState(false);
  const [joined, setJoined] = useState(false);
  const [error, setError] = useState(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const candidateCount = useMemo(() => Object.keys(candidates).length, [candidates]);

  // ── Fullscreen sync ────────────────────────────────
  useEffect(() => {
    const onFS = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', onFS);
    return () => document.removeEventListener('fullscreenchange', onFS);
  }, []);

  const toggleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen?.().catch(() => {});
    } else {
      document.exitFullscreen?.().catch(() => {});
    }
  }, []);

  // ── Join channel ───────────────────────────────────
  const handleJoin = useCallback(async () => {
    if (joining || joined) return;
    setJoining(true);
    setError(null);

    try {
      const channel = `interview_${sessionId}`;
      const tokenData = await getToken(channel, HR_UID, 'subscriber');
      await joinAsHR(tokenData.appId, channel, tokenData.token, HR_UID);
      setJoined(true);
      toast.success('Connected to monitoring channel');
    } catch (err) {
      const msg = err.message || 'Failed to connect';
      setError(msg);
      toast.error(msg);
    } finally {
      setJoining(false);
    }
  }, [sessionId, joining, joined, getToken, joinAsHR]);

  // ── Auto-join on mount ─────────────────────────────
  useEffect(() => {
    handleJoin();
    return () => {
      leave();
    };
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  // ── Reconnect on disconnect ────────────────────────
  useEffect(() => {
    if (connectionState === 'DISCONNECTED' && joined && !joining) {
      const timer = setTimeout(() => {
        setJoined(false);
        handleJoin();
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [connectionState, joined, joining]);  // eslint-disable-line react-hooks/exhaustive-deps

  // ── Candidate selection ────────────────────────────
  const handleSelectCandidate = useCallback((candidateIndex) => {
    setSelectedCandidate(candidateIndex);
    setViewMode('focus');
  }, []);

  const handleBackToGallery = useCallback(() => {
    setViewMode('gallery');
    setSelectedCandidate(null);
  }, []);

  // ── Connection status color ────────────────────────
  const getConnectionStatusColor = () => {
    switch (connectionState) {
      case 'CONNECTED': return 'text-emerald-400';
      case 'CONNECTING':
      case 'RECONNECTING': return 'text-amber-400';
      default: return 'text-red-400';
    }
  };

  const getConnectionStatusBg = () => {
    switch (connectionState) {
      case 'CONNECTED': return 'bg-emerald-500/10 border-emerald-500/20';
      case 'CONNECTING':
      case 'RECONNECTING': return 'bg-amber-500/10 border-amber-500/20';
      default: return 'bg-red-500/10 border-red-500/20';
    }
  };

  return (
    <div className="min-h-screen bg-gray-950 text-white flex flex-col">
      {/* ── Header ─────────────────────────────────────── */}
      <header className="bg-gray-900/80 backdrop-blur-xl border-b border-white/5 px-4 py-3">
        <div className="flex items-center justify-between">
          {/* Left */}
          <div className="flex items-center space-x-4">
            <Link
              to={`/hr/live/${sessionId}`}
              className="p-2 rounded-lg bg-white/5 text-gray-400 hover:text-white hover:bg-white/10 transition"
              title="Back to session"
            >
              <ArrowLeft size={18} />
            </Link>

            <div>
              <h1 className="text-lg font-bold bg-gradient-to-r from-primary-400 to-purple-400 bg-clip-text text-transparent">
                Agora Monitor
              </h1>
              <p className="text-xs text-gray-500">Session: {sessionId}</p>
            </div>
          </div>

          {/* Center — Connection status */}
          <div className={`flex items-center space-x-2 px-3 py-1.5 rounded-full border ${getConnectionStatusBg()}`}>
            {connectionState === 'CONNECTED' ? (
              <Wifi size={14} className={getConnectionStatusColor()} />
            ) : connectionState === 'CONNECTING' || connectionState === 'RECONNECTING' ? (
              <Loader2 size={14} className={`${getConnectionStatusColor()} animate-spin`} />
            ) : (
              <WifiOff size={14} className={getConnectionStatusColor()} />
            )}
            <span className={`text-xs font-medium ${getConnectionStatusColor()}`}>
              {connectionState === 'CONNECTED' ? 'Connected' :
               connectionState === 'CONNECTING' ? 'Connecting...' :
               connectionState === 'RECONNECTING' ? 'Reconnecting...' :
               'Disconnected'}
            </span>
          </div>

          {/* Right — Controls */}
          <div className="flex items-center space-x-2">
            {/* Candidate count */}
            <div className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-white/5 text-gray-300">
              <Users size={14} />
              <span className="text-sm font-medium">{candidateCount}</span>
            </div>

            {/* View toggle */}
            {viewMode === 'focus' && (
              <button
                onClick={handleBackToGallery}
                className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-primary-500/20 text-primary-400
                  hover:bg-primary-500/30 transition text-sm font-medium"
              >
                <LayoutGrid size={14} />
                <span>Gallery</span>
              </button>
            )}

            {/* Fullscreen */}
            <button
              onClick={toggleFullscreen}
              className="p-2 rounded-lg bg-white/5 text-gray-400 hover:text-white hover:bg-white/10 transition"
              title="Toggle fullscreen"
            >
              {isFullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
            </button>

            {/* Reconnect */}
            {connectionState !== 'CONNECTED' && (
              <button
                onClick={() => { setJoined(false); handleJoin(); }}
                disabled={joining}
                className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-primary-500 text-white
                  hover:bg-primary-600 disabled:opacity-50 transition text-sm font-medium"
              >
                <RefreshCw size={14} className={joining ? 'animate-spin' : ''} />
                <span>Reconnect</span>
              </button>
            )}

            {/* Debug logs toggle */}
            <button
              onClick={() => setShowLogs((v) => !v)}
              className={`p-2 rounded-lg transition ${showLogs
                ? 'bg-primary-500/20 text-primary-400'
                : 'bg-white/5 text-gray-400 hover:text-white hover:bg-white/10'
              }`}
              title="Toggle debug logs"
            >
              <Terminal size={16} />
            </button>
          </div>
        </div>
      </header>

      {/* ── Error Banner ───────────────────────────────── */}
      {(error || tokenError) && (
        <div className="mx-4 mt-3 px-4 py-2 rounded-lg bg-red-500/10 border border-red-500/20
          flex items-center space-x-2 text-red-400 text-sm">
          <AlertTriangle size={16} />
          <span>{error || tokenError}</span>
          <button
            onClick={() => { setError(null); setJoined(false); handleJoin(); }}
            className="ml-auto text-xs underline hover:text-red-300"
          >
            Retry
          </button>
        </div>
      )}

      {/* ── Reconnecting Overlay ───────────────────────── */}
      {connectionState === 'RECONNECTING' && (
        <div className="mx-4 mt-3 px-4 py-2 rounded-lg bg-amber-500/10 border border-amber-500/20
          flex items-center space-x-2 text-amber-400 text-sm animate-pulse">
          <Loader2 size={16} className="animate-spin" />
          <span>Reconnecting to monitoring channel...</span>
        </div>
      )}

      {/* ── Main Content ───────────────────────────────── */}
      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 flex flex-col">
          {viewMode === 'gallery' ? (
            <GalleryView
              candidates={candidates}
              selectedCandidate={selectedCandidate}
              onSelectCandidate={handleSelectCandidate}
            />
          ) : (
            <FocusView
              candidates={candidates}
              selectedCandidate={selectedCandidate}
              onBack={handleBackToGallery}
              onSelectCandidate={(idx) => setSelectedCandidate(idx)}
            />
          )}
        </div>

        {/* ── Debug Log Panel ────────────────────────────── */}
        {showLogs && (
          <div className="w-80 bg-gray-900/80 border-l border-white/5 flex flex-col">
            <div className="flex items-center justify-between px-3 py-2 border-b border-white/5">
              <div className="flex items-center space-x-2">
                <Terminal size={14} className="text-primary-400" />
                <span className="text-xs font-medium text-gray-400 uppercase tracking-wider">
                  Debug Logs
                </span>
              </div>
              <button
                onClick={() => setShowLogs(false)}
                className="text-gray-500 hover:text-gray-300 transition"
              >
                <ChevronDown size={14} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-2 font-mono text-[10px] leading-relaxed text-gray-500">
              {logs.length === 0 ? (
                <p className="text-gray-600 p-2">No logs yet...</p>
              ) : (
                logs.map((log, i) => (
                  <div
                    key={i}
                    className={`py-0.5 px-1 rounded ${
                      log.includes('✅') ? 'text-emerald-400' :
                      log.includes('❌') ? 'text-red-400' :
                      log.includes('⚠️') ? 'text-amber-400' :
                      log.includes('Published') || log.includes('Subscribed') ? 'text-blue-400' :
                      'text-gray-500'
                    }`}
                  >
                    {log}
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
