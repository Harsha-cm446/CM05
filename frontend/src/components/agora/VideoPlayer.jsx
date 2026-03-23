/**
 * VideoPlayer — Renders an Agora video track into a DOM element.
 *
 * Uses track.play(containerId) and ensures cleanup on unmount.
 * Shows a loader while the track loads and a fallback if the track is null.
 */
import React, { useEffect, useRef, useState } from 'react';
import { Loader2, VideoOff, Monitor } from 'lucide-react';

const VideoPlayer = React.memo(function VideoPlayer({
  track,
  type = 'cam', // 'cam' | 'screen'
  className = '',
  style = {},
  muted = true,
}) {
  const containerRef = useRef(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const playIdRef = useRef(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !track) {
      setIsPlaying(false);
      return;
    }

    // Generate unique ID for the container
    if (!container.id) {
      container.id = `agora-video-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    }

    const id = container.id;
    playIdRef.current = id;

    // Small delay to ensure DOM is painted
    const timer = setTimeout(() => {
      if (playIdRef.current !== id) return; // stale
      try {
        track.play(id, { fit: type === 'screen' ? 'contain' : 'cover' });
        setIsPlaying(true);
      } catch (err) {
        console.warn('[VideoPlayer] play error:', err);
      }
    }, 50);

    return () => {
      clearTimeout(timer);
      playIdRef.current = null;
      try {
        track.stop();
      } catch {
        // track may already be stopped
      }
      setIsPlaying(false);
    };
  }, [track, type]);

  if (!track) {
    return (
      <div
        className={`flex flex-col items-center justify-center bg-gray-900/90 text-gray-500 ${className}`}
        style={style}
      >
        {type === 'screen' ? (
          <Monitor size={28} className="mb-2 text-gray-600" />
        ) : (
          <VideoOff size={28} className="mb-2 text-gray-600" />
        )}
        <span className="text-xs text-gray-600">
          No {type === 'screen' ? 'screen share' : 'camera'} feed
        </span>
      </div>
    );
  }

  return (
    <div className={`relative ${className}`} style={style}>
      {!isPlaying && (
        <div className="absolute inset-0 flex items-center justify-center bg-gray-900/80 z-10">
          <Loader2 size={24} className="animate-spin text-primary-400" />
        </div>
      )}
      <div
        ref={containerRef}
        className="w-full h-full"
        style={{ minHeight: '1px' }}
      />
    </div>
  );
});

export default VideoPlayer;
