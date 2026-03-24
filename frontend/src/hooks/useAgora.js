/**
 * useAgora — Agora RTC client management hook.
 *
 * Supports two modes:
 *   - HR (subscriber): joins channel, subscribes to all remote users, maps streams by UID
 *   - Candidate (publisher): joins channel, publishes camera + screen tracks
 *
 * UID Strategy:
 *   Each candidate uses two numeric UIDs:
 *     camUid = baseId * 10 + 1
 *     screenUid = baseId * 10 + 2
 *   This allows HR to parse the UID and map tracks to the correct candidate.
 */
import { useState, useRef, useCallback, useEffect } from 'react';
import AgoraRTC from 'agora-rtc-sdk-ng';

// Disable Agora's own logging in production
AgoraRTC.setLogLevel(import.meta.env.MODE === 'production' ? 4 : 1);

/**
 * Parse a numeric UID into candidateId and stream type.
 * uid % 10 === 1 → camera
 * uid % 10 === 2 → screen
 */
function parseUid(uid) {
  const numUid = Number(uid);
  const type = numUid % 10 === 2 ? 'screen' : 'cam';
  const candidateIndex = Math.floor(numUid / 10);
  return { candidateIndex, type };
}

/**
 * Generate a base ID from a candidate name/identifier.
 * Uses a simple hash to create a deterministic numeric base.
 */
export function generateBaseId(candidateId) {
  let hash = 0;
  const str = String(candidateId);
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
  }
  // Ensure positive and within Agora's UID range (avoid 0)
  return (Math.abs(hash) % 99999) + 1;
}

export default function useAgora() {
  // ── State ──────────────────────────────────────────
  const [connectionState, setConnectionState] = useState('DISCONNECTED');
  const [candidates, setCandidates] = useState({});
  // candidates shape: { [candidateIndex]: { cameraTrack, screenTrack, uidCam, uidScreen } }

  const [logs, setLogs] = useState([]);

  // ── Refs ───────────────────────────────────────────
  const clientRef = useRef(null);
  const localCameraTrackRef = useRef(null);
  const localScreenTrackRef = useRef(null);
  const joinedRef = useRef(false);

  // ── Logging ────────────────────────────────────────
  const addLog = useCallback((msg) => {
    const entry = `[${new Date().toLocaleTimeString()}] ${msg}`;
    console.log('[useAgora]', msg);
    setLogs((prev) => [...prev.slice(-99), entry]);
  }, []);

  // ── Initialize Agora Client ────────────────────────
  const getClient = useCallback(() => {
    if (!clientRef.current) {
      clientRef.current = AgoraRTC.createClient({ mode: 'rtc', codec: 'vp8' });
      addLog('Agora client created (mode=rtc, codec=vp8)');
    }
    return clientRef.current;
  }, [addLog]);

  // ── Event Handlers ─────────────────────────────────
  const setupEventHandlers = useCallback(() => {
    const client = getClient();

    client.on('connection-state-change', (curState, prevState) => {
      addLog(`Connection: ${prevState} → ${curState}`);
      setConnectionState(curState);
    });

    client.on('user-published', async (user, mediaType) => {
      const { candidateIndex, type } = parseUid(user.uid);
      addLog(`user-published: uid=${user.uid} candidate=${candidateIndex} type=${type} media=${mediaType}`);

      try {
        await client.subscribe(user, mediaType);
        addLog(`Subscribed to uid=${user.uid} ${mediaType}`);

        if (mediaType === 'video') {
          const videoTrack = user.videoTrack;
          setCandidates((prev) => {
            const existing = prev[candidateIndex] || {
              cameraTrack: null,
              screenTrack: null,
              uidCam: null,
              uidScreen: null,
            };

            if (type === 'cam') {
              return {
                ...prev,
                [candidateIndex]: {
                  ...existing,
                  cameraTrack: videoTrack,
                  uidCam: user.uid,
                },
              };
            } else {
              return {
                ...prev,
                [candidateIndex]: {
                  ...existing,
                  screenTrack: videoTrack,
                  uidScreen: user.uid,
                },
              };
            }
          });
        }

        if (mediaType === 'audio') {
          const audioTrack = user.audioTrack;
          if (audioTrack) {
            audioTrack.play();
            addLog(`Playing audio from uid=${user.uid}`);
          }
        }
      } catch (err) {
        addLog(`Subscribe error uid=${user.uid}: ${err.message}`);
      }
    });

    client.on('user-unpublished', (user, mediaType) => {
      const { candidateIndex, type } = parseUid(user.uid);
      addLog(`user-unpublished: uid=${user.uid} candidate=${candidateIndex} type=${type} media=${mediaType}`);

      if (mediaType === 'video') {
        setCandidates((prev) => {
          const existing = prev[candidateIndex];
          if (!existing) return prev;

          if (type === 'cam') {
            return {
              ...prev,
              [candidateIndex]: { ...existing, cameraTrack: null },
            };
          } else {
            return {
              ...prev,
              [candidateIndex]: { ...existing, screenTrack: null },
            };
          }
        });
      }
    });

    client.on('user-left', (user) => {
      const { candidateIndex, type } = parseUid(user.uid);
      addLog(`user-left: uid=${user.uid} candidate=${candidateIndex} type=${type}`);

      setCandidates((prev) => {
        const existing = prev[candidateIndex];
        if (!existing) return prev;

        const updated = { ...existing };
        if (type === 'cam') {
          updated.cameraTrack = null;
          updated.uidCam = null;
        } else {
          updated.screenTrack = null;
          updated.uidScreen = null;
        }

        // Remove candidate entirely if both UIDs have left
        if (!updated.uidCam && !updated.uidScreen) {
          const next = { ...prev };
          delete next[candidateIndex];
          return next;
        }

        return { ...prev, [candidateIndex]: updated };
      });
    });

    client.on('token-privilege-will-expire', () => {
      addLog('⚠️ Token expiring soon — renewal needed');
    });

    client.on('token-privilege-did-expire', () => {
      addLog('❌ Token expired — must rejoin');
      setConnectionState('DISCONNECTED');
    });
  }, [getClient, addLog]);

  // ── Join Channel (HR mode — subscribe only) ────────
  const joinAsHR = useCallback(
    async (appId, channel, token, uid) => {
      const client = getClient();
      setupEventHandlers();

      try {
        addLog(`Joining channel "${channel}" as HR (uid=${uid})...`);
        const safeAppId = "921218d596ef4db18072b5c4730ba6da"; // HARCODED FOR DEBUGGING
        addLog(`Using forced AppID override: ${safeAppId}`);
        await client.join(safeAppId, channel, token, uid);
        joinedRef.current = true;
        addLog(`✅ Joined channel "${channel}" successfully`);
        setConnectionState('CONNECTED');
      } catch (err) {
        addLog(`❌ Join failed: ${err.message}`);
        setConnectionState('DISCONNECTED');
        throw err;
      }
    },
    [getClient, setupEventHandlers, addLog]
  );

  // ── Join + Publish (Candidate mode) ────────────────
  const joinAsCandidate = useCallback(
    async (appId, channel, camToken, camUid, screenToken, screenUid) => {
      const client = getClient();
      setupEventHandlers();

      try {
        // Join with camera UID first
        addLog(`Joining channel "${channel}" as candidate cam (uid=${camUid})...`);
        const safeAppId = "921218d596ef4db18072b5c4730ba6da"; // HARCODED FOR DEBUGGING
        await client.join(safeAppId, channel, camToken, camUid);
        joinedRef.current = true;
        addLog(`✅ Joined channel "${channel}" with cam UID`);
        setConnectionState('CONNECTED');
      } catch (err) {
        addLog(`❌ Join failed: ${err.message}`);
        throw err;
      }
    },
    [getClient, setupEventHandlers, addLog]
  );

  // ── Publish Camera ─────────────────────────────────
  const publishCamera = useCallback(async (nativeVideoTrack, nativeAudioTrack = null) => {
    const client = getClient();
    if (!joinedRef.current) {
      addLog('Cannot publish camera — not joined');
      return null;
    }

    try {
      const tracksToPublish = [];
      
      const cameraTrack = AgoraRTC.createCustomVideoTrack({
        mediaStreamTrack: nativeVideoTrack,
        bitrateMax: 600,
      });
      tracksToPublish.push(cameraTrack);
      localCameraTrackRef.current = cameraTrack;

      if (nativeAudioTrack) {
        const audioTrack = AgoraRTC.createCustomAudioTrack({
          mediaStreamTrack: nativeAudioTrack,
        });
        tracksToPublish.push(audioTrack);
        // Store audio track inside localCameraTrackRef for unpublish purposes
        localCameraTrackRef.current = { video: cameraTrack, audio: audioTrack };
      }

      await client.publish(tracksToPublish);
      addLog('📹 Camera published');
      return cameraTrack;
    } catch (err) {
      addLog(`Camera publish error: ${err.message}`);
      return null;
    }
  }, [getClient, addLog]);

  // ── Publish Screen ─────────────────────────────────
  const publishScreen = useCallback(async (nativeVideoTrack) => {
    const client = getClient();
    if (!joinedRef.current) {
      addLog('Cannot publish screen — not joined');
      return null;
    }

    try {
      const screenTrack = AgoraRTC.createCustomVideoTrack({
        mediaStreamTrack: nativeVideoTrack,
        bitrateMax: 1500,
      });

      localScreenTrackRef.current = screenTrack;
      await client.publish([screenTrack]);
      addLog('🖥️ Screen published');

      return screenTrack;
    } catch (err) {
      addLog(`Screen publish error: ${err.message}`);
      return null;
    }
  }, [getClient, addLog]);

  // ── Unpublish ──────────────────────────────────────
  const unpublishCamera = useCallback(async () => {
    const client = getClient();
    if (localCameraTrackRef.current) {
      try {
        const tracks = localCameraTrackRef.current.audio 
          ? [localCameraTrackRef.current.video, localCameraTrackRef.current.audio]
          : [localCameraTrackRef.current];
          
        await client.unpublish(tracks);
        tracks.forEach(t => {
          t.stop();
          t.close();
        });
        localCameraTrackRef.current = null;
        addLog('Camera unpublished');
      } catch (err) {
        addLog(`Camera unpublish error: ${err.message}`);
      }
    }
  }, [getClient, addLog]);

  const unpublishScreen = useCallback(async () => {
    const client = getClient();
    if (localScreenTrackRef.current) {
      try {
        await client.unpublish([localScreenTrackRef.current]);
        localScreenTrackRef.current.stop();
        localScreenTrackRef.current.close();
        localScreenTrackRef.current = null;
        addLog('Screen unpublished');
      } catch (err) {
        addLog(`Screen unpublish error: ${err.message}`);
      }
    }
  }, [getClient, addLog]);

  // ── Leave ──────────────────────────────────────────
  const leave = useCallback(async () => {
    const client = getClient();

    // Cleanup local tracks
    if (localCameraTrackRef.current) {
      const tracks = localCameraTrackRef.current.audio 
        ? [localCameraTrackRef.current.video, localCameraTrackRef.current.audio]
        : [localCameraTrackRef.current];
      tracks.forEach(t => {
        t.stop();
        t.close();
      });
      localCameraTrackRef.current = null;
    }
    if (localScreenTrackRef.current) {
      localScreenTrackRef.current.stop();
      localScreenTrackRef.current.close();
      localScreenTrackRef.current = null;
    }

    if (joinedRef.current) {
      try {
        await client.leave();
        addLog('Left channel');
      } catch (err) {
        addLog(`Leave error: ${err.message}`);
      }
      joinedRef.current = false;
    }

    setCandidates({});
    setConnectionState('DISCONNECTED');
  }, [getClient, addLog]);

  // ── Cleanup on unmount ─────────────────────────────
  useEffect(() => {
    return () => {
      if (localCameraTrackRef.current) {
        const tracks = localCameraTrackRef.current.audio 
          ? [localCameraTrackRef.current.video, localCameraTrackRef.current.audio]
          : [localCameraTrackRef.current];
        tracks.forEach(t => {
          t.stop();
          t.close();
        });
      }
      if (localScreenTrackRef.current) {
        localScreenTrackRef.current.stop();
        localScreenTrackRef.current.close();
      }
      if (clientRef.current && joinedRef.current) {
        clientRef.current.leave().catch(() => {});
      }
    };
  }, []);

  return {
    candidates,
    connectionState,
    logs,
    joinAsHR,
    joinAsCandidate,
    publishCamera,
    publishScreen,
    unpublishCamera,
    unpublishScreen,
    leave,
    getClient,
  };
}
