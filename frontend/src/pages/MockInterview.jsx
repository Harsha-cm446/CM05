import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { mockAPI, WS_BASE } from '../services/api';
import toast from 'react-hot-toast';
import {
  Mic, MicOff, Camera, Send, Loader2, ArrowRight, Clock, Code,
  Volume2, VolumeX, Timer, AlertTriangle, CheckCircle, XCircle,
  Activity, TrendingUp, Eye, Zap, Target, Brain, Shield, UserX, MonitorX, LogOut,
} from 'lucide-react';
import {
  RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  Radar, ResponsiveContainer, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, BarChart, Bar,
} from 'recharts';

const ROLES = [
  'Software Engineer', 'Data Analyst', 'Product Manager', 'HR Manager',
  'DevOps Engineer', 'Frontend Developer', 'Backend Developer',
  'Machine Learning Engineer', 'Business Analyst', 'QA Engineer',
];

export default function MockInterview() {
  const navigate = useNavigate();
  const [phase, setPhase] = useState('setup'); // setup | face_registration | interview | round_transition | done | failed
  const [role, setRole] = useState('Software Engineer');
  const [difficulty, setDifficulty] = useState('medium');
  const [jobDescription, setJobDescription] = useState('');
  const [experienceLevel, setExperienceLevel] = useState('');
  const [durationMinutes, setDurationMinutes] = useState(20);
  const [githubUrl, setGithubUrl] = useState('');
  const [linkedinUrl, setLinkedinUrl] = useState('');
  const [sessionId, setSessionId] = useState(null);
  const [currentQuestion, setCurrentQuestion] = useState(null);
  const [currentRound, setCurrentRound] = useState('Technical');
  const [answer, setAnswer] = useState('');
  const [codeText, setCodeText] = useState('');
  const [codeLanguage, setCodeLanguage] = useState('python');
  const [evaluation, setEvaluation] = useState(null);
  const [loading, setLoading] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [cameraOn, setCameraOn] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [ttsEnabled, setTtsEnabled] = useState(true);
  const [timeStatus, setTimeStatus] = useState(null);
  const [questionNumber, setQuestionNumber] = useState(0);
  const [endReason, setEndReason] = useState('');
  const [techScore, setTechScore] = useState(null);
  const [permissionDenied, setPermissionDenied] = useState(false);
  const [permissionError, setPermissionError] = useState('');

  // Live metrics state
  const [liveMetrics, setLiveMetrics] = useState(null);
  const [metricsHistory, setMetricsHistory] = useState([]);
  const [scoreHistory, setScoreHistory] = useState([]);
  const [microSuggestion, setMicroSuggestion] = useState('');
  const [eyeTrackAlert, setEyeTrackAlert] = useState(false);
  const [gazeState, setGazeState] = useState('ATTENTIVE');
  const [multiPersonAlert, setMultiPersonAlert] = useState(false);

  // Face registration & enhanced proctoring
  const [faceRegPhase, setFaceRegPhase] = useState('idle');
  const [faceRegProgress, setFaceRegProgress] = useState(0);
  const [identityVerified, setIdentityVerified] = useState(null);
  const [identityMismatchAlert, setIdentityMismatchAlert] = useState(false);
  const [riskScore, setRiskScore] = useState(0);
  const [riskVerdict, setRiskVerdict] = useState('SAFE');
  const [suspiciousObjects, setSuspiciousObjects] = useState([]);
  const [faceAbsentAlert, setFaceAbsentAlert] = useState(false);

  // Proctoring state
  const [proctoringStats, setProctoringStats] = useState({
    gazeViolations: 0, multiPersonAlerts: 0, tabSwitches: 0, totalAwayTime: 0,
  });
  const [tabSwitchAlert, setTabSwitchAlert] = useState(false);
  const [showEndConfirm, setShowEndConfirm] = useState(false);
  const [endingInterview, setEndingInterview] = useState(false);
  const gazeWarningStartRef = useRef(null);

  // Live conversation mode refs
  const silenceTimerRef = useRef(null);
  const autoListenRef = useRef(false);       // whether to auto-listen after AI speaks
  const isSubmittingRef = useRef(false);      // prevent double-submit
  const answerRef = useRef('');               // track answer for silence-submit
  const submitRef = useRef(null);            // always-latest submit function ref
  const SILENCE_TIMEOUT = 5500;               // ms of silence before auto-submit

  const videoRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const streamRef = useRef(null);
  const chunksRef = useRef([]);
  const recognitionRef = useRef(null);
  const timeIntervalRef = useRef(null);
  const synthRef = useRef(window.speechSynthesis);

  // Vosk STT WebSocket refs
  const sttWsRef = useRef(null);
  const audioContextRef = useRef(null);
  const audioProcessorRef = useRef(null);
  const sttStreamRef = useRef(null);
  const [sttEngine, setSttEngine] = useState('');
  const voskAvailableRef = useRef(null); // null = unknown, true/false = checked

  // Keep answerRef in sync with answer state
  useEffect(() => { answerRef.current = answer; }, [answer]);

  // ── TTS: Speak question aloud, then auto-start listening ──
  const speakQuestion = useCallback((text) => {
    if (!ttsEnabled || !text) return;
    // Stop listening while AI speaks
    if (recognitionRef.current) {
      autoListenRef.current = false;
      if (recognitionRef.current.engine === 'vosk') {
        stopVoskStreaming();
      } else {
        recognitionRef.current.stop?.();
      }
      recognitionRef.current = null;
      setIsRecording(false);
    }
    synthRef.current.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 0.95;
    utterance.pitch = 1;
    utterance.onstart = () => setIsSpeaking(true);
    utterance.onend = () => {
      setIsSpeaking(false);
      // Auto-start listening after AI finishes speaking (live conversation)
      autoListenRef.current = true;
      setTimeout(() => {
        if (autoListenRef.current && !isSubmittingRef.current) {
          startSpeechRecognition();
        }
      }, 400); // brief pause before listening
    };
    utterance.onerror = () => {
      setIsSpeaking(false);
      // Still auto-listen even if TTS errors
      autoListenRef.current = true;
      startSpeechRecognition();
    };
    synthRef.current.speak(utterance);
  }, [ttsEnabled]);

  // ── Speech-to-text — Vosk server-side (primary) with Web Speech API fallback ──

  const connectSttWebSocket = useCallback(() => {
    if (sttWsRef.current && sttWsRef.current.readyState <= 1) return sttWsRef.current;

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const wsBase = WS_BASE || `${proto}://${window.location.hostname}:8000`;
    const ws = new WebSocket(`${wsBase}/ws/stt`);
    ws.binaryType = 'arraybuffer';

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'ready') {
          setSttEngine('vosk');
        } else if (data.type === 'partial' || data.type === 'final') {
          const newAnswer = data.full_text || data.text || '';
          if (newAnswer) {
            setAnswer(newAnswer);
            answerRef.current = newAnswer;
            if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
            silenceTimerRef.current = setTimeout(() => {
              if (answerRef.current.trim().length >= 5 && !isSubmittingRef.current) {
                autoListenRef.current = false;
                stopSpeechRecognition();
                if (submitRef.current) submitRef.current();
              }
            }, SILENCE_TIMEOUT);
          }
        }
      } catch (e) { console.error('STT WS parse error:', e); }
    };

    ws.onerror = () => console.warn('STT WebSocket error — will fall back to Web Speech API');
    ws.onclose = () => { sttWsRef.current = null; };
    sttWsRef.current = ws;
    return ws;
  }, []);

  const startVoskStreaming = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, sampleRate: 16000, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      sttStreamRef.current = stream;
      const audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
      audioContextRef.current = audioContext;
      const source = audioContext.createMediaStreamSource(stream);
      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      audioProcessorRef.current = processor;
      processor.onaudioprocess = (e) => {
        if (sttWsRef.current && sttWsRef.current.readyState === WebSocket.OPEN) {
          const float32 = e.inputBuffer.getChannelData(0);
          const int16 = new Int16Array(float32.length);
          for (let i = 0; i < float32.length; i++) {
            const s = Math.max(-1, Math.min(1, float32[i]));
            int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
          }
          sttWsRef.current.send(int16.buffer);
        }
      };
      source.connect(processor);
      processor.connect(audioContext.destination);
      return true;
    } catch (e) {
      console.error('Failed to start Vosk audio streaming:', e);
      return false;
    }
  }, []);

  const stopVoskStreaming = useCallback(() => {
    if (sttWsRef.current && sttWsRef.current.readyState === WebSocket.OPEN) {
      try { sttWsRef.current.send(JSON.stringify({ type: 'eof' })); } catch {}
    }
    if (audioProcessorRef.current) { audioProcessorRef.current.disconnect(); audioProcessorRef.current = null; }
    if (audioContextRef.current) { audioContextRef.current.close().catch(() => {}); audioContextRef.current = null; }
    if (sttStreamRef.current) { sttStreamRef.current.getTracks().forEach(t => t.stop()); sttStreamRef.current = null; }
  }, []);

  const startSpeechRecognition = useCallback(async () => {
    if (recognitionRef.current || isSubmittingRef.current) return;

    // Check if Vosk is available on the server (cached after first check)
    if (voskAvailableRef.current === null) {
      try {
        const API_BASE = import.meta.env.VITE_API_URL || '/api';
        const resp = await fetch(`${API_BASE}/stt/status`);
        if (resp.ok) {
          const data = await resp.json();
          voskAvailableRef.current = data.model_loaded === true;
        } else {
          voskAvailableRef.current = false;
        }
      } catch {
        voskAvailableRef.current = false;
      }
    }

    // Try Vosk WebSocket only if server has it ready
    if (voskAvailableRef.current) {
      const ws = connectSttWebSocket();
      const waitForWs = () => new Promise((resolve) => {
        if (ws.readyState === WebSocket.OPEN) return resolve(true);
        const timeout = setTimeout(() => resolve(false), 2000);
        ws.addEventListener('open', () => { clearTimeout(timeout); resolve(true); }, { once: true });
        ws.addEventListener('error', () => { clearTimeout(timeout); resolve(false); }, { once: true });
      });

      const wsReady = await waitForWs();
      if (wsReady) {
        const started = await startVoskStreaming();
        if (started) {
          try { ws.send(JSON.stringify({ type: 'reset' })); } catch {}
          recognitionRef.current = { engine: 'vosk' };
          setIsRecording(true);
          setSttEngine('vosk');
          if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
          silenceTimerRef.current = setTimeout(() => {
            if (answerRef.current.trim().length >= 5 && !isSubmittingRef.current) {
              autoListenRef.current = false;
              stopSpeechRecognition();
              if (submitRef.current) submitRef.current();
            }
          }, SILENCE_TIMEOUT);
          return;
        }
      }
    }

    // Fallback: Web Speech API
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      toast.error('Speech recognition not supported in this browser');
      return;
    }
    setSttEngine('web-speech');
    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    let finalTranscript = answerRef.current;

    const resetSilenceTimer = () => {
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = setTimeout(() => {
        if (answerRef.current.trim().length >= 5 && !isSubmittingRef.current) {
          autoListenRef.current = false;
          if (recognitionRef.current) {
            recognitionRef.current.stop?.();
            recognitionRef.current = null;
          }
          setIsRecording(false);
          if (submitRef.current) submitRef.current();
        }
      }, SILENCE_TIMEOUT);
    };

    recognition.onresult = (event) => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalTranscript += ' ' + transcript;
        } else {
          interim += transcript;
        }
      }
      const newAnswer = finalTranscript.trim() + (interim ? ' ' + interim : '');
      setAnswer(newAnswer);
      answerRef.current = newAnswer;
      resetSilenceTimer();
    };

    recognition.onerror = (event) => {
      if (event.error !== 'no-speech' && event.error !== 'aborted') {
        console.error('Speech recognition error:', event.error);
      }
    };

    recognition.onend = () => {
      setIsRecording(false);
      recognitionRef.current = null;
      if (autoListenRef.current && !isSubmittingRef.current) {
        setTimeout(() => {
          if (autoListenRef.current && !isSubmittingRef.current) {
            startSpeechRecognition();
          }
        }, 300);
      }
    };

    try {
      recognition.start();
      recognitionRef.current = recognition;
      setIsRecording(true);
      resetSilenceTimer();
    } catch (e) {
      console.error('Failed to start recognition:', e);
    }
  }, [connectSttWebSocket, startVoskStreaming]);

  const stopSpeechRecognition = useCallback(() => {
    autoListenRef.current = false;
    if (silenceTimerRef.current) { clearTimeout(silenceTimerRef.current); silenceTimerRef.current = null; }
    if (recognitionRef.current?.engine === 'vosk') {
      stopVoskStreaming();
      recognitionRef.current = null;
      setIsRecording(false);
      return;
    }
    if (recognitionRef.current) {
      recognitionRef.current.stop?.();
      recognitionRef.current = null;
    }
    setIsRecording(false);
  }, [stopVoskStreaming]);

  const toggleRecording = useCallback(() => {
    if (isRecording) {
      stopSpeechRecognition();
    } else {
      autoListenRef.current = true;
      startSpeechRecognition();
    }
  }, [isRecording, startSpeechRecognition, stopSpeechRecognition]);

  // ── Camera ─────────────────────────────────────────
  const toggleCamera = async () => {
    if (cameraOn) {
      streamRef.current?.getTracks().forEach((t) => t.stop());
      if (videoRef.current) videoRef.current.srcObject = null;
      setCameraOn(false);
    } else {
      try {
        const constraints = {
          video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } },
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        };
        const stream = await navigator.mediaDevices.getUserMedia(constraints);
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          try { await videoRef.current.play(); } catch (e) { console.log('Video autoplay handled:', e); }
        }
        setCameraOn(true);
      } catch {
        toast.error('Camera access denied');
      }
    }
  };

  // ── End Interview handler ─────────────────────
  const handleEndInterview = useCallback(async () => {
    if (endingInterview) return;
    setEndingInterview(true);
    try {
      stopSpeechRecognition();
      synthRef.current.cancel();
      await mockAPI.endInterview(sessionId);
      setEndReason('manually_ended');
      setPhase('done');
      toast.success('Interview ended successfully');
    } catch (err) {
      toast.error('Failed to end interview');
    } finally {
      setEndingInterview(false);
      setShowEndConfirm(false);
    }
  }, [sessionId, endingInterview, stopSpeechRecognition]);

  // ── Timer: local 1-second countdown + periodic server sync ──
  const localTickRef = useRef(null);
  useEffect(() => {
    if (phase !== 'interview' || !sessionId) return;

    // Sync with the server for authoritative time
    const pollTime = async () => {
      try {
        const res = await mockAPI.checkTime(sessionId);
        setTimeStatus(res.data);
        if (res.data.is_expired) {
          await mockAPI.endInterview(sessionId);
          setPhase('done');
          setEndReason('time_expired');
          toast('Time is up! Interview ended.');
        }
      } catch {}
    };

    // Local tick: decrement remaining_seconds every second for smooth UI
    localTickRef.current = setInterval(() => {
      setTimeStatus(prev => {
        if (!prev || prev.is_expired) return prev;
        const newSec = Math.max(0, (prev.remaining_seconds ?? 0) - 1);
        const newMin = newSec / 60;
        const elapsed = (prev.elapsed_minutes ?? 0) + 1 / 60;
        const totalDur = (prev.elapsed_minutes ?? 0) + (prev.remaining_minutes ?? 0);
        return {
          ...prev,
          remaining_seconds: newSec,
          remaining_minutes: Math.round(newMin * 10) / 10,
          elapsed_minutes: Math.round(elapsed * 10) / 10,
          is_expired: newSec <= 0,
          is_wrap_up: newSec > 0 && newMin < 2,
          progress_pct: Math.min(100, Math.round((elapsed / Math.max(totalDur, 1)) * 1000) / 10),
        };
      });
    }, 1000);

    // Server sync every 30 seconds (authoritative) + initial fetch
    timeIntervalRef.current = setInterval(pollTime, 30000);
    pollTime();

    return () => {
      clearInterval(localTickRef.current);
      clearInterval(timeIntervalRef.current);
    };
  }, [phase, sessionId]);

  // ── Speak new questions via TTS ────────────────────
  useEffect(() => {
    if (currentQuestion?.question && phase === 'interview') {
      speakQuestion(currentQuestion.question);
    }
  }, [currentQuestion?.question_id, phase, speakQuestion]);

  // ── Cleanup ────────────────────────────────────────
  useEffect(() => {
    return () => {
      autoListenRef.current = false;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      sttStreamRef.current?.getTracks().forEach((t) => t.stop());
      synthRef.current.cancel();
      if (recognitionRef.current?.engine === 'vosk') {
        if (audioProcessorRef.current) audioProcessorRef.current.disconnect();
        if (audioContextRef.current) audioContextRef.current.close().catch(() => {});
      } else if (recognitionRef.current) {
        recognitionRef.current.stop?.();
      }
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
      clearInterval(timeIntervalRef.current);
      clearInterval(localTickRef.current);
      if (sttWsRef.current) sttWsRef.current.close();
    };
  }, []);

  // ── Tab Switch / Visibility Detection (Proctoring) ──
  useEffect(() => {
    if (phase !== 'interview' || !sessionId) return;

    const handleVisibilityChange = () => {
      if (document.hidden) {
        // Tab switched away
        setTabSwitchAlert(true);
        setProctoringStats(prev => ({ ...prev, tabSwitches: prev.tabSwitches + 1 }));
        mockAPI.logViolation(sessionId, {
          violation_type: 'tab_switch',
          duration_sec: 0,
          details: 'Candidate switched tab or minimized window',
        }).catch(() => {});
        toast.error('Tab switch detected! Stay on the interview tab.', { duration: 4000 });
      } else {
        // Tab returned
        setTimeout(() => setTabSwitchAlert(false), 3000);
      }
    };

    const handleWindowBlur = () => {
      if (phase === 'interview' && sessionId) {
        setTabSwitchAlert(true);
        setProctoringStats(prev => ({ ...prev, tabSwitches: prev.tabSwitches + 1 }));
        mockAPI.logViolation(sessionId, {
          violation_type: 'tab_switch',
          duration_sec: 0,
          details: 'Window lost focus',
        }).catch(() => {});
      }
    };

    const handleWindowFocus = () => {
      setTimeout(() => setTabSwitchAlert(false), 3000);
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('blur', handleWindowBlur);
    window.addEventListener('focus', handleWindowFocus);

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('blur', handleWindowBlur);
      window.removeEventListener('focus', handleWindowFocus);
    };
  }, [phase, sessionId]);

  // ── Track gaze violations locally (backend proctoring_service already logs them) ──
  useEffect(() => {
    if (phase !== 'interview' || !sessionId) return;

    if (eyeTrackAlert && gazeState === 'WARNING_ACTIVE') {
      if (!gazeWarningStartRef.current) {
        gazeWarningStartRef.current = Date.now();
        setProctoringStats(prev => ({ ...prev, gazeViolations: prev.gazeViolations + 1 }));
      }
    } else if (gazeWarningStartRef.current) {
      const duration = (Date.now() - gazeWarningStartRef.current) / 1000;
      gazeWarningStartRef.current = null;
      setProctoringStats(prev => ({ ...prev, totalAwayTime: prev.totalAwayTime + duration }));
      // No need to call logViolation — proctoring_service.process_frame() already
      // logs gaze_away violations with richer data (confidence, risk points, thumbnails)
    }
  }, [eyeTrackAlert, gazeState, phase, sessionId]);

  // ── Track multi-person alerts locally (backend proctoring_service already logs them) ──
  useEffect(() => {
    if (phase !== 'interview' || !sessionId || !multiPersonAlert) return;
    setProctoringStats(prev => ({ ...prev, multiPersonAlerts: prev.multiPersonAlerts + 1 }));
    // No need to call logViolation — proctoring_service.process_frame() already
    // logs multiple_persons violations with richer data
  }, [multiPersonAlert, phase, sessionId]);

  // ── Re-attach camera stream when video element mounts ──
  useEffect(() => {
    if ((phase === 'interview' || phase === 'face_registration') && videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
    }
  }, [phase]);

  // ── Video frame capture helper (shared by both polling loops) ──
  const captureVideoFrame = useCallback(() => {
    if (!videoRef.current || !streamRef.current) return null;
    try {
      const video = videoRef.current;
      if (video.videoWidth === 0 || video.videoHeight === 0) return null;
      const canvas = document.createElement('canvas');
      canvas.width = 320;
      canvas.height = 240;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(video, 0, 0, 320, 240);
      return canvas.toDataURL('image/jpeg', 0.6).split(',')[1];
    } catch {
      return null;
    }
  }, []);

  // ── Unified polling: gaze + proctoring + live metrics (every 2s) ──
  // Merges the old separate gaze-only (2s) and live-metrics (3s) loops
  // into a single loop to avoid double-processing frames on the backend.
  useEffect(() => {
    if (phase !== 'interview' || !sessionId || !cameraOn) {
      if (phase !== 'interview') {
        setEyeTrackAlert(false);
        setGazeState('ATTENTIVE');
      }
      return;
    }

    const pollUnified = async () => {
      try {
        const videoFrame = captureVideoFrame();
        if (!videoFrame) return;
        // Always send partial answer text so backend can compute live metrics in one call
        const currentAnswer = answerRef.current || '';
        const { data } = await mockAPI.getPracticeMetrics(sessionId, currentAnswer, videoFrame);

        // Gaze FSM
        if (data.gaze) {
          console.log('[GAZE]', data.gaze.state, 'warn:', data.gaze.show_warning, 'score:', data.gaze.gaze_score, 'look%:', data.gaze.looking_pct);
          setGazeState(data.gaze.state || 'ATTENTIVE');
          setEyeTrackAlert(!!data.gaze.show_warning);
        }
        // Multi-person
        setMultiPersonAlert((data.person_count ?? 0) > 1);

        // Enhanced proctoring data
        // Only update identity when backend actually ran a verification check
        if (data.identity !== undefined && data.identity !== null) {
          setIdentityVerified(data.identity?.verified ?? null);
          setIdentityMismatchAlert(data.identity?.verified === false);
        }
        if (data.risk !== undefined) {
          setRiskScore(data.risk.score ?? 0);
          setRiskVerdict(data.risk.verdict ?? 'SAFE');
        }
        if (data.suspicious_objects) {
          setSuspiciousObjects(data.suspicious_objects);
        }
        if (data.face_absent !== undefined) {
          setFaceAbsentAlert(!!data.face_absent);
        }

        // Live metrics (only if there's enough text)
        if (currentAnswer.trim().length >= 5) {
          if (data.metrics) {
            setLiveMetrics(data.metrics);
            setMetricsHistory(prev => [
              ...prev.slice(-59),
              { time: prev.length + 1, confidence: data.metrics.confidence, stress: data.metrics.stress, clarity: data.metrics.speech_clarity },
            ]);
          }
          if (data.suggestion) setMicroSuggestion(data.suggestion);
        }
      } catch { /* ignore */ }
    };

    pollUnified();
    const interval = setInterval(pollUnified, 2000);
    return () => clearInterval(interval);
  }, [phase, sessionId, cameraOn, captureVideoFrame]);

  // ── Track scores for chart ─────────────────────────
  useEffect(() => {
    if (evaluation?.overall_score) {
      setScoreHistory(prev => [...prev, { q: `Q${questionNumber}`, score: Math.round(evaluation.overall_score) }]);
    }
  }, [evaluation?.overall_score]);

  // ── Metric helpers ─────────────────────────────────
  const getMetricColor = (v, inv = false) => { const x = inv ? 100 - v : v; return x >= 70 ? 'text-green-400' : x >= 45 ? 'text-yellow-500' : 'text-red-500'; };
  const getMetricBg = (v, inv = false) => { const x = inv ? 100 - v : v; return x >= 70 ? 'bg-green-500' : x >= 45 ? 'bg-yellow-500' : 'bg-red-500'; };

  // ── Derived state for interview phase ──────────────
  const isCoding = currentQuestion?.is_coding;

  const radarData = liveMetrics ? [
    { metric: 'Confidence', value: liveMetrics.confidence },
    { metric: 'Attention', value: liveMetrics.attention },
    { metric: 'Clarity', value: liveMetrics.speech_clarity },
    { metric: 'Stability', value: liveMetrics.emotional_stability },
    { metric: 'Completeness', value: liveMetrics.answer_completeness },
  ] : [];

  // ── Request permissions and start interview ────────
  const startInterview = async () => {
    setPermissionDenied(false);
    setPermissionError('');

    // Request camera + mic permissions first (mobile-friendly constraints)
    try {
      const constraints = {
        video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } },
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      };
      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        try { await videoRef.current.play(); } catch (e) { console.log('Video autoplay handled:', e); }
      }
      setCameraOn(true);
    } catch (err) {
      // On mobile, try audio-only if video fails
      try {
        const audioOnlyStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        streamRef.current = audioOnlyStream;
        setCameraOn(false);
        toast('Camera not available — continuing with audio only', { icon: '🎤' });
      } catch (audioErr) {
        setPermissionDenied(true);
        if (err.name === 'NotAllowedError') {
          setPermissionError('Camera and microphone access is required to start the interview. Please allow access in your browser settings and try again.');
        } else if (err.name === 'NotFoundError') {
          setPermissionError('No camera or microphone found. Please connect a camera and microphone to start the interview.');
        } else {
          setPermissionError(`Unable to access camera/microphone: ${err.message}. Please check your device settings.`);
        }
        return;
      }
    }

    setLoading(true);
    try {
      const res = await mockAPI.start({
        job_role: role,
        difficulty,
        job_description: jobDescription || undefined,
        experience_level: experienceLevel || undefined,
        duration_minutes: durationMinutes,
        github_url: githubUrl || undefined,
        linkedin_url: linkedinUrl || undefined,
      });
      setSessionId(res.data.session_id);
      setCurrentQuestion(res.data.question);
      setCurrentRound(res.data.round || 'Technical');
      setTimeStatus(res.data.time_status);
      setQuestionNumber(1);
      setEvaluation(null);
      setAnswer('');
      setCodeText('');

      // ── Face Registration Phase (blocks before questions) ──
      setFaceRegPhase('registering');
      setPhase('face_registration');
      let regCount = 0;
      const regTarget = 7;
      const doRegister = async () => {
        // Wait for video element to be ready (stream attached + producing frames)
        for (let w = 0; w < 15; w++) {
          await new Promise(r => setTimeout(r, 200));
          if (videoRef.current?.videoWidth > 0) break;
        }
        for (let i = 0; i < regTarget; i++) {
          await new Promise(r => setTimeout(r, 700));
          try {
            const frame = captureVideoFrame();
            if (!frame) { setFaceRegProgress(i + 1); continue; }
            const resp = await mockAPI.registerFace(res.data.session_id, frame);
            if (resp.data?.registered) regCount++;
            setFaceRegProgress(i + 1);
          } catch { setFaceRegProgress(i + 1); /* skip frame */ }
        }
        if (regCount >= 3) {
          setFaceRegPhase('done');
          toast.success('Face registered for identity verification', { duration: 3000 });
        } else {
          setFaceRegPhase('failed');
          toast('Face registration limited — proctoring will still run', { icon: '⚠️', duration: 4000 });
        }
        // Transition to interview phase — questions start now
        setPhase('interview');
      };
      await doRegister();
    } catch (err) {
      toast.error('Failed to start interview');
    } finally {
      setLoading(false);
    }
  };

  // ── Submit answer (called manually or by silence detection) ──
  const doSubmit = async (answerText) => {
    if (isSubmittingRef.current) return;
    isSubmittingRef.current = true;

    const isCoding = currentQuestion?.is_coding;
    const finalAnswer = answerText || answerRef.current;

    if (!isCoding && !finalAnswer.trim()) {
      isSubmittingRef.current = false;
      return; // Nothing to submit yet
    }
    if (isCoding && !codeText.trim()) {
      toast.error('Please write your code solution');
      isSubmittingRef.current = false;
      return;
    }

    stopSpeechRecognition();
    synthRef.current.cancel();
    setLoading(true);
    setEvaluation(null);

    try {
      const payload = {
        question_id: currentQuestion.question_id,
        answer_text: isCoding ? (finalAnswer || 'Code submitted') : finalAnswer,
      };
      if (isCoding) {
        payload.code_text = codeText;
        payload.code_language = codeLanguage;
      }

      const res = await mockAPI.submitAnswer(sessionId, payload);
      setEvaluation(res.data.evaluation);
      setTimeStatus(res.data.time_status);

      if (res.data.is_complete) {
        setEndReason(res.data.reason || 'completed');
        if (res.data.reason === 'technical_cutoff_not_met') {
          setTechScore(res.data.technical_score);
          setPhase('failed');
        } else {
          setPhase('done');
        }
      } else {
        // Check for round transition
        const newRound = res.data.round || currentRound;
        if (newRound !== currentRound) {
          setCurrentRound(newRound);
          setTechScore(res.data.technical_score || null);
          // Brief transition display
          setPhase('round_transition');
          setTimeout(() => {
            setPhase('interview');
            setCurrentQuestion(res.data.next_question);
            setQuestionNumber((prev) => prev + 1);
            setAnswer('');
            answerRef.current = '';
            setCodeText('');
            setEvaluation(null);
            setLiveMetrics(null);
            setMicroSuggestion('');
          }, 3000);
        } else {
          setTimeout(() => {
            setCurrentQuestion(res.data.next_question);
            setQuestionNumber((prev) => prev + 1);
            setAnswer('');
            answerRef.current = '';
            setCodeText('');
            setEvaluation(null);
            setLiveMetrics(null);
            setMicroSuggestion('');
          }, 3000);
        }
      }
    } catch (err) {
      toast.error('Failed to submit answer');
    } finally {
      setLoading(false);
      isSubmittingRef.current = false;
    }
  };

  // Auto-submit triggered by silence detection
  const submitAnswerAuto = useCallback(() => {
    doSubmit(answerRef.current);
  }, [currentQuestion, sessionId, codeText, codeLanguage, currentRound]);

  // Keep submitRef always pointing to the latest auto-submit function
  useEffect(() => { submitRef.current = submitAnswerAuto; }, [submitAnswerAuto]);

  // Manual submit (button click)
  const submitAnswer = () => doSubmit(answer);

  // ── Format time ────────────────────────────────────
  const formatTime = (timeStatus) => {
    // Use remaining_seconds if available for better precision
    const totalSec = timeStatus?.remaining_seconds ?? Math.round((timeStatus?.remaining_minutes ?? 0) * 60);
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  // ─── Setup Phase ───────────────────────────────────
  if (phase === 'setup') {
    return (
      <div className="max-w-2xl mx-auto px-4 py-12">
        <div className="slide-up">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-xl gradient-bg flex items-center justify-center shadow-sm pulse-glow">
              <Mic className="text-white" size={20} />
            </div>
            <h1 className="text-3xl font-bold text-gray-900">Mock Interview</h1>
          </div>
          <p className="text-gray-500 mb-8 ml-[52px]">Configure your practice session. AI will interview you using voice.</p>
        </div>

        <div className="bg-white/80 backdrop-blur-sm rounded-2xl shadow-sm border border-gray-100 p-8">
          <div className="space-y-6">
            <div>
              <label className="block text-sm font-semibold text-gray-700 mb-2">Target Role</label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className="w-full px-4 py-3 bg-gray-50/80 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-transparent outline-none transition-all"
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-semibold text-gray-700 mb-2">Experience Level</label>
              <select
                value={experienceLevel}
                onChange={(e) => setExperienceLevel(e.target.value)}
                className="w-full px-4 py-3 bg-gray-50/80 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-transparent outline-none transition-all"
              >
                <option value="">Select experience</option>
                <option value="Fresher (0-1 years)">Fresher (0-1 years)</option>
                <option value="Junior (1-3 years)">Junior (1-3 years)</option>
                <option value="Mid-level (3-5 years)">Mid-level (3-5 years)</option>
                <option value="Senior (5-8 years)">Senior (5-8 years)</option>
                <option value="Lead (8+ years)">Lead (8+ years)</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-semibold text-gray-700 mb-2">Job Description (Optional)</label>
              <textarea
                value={jobDescription}
                onChange={(e) => setJobDescription(e.target.value)}
                rows={4}
                placeholder="Paste the full Job Description here for JD-driven questions..."
                className="w-full px-4 py-3 bg-gray-50/80 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-transparent outline-none resize-none text-sm transition-all"
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-2">GitHub Profile (Optional)</label>
                <input
                  type="text"
                  value={githubUrl}
                  onChange={(e) => setGithubUrl(e.target.value)}
                  placeholder="github.com/username or username"
                  className="w-full px-4 py-3 bg-gray-50/80 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-transparent outline-none text-sm transition-all"
                />
                <p className="text-xs text-gray-400 mt-1">We'll analyze your repos to tailor questions to your stack</p>
              </div>
              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-2">LinkedIn Profile (Optional)</label>
                <input
                  type="text"
                  value={linkedinUrl}
                  onChange={(e) => setLinkedinUrl(e.target.value)}
                  placeholder="linkedin.com/in/username"
                  className="w-full px-4 py-3 bg-gray-50/80 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-transparent outline-none text-sm transition-all"
                />
                <p className="text-xs text-gray-400 mt-1">Links your professional profile for contextual questions</p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-2">Difficulty</label>
                <div className="grid grid-cols-3 gap-2">
                  {['easy', 'medium', 'hard'].map((d) => (
                    <button
                      key={d}
                      onClick={() => setDifficulty(d)}
                      className={`py-2.5 rounded-xl border-2 text-sm font-semibold capitalize transition-all ${
                        difficulty === d
                          ? d === 'easy' ? 'border-green-500 bg-green-50 text-green-700'
                            : d === 'hard' ? 'border-red-500 bg-red-50 text-red-700'
                            : 'border-primary-500 bg-primary-50 text-primary-700'
                          : 'border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50'
                      }`}
                    >
                      {d}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="block text-sm font-semibold text-gray-700 mb-2">Duration</label>
                <select
                  value={durationMinutes}
                  onChange={(e) => setDurationMinutes(Number(e.target.value))}
                  className="w-full px-4 py-3 bg-gray-50/80 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-transparent outline-none transition-all"
                >
                  {[10, 15, 20, 30, 45, 60].map((m) => (
                    <option key={m} value={m}>{m} minutes</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="bg-gradient-to-r from-blue-50 to-primary-50 border border-blue-200/60 rounded-xl p-5 text-sm text-blue-800">
              <p className="font-semibold mb-1.5 flex items-center gap-2">
                <span className="w-6 h-6 bg-blue-100 rounded-full flex items-center justify-center text-xs">🎤</span>
                Voice-Based Interview
              </p>
              <p className="text-blue-700/80">The AI will ask questions using text-to-speech. Answer using your microphone — no typing needed except for coding questions. Camera captures your video for confidence analysis.</p>
            </div>

            {permissionDenied && (
              <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-800 flex items-start gap-3">
                <AlertTriangle size={20} className="text-red-500 mt-0.5 shrink-0" />
                <div>
                  <p className="font-semibold mb-1">Permission Required</p>
                  <p>{permissionError}</p>
                </div>
              </div>
            )}

            <button
              onClick={startInterview}
              disabled={loading}
              className="w-full gradient-bg text-white py-3.5 rounded-xl font-semibold flex items-center justify-center gap-2 hover:opacity-90 transition-all disabled:opacity-50 shadow-md hover:shadow-lg"
            >
              {loading ? <span className="inline-block w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" /> : <ArrowRight size={20} />}
              <span>{loading ? 'Preparing...' : 'Start Interview'}</span>
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ─── Face Registration Phase ───────────────────────
  if (phase === 'face_registration') {
    return (
      <div className="max-w-2xl mx-auto px-4 py-12 text-center slide-up">
        <div className="bg-white/80 backdrop-blur-sm rounded-2xl shadow-xl border border-gray-100 p-12">
          <div className="w-20 h-20 bg-blue-100 rounded-2xl flex items-center justify-center mx-auto mb-5">
            <Shield size={40} className="text-blue-500" />
          </div>
          <h1 className="text-3xl font-bold text-gray-900 mb-2">Face Registration</h1>
          <p className="text-gray-500 mb-6">
            Please look directly at the camera. We're capturing your face for identity verification during the interview.
          </p>

          {/* Camera preview */}
          <div className="relative w-64 h-48 mx-auto mb-6 rounded-xl overflow-hidden border-2 border-blue-200 bg-black">
            <video ref={videoRef} autoPlay playsInline muted className="w-full h-full object-cover" />
          </div>

          {/* Progress bar */}
          <div className="w-full max-w-xs mx-auto mb-4">
            <div className="flex justify-between text-sm text-gray-500 mb-1">
              <span>Capturing faces...</span>
              <span>{faceRegProgress}/7</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2.5">
              <div
                className="bg-blue-500 h-2.5 rounded-full transition-all duration-300"
                style={{ width: `${(faceRegProgress / 7) * 100}%` }}
              />
            </div>
          </div>

          <p className="text-sm text-gray-400">
            {faceRegPhase === 'registering' ? 'Please hold still and look at the camera...' :
             faceRegPhase === 'done' ? '✅ Face registered successfully!' :
             faceRegPhase === 'failed' ? '⚠️ Limited registration — proceeding with available data' : ''}
          </p>

          <div className="mt-4">
            <Loader2 className="animate-spin mx-auto text-blue-500" size={24} />
          </div>
        </div>
      </div>
    );
  }

  // ─── Round Transition ──────────────────────────────
  if (phase === 'round_transition') {
    return (
      <div className="max-w-2xl mx-auto px-4 py-12 text-center slide-up">
        <div className="bg-white/80 backdrop-blur-sm rounded-2xl shadow-xl border border-gray-100 p-12">
          <div className="w-20 h-20 bg-green-100 rounded-2xl flex items-center justify-center mx-auto mb-5">
            <CheckCircle size={40} className="text-green-500" />
          </div>
          <h1 className="text-3xl font-bold text-gray-900 mb-2">Technical Round Passed!</h1>
          <p className="text-gray-500 mb-4">
            Score: <span className="font-bold text-green-600 text-lg">{techScore}%</span> (Cutoff: 70%)
          </p>
          <p className="text-lg text-primary-600 font-semibold">Proceeding to HR Round...</p>
          <span className="inline-block w-8 h-8 border-3 border-primary-200 border-t-primary-600 rounded-full animate-spin mt-5" />
        </div>
      </div>
    );
  }

  // ─── Failed (Technical cutoff not met) ─────────────
  if (phase === 'failed') {
    return (
      <div className="max-w-2xl mx-auto px-4 py-12 text-center slide-up">
        <div className="bg-white/80 backdrop-blur-sm rounded-2xl shadow-xl border border-gray-100 p-12">
          <div className="w-20 h-20 bg-red-100 rounded-2xl flex items-center justify-center mx-auto mb-5">
            <XCircle size={40} className="text-red-500" />
          </div>
          <h1 className="text-3xl font-bold text-gray-900 mb-2">Interview Ended</h1>
          <p className="text-gray-500 mb-4">
            Technical Round Score: <span className="font-bold text-red-600 text-lg">{techScore}%</span>
          </p>
          <p className="text-gray-600 mb-8">
            Your technical score did not meet the 70% cutoff required to proceed to the HR round.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <button
              onClick={() => navigate(`/report/${sessionId}`)}
              className="gradient-bg text-white px-8 py-3 rounded-xl font-semibold hover:opacity-90 transition-all shadow-md"
            >
              View Report
            </button>
            <button
              onClick={() => { setPhase('setup'); setSessionId(null); setCurrentQuestion(null); }}
              className="border-2 border-gray-200 text-gray-700 px-8 py-3 rounded-xl font-semibold hover:bg-gray-50 transition-all"
            >
              Try Again
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ─── Done Phase ────────────────────────────────────
  if (phase === 'done') {
    return (
      <div className="max-w-2xl mx-auto px-4 py-12 text-center slide-up">
        <div className="bg-white/80 backdrop-blur-sm rounded-2xl shadow-xl border border-gray-100 p-12">
          <div className="text-6xl mb-5">🎉</div>
          <h1 className="text-3xl font-bold text-gray-900 mb-2">Interview Complete!</h1>
          <p className="text-gray-500 mb-2">
            {endReason === 'time_expired'
              ? 'Time expired. Your answers have been recorded.'
              : endReason === 'manually_ended'
              ? 'You ended the interview early. Your answers have been saved.'
              : 'Great job! View your detailed performance report.'}
          </p>
          <p className="text-sm text-gray-400 mb-8">
            Rounds completed: Technical {currentRound === 'HR' ? '+ HR' : 'only'}
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <button
              onClick={() => navigate(`/report/${sessionId}`)}
              className="gradient-bg text-white px-8 py-3 rounded-xl font-semibold hover:opacity-90 transition-all shadow-md"
            >
              View Report
            </button>
            <button
              onClick={() => { setPhase('setup'); setSessionId(null); setCurrentQuestion(null); }}
              className="border-2 border-gray-200 text-gray-700 px-8 py-3 rounded-xl font-semibold hover:bg-gray-50 transition-all"
            >
              Practice Again
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ─── Interview Phase ───────────────────────────────
  return (
    <div className="flex h-screen overflow-hidden">
    {/* ── Live Metrics Sidebar ─────────────────────── */}
    <div className="w-72 bg-gray-900 text-white border-r border-gray-800 p-4 overflow-y-auto flex-shrink-0 hidden lg:block">
      <h3 className="font-semibold mb-4 flex items-center gap-2 text-sm">
        <Activity className="text-purple-400" size={16} />
        Live Metrics
      </h3>

      {!liveMetrics ? (
        <div className="text-center py-8">
          <Brain className="mx-auto text-gray-600 mb-3" size={32} />
          <p className="text-xs text-gray-500">Start speaking your answer to see live metrics</p>
          <p className="text-[10px] text-gray-600 mt-1">Metrics update in real-time as you respond</p>
        </div>
      ) : (
      <>
      {/* Metric Bars */}
      <div className="space-y-2.5 mb-5">
        {[
          { label: 'Confidence', key: 'confidence', icon: <TrendingUp size={12} /> },
          { label: 'Stress', key: 'stress', icon: <AlertTriangle size={12} />, inv: true },
          { label: 'Attention', key: 'attention', icon: <Eye size={12} /> },
          { label: 'Stability', key: 'emotional_stability', icon: <Activity size={12} /> },
          { label: 'Clarity', key: 'speech_clarity', icon: <Zap size={12} /> },
          { label: 'Completeness', key: 'answer_completeness', icon: <Target size={12} /> },
        ].map(m => (
          <div key={m.key}>
            <div className="flex items-center justify-between mb-0.5">
              <span className="text-[10px] text-gray-400 flex items-center gap-1">{m.icon} {m.label}</span>
              <span className={`text-[10px] font-bold ${getMetricColor(liveMetrics[m.key], m.inv)}`}>{Math.round(liveMetrics[m.key])}%</span>
            </div>
            <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
              <div className={`h-full rounded-full transition-all duration-700 ${getMetricBg(liveMetrics[m.key], m.inv)}`} style={{ width: `${liveMetrics[m.key]}%` }} />
            </div>
          </div>
        ))}
      </div>

      {/* Micro-suggestion */}
      {microSuggestion && (
        <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-2 mb-4">
          <p className="text-[10px] text-yellow-200 flex items-start gap-1"><Zap size={10} className="mt-0.5 shrink-0 text-yellow-400" />{microSuggestion}</p>
        </div>
      )}

      {/* Radar */}
      <div className="bg-gray-800/60 rounded-lg p-2 mb-4">
        <p className="text-[10px] text-gray-500 mb-1">Performance Radar</p>
        <ResponsiveContainer width="100%" height={160}>
          <RadarChart data={radarData}>
            <PolarGrid stroke="#374151" />
            <PolarAngleAxis dataKey="metric" tick={{ fill: '#9CA3AF', fontSize: 8 }} />
            <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
            <Radar dataKey="value" stroke="#a855f7" fill="#a855f7" fillOpacity={0.2} strokeWidth={1.5} />
          </RadarChart>
        </ResponsiveContainer>
      </div>

      {/* Trend line */}
      {metricsHistory.length > 3 && (
        <div className="bg-gray-800/60 rounded-lg p-2 mb-4">
          <p className="text-[10px] text-gray-500 mb-1">Trend</p>
          <ResponsiveContainer width="100%" height={100}>
            <LineChart data={metricsHistory.slice(-30)}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="time" tick={false} />
              <YAxis domain={[0, 100]} tick={{ fill: '#6B7280', fontSize: 8 }} />
              <Tooltip contentStyle={{ backgroundColor: '#1F2937', border: 'none', borderRadius: '8px', fontSize: '10px' }} />
              <Line type="monotone" dataKey="confidence" stroke="#22c55e" dot={false} strokeWidth={1.5} />
              <Line type="monotone" dataKey="stress" stroke="#ef4444" dot={false} strokeWidth={1.5} />
              <Line type="monotone" dataKey="clarity" stroke="#3b82f6" dot={false} strokeWidth={1.5} />
            </LineChart>
          </ResponsiveContainer>
          <div className="flex gap-2 mt-1 justify-center">
            <span className="text-[8px] text-green-400">● Confidence</span>
            <span className="text-[8px] text-red-400">● Stress</span>
            <span className="text-[8px] text-blue-400">● Clarity</span>
          </div>
        </div>
      )}

      {/* Score history */}
      {scoreHistory.length > 0 && (
        <div className="bg-gray-800/60 rounded-lg p-2">
          <p className="text-[10px] text-gray-500 mb-1">Answer Scores</p>
          <ResponsiveContainer width="100%" height={80}>
            <BarChart data={scoreHistory}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="q" tick={{ fill: '#6B7280', fontSize: 8 }} />
              <YAxis domain={[0, 100]} tick={{ fill: '#6B7280', fontSize: 8 }} />
              <Bar dataKey="score" fill="#a855f7" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      </>
      )}

      {/* ── Proctoring Panel ─────────────────────── */}
      <div className="mt-4 border-t border-gray-700 pt-4">
        <h3 className="font-semibold mb-3 flex items-center gap-2 text-sm">
          <Shield className="text-cyan-400" size={14} />
          Proctoring
        </h3>
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-gray-400 flex items-center gap-1"><Eye size={10} /> Gaze Violations</span>
            <span className={`text-[10px] font-bold ${proctoringStats.gazeViolations === 0 ? 'text-green-400' : proctoringStats.gazeViolations < 5 ? 'text-yellow-400' : 'text-red-400'}`}>
              {proctoringStats.gazeViolations}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-gray-400 flex items-center gap-1"><UserX size={10} /> Multi-Person</span>
            <span className={`text-[10px] font-bold ${proctoringStats.multiPersonAlerts === 0 ? 'text-green-400' : 'text-red-400'}`}>
              {proctoringStats.multiPersonAlerts}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-gray-400 flex items-center gap-1"><MonitorX size={10} /> Tab Switches</span>
            <span className={`text-[10px] font-bold ${proctoringStats.tabSwitches === 0 ? 'text-green-400' : proctoringStats.tabSwitches < 3 ? 'text-yellow-400' : 'text-red-400'}`}>
              {proctoringStats.tabSwitches}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-gray-400 flex items-center gap-1"><Clock size={10} /> Away Time</span>
            <span className="text-[10px] font-bold text-gray-300">
              {Math.round(proctoringStats.totalAwayTime)}s
            </span>
          </div>
          {/* Integrity indicator */}
          {(() => {
            const score = Math.max(0, 100 - (proctoringStats.gazeViolations * 3) - (proctoringStats.multiPersonAlerts * 15) - (proctoringStats.tabSwitches * 10) - (proctoringStats.totalAwayTime * 0.5));
            return (
              <div className="mt-2 bg-gray-800/60 rounded-lg p-2">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] text-gray-400">Integrity Score</span>
                  <span className={`text-xs font-bold ${score >= 80 ? 'text-green-400' : score >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>
                    {Math.round(score)}%
                  </span>
                </div>
                <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
                  <div className={`h-full rounded-full transition-all duration-500 ${score >= 80 ? 'bg-green-500' : score >= 50 ? 'bg-yellow-500' : 'bg-red-500'}`} style={{ width: `${score}%` }} />
                </div>
              </div>
            );
          })()}
          {/* Identity & Risk */}
          <div className="flex items-center justify-between mt-2">
            <span className="text-[10px] text-gray-400 flex items-center gap-1"><Shield size={10} /> Identity</span>
            <span className={`text-[10px] font-bold ${identityVerified === null ? 'text-gray-500' : identityVerified ? 'text-green-400' : 'text-red-400'}`}>
              {identityVerified === null ? 'Pending' : identityVerified ? 'Verified' : 'Mismatch!'}
            </span>
          </div>
          {suspiciousObjects.length > 0 && (
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-gray-400 flex items-center gap-1"><AlertTriangle size={10} /> Objects</span>
              <span className="text-[10px] font-bold text-orange-400">{suspiciousObjects.join(', ')}</span>
            </div>
          )}
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-gray-400 flex items-center gap-1"><Shield size={10} /> Risk</span>
            <span className={`text-[10px] font-bold ${riskVerdict === 'SAFE' ? 'text-green-400' : riskVerdict === 'SUSPICIOUS' ? 'text-yellow-400' : 'text-red-400'}`}>
              {riskVerdict} ({riskScore})
            </span>
          </div>
        </div>
      </div>
    </div>

    {/* ── Main Interview Content ───────────────────── */}
    <div className="flex-1 overflow-y-auto px-4 py-6">
    <div className="max-w-5xl mx-auto">
      {/* Top bar: Round + Timer */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center space-x-3">
          <span className={`px-4 py-1.5 rounded-full text-sm font-semibold ${
            currentRound === 'Technical'
              ? 'bg-blue-100 text-blue-700'
              : 'bg-purple-100 text-purple-700'
          }`}>
            {currentRound === 'Technical' ? '🔧 Technical Round' : '🤝 HR Round'}
          </span>
          <span className="text-sm text-gray-500">Question #{questionNumber}</span>
          <span className={`capitalize px-3 py-1 rounded-full text-xs font-medium ${
            currentQuestion?.difficulty === 'hard' ? 'bg-red-100 text-red-700' :
            currentQuestion?.difficulty === 'easy' ? 'bg-green-100 text-green-700' :
            'bg-yellow-100 text-yellow-700'
          }`}>
            {currentQuestion?.difficulty}
          </span>
        </div>

        <div className="flex items-center space-x-4">
          {/* TTS toggle */}
          <button
            onClick={() => { setTtsEnabled(!ttsEnabled); synthRef.current.cancel(); }}
            className={`p-2 rounded-lg ${ttsEnabled ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}
            title={ttsEnabled ? 'TTS On' : 'TTS Off'}
          >
            {ttsEnabled ? <Volume2 size={18} /> : <VolumeX size={18} />}
          </button>

          {/* Timer */}
          {timeStatus && (
            <div className={`flex items-center space-x-2 px-4 py-2 rounded-xl text-sm font-mono font-semibold ${
              timeStatus.remaining_minutes < 2 ? 'bg-red-100 text-red-700 animate-pulse' :
              timeStatus.remaining_minutes < 5 ? 'bg-yellow-100 text-yellow-700' :
              'bg-gray-100 text-gray-700'
            }`}>
              <Timer size={16} />
              <span>{formatTime(timeStatus)} left</span>
            </div>
          )}

          {/* End Interview */}
          <button
            onClick={() => setShowEndConfirm(true)}
            className="flex items-center space-x-1.5 px-4 py-2 rounded-xl text-sm font-semibold bg-red-50 text-red-600 hover:bg-red-100 transition"
            title="End Interview"
          >
            <LogOut size={16} />
            <span className="hidden sm:inline">End Interview</span>
          </button>
        </div>
      </div>

      {/* End Interview Confirmation Modal */}
      {showEndConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-2xl border border-gray-200 p-8 max-w-md w-full mx-4 slide-up">
            <div className="text-center">
              <div className="w-14 h-14 rounded-full bg-red-100 flex items-center justify-center mx-auto mb-4">
                <LogOut className="text-red-600" size={28} />
              </div>
              <h3 className="text-xl font-bold text-gray-900 mb-2">End Interview?</h3>
              <p className="text-gray-500 text-sm mb-6">
                Are you sure you want to end the interview now? Your answers so far will be saved and evaluated.
              </p>
              <div className="flex gap-3">
                <button
                  onClick={() => setShowEndConfirm(false)}
                  className="flex-1 px-4 py-2.5 rounded-xl border-2 border-gray-200 text-gray-700 font-semibold hover:bg-gray-50 transition"
                  disabled={endingInterview}
                >
                  Continue Interview
                </button>
                <button
                  onClick={handleEndInterview}
                  disabled={endingInterview}
                  className="flex-1 px-4 py-2.5 rounded-xl bg-red-600 text-white font-semibold hover:bg-red-700 transition flex items-center justify-center gap-2 disabled:opacity-50"
                >
                  {endingInterview ? <Loader2 size={16} className="animate-spin" /> : <LogOut size={16} />}
                  {endingInterview ? 'Ending...' : 'End Now'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Time progress bar */}
      {timeStatus && (
        <div className="w-full bg-gray-200 rounded-full h-1.5 mb-6">
          <div
            className={`h-1.5 rounded-full transition-all ${
              timeStatus.progress_pct > 80 ? 'bg-red-500' :
              timeStatus.progress_pct > 60 ? 'bg-yellow-500' : 'bg-green-500'
            }`}
            style={{ width: `${timeStatus.progress_pct}%` }}
          />
        </div>
      )}

      {/* Wrap-up warning */}
      {currentQuestion?.is_wrap_up && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 mb-4 flex items-center space-x-2 text-sm text-yellow-800">
          <AlertTriangle size={16} />
          <span>Less than 2 minutes remaining. This is your final question.</span>
        </div>
      )}

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Camera feed + Controls */}
        <div className="lg:col-span-1">
          <div className="bg-black rounded-2xl overflow-hidden aspect-[4/3] relative">
            <video ref={videoRef} autoPlay muted playsInline className="w-full h-full object-cover" />
            {!cameraOn && (
              <div className="absolute inset-0 flex items-center justify-center bg-gray-800">
                <Camera className="text-gray-500" size={48} />
              </div>
            )}
            {isSpeaking && (
              <div className="absolute top-3 left-3 bg-green-500/90 text-white px-3 py-1 rounded-full text-xs font-medium flex items-center space-x-1">
                <Volume2 size={12} className="animate-pulse" />
                <span>AI Speaking...</span>
              </div>
            )}
            {eyeTrackAlert && !isSpeaking && (
              <div className="absolute inset-0 flex items-center justify-center bg-red-900/40 backdrop-blur-[2px] animate-pulse">
                <div className="bg-red-600/90 text-white px-4 py-2 rounded-xl text-sm font-semibold flex items-center space-x-2 shadow-lg">
                  <Eye size={18} />
                  <span>Please look at the screen</span>
                </div>
              </div>
            )}
            {gazeState === 'RECOVERING' && !isSpeaking && (
              <div className="absolute top-3 right-3 bg-yellow-500/90 text-white px-3 py-1 rounded-full text-xs font-medium flex items-center space-x-1 transition-opacity">
                <Eye size={12} />
                <span>Refocusing...</span>
              </div>
            )}
            {multiPersonAlert && (
              <div className="absolute bottom-3 left-3 right-3 flex items-center justify-center">
                <div className="bg-orange-600/95 text-white px-4 py-2 rounded-xl text-sm font-semibold flex items-center space-x-2 shadow-lg">
                  <AlertTriangle size={18} />
                  <span>Multiple persons detected — only the candidate should be visible</span>
                </div>
              </div>
            )}
            {tabSwitchAlert && (
              <div className="absolute inset-0 flex items-center justify-center bg-purple-900/50 backdrop-blur-[2px]">
                <div className="bg-purple-600/95 text-white px-4 py-2 rounded-xl text-sm font-semibold flex items-center space-x-2 shadow-lg animate-pulse">
                  <MonitorX size={18} />
                  <span>Tab switch detected!</span>
                </div>
              </div>
            )}
            {identityMismatchAlert && (
              <div className="absolute top-3 left-3 right-3 flex items-center justify-center">
                <div className="bg-red-600/95 text-white px-4 py-1.5 rounded-xl text-xs font-semibold flex items-center space-x-2 animate-pulse shadow-lg">
                  <Shield size={14} />
                  <span>Person change detected — different person identified!</span>
                </div>
              </div>
            )}
            {faceAbsentAlert && !eyeTrackAlert && (
              <div className="absolute bottom-3 left-3 right-3 flex items-center justify-center">
                <div className="bg-yellow-500/90 text-white px-4 py-1.5 rounded-xl text-xs font-semibold flex items-center space-x-2 animate-pulse shadow-lg">
                  <AlertTriangle size={14} />
                  <span>No face detected</span>
                </div>
              </div>
            )}
            {suspiciousObjects.length > 0 && (
              <div className="absolute top-3 right-3">
                <div className="bg-orange-600/90 text-white px-2 py-1 rounded-lg text-[10px] font-semibold">
                  ⚠ {suspiciousObjects.map(o => typeof o === 'string' ? o : (o.type || 'object').replace('_', ' ')).join(', ')} detected
                </div>
              </div>
            )}
            {faceRegPhase === 'registering' && (
              <div className="absolute inset-0 bg-black/50 flex items-center justify-center rounded-2xl">
                <div className="bg-white rounded-xl p-4 text-center shadow-lg">
                  <Loader2 className="animate-spin mx-auto mb-2 text-cyan-600" size={24} />
                  <p className="text-sm font-semibold text-gray-800">Registering face...</p>
                  <p className="text-xs text-gray-500 mt-1">Frame {faceRegProgress}/7</p>
                  <div className="mt-2 h-1.5 bg-gray-200 rounded-full overflow-hidden w-28 mx-auto">
                    <div className="h-full bg-cyan-500 rounded-full transition-all" style={{ width: `${(faceRegProgress / 7) * 100}%` }} />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* AI Interviewer card */}
          <div className="mt-4 bg-white rounded-xl border border-gray-100 p-4">
            <div className="flex items-center space-x-3">
              <div className={`w-10 h-10 rounded-full flex items-center justify-center text-white font-bold text-lg ${
                isSpeaking ? 'bg-green-500 animate-pulse' : 'gradient-bg'
              }`}>
                AI
              </div>
              <div>
                <p className="font-medium text-gray-900 text-sm">AI Interviewer</p>
                <p className="text-xs text-green-600 flex items-center">
                  <span className="w-2 h-2 bg-green-500 rounded-full mr-1"></span>
                  {isSpeaking ? 'Speaking...' : 'Listening'}
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Question & Answer */}
        <div className="lg:col-span-2 space-y-5">
          {/* Question */}
          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
            <div className="flex items-start space-x-3">
              <div className="w-8 h-8 rounded-full gradient-bg flex items-center justify-center text-white font-bold text-xs flex-shrink-0 mt-0.5">
                AI
              </div>
              <div className="flex-1">
                <div className="flex items-center justify-between mb-1">
                  <h2 className="text-lg font-semibold text-gray-900">Question:</h2>
                  {isCoding && (
                    <span className="flex items-center space-x-1 px-3 py-1 bg-orange-100 text-orange-700 rounded-full text-xs font-medium">
                      <Code size={12} />
                      <span>Coding Question</span>
                    </span>
                  )}
                </div>
                <p className="text-gray-700 text-lg leading-relaxed">{currentQuestion?.question}</p>
              </div>
            </div>
          </div>

          {/* Answer Area — Voice transcript (non-coding) or Code Editor (coding) */}
          {isCoding ? (
            <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
              <div className="flex items-center justify-between mb-3">
                <label className="block text-sm font-medium text-gray-700">Your Code Solution</label>
                <select
                  value={codeLanguage}
                  onChange={(e) => setCodeLanguage(e.target.value)}
                  className="px-3 py-1 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-primary-500 outline-none"
                >
                  {['python', 'javascript', 'java', 'cpp', 'c', 'go', 'rust', 'typescript'].map((l) => (
                    <option key={l} value={l}>{l}</option>
                  ))}
                </select>
              </div>
              <div className="relative border border-gray-300 rounded-lg overflow-hidden focus-within:ring-2 focus-within:ring-primary-500">
                {/* Line numbers */}
                <div className="absolute left-0 top-0 bottom-0 w-10 bg-gray-800 border-r border-gray-700 text-gray-500 text-xs font-mono pt-3 text-right pr-2 select-none overflow-hidden leading-[1.375rem]">
                  {(codeText || '').split('\n').map((_, i) => (
                    <div key={i}>{i + 1}</div>
                  ))}
                </div>
                <textarea
                  value={codeText}
                  onChange={(e) => setCodeText(e.target.value)}
                  onKeyDown={(e) => {
                    const ta = e.target;
                    const { selectionStart, selectionEnd, value } = ta;
                    // Tab key — insert 2 spaces or indent selection
                    if (e.key === 'Tab') {
                      e.preventDefault();
                      if (e.shiftKey) {
                        const lineStart = value.lastIndexOf('\n', selectionStart - 1) + 1;
                        const lineText = value.substring(lineStart, selectionStart);
                        const spaces = lineText.match(/^ {1,2}/)?.[0]?.length || 0;
                        if (spaces > 0) {
                          const newVal = value.substring(0, lineStart) + value.substring(lineStart + spaces);
                          setCodeText(newVal);
                          requestAnimationFrame(() => { ta.selectionStart = ta.selectionEnd = selectionStart - spaces; });
                        }
                      } else {
                        const newVal = value.substring(0, selectionStart) + '  ' + value.substring(selectionEnd);
                        setCodeText(newVal);
                        requestAnimationFrame(() => { ta.selectionStart = ta.selectionEnd = selectionStart + 2; });
                      }
                    }
                    // Enter — auto-indent to match previous line
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      const lineStart = value.lastIndexOf('\n', selectionStart - 1) + 1;
                      const indent = value.substring(lineStart).match(/^(\s*)/)[1];
                      const charBefore = value[selectionStart - 1];
                      const extra = ['{', '(', '[', ':'].includes(charBefore) ? '  ' : '';
                      const insertion = '\n' + indent + extra;
                      const newVal = value.substring(0, selectionStart) + insertion + value.substring(selectionEnd);
                      setCodeText(newVal);
                      requestAnimationFrame(() => { ta.selectionStart = ta.selectionEnd = selectionStart + insertion.length; });
                    }
                    // Auto-close brackets
                    const pairs = { '{': '}', '(': ')', '[': ']', "'": "'", '"': '"', '`': '`' };
                    if (pairs[e.key]) {
                      e.preventDefault();
                      const close = pairs[e.key];
                      const newVal = value.substring(0, selectionStart) + e.key + close + value.substring(selectionEnd);
                      setCodeText(newVal);
                      requestAnimationFrame(() => { ta.selectionStart = ta.selectionEnd = selectionStart + 1; });
                    }
                  }}
                  rows={14}
                  placeholder="Write your code here..."
                  className="w-full pl-12 pr-4 py-3 border-0 outline-none resize-none font-mono text-sm bg-gray-900 text-green-400 leading-[1.375rem]"
                  spellCheck={false}
                  autoCapitalize="off"
                  autoCorrect="off"
                />
              </div>
              <button
                onClick={submitAnswer}
                disabled={loading || !codeText.trim()}
                className="mt-4 w-full gradient-bg text-white py-3 rounded-xl font-semibold flex items-center justify-center space-x-2 hover:opacity-90 transition disabled:opacity-50"
              >
                {loading ? <Loader2 className="animate-spin" size={20} /> : <Send size={18} />}
                <span>{loading ? 'Evaluating Code...' : 'Submit Code'}</span>
              </button>
            </div>
          ) : (
            <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
              <div className="flex items-center justify-between mb-2">
                <label className="block text-sm font-medium text-gray-700">
                  Your Answer <span className="text-gray-400">(live conversation mode)</span>
                </label>
                <div className="flex items-center gap-2">
                  {isRecording && (
                    <span className="flex items-center gap-1.5 px-3 py-1.5 bg-green-100 text-green-700 rounded-full text-xs font-medium">
                      <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
                      Listening
                    </span>
                  )}
                  {isSpeaking && (
                    <span className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-100 text-blue-700 rounded-full text-xs font-medium">
                      <Volume2 size={12} className="animate-pulse" />
                      AI Speaking
                    </span>
                  )}
                  <button
                    onClick={toggleRecording}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition ${
                      isRecording ? 'bg-red-100 text-red-600 hover:bg-red-200' : 'bg-primary-100 text-primary-700 hover:bg-primary-200'
                    }`}
                    title={isRecording ? 'Pause mic' : 'Resume mic'}
                  >
                    {isRecording ? <MicOff size={14} /> : <Mic size={14} />}
                    {isRecording ? 'Pause' : 'Resume'}
                  </button>
                </div>
              </div>
              <div className={`w-full min-h-[120px] px-4 py-3 border rounded-lg text-gray-700 text-base leading-relaxed ${
                isRecording ? 'border-green-400 bg-green-50/50' : isSpeaking ? 'border-blue-300 bg-blue-50/30' : 'border-gray-200 bg-gray-50'
              }`}>
                {answer || (
                  <span className="text-gray-400 italic">
                    {isSpeaking ? 'AI is speaking... listen to the question' : isRecording ? '🎤 Listening... speak your answer naturally' : 'Microphone paused'}
                  </span>
                )}
              </div>
              {isRecording && !isSpeaking && (
                <div className="flex items-center justify-between mt-2">
                  <div className="flex items-center space-x-2 text-green-600 text-sm">
                    <div className="w-2.5 h-2.5 bg-green-500 rounded-full animate-pulse"></div>
                    <span>Speak naturally — answer auto-submits after you pause</span>
                  </div>
                </div>
              )}
              {loading && (
                <div className="flex items-center space-x-2 mt-2 text-primary-600 text-sm">
                  <Loader2 size={14} className="animate-spin" />
                  <span>Evaluating your answer...</span>
                </div>
              )}
              <button
                onClick={submitAnswer}
                disabled={loading || !answer.trim()}
                className="mt-4 w-full gradient-bg text-white py-3 rounded-xl font-semibold flex items-center justify-center space-x-2 hover:opacity-90 transition disabled:opacity-50"
              >
                {loading ? <Loader2 className="animate-spin" size={20} /> : <Send size={18} />}
                <span>{loading ? 'Evaluating...' : 'Submit Early'}</span>
              </button>
            </div>
          )}

          {/* Evaluation feedback */}
          {evaluation && (
            <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
              <h3 className="font-semibold text-gray-900 mb-3">📊 Evaluation</h3>

              {/* Code-specific evaluation scores */}
              {evaluation.code_evaluation ? (
                <>
                  <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-4">
                    {[
                      { label: 'Correctness', value: evaluation.code_evaluation.correctness_score, color: 'blue' },
                      { label: 'Quality', value: evaluation.code_evaluation.quality_score, color: 'indigo' },
                      { label: 'Efficiency', value: evaluation.code_evaluation.efficiency_score, color: 'orange' },
                      { label: 'Edge Cases', value: evaluation.code_evaluation.edge_case_score, color: 'green' },
                      { label: 'Overall', value: evaluation.code_evaluation.overall_score, color: 'purple' },
                    ].map((s) => (
                      <div key={s.label} className="text-center bg-gray-50 rounded-lg p-2">
                        <div className={`text-xl font-bold text-${s.color}-600`}>{Math.round(s.value || 0)}%</div>
                        <div className="text-[10px] text-gray-500">{s.label}</div>
                      </div>
                    ))}
                  </div>
                  {evaluation.code_evaluation.feedback && (
                    <p className="text-sm text-gray-600 bg-gray-50 rounded-lg p-3 mb-2">{evaluation.code_evaluation.feedback}</p>
                  )}
                </>
              ) : (
                <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-4">
                  {[
                    { label: 'Content', value: evaluation.content_score, color: 'blue' },
                    { label: 'Keywords', value: evaluation.keyword_score || evaluation.keyword_coverage, color: 'orange' },
                    { label: 'Depth', value: evaluation.depth_score, color: 'indigo' },
                    { label: 'Communication', value: evaluation.communication_score, color: 'green' },
                    { label: 'Overall', value: evaluation.overall_score, color: 'purple' },
                  ].map((s) => (
                    <div key={s.label} className="text-center bg-gray-50 rounded-lg p-2">
                      <div className={`text-xl font-bold text-${s.color}-600`}>{Math.round(s.value || 0)}%</div>
                      <div className="text-[10px] text-gray-500">{s.label}</div>
                    </div>
                  ))}
                </div>
              )}

              <div className={`text-sm font-medium mb-2 ${
                evaluation.answer_strength === 'strong' ? 'text-green-600' :
                evaluation.answer_strength === 'moderate' ? 'text-yellow-600' : 'text-red-600'
              }`}>
                Strength: {evaluation.answer_strength?.toUpperCase()}
              </div>
              {!evaluation.code_evaluation && evaluation.feedback && (
                <p className="text-sm text-gray-600 bg-gray-50 rounded-lg p-3">{evaluation.feedback}</p>
              )}
              {evaluation.keywords_missed?.length > 0 && (
                <p className="text-xs text-gray-500 mt-2">
                  <span className="font-medium">Keywords missed:</span> {evaluation.keywords_missed.join(', ')}
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
    </div>
    </div>
  );
}
