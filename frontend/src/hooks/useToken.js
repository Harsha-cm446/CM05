/**
 * useToken — Fetch LiveKit tokens from the backend.
 *
 * Usage:
 *   const { getToken, loading, error } = useToken();
 *   const { token } = await getToken(user, room);
 */
import { useState, useRef, useCallback } from 'react';
import api from '../services/api';

export default function useToken() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const cache = useRef({}); // key: "room:user" → { token }

  const getToken = useCallback(async (room, user) => {
    const key = `${room}:${user}`;

    // Return cached token if exists (for demo purposes)
    const cached = cache.current[key];
    if (cached) {
      return cached;
    }

    setLoading(true);
    setError(null);

    try {
      const res = await api.get('/livekit/get-token', {
        params: { user, room },
      });
      const data = res.data;
      cache.current[key] = {
        token: data.token,
        room: data.room,
        user: data.user,
      };
      return cache.current[key];
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Failed to fetch LiveKit token';
      setError(msg);
      throw new Error(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  const clearCache = useCallback(() => {
    cache.current = {};
  }, []);

  return { getToken, loading, error, clearCache };
}
