import { useState, useCallback, useRef } from 'react';
import { Room, RoomEvent, LocalVideoTrack, LocalAudioTrack, Track } from 'livekit-client';

export default function useLiveKit() {
  const roomRef = useRef(null);
  const [isConnected, setIsConnected] = useState(false);

  const joinAsCandidate = useCallback(async (token) => {
    try {
      const room = new Room({
        adaptiveStream: true,
        dynacast: true,
      });

      roomRef.current = room;

      room.on(RoomEvent.Connected, () => {
        setIsConnected(true);
      });

      room.on(RoomEvent.Disconnected, () => {
        setIsConnected(false);
      });

      // Use the injected environment variable for the LiveKit URL
      await room.connect(import.meta.env.VITE_LIVEKIT_URL, token, {
        autoSubscribe: false,
      });

      return room;
    } catch (error) {
      console.error('Failed to join LiveKit room', error);
      throw error;
    }
  }, []);

  const publishCamera = useCallback(async (videoTrack, audioTrack) => {
    if (!roomRef.current) return;
    
    if (videoTrack) {
        const lvt = new LocalVideoTrack(videoTrack);
        await roomRef.current.localParticipant.publishTrack(lvt, { source: Track.Source.Camera });
    }
    
    if (audioTrack) {
        const lat = new LocalAudioTrack(audioTrack);
        await roomRef.current.localParticipant.publishTrack(lat, { source: Track.Source.Microphone });
    }
  }, []);

  const publishScreen = useCallback(async (screenVideoTrack) => {
    if (!roomRef.current || !screenVideoTrack) return;
    const lvt = new LocalVideoTrack(screenVideoTrack);
    await roomRef.current.localParticipant.publishTrack(lvt, { source: Track.Source.ScreenShare });
  }, []);

  const unpublishCamera = useCallback(async () => {
      if (!roomRef.current) return;
      const participant = roomRef.current.localParticipant;
      for (const pub of participant.getTracks()) {
          if (pub.source === Track.Source.Camera || pub.source === Track.Source.Microphone) {
              if (pub.track) participant.unpublishTrack(pub.track);
          }
      }
  }, []);

  const unpublishScreen = useCallback(async () => {
      if (!roomRef.current) return;
      const participant = roomRef.current.localParticipant;
      for (const pub of participant.getTracks()) {
          if (pub.source === Track.Source.ScreenShare) {
              if (pub.track) participant.unpublishTrack(pub.track);
          }
      }
  }, []);

  const leave = useCallback(async () => {
    if (roomRef.current) {
        await roomRef.current.disconnect();
        roomRef.current = null;
        setIsConnected(false);
    }
  }, []);

  return {
    joinAsCandidate,
    publishCamera,
    publishScreen,
    unpublishCamera,
    unpublishScreen,
    leave,
    isConnected
  };
}