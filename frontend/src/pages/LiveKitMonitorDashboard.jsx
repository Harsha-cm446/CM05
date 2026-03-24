import React, { useState, useEffect } from 'react';
import {
  LiveKitRoom,
  useParticipants,
  useTracks,
  VideoTrack,
  AudioTrack,
  ParticipantName
} from '@livekit/components-react';
import '@livekit/components-styles/index.css';
import { Track } from 'livekit-client';
import { Loader2, Users, Maximize2, Minimize2 } from 'lucide-react';
import api from '../services/api';

export default function LiveKitMonitorDashboard({ sessionId, embedded = false, focusId = null }) {
  const [token, setToken] = useState(null);
  const [error, setError] = useState(null);

  // For the HR monitor, we assign a special user ID (e.g., hr-monitor-sessionX)
  const hrUserId = `hr-monitor-${sessionId}`;

  useEffect(() => {
    // Fetch LiveKit Token
    const fetchToken = async () => {
      try {
        const response = await api.get('/livekit/get-token', {
          params: { user: hrUserId, room: sessionId }
        });
        setToken(response.data.token);
      } catch (err) {
        setError(err.message || 'Failed to fetch LiveKit token');
      }
    };

    if (sessionId) {
      fetchToken();
    }
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
        <div className="flex-1 bg-black overflow-hidden relative p-4">
          <DashboardContent focusId={focusId} />
        </div>
      </div>
      {/* We purposefully omit RoomAudioRenderer here because we handle audio manually per-candidate */}
    </LiveKitRoom>
  );
}

function DashboardContent({ focusId }) {
  const allParticipants = useParticipants();
  const candidates = allParticipants.filter(p => !p.isLocal); // Exclude the HR monitor itself
  const [selectedCandidateId, setSelectedCandidateId] = useState(focusId || null);

  // Get all track references for all participants in the room
  const cameraTracks = useTracks([{ source: Track.Source.Camera, withPlaceholder: true }]);
  const screenTracks = useTracks([{ source: Track.Source.ScreenShare, withPlaceholder: true }]);
  const micTracks = useTracks([{ source: Track.Source.Microphone, withPlaceholder: true }]);

  if (candidates.length === 0) {
    return (
      <div className="w-full h-full flex flex-col items-center justify-center text-gray-500">
        <Users className="w-12 h-12 mb-4 opacity-50" />
        <p className="text-lg">Waiting for candidates to join...</p>
      </div>
    );
  }

  // If a candidate is selected, show them in full view
  const selectedCandidate = candidates.find(c => c.identity === selectedCandidateId);
  if (selectedCandidate) {
    const camRef = cameraTracks.find(t => t.participant.identity === selectedCandidateId);
    const screenRef = screenTracks.find(t => t.participant.identity === selectedCandidateId);
    const micRef = micTracks.find(t => t.participant.identity === selectedCandidateId);

    return (
      <div className="w-full h-full flex flex-col">
        <div className="flex justify-between items-center mb-4">
          <div className="text-white">
            <h3 className="text-xl font-bold">{selectedCandidate.name || selectedCandidate.identity}</h3>
            <span className="text-sm text-gray-400">{selectedCandidate.identity}</span>
          </div>
          <button 
            onClick={() => setSelectedCandidateId(null)}
            className="flex items-center gap-2 px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg transition-colors"
          >
            <Minimize2 className="w-4 h-4" /> Back to Grid
          </button>
        </div>
        
        {/* Play audio only for the selected candidate */}
        {micRef && <AudioTrack trackRef={micRef} />}

        <div className="flex-1 min-h-0 flex gap-4">
          {/* Main Screen Share Area */}
          <div className="flex-1 bg-gray-900 rounded-lg overflow-hidden border border-gray-700 relative flex items-center justify-center">
            {screenRef ? (
              <VideoTrack trackRef={screenRef} className="w-full h-full object-contain bg-black" />
            ) : (
              <div className="text-gray-500">No screen share available</div>
            )}
            <div className="absolute top-2 left-2 bg-black/60 px-2 py-1 rounded text-xs text-white">Screen Share</div>
          </div>
          
          {/* Side Camera Feed */}
          <div className="w-1/4 max-w-sm bg-gray-900 rounded-lg overflow-hidden border border-gray-700 relative flex flex-col items-center justify-center">
            {camRef ? (
              <VideoTrack trackRef={camRef} className="w-full h-full object-cover bg-black" />
            ) : (
              <div className="text-gray-500">No camera available</div>
            )}
            <div className="absolute top-2 left-2 bg-black/60 px-2 py-1 rounded text-xs text-white">Camera</div>
          </div>
        </div>
      </div>
    );
  }

  // Otherwise, show all candidates in a grid style
  return (
    <div className="w-full h-full grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 overflow-y-auto">
      {candidates.map(participant => {
        const id = participant.identity;
        const camRef = cameraTracks.find(t => t.participant.identity === id);
        const screenRef = screenTracks.find(t => t.participant.identity === id);

        return (
          <div 
            key={id}
            className="col-span-1 bg-gray-800 rounded-xl overflow-hidden border border-gray-700 flex flex-col cursor-pointer hover:border-indigo-500 transition-colors group"
            onClick={() => setSelectedCandidateId(id)}
          >
            {/* Card Header */}
            <div className="p-3 bg-gray-900 flex justify-between items-center border-b border-gray-700">
              <div>
                <div className="font-semibold text-white truncate max-w-[200px]" title={participant.name || id}>
                  {participant.name || id}
                </div>
                <div className="text-xs text-gray-400 truncate max-w-[200px]" title={id}>
                  {id}
                </div>
              </div>
              <Maximize2 className="w-4 h-4 text-gray-500 group-hover:text-indigo-400" />
            </div>

            {/* Card Media (No Audio Rendered Here) */}
            <div className="flex-1 p-2 gap-2 flex flex-col aspect-video relative bg-black">
              <div className="flex-1 relative rounded overflow-hidden flex items-center justify-center bg-gray-900">
                 {screenRef ? (
                   <VideoTrack trackRef={screenRef} className="w-full h-full object-contain bg-gray-900" />
                 ) : (
                   <span className="text-gray-600 text-xs">No Screen Share</span>
                 )}
                 <div className="absolute top-1 left-1 bg-black/50 text-[10px] text-white px-1 rounded">Screen</div>
              </div>
              <div className="absolute bottom-2 right-2 w-1/3 aspect-video rounded border border-gray-600 overflow-hidden shadow-lg z-10 flex items-center justify-center bg-gray-800">
                 {camRef ? (
                   <VideoTrack trackRef={camRef} className="w-full h-full object-cover bg-gray-800" />
                 ) : (
                   <span className="text-gray-600 text-xs">No Cam</span>
                 )}
                 <div className="absolute bottom-1 left-1 bg-black/50 text-[10px] text-white px-1 rounded">Cam</div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
