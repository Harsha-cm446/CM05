import React, { useState, useEffect } from 'react';
import {
  LiveKitRoom,
  VideoConference,
  RoomAudioRenderer,
  ControlBar,
  useTracks,
  GridLayout,
  ParticipantTile,
  ParticipantName
} from '@livekit/components-react';
import '@livekit/components-styles';
import { Track } from 'livekit-client';
import { Loader2, Users } from 'lucide-react';

export default function LiveKitMonitorDashboard({ sessionId, embedded = false, focusId = null }) {
  const [token, setToken] = useState(null);
  const [error, setError] = useState(null);
  
  // For the HR monitor, we assign a special user ID (e.g., hr-monitor-sessionX)
  const hrUserId = `hr-monitor-${sessionId}`;
  
  useEffect(() => {
    // Fetch LiveKit Token
    const fetchToken = async () => {
      try {
        const response = await fetch(`http://localhost:8000/livekit/get-token?user=${hrUserId}&room=${sessionId}`);
        if (!response.ok) {
          throw new Error('Failed to fetch LiveKit token');
        }
        const data = await response.json();
        setToken(data.token);
      } catch (err) {
        setError(err.message);
      }
    };
    
    fetchToken();
  }, [sessionId, hrUserId]);

  if (error) {
    return (
      <div className="flex h-full items-center justify-center bg-gray-900 text-red-400 p-8 rounded-lg">
        <p>Error loading LiveKit: {error}</p>
      </div>
    );
  }

  if (!token) {
    return (
      <div className="flex flex-col h-full items-center justify-center bg-gray-900 text-gray-400 p-8 rounded-lg">
        <Loader2 className="w-8 h-8 animate-spin mb-4 text-indigo-500" />
        <p>Connecting to secure LiveKit room...</p>
      </div>
    );
  }

  return (
    <LiveKitRoom
      video={false} // HR doesn't publish video by default
      audio={false} // HR doesn't publish audio by default
      token={token}
      serverUrl={import.meta.env.VITE_LIVEKIT_URL}
      data-lk-theme="default"
      className="h-full w-full"
    >
      <div className="flex flex-col h-full">
        {/* Header */}
        {!embedded && (
          <div className="flex items-center justify-between p-4 bg-gray-800 border-b border-gray-700">
            <h2 className="text-xl font-semibold flex items-center">
              <Users className="w-5 h-5 mr-2 text-indigo-400" />
              Live Interview Monitor
            </h2>
            <div className="text-sm bg-gray-700 px-3 py-1 rounded-full text-gray-300">
              Session: {sessionId}
            </div>
          </div>
        )}
        
        {/* Main Content Area */}
        <div className="flex-1 bg-black overflow-hidden relative">
          <GalleryView focusId={focusId} />
        </div>
      </div>
      <RoomAudioRenderer />
    </LiveKitRoom>
  );
}

// Custom Grid layout to display both camera and screen share tracks
function GalleryView({ focusId }) {
  // Get all camera and screen share video tracks
  const tracks = useTracks([
    { source: Track.Source.Camera, withPlaceholder: true },
    { source: Track.Source.ScreenShare, withPlaceholder: false },
  ]);

  if (tracks.length === 0) {
    return (
      <div className="w-full h-full flex flex-col items-center justify-center text-gray-500">
        <Users className="w-12 h-12 mb-4 opacity-50" />
        <p className="text-lg">Waiting for candidates to join...</p>
      </div>
    );
  }

  // Filter if we are focusing on a specific candidate ID
  const filteredTracks = focusId 
    ? tracks.filter(t => t.participant.identity === focusId)
    : tracks;

  return (
    <GridLayout
      tracks={filteredTracks}
      style={{ height: 'calc(100vh - var(--lk-control-bar-height))', width: '100%' }}
    >
      <ParticipantTile />
    </GridLayout>
  );
}
