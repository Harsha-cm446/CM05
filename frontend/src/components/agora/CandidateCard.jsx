/**
 * CandidateCard — Displays a single candidate's feeds.
 *
 * Layout:
 *   ┌──────────────────────┐
 *   │                      │  ← Screen share (main view)
 *   │                ┌────┐│
 *   │                │ 📹 ││  ← Camera overlay (top-right)
 *   │                └────┘│
 *   │  ● Candidate 3       │  ← Label + status
 *   └──────────────────────┘
 */
import React from 'react';
import { Video, VideoOff, Monitor, MonitorX, Wifi, WifiOff } from 'lucide-react';
import VideoPlayer from './VideoPlayer';

const CandidateCard = React.memo(function CandidateCard({
  candidateIndex,
  cameraTrack,
  screenTrack,
  onClick,
  isSelected = false,
}) {
  const hasCam = !!cameraTrack;
  const hasScreen = !!screenTrack;
  const hasAnyFeed = hasCam || hasScreen;

  return (
    <div
      onClick={onClick}
      className={`agora-candidate-card group relative overflow-hidden rounded-xl cursor-pointer transition-all duration-300
        ${isSelected
          ? 'ring-2 ring-primary-400 ring-offset-2 ring-offset-gray-900 scale-[1.02]'
          : 'ring-1 ring-white/10 hover:ring-primary-400/50 hover:scale-[1.01]'
        }
        ${hasAnyFeed ? 'bg-gray-900' : 'bg-gray-900/60'}
      `}
      style={{ aspectRatio: '16/10' }}
    >
      {/* Main view — Screen share (or camera fallback) */}
      <div className="absolute inset-0">
        {hasScreen ? (
          <VideoPlayer
            track={screenTrack}
            type="screen"
            className="w-full h-full"
          />
        ) : hasCam ? (
          <VideoPlayer
            track={cameraTrack}
            type="cam"
            className="w-full h-full"
          />
        ) : (
          <div className="w-full h-full flex flex-col items-center justify-center bg-gradient-to-br from-gray-800 to-gray-900">
            <div className="w-14 h-14 rounded-full bg-gray-700/50 flex items-center justify-center mb-3">
              <VideoOff size={24} className="text-gray-500" />
            </div>
            <span className="text-xs text-gray-500 font-medium">Waiting for streams...</span>
          </div>
        )}
      </div>

      {/* Camera overlay — top-right pip (only when screen share is active) */}
      {hasScreen && (
        <div className="absolute top-2 right-2 w-28 h-20 rounded-lg overflow-hidden ring-1 ring-white/20 shadow-lg z-20
          transition-all duration-200 group-hover:w-32 group-hover:h-24">
          {hasCam ? (
            <VideoPlayer
              track={cameraTrack}
              type="cam"
              className="w-full h-full"
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center bg-gray-800/90">
              <VideoOff size={14} className="text-gray-600" />
            </div>
          )}
        </div>
      )}

      {/* Bottom info bar */}
      <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/80 via-black/40 to-transparent
        p-3 pt-8 z-10">
        <div className="flex items-center justify-between">
          {/* Candidate label */}
          <div className="flex items-center space-x-2">
            <div className={`w-2 h-2 rounded-full ${hasAnyFeed ? 'bg-emerald-400 animate-pulse' : 'bg-gray-600'}`} />
            <span className="text-white text-sm font-medium tracking-wide">
              Candidate {candidateIndex}
            </span>
          </div>

          {/* Status indicators */}
          <div className="flex items-center space-x-1.5">
            <div className={`p-1 rounded-md ${hasCam ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}`}
              title={hasCam ? 'Camera active' : 'Camera off'}>
              {hasCam ? <Video size={12} /> : <VideoOff size={12} />}
            </div>
            <div className={`p-1 rounded-md ${hasScreen ? 'bg-blue-500/20 text-blue-400' : 'bg-red-500/20 text-red-400'}`}
              title={hasScreen ? 'Screen sharing' : 'No screen share'}>
              {hasScreen ? <Monitor size={12} /> : <MonitorX size={12} />}
            </div>
          </div>
        </div>
      </div>

      {/* LIVE badge */}
      {hasAnyFeed && (
        <div className="absolute top-2 left-2 z-20 flex items-center space-x-1
          bg-red-500/90 backdrop-blur-sm text-white text-[10px] font-bold px-2 py-0.5 rounded-md">
          <span className="w-1.5 h-1.5 bg-white rounded-full animate-pulse" />
          <span>LIVE</span>
        </div>
      )}
    </div>
  );
});

export default CandidateCard;
