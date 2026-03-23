/**
 * FocusView — Enlarged view of a single candidate with sidebar filmstrip.
 *
 * Layout:
 *   ┌────────────────────────────┬──────┐
 *   │                            │ C1   │
 *   │   Selected Candidate       │ C2   │  ← Sidebar
 *   │   (Screen + Camera PIP)    │ C3   │
 *   │                            │ ...  │
 *   └────────────────────────────┴──────┘
 */
import React from 'react';
import {
  ArrowLeft, Video, VideoOff, Monitor, MonitorX,
  Maximize2, Minimize2,
} from 'lucide-react';
import VideoPlayer from './VideoPlayer';

export default function FocusView({
  candidates,         // full candidates map
  selectedCandidate,  // candidateIndex
  onBack,             // () => void — go back to gallery
  onSelectCandidate,  // (candidateIndex) => void
}) {
  const [isFullscreen, setIsFullscreen] = React.useState(false);
  const containerRef = React.useRef(null);

  const selected = candidates[selectedCandidate];
  const otherEntries = Object.entries(candidates)
    .filter(([idx]) => idx !== String(selectedCandidate))
    .sort(([a], [b]) => Number(a) - Number(b));

  // Keyboard shortcut: Esc to exit focus mode
  React.useEffect(() => {
    const handleKey = (e) => {
      if (e.key === 'Escape') onBack();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onBack]);

  const toggleFullscreen = React.useCallback(() => {
    if (!document.fullscreenElement) {
      containerRef.current?.requestFullscreen?.().catch(() => {});
      setIsFullscreen(true);
    } else {
      document.exitFullscreen?.().catch(() => {});
      setIsFullscreen(false);
    }
  }, []);

  React.useEffect(() => {
    const onFSChange = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', onFSChange);
    return () => document.removeEventListener('fullscreenchange', onFSChange);
  }, []);

  if (!selected) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-500">
        <p>Candidate not found. <button onClick={onBack} className="text-primary-400 underline">Go back</button></p>
      </div>
    );
  }

  const hasCam = !!selected.cameraTrack;
  const hasScreen = !!selected.screenTrack;

  return (
    <div ref={containerRef} className="flex-1 flex bg-gray-950">
      {/* Main area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <div className="flex items-center justify-between px-4 py-2 bg-gray-900/80 border-b border-white/5">
          <div className="flex items-center space-x-3">
            <button
              onClick={onBack}
              className="p-2 rounded-lg bg-white/5 text-white hover:bg-white/10 transition"
              title="Back to gallery (Esc)"
            >
              <ArrowLeft size={16} />
            </button>
            <div className="flex items-center space-x-2">
              <div className={`w-2.5 h-2.5 rounded-full ${(hasCam || hasScreen) ? 'bg-emerald-400 animate-pulse' : 'bg-gray-600'}`} />
              <h2 className="text-white font-semibold text-lg">
                Candidate {selectedCandidate}
              </h2>
            </div>

            {/* Status pills */}
            <div className="flex items-center space-x-2 ml-4">
              <span className={`inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-xs font-medium
                ${hasCam ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}`}>
                {hasCam ? <Video size={10} /> : <VideoOff size={10} />}
                <span>{hasCam ? 'Camera On' : 'Camera Off'}</span>
              </span>
              <span className={`inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-xs font-medium
                ${hasScreen ? 'bg-blue-500/20 text-blue-400' : 'bg-red-500/20 text-red-400'}`}>
                {hasScreen ? <Monitor size={10} /> : <MonitorX size={10} />}
                <span>{hasScreen ? 'Screen On' : 'Screen Off'}</span>
              </span>
            </div>
          </div>

          <button
            onClick={toggleFullscreen}
            className="p-2 rounded-lg bg-white/5 text-white hover:bg-white/10 transition"
            title="Toggle fullscreen"
          >
            {isFullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
          </button>
        </div>

        {/* Video area */}
        <div className="flex-1 relative">
          {/* Main feed — screen share preferred */}
          <div className="absolute inset-0">
            {hasScreen ? (
              <VideoPlayer
                track={selected.screenTrack}
                type="screen"
                className="w-full h-full"
              />
            ) : hasCam ? (
              <VideoPlayer
                track={selected.cameraTrack}
                type="cam"
                className="w-full h-full"
              />
            ) : (
              <div className="w-full h-full flex flex-col items-center justify-center bg-gray-900">
                <VideoOff size={48} className="text-gray-600 mb-3" />
                <span className="text-gray-500">No streams available</span>
              </div>
            )}
          </div>

          {/* Camera PIP — bottom-right when screen is the main view */}
          {hasScreen && (
            <div className="absolute bottom-4 right-4 w-48 h-36 rounded-xl overflow-hidden
              ring-2 ring-white/20 shadow-2xl z-20 hover:w-64 hover:h-48 transition-all duration-300">
              {hasCam ? (
                <VideoPlayer
                  track={selected.cameraTrack}
                  type="cam"
                  className="w-full h-full"
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center bg-gray-800">
                  <VideoOff size={20} className="text-gray-600" />
                </div>
              )}
            </div>
          )}

          {/* LIVE indicator */}
          {(hasCam || hasScreen) && (
            <div className="absolute top-4 left-4 z-20 flex items-center space-x-1.5
              bg-red-500/90 backdrop-blur-sm text-white text-xs font-bold px-3 py-1 rounded-lg">
              <span className="w-2 h-2 bg-white rounded-full animate-pulse" />
              <span>LIVE</span>
            </div>
          )}
        </div>
      </div>

      {/* Sidebar — other candidates */}
      {otherEntries.length > 0 && (
        <div className="w-52 bg-gray-900/60 border-l border-white/5 overflow-y-auto">
          <div className="p-2 text-xs text-gray-500 font-medium uppercase tracking-wider border-b border-white/5">
            Other Candidates ({otherEntries.length})
          </div>
          <div className="p-2 space-y-2">
            {otherEntries.map(([idx, data]) => (
              <button
                key={idx}
                onClick={() => onSelectCandidate(idx)}
                className="w-full rounded-lg overflow-hidden ring-1 ring-white/10 hover:ring-primary-400/50
                  transition-all duration-200 group"
              >
                <div className="relative" style={{ aspectRatio: '16/10' }}>
                  {data.screenTrack ? (
                    <VideoPlayer
                      track={data.screenTrack}
                      type="screen"
                      className="w-full h-full"
                    />
                  ) : data.cameraTrack ? (
                    <VideoPlayer
                      track={data.cameraTrack}
                      type="cam"
                      className="w-full h-full"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center bg-gray-800">
                      <VideoOff size={14} className="text-gray-600" />
                    </div>
                  )}
                  {/* Label */}
                  <div className="absolute bottom-0 inset-x-0 bg-black/70 px-2 py-0.5">
                    <div className="flex items-center space-x-1">
                      <div className={`w-1.5 h-1.5 rounded-full
                        ${(data.cameraTrack || data.screenTrack) ? 'bg-emerald-400' : 'bg-gray-600'}`} />
                      <span className="text-[10px] text-white font-medium">
                        Candidate {idx}
                      </span>
                    </div>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
