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

const ICE_SERVERS = [
  { urls: 'stun:stun.l.google.com:19302' },
  { urls: 'stun:stun1.l.google.com:19302' },
  { urls: 'stun:stun2.l.google.com:19302' },
  { urls: 'stun:stun3.l.google.com:19302' },
  { urls: 'stun:stun4.l.google.com:19302' },
  // Free TURN servers for NAT traversal
  {
    urls: 'turn:openrelay.metered.ca:80',
    username: 'openrelayproject',
    credential: 'openrelayproject',
  },
  {
    urls: 'turn:openrelay.metered.ca:443',
    username: 'openrelayproject',
    credential: 'openrelayproject',
  },
  {
    urls: 'turn:openrelay.metered.ca:443?transport=tcp',
    username: 'openrelayproject',
    credential: 'openrelayproject',
  },
  // Additional free TURN (relay.metered.ca)
  {
    urls: 'turn:a.relay.metered.ca:80',
    username: 'e8dd65b92af416a2b710dc24',
    credential: '1laBSqnG6QRKfk+1',
  },
  {
    urls: 'turn:a.relay.metered.ca:443',
    username: 'e8dd65b92af416a2b710dc24',
    credential: '1laBSqnG6QRKfk+1',
  },
  {
    urls: 'turn:a.relay.metered.ca:443?transport=tcp',
    username: 'e8dd65b92af416a2b710dc24',
    credential: '1laBSqnG6QRKfk+1',
  },
];

// ── Gallery Tile: auto-attaches stream to video ─────────────────────
const GalleryVideoTile = React.memo(function GalleryVideoTile({ token, stream, candidateName, type, onEnlarge }) {
  const videoCallbackRef = useCallback((node) => {
    if (!node || !stream) return;
    if (node.srcObject?.id === stream.id) return;
    node.srcObject = stream;
    node.play().catch(() => {});
  }, [stream]);

  return (
    <div className="absolute inset-0">
      {stream ? (
        <video ref={videoCallbackRef} autoPlay playsInline muted className={`w-full h-full ${type === 'screen' ? 'object-contain' : 'object-cover'}`} />
      ) : (
        <div className="w-full h-full flex flex-col items-center justify-center text-gray-500 bg-gray-900">
          {type === 'screen' ? <Monitor size={20} className="mb-1 text-gray-600" /> : <VideoOff size={20} className="mb-1 text-gray-600" />}
          <span className="text-[10px] text-gray-600">No {type}</span>
        </div>
      )}
      {/* Type badge */}
      <div className="absolute bottom-1 left-1 bg-black/60 text-white text-[9px] px-1.5 py-0.5 rounded flex items-center space-x-1">
        {type === 'screen' ? <Monitor size={8} /> : <Video size={8} />}
        <span>{candidateName}</span>
      </div>
    </div>
  );
});

// ── Enlarged Video: used in the modal ───────────────────────────────
function EnlargedVideo({ stream, label, icon, objectFit }) {
  const videoRef = useRef(null);
  useEffect(() => {
    if (videoRef.current && stream) {
      videoRef.current.srcObject = stream;
      videoRef.current.play().catch(() => {});
    }
  }, [stream]);
  return (
    <>
      {stream ? (
        <video ref={videoRef} autoPlay playsInline muted className={`w-full h-full ${objectFit}`} />
      ) : (
        <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-500">
          <VideoOff size={28} className="mb-2" />
          <span className="text-xs">No {label.toLowerCase()} feed</span>
        </div>
      )}
      <div className="absolute top-3 left-3 bg-black/60 text-white text-xs px-2 py-1 rounded-md flex items-center space-x-1">
        {icon}
        <span>{label}</span>
      </div>
      {stream && (
        <div className="absolute top-3 right-3 bg-red-500 text-white text-xs px-2 py-1 rounded-md flex items-center space-x-1">
          <span className="w-1.5 h-1.5 bg-white rounded-full animate-pulse"></span>
          <span>LIVE</span>
        </div>
      )}
    </>
  );
}

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

  // ── Live Feed State ─────────────────────────────────
  const [watchingCandidate, setWatchingCandidate] = useState(null); // token of candidate being watched
  const watchingCandidateRef = useRef(null);
  const [streamableCandidates, setStreamableCandidates] = useState({}); // conn_id -> { name, has_camera, has_screen }
  const wsRef = useRef(null);
  const peerConnectionRef = useRef(null);
  const cameraVideoRef = useRef(null);
  const screenVideoRef = useRef(null);
  const [cameraStream, setCameraStream] = useState(null);
  const [screenStream, setScreenStream] = useState(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [showEndConfirm, setShowEndConfirm] = useState(false);
  const [endingSession, setEndingSession] = useState(false);

  // ── Gallery View State ──────────────────────────────
  const [galleryPage, setGalleryPage] = useState(0);
  const GALLERY_PAGE_SIZE = 10;
  const galleryPeersRef = useRef({}); // token -> { pc, name }
  const galleryICEQueueRef = useRef({}); // token -> [candidates] — queued ICE before PC exists
  const [galleryStreams, setGalleryStreams] = useState({}); // token -> { camera: MediaStream|null, screen: MediaStream|null, name }
  const galleryVideoRefs = useRef({}); // token -> video element ref
  const [enlargedFeed, setEnlargedFeed] = useState(null); // { token, type: 'camera'|'screen' } | null
  const [isFullscreen, setIsFullscreen] = useState(false);
  const enlargedModalRef = useRef(null);

  // Sync isFullscreen state with browser fullscreen changes (e.g. user presses Esc)
  useEffect(() => {
    const onFSChange = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', onFSChange);
    return () => document.removeEventListener('fullscreenchange', onFSChange);
  }, []);

  const toggleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  }, []);

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

  // ── WebSocket for live feed ─────────────────────────
  useEffect(() => {
    if (!sessionId) return;

    const hrName = 'HR Manager';
    let wsUrl;
    if (WS_BASE) {
      wsUrl = `${WS_BASE}/ws/interview/${sessionId}?role=hr&name=${encodeURIComponent(hrName)}&token=hr_${sessionId}`;
    } else {
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      wsUrl = `${wsProtocol}//${window.location.host}/ws/interview/${sessionId}?role=hr&name=${encodeURIComponent(hrName)}&token=hr_${sessionId}`;
    }

    let ws;
    let reconnectTimer;
    let reconnectAttempts = 0;

    const connect = () => {
      ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('[WS] HR connected to interview room');
        setWsConnected(true);
        reconnectAttempts = 0;
        // Request all candidate stream statuses immediately — no delay
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'request_all_streams' }));
        }
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          handleWSMessage(data);
        } catch (e) {
          console.error('[WS] Parse error:', e);
        }
      };

      ws.onclose = () => {
        console.log('[WS] HR disconnected');
        setWsConnected(false);
        // Auto-reconnect with exponential backoff (max 10s)
        if (reconnectAttempts < 20) {
          const delay = Math.min(1000 * Math.pow(1.5, reconnectAttempts), 10000);
          reconnectAttempts++;
          console.log(`[WS] Reconnecting in ${Math.round(delay)}ms (attempt ${reconnectAttempts})`);
          reconnectTimer = setTimeout(connect, delay);
        }
      };

      ws.onerror = () => setWsConnected(false);
    };

    connect();

    return () => {
      reconnectAttempts = 100; // prevent reconnect during cleanup
      clearTimeout(reconnectTimer);
      if (wsRef.current) wsRef.current.close();
      closeStream();
      cleanupAllGalleryPeers();
    };
  }, [sessionId]);

  // Helper: populate streamableCandidates from a stream_status map { conn_id: {name, has_camera, has_screen} }
  const applyStreamStatus = useCallback((streams) => {
    if (!streams || typeof streams !== 'object') return;
    setStreamableCandidates((prev) => {
      const next = { ...prev };
      Object.entries(streams).forEach(([connId, info]) => {
        next[connId] = {
          name: info.name || connId,
          has_camera: !!info.has_camera,
          has_screen: !!info.has_screen,
        };
      });
      return next;
    });
  }, []);

  const handleWSMessage = useCallback((data) => {
    console.log('[HR WS] Received:', data.type, data.from || '');
    switch (data.type) {
      case 'room_state':
        // On (re)connect the backend sends participants + persisted stream_status
        if (data.stream_status) {
          applyStreamStatus(data.stream_status);
          // Pre-populate galleryPeersRef AND immediately request streams
          // so gallery is pre-connected even before HR opens the gallery tab
          Object.entries(data.stream_status).forEach(([connId, info]) => {
            if ((info.has_camera || info.has_screen) && !galleryPeersRef.current[connId]) {
              galleryPeersRef.current[connId] = { pc: null, name: info.name || connId };
              galleryICEQueueRef.current[connId] = [];
              // Immediately request stream — don't wait for tab switch
              if (wsRef.current?.readyState === WebSocket.OPEN) {
                wsRef.current.send(JSON.stringify({ type: 'request_stream', target: connId }));
              }
            }
          });
        }
        break;
      case 'all_stream_status':
        // Response to request_all_streams — bulk update
        if (data.streams) {
          applyStreamStatus(data.streams);
          // Pre-populate galleryPeersRef AND immediately request streams
          Object.entries(data.streams).forEach(([connId, info]) => {
            if ((info.has_camera || info.has_screen) && !galleryPeersRef.current[connId]) {
              galleryPeersRef.current[connId] = { pc: null, name: info.name || connId };
              galleryICEQueueRef.current[connId] = [];
              // Immediately request stream — don't wait for tab switch
              if (wsRef.current?.readyState === WebSocket.OPEN) {
                wsRef.current.send(JSON.stringify({ type: 'request_stream', target: connId }));
              }
            }
          });
        }
        break;
      case 'stream_ready':
        console.log('[HR WS] Candidate stream ready:', data.from, 'camera:', data.has_camera, 'screen:', data.has_screen);
        setStreamableCandidates((prev) => ({
          ...prev,
          [data.from]: {
            name: data.name,
            has_camera: data.has_camera,
            has_screen: data.has_screen,
          },
        }));
        // Proactive auto-connect: immediately establish gallery peer for ANY
        // candidate that announces streams, regardless of which tab is active.
        // This ensures video is already connected when HR opens gallery.
        if (data.from && (data.has_camera || data.has_screen)) {
          const pc = peerConnectionRef.current;
          const pcDead = !pc || pc.connectionState === 'failed' || pc.connectionState === 'closed';
          // Single-view: re-request if watching this candidate and connection died
          if (watchingCandidateRef.current === data.from && pcDead) {
              console.log('[HR WS] Auto-re-requesting stream for watched candidate:', data.from);
              if (wsRef.current?.readyState === WebSocket.OPEN) {
                wsRef.current.send(JSON.stringify({ type: 'request_stream', target: data.from }));
              }
          }
          // Gallery: proactively connect to this candidate
          const galleryEntry = galleryPeersRef.current[data.from];
          if (galleryEntry !== undefined) {
            // Already tracked — re-request only if dead
            const galleryPcDead = !galleryEntry.pc || galleryEntry.pc.connectionState === 'failed' || galleryEntry.pc.connectionState === 'closed';
            if (galleryPcDead) {
              console.log('[HR WS] Re-requesting dead gallery stream for:', data.from);
              galleryPeersRef.current[data.from] = { pc: null, name: data.name || galleryEntry.name };
              galleryICEQueueRef.current[data.from] = [];
              if (wsRef.current?.readyState === WebSocket.OPEN) {
                wsRef.current.send(JSON.stringify({ type: 'request_stream', target: data.from }));
              }
            }
          } else {
            // New candidate — proactively pre-connect so gallery view is instant
            console.log('[HR WS] Proactive gallery pre-connect for:', data.from, data.name);
            galleryPeersRef.current[data.from] = { pc: null, name: data.name || data.from };
            galleryICEQueueRef.current[data.from] = [];
            if (wsRef.current?.readyState === WebSocket.OPEN) {
              wsRef.current.send(JSON.stringify({ type: 'request_stream', target: data.from }));
            }
          }
        }
        break;
      case 'user_joined':
        // A candidate just joined — request their stream status immediately
        if (data.conn_id && wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'request_all_streams' }));
        }
        break;
      case 'user_left':
        setStreamableCandidates((prev) => {
          const next = { ...prev };
          delete next[data.conn_id];
          return next;
        });
        cleanupGalleryPeer(data.conn_id);
        break;
      case 'candidate_disconnected':
        // Candidate WebSocket disconnected — clean up their streams but keep stream_status
        // so when they reconnect and send stream_ready, we can auto-re-request
        console.log('[HR WS] Candidate disconnected:', data.conn_id, data.name);
        cleanupGalleryPeer(data.conn_id);
        if (watchingCandidateRef.current === data.conn_id) {
            watchingCandidateRef.current = null;
            setWatchingCandidate(null);
            if (peerConnectionRef.current) {
                peerConnectionRef.current.close();
                peerConnectionRef.current = null;
            }
            setCameraStream(null);
            setScreenStream(null);
        }
        break;
      case 'webrtc_offer': {
        console.log('[HR WS] Got WebRTC offer from:', data.from);
        const isWatching = watchingCandidateRef.current === data.from;
        const inGallery  = galleryPeersRef.current[data.from] !== undefined;

        if (isWatching) {
            // Single-view (Watch button) takes priority when actively watching
            handleWebRTCOffer(data).catch(e => console.error('[WebRTC Offer]', e));
            // Also update gallery peer so gallery view stays in sync
            if (inGallery) {
                if (!galleryPeersRef.current[data.from]) {
                    galleryPeersRef.current[data.from] = { pc: null, name: data.from };
                    galleryICEQueueRef.current[data.from] = [];
                }
                handleGalleryOffer(data).catch(e => console.error('[Gallery Offer]', e));
            }
        } else {
            // Gallery view — route to gallery handler
            if (!galleryPeersRef.current[data.from]) {
                galleryPeersRef.current[data.from] = { pc: null, name: data.from };
                galleryICEQueueRef.current[data.from] = [];
            }
            handleGalleryOffer(data).catch(e => console.error('[Gallery Offer]', e));
        }
        break;
      }
      case 'ice_candidate':
        if (galleryPeersRef.current[data.from] !== undefined) {
          // Gallery peer exists — route to gallery ICE handler (handles queuing if PC not ready)
          handleGalleryICE(data).catch(e => console.error('[Gallery ICE] Error:', e));
        } else if (peerConnectionRef.current && watchingCandidateRef.current === data.from) {
          // Single-view peer — route to single-view ICE handler
          handleICECandidate(data).catch(e => console.error('[ICE] Error:', e));
        } else {
          // Unknown peer — queue in gallery ICE queue for when peer is created
          console.log('[HR ICE] Queuing ICE for unknown peer:', data.from);
          if (!galleryICEQueueRef.current[data.from]) galleryICEQueueRef.current[data.from] = [];
          if (data.candidate) galleryICEQueueRef.current[data.from].push(data.candidate);
        }
        break;
      case 'session_ended':
        // Session ended — refresh data to show updated statuses
        loadData();
        break;
      default:
        break;
    }
  }, []);

  // ICE candidate queue — candidates arriving before remote description is set
  const pendingICERef = useRef([]);

  const handleWebRTCOffer = useCallback(async (data) => {
    console.log('[HR WebRTC] Handling offer from:', data.from);
    // Close previous peer connection only — do NOT reset watchingCandidate
    if (peerConnectionRef.current) {
      peerConnectionRef.current.close();
      peerConnectionRef.current = null;
    }
    setCameraStream(null);
    setScreenStream(null);
    pendingICERef.current = [];

    const pc = new RTCPeerConnection({
      iceServers: ICE_SERVERS,
      iceCandidatePoolSize: 4,
      bundlePolicy: 'max-bundle',
      rtcpMuxPolicy: 'require',
    });
    peerConnectionRef.current = pc;

    // Collect incoming streams — identify by track kind and stream id
    const assignedStreams = new Map(); // stream.id -> 'camera' | 'screen'
    let cameraAssigned = false;

    pc.ontrack = (event) => {
      const stream = event.streams[0];
      if (!stream) return;

      console.log('[HR WebRTC] ontrack:', event.track.kind, 'label:', event.track.label, 'stream:', stream.id);

      const trackLabel = (event.track.label || '').toLowerCase();
      const isScreenTrack = trackLabel.includes('screen') || trackLabel.includes('display') || trackLabel.includes('monitor') || trackLabel.includes('window');

      if (!assignedStreams.has(stream.id)) {
        if (isScreenTrack) {
          assignedStreams.set(stream.id, 'screen');
        } else if (!cameraAssigned) {
          assignedStreams.set(stream.id, 'camera');
          cameraAssigned = true;
        } else {
          assignedStreams.set(stream.id, 'screen');
        }
      }

      const streamType = assignedStreams.get(stream.id);
      console.log('[HR WebRTC] Stream type:', streamType, 'track:', event.track.kind);
      if (streamType === 'camera') {
        setCameraStream(stream);
      } else {
        setScreenStream(stream);
      }
    };

    pc.onicecandidate = (event) => {
      if (event.candidate && wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({
          type: 'ice_candidate',
          target: data.from,
          candidate: event.candidate.toJSON(),
        }));
      }
    };

    pc.onconnectionstatechange = () => {
      console.log('[HR WebRTC] Connection state:', pc.connectionState);
      if (pc.connectionState === 'failed') {
        // Connection failed — close PC and auto-retry requesting the stream
        if (peerConnectionRef.current === pc) {
          peerConnectionRef.current.close();
          peerConnectionRef.current = null;
          setCameraStream(null);
          setScreenStream(null);
          // Auto-retry after 1s
          setTimeout(() => {
            if (wsRef.current?.readyState === WebSocket.OPEN) {
              console.log('[HR WebRTC] Auto-retrying stream request after failure');
              wsRef.current.send(JSON.stringify({
                type: 'request_stream',
                target: data.from,
              }));
            }
          }, 1000);
        }
      } else if (pc.connectionState === 'disconnected') {
        // "disconnected" may recover on its own — wait 3s before closing
        setTimeout(() => {
          if (pc.connectionState === 'disconnected' || pc.connectionState === 'failed') {
            if (peerConnectionRef.current === pc) {
              peerConnectionRef.current.close();
              peerConnectionRef.current = null;
              setCameraStream(null);
              setScreenStream(null);
              // Auto-retry
              if (wsRef.current?.readyState === WebSocket.OPEN) {
                console.log('[HR WebRTC] Auto-retrying stream after prolonged disconnect');
                wsRef.current.send(JSON.stringify({
                  type: 'request_stream',
                  target: data.from,
                }));
              }
            }
          }
        }, 3000);
      }
    };

    // Monitor ICE connection state for faster failure detection
    pc.oniceconnectionstatechange = () => {
      console.log('[HR WebRTC] ICE state:', pc.iceConnectionState);
      if (pc.iceConnectionState === 'failed' && peerConnectionRef.current === pc) {
        peerConnectionRef.current.close();
        peerConnectionRef.current = null;
        setCameraStream(null);
        setScreenStream(null);
        setTimeout(() => {
          if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ type: 'request_stream', target: data.from }));
          }
        }, 1000);
      }
    };

    await pc.setRemoteDescription(new RTCSessionDescription(data.offer));

    // Flush any ICE candidates that arrived while we were processing the offer
    for (const candidate of pendingICERef.current) {
      try {
        await pc.addIceCandidate(new RTCIceCandidate(candidate));
      } catch (err) {
        console.error('[ICE] Error adding queued candidate:', err);
      }
    }
    pendingICERef.current = [];

    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);

    wsRef.current?.send(JSON.stringify({
      type: 'webrtc_answer',
      target: data.from,
      answer: pc.localDescription.toJSON(),
    }));
  }, []);

  const handleICECandidate = useCallback(async (data) => {
    const pc = peerConnectionRef.current;
    if (pc && data.candidate) {
      // If remote description isn't set yet, queue the candidate
      if (!pc.remoteDescription) {
        console.log('[ICE] Queuing candidate (remote desc not set yet)');
        pendingICERef.current.push(data.candidate);
        return;
      }
      try {
        await pc.addIceCandidate(new RTCIceCandidate(data.candidate));
      } catch (err) {
        console.error('[ICE] Error adding candidate:', err);
      }
    } else if (data.candidate) {
      // PC doesn't exist yet — queue it
      pendingICERef.current.push(data.candidate);
    }
  }, []);

  const requestStream = useCallback((candidateToken) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      toast.error('Not connected to interview room');
      return;
    }
    console.log('[HR] Requesting stream from:', candidateToken);
    watchingCandidateRef.current = candidateToken;
    setWatchingCandidate(candidateToken);
    setCameraStream(null);
    setScreenStream(null);
    pendingICERef.current = [];

    const sendRequest = () => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({
          type: 'request_stream',
          target: candidateToken,
        }));
      }
    };

    sendRequest();
    // Fast auto-retry at 1s, 2s, 4s if no peer connection established
    [1000, 2000, 4000].forEach((delay) => {
      setTimeout(() => {
        if (!peerConnectionRef.current || peerConnectionRef.current.connectionState === 'failed') {
          console.log(`[HR] Retrying stream request (${delay / 1000}s)`);
          sendRequest();
        }
      }, delay);
    });
  }, []);

  const closeStream = useCallback(() => {
    peerConnectionRef.current?.close();
    peerConnectionRef.current = null;
    setCameraStream(null);
    setScreenStream(null);
    watchingCandidateRef.current = null;
    setWatchingCandidate(null);
  }, []);

  // ── Gallery Multi-Stream Functions ──────────────────

  const handleGalleryOffer = useCallback(async (data) => {
    const token = data.from;
    const existing = galleryPeersRef.current[token];
    if (existing?.pc) {
      existing.pc.close();
    }

    const pc = new RTCPeerConnection({
      iceServers: ICE_SERVERS,
      iceCandidatePoolSize: 4,
      bundlePolicy: 'max-bundle',
      rtcpMuxPolicy: 'require',
    });
    const candidateName = existing?.name || token;
    galleryPeersRef.current[token] = { pc, name: candidateName };

    // Flush any ICE candidates that arrived before this PC was created
    const queued = galleryICEQueueRef.current[token] || [];
    galleryICEQueueRef.current[token] = [];

    const assignedStreams = new Map();
    let cameraAssigned = false;

    pc.ontrack = (event) => {
      const stream = event.streams[0];
      if (!stream) return;

      const trackLabel = (event.track.label || '').toLowerCase();
      const isScreenTrack = trackLabel.includes('screen') || trackLabel.includes('display') || trackLabel.includes('monitor') || trackLabel.includes('window');

      if (!assignedStreams.has(stream.id)) {
        if (isScreenTrack) {
          assignedStreams.set(stream.id, 'screen');
        } else if (!cameraAssigned) {
          assignedStreams.set(stream.id, 'camera');
          cameraAssigned = true;
        } else {
          assignedStreams.set(stream.id, 'screen');
        }
      }

      const streamType = assignedStreams.get(stream.id);
      setGalleryStreams(prev => ({
        ...prev,
        [token]: {
          ...prev[token],
          name: candidateName,
          [streamType === 'camera' ? 'camera' : 'screen']: stream,
        },
      }));
    };

    pc.onicecandidate = (event) => {
      if (event.candidate && wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({
          type: 'ice_candidate',
          target: token,
          candidate: event.candidate.toJSON(),
        }));
      }
    };

    pc.onconnectionstatechange = () => {
      const state = pc.connectionState;
      console.log('[Gallery] Connection state for', token, ':', state);
      if (state === 'failed') {
        console.log('[Gallery] Peer connection failed for', token, '— retrying in 1.5s');
        cleanupGalleryPeer(token);
        setTimeout(() => {
          if (wsRef.current?.readyState === WebSocket.OPEN) {
            galleryPeersRef.current[token] = { pc: null, name: candidateName };
            galleryICEQueueRef.current[token] = [];
            wsRef.current.send(JSON.stringify({ type: 'request_stream', target: token }));
          }
        }, 1500);
      } else if (state === 'disconnected') {
        // Wait longer before acting — ICE often recovers on its own
        setTimeout(() => {
          const current = galleryPeersRef.current[token];
          if (current?.pc === pc && (pc.connectionState === 'disconnected' || pc.connectionState === 'failed')) {
            console.log('[Gallery] Peer still disconnected for', token, '— restarting ICE');
            try {
              pc.restartIce(); // Try ICE restart first — keeps video alive
            } catch (e) {
              // restartIce not supported, fall back to full reconnect
              cleanupGalleryPeer(token);
              if (wsRef.current?.readyState === WebSocket.OPEN) {
                galleryPeersRef.current[token] = { pc: null, name: candidateName };
                galleryICEQueueRef.current[token] = [];
                wsRef.current.send(JSON.stringify({ type: 'request_stream', target: token }));
              }
            }
          }
        }, 8000); // Increased from 3s: give ICE time to self-recover
      }
    };

    // ICE-level failure detection (fires faster than connectionState)
    pc.oniceconnectionstatechange = () => {
      if (pc.iceConnectionState === 'failed') {
        console.log('[Gallery] ICE failed for', token, '— attempting ICE restart');
        try {
          pc.restartIce(); // Try in-place ICE restart — avoids visible stream interruption
        } catch (e) {
          // Fall back to full reconnect if restartIce fails
          cleanupGalleryPeer(token);
          setTimeout(() => {
            if (wsRef.current?.readyState === WebSocket.OPEN) {
              galleryPeersRef.current[token] = { pc: null, name: candidateName };
              galleryICEQueueRef.current[token] = [];
              wsRef.current.send(JSON.stringify({ type: 'request_stream', target: token }));
            }
          }, 1000);
        }
      }
    };

    await pc.setRemoteDescription(new RTCSessionDescription(data.offer));

    // Now that remote description is set, flush queued ICE candidates
    for (const candidate of queued) {
      try {
        await pc.addIceCandidate(new RTCIceCandidate(candidate));
      } catch (err) {
        console.error('[Gallery ICE] Error adding queued candidate:', err);
      }
    }

    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);

    wsRef.current?.send(JSON.stringify({
      type: 'webrtc_answer',
      target: token,
      answer: pc.localDescription.toJSON(),
    }));
  }, []);

  const handleGalleryICE = useCallback(async (data) => {
    const pc = galleryPeersRef.current[data.from]?.pc;
    if (pc && data.candidate) {
      // If remote description isn't set yet, queue the candidate
      if (!pc.remoteDescription) {
        if (!galleryICEQueueRef.current[data.from]) galleryICEQueueRef.current[data.from] = [];
        galleryICEQueueRef.current[data.from].push(data.candidate);
        return;
      }
      try {
        await pc.addIceCandidate(new RTCIceCandidate(data.candidate));
      } catch (err) {
        console.error('[Gallery ICE] Error:', err);
      }
    } else if (data.candidate) {
      // PC doesn't exist yet — queue it
      if (!galleryICEQueueRef.current[data.from]) galleryICEQueueRef.current[data.from] = [];
      galleryICEQueueRef.current[data.from].push(data.candidate);
    }
  }, []);

  const cleanupGalleryPeer = useCallback((token) => {
    const entry = galleryPeersRef.current[token];
    if (entry?.pc) {
      entry.pc.close();
    }
    delete galleryPeersRef.current[token];
    delete galleryICEQueueRef.current[token];
    setGalleryStreams(prev => {
      const next = { ...prev };
      delete next[token];
      return next;
    });
  }, []);

  const cleanupAllGalleryPeers = useCallback(() => {
    Object.keys(galleryPeersRef.current).forEach(token => {
      galleryPeersRef.current[token]?.pc?.close();
    });
    galleryPeersRef.current = {};
    galleryICEQueueRef.current = {};
    setGalleryStreams({});
  }, []);

  // Ensure all streamable candidates have gallery peer connections
  const ensureAllGalleryConnections = useCallback(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    // Get all streamable candidate tokens
    Object.entries(streamableCandidates).forEach(([token, info]) => {
      if (!info.has_camera && !info.has_screen) return;
      const entry = galleryPeersRef.current[token];
      const needsConnect = !entry || !entry.pc || entry.pc.connectionState === 'failed' || entry.pc.connectionState === 'closed';
      if (needsConnect) {
        const name = info.name || token;
        galleryPeersRef.current[token] = { pc: null, name };
        galleryICEQueueRef.current[token] = [];
        wsRef.current.send(JSON.stringify({ type: 'request_stream', target: token }));
      }
    });
  }, [streamableCandidates]);

  // ── Periodic gallery health check: detect dead peers and ensure all candidates connected ──
  // Runs regardless of active tab so streams are always pre-warmed
  const stuckPeerTimersRef = useRef({}); // token -> timestamp when first seen as stuck
  useEffect(() => {
    const healthCheck = setInterval(() => {
      // Clean up dead or stuck peers
      const peers = galleryPeersRef.current;
      Object.entries(peers).forEach(([token, entry]) => {
        if (!entry?.pc) {
          // Peer entry exists but PC is null — stuck waiting for offer response
          if (!stuckPeerTimersRef.current[token]) {
            stuckPeerTimersRef.current[token] = Date.now();
          } else if (Date.now() - stuckPeerTimersRef.current[token] > 10000) {
            // Stuck for >10s — re-request stream
            console.log('[Gallery Health] Stuck peer (no PC) detected:', token, '— re-requesting');
            delete stuckPeerTimersRef.current[token];
            galleryPeersRef.current[token] = { pc: null, name: entry.name || token };
            galleryICEQueueRef.current[token] = [];
            if (wsRef.current?.readyState === WebSocket.OPEN) {
              wsRef.current.send(JSON.stringify({ type: 'request_stream', target: token }));
            }
          }
          return;
        }
        delete stuckPeerTimersRef.current[token]; // Has a PC, not stuck
        const state = entry.pc.connectionState;
        if (state === 'failed' || state === 'closed') {
          console.log('[Gallery Health] Dead peer detected:', token, state);
          cleanupGalleryPeer(token);
        } else if (state === 'new') {
          // Stuck in 'new' — negotiation never completed
          if (!stuckPeerTimersRef.current[token]) {
            stuckPeerTimersRef.current[token] = Date.now();
          } else if (Date.now() - stuckPeerTimersRef.current[token] > 10000) {
            console.log('[Gallery Health] Stuck peer (state=new) detected:', token, '— re-requesting');
            delete stuckPeerTimersRef.current[token];
            cleanupGalleryPeer(token);
            galleryPeersRef.current[token] = { pc: null, name: entry.name || token };
            galleryICEQueueRef.current[token] = [];
            if (wsRef.current?.readyState === WebSocket.OPEN) {
              wsRef.current.send(JSON.stringify({ type: 'request_stream', target: token }));
            }
          }
        }
      });
      // Ensure all streamable candidates have connections
      ensureAllGalleryConnections();
    }, 8000);
    return () => clearInterval(healthCheck);
  }, [cleanupGalleryPeer, ensureAllGalleryConnections]);

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

  // ── Attach streams to video elements (with explicit play for mobile) ───
  useEffect(() => {
    if (cameraVideoRef.current && cameraStream) {
      cameraVideoRef.current.srcObject = cameraStream;
      cameraVideoRef.current.play().catch(() => {});
    }
  }, [cameraStream]);

  useEffect(() => {
    if (screenVideoRef.current && screenStream) {
      screenVideoRef.current.srcObject = screenStream;
      screenVideoRef.current.play().catch(() => {});
    }
  }, [screenStream]);

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
          <div className={`rounded-xl p-5 mb-6 border flex items-start space-x-3 ${
            rpt.recommendation === 'Selected'
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
              <p className={`font-semibold ${
                rpt.recommendation === 'Selected' ? 'text-green-800'
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
              <div className={`text-2xl font-bold ${
                roundSummary.hr?.questions_asked > 0 ? getScoreColor(roundSummary.hr?.score || 0) : 'text-gray-300'
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
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      qe.round === 'HR' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'
                    }`}>
                      {qe.round || 'Technical'}
                    </span>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      qe.difficulty === 'hard' ? 'bg-red-100 text-red-700'
                        : qe.difficulty === 'easy' ? 'bg-green-100 text-green-700'
                        : 'bg-yellow-100 text-yellow-700'
                    }`}>
                      {qe.difficulty || 'medium'}
                    </span>
                    <p className="text-sm font-medium text-gray-900">Q{i + 1}: {qe.question}</p>
                  </div>
                  <div className="flex items-center space-x-2 flex-shrink-0">
                    {qe.answer_strength && (
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                        qe.answer_strength === 'strong' ? 'bg-green-100 text-green-700'
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
          <button
            onClick={() => loadData(true)}
            disabled={refreshing}
            className="flex items-center space-x-2 px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg text-sm font-medium text-gray-700 transition"
          >
            <RefreshCw size={16} className={refreshing ? 'animate-spin' : ''} />
            <span>Refresh</span>
          </button>
          <button
            onClick={toggleFullscreen}
            className="p-2 bg-gray-100 hover:bg-gray-200 rounded-lg transition"
            title={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
          >
            {isFullscreen ? <Minimize2 size={16} className="text-gray-600" /> : <Maximize2 size={16} className="text-gray-600" />}
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
        {wsConnected ? (
          <span className="flex items-center space-x-1 text-xs text-green-700 bg-green-100 px-2 py-1 rounded-full flex-shrink-0">
            <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></span>
            <span>Live ({Object.keys(streamableCandidates).length} streaming)</span>
          </span>
        ) : (
          <span className="flex items-center space-x-1 text-xs text-red-700 bg-red-100 px-2 py-1 rounded-full flex-shrink-0">
            <span className="w-2 h-2 bg-red-500 rounded-full"></span>
            <span>Disconnected</span>
          </span>
        )}
      </div>

      {/* ── Live Feed Panel ────────────────────────── */}
      {watchingCandidate && (
        <div className="bg-gray-900 rounded-2xl overflow-hidden mb-6 shadow-xl">
          <div className="flex items-center justify-between px-5 py-3 bg-gray-800">
            <div className="flex items-center space-x-2 text-white">
              <Video size={18} className="text-red-400" />
              <span className="font-semibold text-sm">Live Feed</span>
              <span className="text-xs text-gray-400">— Watching candidate</span>
            </div>
            <button
              onClick={closeStream}
              className="p-1.5 hover:bg-gray-700 rounded-lg transition"
            >
              <X size={16} className="text-gray-400" />
            </button>
          </div>
          <div className="grid md:grid-cols-2 gap-1 p-1">
            {/* Camera Feed */}
            <div className="relative bg-black rounded-lg overflow-hidden aspect-video">
              {cameraStream ? (
                <video
                  ref={cameraVideoRef}
                  autoPlay
                  playsInline
                  muted
                  className="w-full h-full object-cover"
                />
              ) : (
                <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-500">
                  <VideoOff size={32} className="mb-2" />
                  <span className="text-xs">Waiting for camera feed...</span>
                  <span className="text-[10px] text-gray-600 mt-1">
                    {streamableCandidates[watchingCandidate] ? 'Establishing WebRTC connection...' : 'Candidate not yet streaming'}
                  </span>
                </div>
              )}
              <div className="absolute top-2 left-2 bg-black/60 text-white text-xs px-2 py-1 rounded-md flex items-center space-x-1">
                <Video size={12} />
                <span>Camera</span>
              </div>
              {cameraStream && (
                <div className="absolute top-2 right-2 bg-red-500 text-white text-xs px-2 py-1 rounded-md flex items-center space-x-1">
                  <span className="w-1.5 h-1.5 bg-white rounded-full animate-pulse"></span>
                  <span>LIVE</span>
                </div>
              )}
            </div>
            {/* Screen Share Feed */}
            <div className="relative bg-black rounded-lg overflow-hidden aspect-video">
              {screenStream ? (
                <video
                  ref={screenVideoRef}
                  autoPlay
                  playsInline
                  muted
                  className="w-full h-full object-contain"
                />
              ) : (
                <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-500">
                  <Monitor size={32} className="mb-2" />
                  <span className="text-xs">No screen share</span>
                </div>
              )}
              <div className="absolute top-2 left-2 bg-black/60 text-white text-xs px-2 py-1 rounded-md flex items-center space-x-1">
                <Monitor size={12} />
                <span>Screen</span>
              </div>
              {screenStream && (
                <div className="absolute top-2 right-2 bg-red-500 text-white text-xs px-2 py-1 rounded-md flex items-center space-x-1">
                  <span className="w-1.5 h-1.5 bg-white rounded-full animate-pulse"></span>
                  <span>LIVE</span>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

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

      {/* Tabs: Candidates | Gallery | Duplicate Questions */}
      <div className="flex items-center space-x-1 mb-6 bg-gray-100 rounded-xl p-1 w-fit">
        <button
          onClick={() => setActiveTab('candidates')}
          className={`px-5 py-2.5 rounded-lg text-sm font-semibold transition-all ${
            activeTab === 'candidates'
              ? 'bg-white text-gray-900 shadow-sm'
              : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          <span className="flex items-center gap-2"><Users size={15} /> Candidates ({candidates.length})</span>
        </button>
        <button
          onClick={() => {
            setActiveTab('gallery');
            // Force re-announce from all candidates + ensure peer connections
            setTimeout(() => {
              if (wsRef.current?.readyState === WebSocket.OPEN) {
                wsRef.current.send(JSON.stringify({ type: 'request_all_streams' }));
              }
              ensureAllGalleryConnections();
            }, 200);
          }}
          className={`px-5 py-2.5 rounded-lg text-sm font-semibold transition-all ${
            activeTab === 'gallery'
              ? 'bg-white text-gray-900 shadow-sm'
              : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          <span className="flex items-center gap-2">
            <LayoutGrid size={15} />
            Gallery
            {Object.keys(streamableCandidates).length > 0 && (
              <span className="ml-1 bg-green-100 text-green-700 text-xs px-2 py-0.5 rounded-full font-bold">
                {Object.keys(streamableCandidates).length}
              </span>
            )}
          </span>
        </button>
        <button
          onClick={() => setActiveTab('duplicates')}
          className={`px-5 py-2.5 rounded-lg text-sm font-semibold transition-all ${
            activeTab === 'duplicates'
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
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                          dup.candidates[0]?.round === 'HR' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'
                        }`}>
                          {dup.candidates[0]?.round || 'Technical'}
                        </span>
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                          dup.candidates[0]?.difficulty === 'hard' ? 'bg-red-100 text-red-700'
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
                    <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${
                      c.current_round === 'HR' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'
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
                    <button
                      onClick={() => requestStream(c.candidate_token)}
                      disabled={!wsConnected || !streamableCandidates[c.candidate_token]}
                      className={`flex items-center space-x-1 px-3 py-1.5 rounded-lg text-sm font-medium transition ${
                        watchingCandidate === c.candidate_token
                          ? 'bg-red-100 text-red-700'
                          : streamableCandidates[c.candidate_token]
                          ? 'bg-green-50 text-green-700 hover:bg-green-100'
                          : 'bg-gray-100 text-gray-400'
                      } ${(!wsConnected || !streamableCandidates[c.candidate_token]) ? 'opacity-50 cursor-not-allowed' : ''}`}
                    >
                      <Video size={14} />
                      <span>{watchingCandidate === c.candidate_token ? 'Watching' : streamableCandidates[c.candidate_token] ? 'Watch Live' : 'Connecting...'}</span>
                    </button>
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
                    <span className={`px-2 py-0.5 rounded-full font-medium ${
                      c.latest_evaluation.answer_strength === 'strong' ? 'bg-green-100 text-green-700'
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

      {/* ── Gallery View Tab ───────────────────────── */}
      {activeTab === 'gallery' && (() => {
        const inProgressCandidates = candidates
          .filter(c => ['in_progress', 'joined'].includes(c.status) && streamableCandidates[c.candidate_token])
          .map(c => ({
            token: c.candidate_token,
            name: c.candidate_name || streamableCandidates[c.candidate_token]?.name || 'Unknown',
            hasCamera: streamableCandidates[c.candidate_token]?.has_camera,
            hasScreen: streamableCandidates[c.candidate_token]?.has_screen,
          }));

        // Build flat list of all individual feed tiles
        const allTiles = [];
        inProgressCandidates.forEach(c => {
          if (c.hasCamera || galleryStreams[c.token]?.camera) {
            allTiles.push({ token: c.token, name: c.name, type: 'camera', stream: galleryStreams[c.token]?.camera || null });
          }
          if (c.hasScreen || galleryStreams[c.token]?.screen) {
            allTiles.push({ token: c.token, name: c.name, type: 'screen', stream: galleryStreams[c.token]?.screen || null });
          }
          // If candidate has neither flag but has a gallery entry, show camera placeholder
          if (!c.hasCamera && !c.hasScreen && !galleryStreams[c.token]?.camera && !galleryStreams[c.token]?.screen) {
            allTiles.push({ token: c.token, name: c.name, type: 'camera', stream: null });
          }
        });

        const totalPages = Math.max(1, Math.ceil(allTiles.length / (GALLERY_PAGE_SIZE * 2))); // 2 tiles per candidate previously
        const currentPage = Math.min(galleryPage, totalPages - 1);
        const tilesPerPage = GALLERY_PAGE_SIZE * 2;
        const pageTiles = allTiles.slice(currentPage * tilesPerPage, (currentPage + 1) * tilesPerPage);

        return (
          <div>
            {allTiles.length === 0 ? (
              <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-12 text-center">
                <VideoOff size={48} className="mx-auto text-gray-300 mb-4" />
                <h2 className="text-lg font-semibold text-gray-700 mb-2">No live streams available</h2>
                <p className="text-gray-400 text-sm">Candidates will appear here once they start their interview with camera enabled.</p>
              </div>
            ) : (
              <>
                {/* Flat gallery grid — each feed is its own tile */}
                <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
                  {pageTiles.map(tile => (
                    <div
                      key={`${tile.token}-${tile.type}`}
                      className="bg-gray-800 rounded-xl overflow-hidden cursor-pointer group hover:ring-2 hover:ring-primary-400 transition-all hover:scale-[1.02]"
                      onClick={() => setEnlargedFeed({ token: tile.token, type: tile.type })}
                    >
                      {/* Video area */}
                      <div className="relative bg-black" style={{ aspectRatio: '16/10' }}>
                        <GalleryVideoTile
                          token={tile.token}
                          stream={tile.stream}
                          candidateName={tile.name}
                          type={tile.type}
                          onEnlarge={() => setEnlargedFeed({ token: tile.token, type: tile.type })}
                        />
                        {/* Enlarge icon on hover */}
                        <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition">
                          <div className="p-1.5 bg-black/60 rounded-lg">
                            <Maximize2 size={14} className="text-white" />
                          </div>
                        </div>
                        {/* LIVE badge */}
                        {tile.stream && (
                          <div className="absolute top-2 right-2 group-hover:top-auto group-hover:bottom-8 group-hover:right-2 transition-all">
                            <span className="bg-red-500 text-white text-[9px] px-1.5 py-0.5 rounded flex items-center space-x-1">
                              <span className="w-1.5 h-1.5 bg-white rounded-full animate-pulse"></span>
                              <span>LIVE</span>
                            </span>
                          </div>
                        )}
                      </div>
                      {/* Footer: candidate name + type */}
                      <div className="flex items-center justify-between px-3 py-2 bg-gray-900">
                        <div className="flex items-center space-x-2 min-w-0">
                          <div className="w-5 h-5 rounded-full bg-primary-600 flex items-center justify-center text-white text-[10px] font-bold flex-shrink-0">
                            {tile.name?.[0]?.toUpperCase() || '?'}
                          </div>
                          <span className="text-white text-xs font-medium truncate">{tile.name}</span>
                        </div>
                        <span className="flex items-center space-x-1 text-gray-400 text-[10px] flex-shrink-0 ml-2">
                          {tile.type === 'screen' ? <Monitor size={10} /> : <Video size={10} />}
                          <span className="capitalize">{tile.type}</span>
                        </span>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Pagination */}
                {totalPages > 1 && (
                  <div className="flex items-center justify-center space-x-4 mt-6">
                    <button
                      onClick={() => setGalleryPage(currentPage - 1)}
                      disabled={currentPage === 0}
                      className="flex items-center space-x-1 px-4 py-2 rounded-lg bg-white border border-gray-200 text-sm font-medium hover:bg-gray-50 transition disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <ChevronLeft size={16} />
                      <span>Previous</span>
                    </button>
                    <div className="flex items-center space-x-2">
                      {Array.from({ length: totalPages }, (_, i) => (
                        <button
                          key={i}
                          onClick={() => setGalleryPage(i)}
                          className={`w-8 h-8 rounded-lg text-sm font-semibold transition ${
                            i === currentPage
                              ? 'bg-primary-600 text-white shadow-sm'
                              : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
                          }`}
                        >
                          {i + 1}
                        </button>
                      ))}
                    </div>
                    <button
                      onClick={() => setGalleryPage(currentPage + 1)}
                      disabled={currentPage >= totalPages - 1}
                      className="flex items-center space-x-1 px-4 py-2 rounded-lg bg-white border border-gray-200 text-sm font-medium hover:bg-gray-50 transition disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <span>Next</span>
                      <ChevronRight size={16} />
                    </button>
                  </div>
                )}

                {/* Tile count info */}
                <div className="text-center mt-3 text-xs text-gray-400">
                  Showing {pageTiles.length} feed{pageTiles.length !== 1 ? 's' : ''} from {inProgressCandidates.length} live candidate{inProgressCandidates.length !== 1 ? 's' : ''}
                </div>
              </>
            )}

            {/* ── Enlarged Feed Modal ──────────────── */}
            {enlargedFeed && (() => {
              const gs = galleryStreams[enlargedFeed.token];
              const feedStream = gs?.[enlargedFeed.type] || null;
              const candidateInfo = inProgressCandidates.find(c => c.token === enlargedFeed.token);
              const candidateName = candidateInfo?.name || gs?.name || enlargedFeed.token;
              const feedLabel = enlargedFeed.type === 'screen' ? 'Screen' : 'Camera';
              const feedIcon = enlargedFeed.type === 'screen' ? <Monitor size={14} /> : <Video size={14} />;
              const objectFit = enlargedFeed.type === 'screen' ? 'object-contain' : 'object-cover';

              // Navigation: find current index in allTiles and enable prev/next
              const currentIdx = allTiles.findIndex(t => t.token === enlargedFeed.token && t.type === enlargedFeed.type);
              const hasPrev = currentIdx > 0;
              const hasNext = currentIdx < allTiles.length - 1;

              const goToPrev = (e) => {
                e.stopPropagation();
                if (hasPrev) {
                  const prev = allTiles[currentIdx - 1];
                  setEnlargedFeed({ token: prev.token, type: prev.type });
                }
              };
              const goToNext = (e) => {
                e.stopPropagation();
                if (hasNext) {
                  const next = allTiles[currentIdx + 1];
                  setEnlargedFeed({ token: next.token, type: next.type });
                }
              };

              return (
                <div
                  ref={enlargedModalRef}
                  className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
                  onClick={() => { if (document.fullscreenElement) document.exitFullscreen().catch(() => {}); setEnlargedFeed(null); }}
                >
                  <div className={`relative w-full mx-4 ${isFullscreen ? 'max-w-full h-full flex flex-col justify-center' : 'max-w-4xl'}`} onClick={e => e.stopPropagation()}>
                    {/* Toolbar */}
                    <div className={`flex items-center justify-between ${isFullscreen ? 'px-6 py-3' : 'mb-4'}`}>
                      <div className={isFullscreen ? '' : 'flex-1'}>
                        <div className="flex items-center space-x-3">
                          <div className="w-8 h-8 rounded-full bg-primary-600 flex items-center justify-center text-white text-sm font-bold">
                            {candidateName?.[0]?.toUpperCase() || '?'}
                          </div>
                          <div>
                            <h3 className="text-white text-lg font-bold">{candidateName}</h3>
                            <span className="text-gray-300 text-sm flex items-center space-x-1">
                              {feedIcon}
                              <span>{feedLabel} Feed</span>
                              {currentIdx >= 0 && <span className="text-gray-500 ml-2">({currentIdx + 1} / {allTiles.length})</span>}
                            </span>
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center space-x-2">
                        <button
                          onClick={toggleFullscreen}
                          className="p-2 bg-white/10 hover:bg-white/20 rounded-full transition"
                          title={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
                        >
                          {isFullscreen ? <Minimize2 size={20} className="text-white" /> : <Maximize2 size={20} className="text-white" />}
                        </button>
                        <button
                          onClick={() => { if (document.fullscreenElement) document.exitFullscreen().catch(() => {}); setEnlargedFeed(null); }}
                          className="p-2 bg-white/10 hover:bg-white/20 rounded-full transition"
                        >
                          <X size={20} className="text-white" />
                        </button>
                      </div>
                    </div>

                    {/* Single enlarged video */}
                    <div className={`relative ${isFullscreen ? 'flex-1 px-6 pb-6' : ''}`}>
                      <div className="relative bg-gray-900 rounded-xl overflow-hidden" style={{ aspectRatio: isFullscreen ? undefined : '16/9', height: isFullscreen ? '100%' : undefined }}>
                        <EnlargedVideo stream={feedStream} label={feedLabel} icon={feedIcon} objectFit={objectFit} />
                      </div>

                      {/* Prev / Next arrows */}
                      {hasPrev && (
                        <button
                          onClick={goToPrev}
                          className="absolute left-2 top-1/2 -translate-y-1/2 p-2 bg-black/50 hover:bg-black/70 rounded-full transition z-10"
                        >
                          <ChevronLeft size={24} className="text-white" />
                        </button>
                      )}
                      {hasNext && (
                        <button
                          onClick={goToNext}
                          className="absolute right-2 top-1/2 -translate-y-1/2 p-2 bg-black/50 hover:bg-black/70 rounded-full transition z-10"
                        >
                          <ChevronRight size={24} className="text-white" />
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              );
            })()}
          </div>
        );
      })()}
    </div>
  );
}
