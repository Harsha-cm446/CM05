/**
 * useToken — Fetch and cache Agora RTC tokens from the backend.
 *
 * Usage:
 *   const { getToken, loading, error } = useToken();
 *   const { token, appId } = await getToken(channel, uid);
 */
import { useState, useRef, useCallback } from 'react';
import api from '../services/api';

export default function useToken() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const cache = useRef({}); // key: "channel:uid" → { token, appId, expiresAt }

  const getToken = useCallback(async (channel, uid, role = 'publisher') => {
    const key = `${channel}:${uid}:${role}`;

    // Return cached token if still valid (with 60s buffer)
    const cached = cache.current[key];
    if (cached && cached.expiresAt > Date.now() / 1000 + 60) {
      return cached;
    }

    setLoading(true);
    setError(null);

    try {
      const res = await api.get('/agora/token', {
        params: { channel, uid, role },
      });
      const data = res.data;
      cache.current[key] = {
        token: data.token,
        appId: data.appId?.trim(),
        uid: data.uid,
        channel: data.channel,
        expiresAt: data.expiresAt,
      };
      return cache.current[key];
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Failed to fetch Agora token';
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
