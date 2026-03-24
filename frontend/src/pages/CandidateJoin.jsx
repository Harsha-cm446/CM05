import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { candidateAPI, WS_BASE } from '../services/api';
import toast from 'react-hot-toast';
import {
  Mic, MicOff, Camera, Send, Loader2, User, Briefcase, Clock,
  CheckCircle, Volume2, VolumeX, Timer, AlertTriangle, XCircle, Code,
  Monitor, Shield, UserX, MonitorX, Eye, LogOut, Maximize2, Minimize2,
} from 'lucide-react';
import useToken from '../hooks/useToken';
import useLiveKit from '../hooks/useLiveKit';


export default function CandidateJoin() {
  const { token } = useParams();
  const [phase, setPhase] = useState('loading'); // loading | welcome | face_registration | interview | round_transition | done | failed | session_ended | error
  const [info, setInfo] = useState(null);
  const [candidateName, setCandidateName] = useState('');
  const [sessionId, setSessionId] = useState(null);
  const [currentQuestion, setCurrentQuestion] = useState(null);
  const [currentRound, setCurrentRound] = useState('Technical');
  const [answer, setAnswer] = useState('');
  const [codeText, setCodeText] = useState('');
  const [codeLanguage, setCodeLanguage] = useState('python');
  const [evaluation, setEvaluation] = useState(null);
  const [loading, setLoading] = useState(false);
  const [cameraOn, setCameraOn] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [ttsEnabled, setTtsEnabled] = useState(true);
  const [timeStatus, setTimeStatus] = useState(null);
  const [questionNumber, setQuestionNumber] = useState(0);
  const [endReason, setEndReason] = useState('');
  const [techScore, setTechScore] = useState(null);
  const [interviewSessionId, setInterviewSessionId] = useState(null);
  const [screenSharing, setScreenSharing] = useState(false);
  const [permissionDenied, setPermissionDenied] = useState(false);
  const [permissionError, setPermissionError] = useState('');

  // ── LiveKit Hooks ────────────────────────────────────
  const { joinAsCandidate, publishCamera, publishScreen, unpublishCamera, unpublishScreen, leave: livekitLeave } = useLiveKit();
  const { getToken } = useToken();

  // Proctoring state
  const [proctoringStats, setProctoringStats] = useState({
    gazeViolations: 0, multiPersonAlerts: 0, tabSwitches: 0, totalAwayTime: 0,
  });
  const [tabSwitchAlert, setTabSwitchAlert] = useState(false);
  const [showEndConfirm, setShowEndConfirm] = useState(false);
  const [endingInterview, setEndingInterview] = useState(false);
  const [eyeTrackAlert, setEyeTrackAlert] = useState(false);
  const [gazeState, setGazeState] = useState('ATTENTIVE');
  const [multiPersonAlert, setMultiPersonAlert] = useState(false);
  const gazeWarningStartRef = useRef(null);

  // Face registration & enhanced proctoring
  const [faceRegPhase, setFaceRegPhase] = useState('idle'); // idle | registering | done | failed
  const [faceRegProgress, setFaceRegProgress] = useState(0); // 0-10
  const [identityVerified, setIdentityVerified] = useState(null); // null | true | false
  const [identityMismatchAlert, setIdentityMismatchAlert] = useState(false);
  const [riskScore, setRiskScore] = useState(0);
  const [riskVerdict, setRiskVerdict] = useState('SAFE');
  const [suspiciousObjects, setSuspiciousObjects] = useState([]);
  const [faceAbsentAlert, setFaceAbsentAlert] = useState(false);

  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const recognitionRef = useRef(null);
  const timeIntervalRef = useRef(null);
  const synthRef = useRef(window.speechSynthesis);
  const wsRef = useRef(null);
  const screenStreamRef = useRef(null);

  // Vosk STT WebSocket refs
  const sttWsRef = useRef(null);
  const audioContextRef = useRef(null);
  const audioProcessorRef = useRef(null);
  const sttStreamRef = useRef(null);  // separate mic stream for STT
  const voskAvailableRef = useRef(null); // null = unknown, true/false = checked

  // Live conversation mode refs
  const silenceTimerRef = useRef(null);
  const autoListenRef = useRef(false);
  const isSubmittingRef = useRef(false);
  const answerRef = useRef('');
  const submitRef = useRef(null);           // always-latest submit function ref
  const SILENCE_TIMEOUT = 5500;
  const [speechSupported, setSpeechSupported] = useState(true);
  const [sttEngine, setSttEngine] = useState('');  // 'vosk' or 'web-speech'
  const [manualAnswer, setManualAnswer] = useState('');
  const [isMobileDevice, setIsMobileDevice] = useState(false);
  const [micDisconnected, setMicDisconnected] = useState(false);
  const micCheckRef = useRef(null);

  // ── Detect mobile device on mount ───────────────────
  useEffect(() => {
    const mobile = /iPhone|iPad|iPod|Android|webOS|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent)
      || (navigator.maxTouchPoints > 1 && /Macintosh/i.test(navigator.userAgent));
    setIsMobileDevice(mobile);
  }, []);

  // ── Load interview info ────────────────────────────
  useEffect(() => {
    const loadInfo = async () => {
      try {
        const res = await candidateAPI.getInfo(token);
        setInfo(res.data);
        if (res.data.ai_session_status === 'completed') {
          setPhase('done');
          setSessionId(res.data.ai_session_id);
        } else {
          // Pre-fill name from previous session if resuming
          if (res.data.candidate_name) {
            setCandidateName(res.data.candidate_name);
          }
          setPhase('welcome');
          setPhase('welcome');
        }
      } catch (err) {
        toast.error('Invalid or expired interview link');
        setPhase('error');
      }
    };
    loadInfo();
  }, [token]);

  // Keep answerRef in sync with answer state
  useEffect(() => { answerRef.current = answer; }, [answer]);

  // ── Fullscreen management ─────────────────────────
  const [isFullscreen, setIsFullscreen] = useState(false);

  const getFullscreenElement = useCallback(() => {
    return (
      document.fullscreenElement
      || document.webkitFullscreenElement
      || document.mozFullScreenElement
      || document.msFullscreenElement
      || null
    );
  }, []);

  const requestFullscreenSafe = useCallback(async () => {
    if (getFullscreenElement()) return true;
    const el = document.documentElement;
    const request = el.requestFullscreen
      || el.webkitRequestFullscreen
      || el.mozRequestFullScreen
      || el.msRequestFullscreen;
    if (!request) return false;
    try {
      await request.call(el);
      return true;
    } catch {
      return false;
    }
  }, [getFullscreenElement]);

  const exitFullscreenSafe = useCallback(async () => {
    const exit = document.exitFullscreen
      || document.webkitExitFullscreen
      || document.mozCancelFullScreen
      || document.msExitFullscreen;
    if (!exit) return;
    try {
      await exit.call(document);
    } catch {
      // Ignore browser-specific fullscreen exit errors.
    }
  }, []);

  // Sync state when Esc key or other browser action exits fullscreen
  useEffect(() => {
    const onFSChange = () => setIsFullscreen(!!getFullscreenElement());
    document.addEventListener('fullscreenchange', onFSChange);
    document.addEventListener('webkitfullscreenchange', onFSChange);
    return () => {
      document.removeEventListener('fullscreenchange', onFSChange);
      document.removeEventListener('webkitfullscreenchange', onFSChange);
    };
  }, [getFullscreenElement]);

  // Auto-enter fullscreen when interview starts, exit when it ends
  useEffect(() => {
    if (['done', 'failed', 'session_ended', 'error'].includes(phase)) {
      if (getFullscreenElement()) {
        exitFullscreenSafe();
      }
    }
  }, [phase, getFullscreenElement, exitFullscreenSafe]);

  const toggleFullscreen = useCallback(() => {
    if (!getFullscreenElement()) {
      requestFullscreenSafe();
    } else {
      exitFullscreenSafe();
    }
  }, [getFullscreenElement, requestFullscreenSafe, exitFullscreenSafe]);

  // ── TTS: Speak question, then auto-start listening ──
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
    utterance.pitch = 1.1; // Slightly higher pitch often sounds more natural/female

    // Try to find a good female English voice natively
    const voices = synthRef.current.getVoices();
    if (voices.length > 0) {
      const preferredVoices = [
        'Google UK English Female',
        'Google US English',
        'Microsoft Zira', // Windows native female voice
        'Microsoft Hazel', // Windows UK female
        'Samantha', // macOS native female voice
        'Karen', // macOS Australian female
        'Tessa', // macOS South African female
        'Victoria' // macOS female
      ];
      
      let selectedVoice = null;
      for (const pref of preferredVoices) {
        selectedVoice = voices.find(v => v.name.includes(pref));
        if (selectedVoice) break;
      }
      
      // Fallback 1: Any voice explicitly containing "Female" and English
      if (!selectedVoice) {
        selectedVoice = voices.find(v => v.lang.startsWith('en') && v.name.toLowerCase().includes('female'));
      }
      // Fallback 2: Any English voice as last resort
      if (!selectedVoice) {
        selectedVoice = voices.find(v => v.lang.startsWith('en'));
      }

      if (selectedVoice) {
        utterance.voice = selectedVoice;
      }
    }

    utterance.onstart = () => setIsSpeaking(true);
    utterance.onend = () => {
      setIsSpeaking(false);
      autoListenRef.current = true;
      setTimeout(() => {
        if (autoListenRef.current && !isSubmittingRef.current) {
          startSpeechRecognition();
        }
      }, 400);
    };
    utterance.onerror = () => {
      setIsSpeaking(false);
      autoListenRef.current = true;
      startSpeechRecognition();
    };
    synthRef.current.speak(utterance);
  }, [ttsEnabled]);

  // ── Speech-to-text — Vosk server-side (primary) with Web Speech API fallback ──
  // Builds a WebSocket to /ws/stt and streams raw PCM audio for accurate recognition.
  // Falls back to browser Web Speech API if Vosk WS is unavailable.

  const connectSttWebSocket = useCallback(() => {
    if (sttWsRef.current && sttWsRef.current.readyState <= 1) return sttWsRef.current;

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const wsBase = WS_BASE || `${proto}://${window.location.hostname}:8000`;
    const ws = new WebSocket(`${wsBase}/ws/stt`);
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {
      console.log('STT WebSocket connected');
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'ready') {
          setSttEngine('vosk');
          console.log('Vosk STT engine ready');
        } else if (data.type === 'partial' || data.type === 'final') {
          const newAnswer = data.full_text || data.text || '';
          if (newAnswer) {
            setAnswer(newAnswer);
            answerRef.current = newAnswer;
            // Reset silence timer on speech
            if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
            silenceTimerRef.current = setTimeout(() => {
              if (answerRef.current.trim().length >= 5 && !isSubmittingRef.current) {
                autoListenRef.current = false;
                stopSpeechRecognition();
                if (submitRef.current) submitRef.current();
              }
            }, SILENCE_TIMEOUT);
          }
        } else if (data.type === 'error') {
          console.warn('Vosk STT error:', data.message);
        }
      } catch (e) {
        console.error('STT WS parse error:', e);
      }
    };

    ws.onerror = () => {
      console.warn('STT WebSocket error — will fall back to Web Speech API');
    };

    ws.onclose = () => {
      console.log('STT WebSocket closed');
      sttWsRef.current = null;
    };

    sttWsRef.current = ws;
    return ws;
  }, []);

  const startVoskStreaming = useCallback(async () => {
    try {
      const requestedRate = 16000;
      // Get mic stream for STT (16kHz mono)
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: requestedRate,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      sttStreamRef.current = stream;

      const audioContext = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: requestedRate,
      });
      audioContextRef.current = audioContext;
      const actualSampleRate = Math.round(audioContext.sampleRate || requestedRate);

      // Keep backend recognizer sample rate aligned with actual browser capture rate.
      if (sttWsRef.current && sttWsRef.current.readyState === WebSocket.OPEN) {
        try {
          sttWsRef.current.send(JSON.stringify({ type: 'config', sample_rate: actualSampleRate }));
        } catch {}
      }

      const source = audioContext.createMediaStreamSource(stream);

      // Use ScriptProcessorNode to get raw PCM data (compatible with all browsers)
      // Buffer size 4096 at 16kHz = ~256ms chunks
      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      audioProcessorRef.current = processor;

      processor.onaudioprocess = (e) => {
        if (sttWsRef.current && sttWsRef.current.readyState === WebSocket.OPEN) {
          const float32 = e.inputBuffer.getChannelData(0);
          // Convert float32 to int16 PCM (what Vosk expects)
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
    // Send EOF to get final result
    if (sttWsRef.current && sttWsRef.current.readyState === WebSocket.OPEN) {
      try { sttWsRef.current.send(JSON.stringify({ type: 'eof' })); } catch {}
    }
    // Stop audio processing
    if (audioProcessorRef.current) {
      audioProcessorRef.current.disconnect();
      audioProcessorRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }
    if (sttStreamRef.current) {
      sttStreamRef.current.getTracks().forEach(t => t.stop());
      sttStreamRef.current = null;
    }
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
          // Send reset to clear any previous state
          try { ws.send(JSON.stringify({ type: 'reset' })); } catch {}
          recognitionRef.current = { engine: 'vosk' };  // marker object
          setIsRecording(true);
          setSttEngine('vosk');
          // Start silence timer
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
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      setSpeechSupported(false);
      toast.error('Speech recognition not supported — use the text box to type your answer');
      return;
    }
    setSttEngine('web-speech');
    const recognition = new SR();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    let finalTranscript = answerRef.current;

    // Reset silence timer whenever we get speech
    const resetSilenceTimer = () => {
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = setTimeout(() => {
        // Silence detected — auto-submit if there's enough answer text
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
        const t = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalTranscript += ' ' + t;
        } else {
          interim += t;
        }
      }
      const newAnswer = finalTranscript.trim() + (interim ? ' ' + interim : '');
      setAnswer(newAnswer);
      answerRef.current = newAnswer;
      // User is speaking — reset the silence timer
      resetSilenceTimer();
    };

    recognition.onerror = (event) => {
      if (event.error !== 'no-speech' && event.error !== 'aborted') {
        console.error('Speech recognition error:', event.error);
      }
      if (event.error === 'not-allowed') {
        setSpeechSupported(false);
        setMicDisconnected(true);
        toast.error('Microphone access denied. Audio is required for this interview.', { duration: 10000 });
      }
    };

    recognition.onend = () => {
      setIsRecording(false);
      recognitionRef.current = null;
      // Auto-restart if we're still in conversation mode and not submitting
      // This is critical for mobile browsers that stop recognition unexpectedly
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
      // Start silence timer
      resetSilenceTimer();
    } catch (e) {
      console.error('Failed to start recognition:', e);
      setSpeechSupported(false);
    }
  }, [connectSttWebSocket, startVoskStreaming]);

  const stopSpeechRecognition = useCallback(() => {
    autoListenRef.current = false;
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
    // Stop Vosk streaming if active
    if (recognitionRef.current?.engine === 'vosk') {
      stopVoskStreaming();
      recognitionRef.current = null;
      setIsRecording(false);
      return;
    }
    // Stop Web Speech API
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

  // ── End Interview handler ─────────────────────
  const handleEndInterview = useCallback(async () => {
    if (endingInterview) return;
    setEndingInterview(true);
    try {
      stopSpeechRecognition();
      synthRef.current.cancel();
      await candidateAPI.endInterview(token);
      setEndReason('manually_ended');
      setPhase('done');
      toast.success('Interview ended successfully');
    } catch (err) {
      toast.error('Failed to end interview');
    } finally {
      setEndingInterview(false);
      setShowEndConfirm(false);
    }
  }, [token, endingInterview, stopSpeechRecognition]);

  // ── Camera ─────────────────────────────────────────
  const toggleCamera = async () => {
    if (cameraOn) {
      streamRef.current?.getTracks().forEach((t) => t.stop());
      if (videoRef.current) videoRef.current.srcObject = null;
      setCameraOn(false);
    } else {
      try {
        // Request video and audio separately for better mobile compatibility
        const constraints = {
          video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } },
          audio: true,
        };
        const stream = await navigator.mediaDevices.getUserMedia(constraints);
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          // Explicit play() for mobile browsers
          try { await videoRef.current.play(); } catch (e) { console.log('Video autoplay handled:', e); }
        }
        setCameraOn(true);
      } catch {
        toast.error('Camera access denied');
      }
    }
  };

  // ── Timer polling ──────────────────────────────────
  useEffect(() => {
    if (phase === 'interview' && token) {
      const pollTime = async () => {
        try {
          const res = await candidateAPI.checkTime(token);
          setTimeStatus(res.data);
          if (res.data.is_expired) {
            await candidateAPI.endInterview(token);
            setPhase('done');
            setEndReason('time_expired');
            toast('Time is up! Interview ended.');
          }
        } catch {}
      };
      timeIntervalRef.current = setInterval(pollTime, 1000);
      pollTime();
      return () => clearInterval(timeIntervalRef.current);
    }
  }, [phase, token]);

  // ── Speak question on change ───────────────────────
  useEffect(() => {
    if (currentQuestion?.question && phase === 'interview') {
      if (ttsEnabled) {
        speakQuestion(currentQuestion.question);
      } else {
        // TTS disabled — start speech recognition directly
        autoListenRef.current = true;
        setTimeout(() => {
          if (autoListenRef.current && !isSubmittingRef.current) {
            startSpeechRecognition();
          }
        }, 400);
      }
    }
  }, [currentQuestion?.question_id, phase, speakQuestion, ttsEnabled, startSpeechRecognition]);

  // ── Mic health monitor — detect mic disconnect during interview ──
  useEffect(() => {
    if (phase !== 'interview' || !streamRef.current) return;
    const checkMicHealth = () => {
      const audioTracks = streamRef.current?.getAudioTracks() || [];
      if (audioTracks.length === 0 || audioTracks.every(t => t.readyState === 'ended' || t.muted)) {
        setMicDisconnected(true);
        toast.error('Microphone disconnected! Audio is required. Please reconnect.', { duration: 10000 });
      } else {
        setMicDisconnected(false);
      }
    };
    micCheckRef.current = setInterval(checkMicHealth, 3000);
    // Also listen to track ended events
    const audioTracks = streamRef.current?.getAudioTracks() || [];
    audioTracks.forEach(t => {
      t.onended = () => {
        setMicDisconnected(true);
        toast.error('Microphone disconnected! Interview paused until mic is restored.', { duration: 10000 });
      };
      t.onmute = () => {
        setMicDisconnected(true);
        toast.error('Microphone muted! Please unmute to continue.', { duration: 8000 });
      };
      t.onunmute = () => setMicDisconnected(false);
    });
    return () => clearInterval(micCheckRef.current);
  }, [phase]);

  // ── Cleanup ────────────────────────────────────────
  useEffect(() => {
    return () => {
      autoListenRef.current = false;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      screenStreamRef.current?.getTracks().forEach((t) => t.stop());
      sttStreamRef.current?.getTracks().forEach((t) => t.stop());
      synthRef.current.cancel();
      if (recognitionRef.current?.engine === 'vosk') {
        // Vosk cleanup
        if (audioProcessorRef.current) audioProcessorRef.current.disconnect();
        if (audioContextRef.current) audioContextRef.current.close().catch(() => {});
      } else if (recognitionRef.current) {
        recognitionRef.current.stop?.();
      }
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
      clearInterval(timeIntervalRef.current);
      clearInterval(micCheckRef.current);
      if (sttWsRef.current) sttWsRef.current.close();
      wsRef.current?.close();
    };
  }, []);

  // ── Tab Switch / Visibility Detection (Proctoring) ──
  useEffect(() => {
    if (phase !== 'interview' || !token) return;

    const handleVisibilityChange = () => {
      if (document.hidden) {
        setTabSwitchAlert(true);
        setProctoringStats(prev => ({ ...prev, tabSwitches: prev.tabSwitches + 1 }));
        candidateAPI.logViolation(token, {
          violation_type: 'tab_switch',
          duration_sec: 0,
          details: 'Candidate switched tab or minimized window',
        }).catch(() => {});
        toast.error('Tab switch detected! Stay on the interview tab.', { duration: 4000 });
      } else {
        setTimeout(() => setTabSwitchAlert(false), 3000);
      }
    };

    const handleWindowBlur = () => {
      if (phase === 'interview' && token) {
        setTabSwitchAlert(true);
        setProctoringStats(prev => ({ ...prev, tabSwitches: prev.tabSwitches + 1 }));
        candidateAPI.logViolation(token, {
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
  }, [phase, token]);

  // ── Track gaze violations locally (backend proctoring_service already logs them) ──
  useEffect(() => {
    if (phase !== 'interview' || !token) return;

    if (eyeTrackAlert) {
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
  }, [eyeTrackAlert, gazeState, phase, token]);

  // ── Track multi-person alerts locally (backend proctoring_service already logs them) ──
  useEffect(() => {
    if (phase !== 'interview' || !token || !multiPersonAlert) return;
    setProctoringStats(prev => ({ ...prev, multiPersonAlerts: prev.multiPersonAlerts + 1 }));
    // No need to call logViolation — proctoring_service.process_frame() already
    // logs multiple_persons violations with richer data
  }, [multiPersonAlert, phase, token]);

  // ── Video frame capture helper ──
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

  // ── Gaze monitoring polling (every 2s during interview) ──
  useEffect(() => {
    if (phase !== 'interview' || !token || !cameraOn) {
      if (phase !== 'interview') {
        setEyeTrackAlert(false);
        setGazeState('ATTENTIVE');
      }
      return;
    }

    const pollGaze = async () => {
      try {
        const videoFrame = captureVideoFrame();
        if (!videoFrame) {
          console.log('[GAZE] No video frame captured — camera may be off or video not ready');
          return;
        }
        console.log('[GAZE] Sending frame for analysis...');
        const { data } = await candidateAPI.analyzeFrame(token, videoFrame);
        console.log('[GAZE] Response:', JSON.stringify(data));
        if (data.gaze) {
          const newState = data.gaze.state || 'ATTENTIVE';
          const showWarn = !!data.gaze.show_warning;
          console.log(`[GAZE] state=${newState} show_warning=${showWarn} score=${data.gaze.gaze_score} looking%=${data.gaze.looking_pct}`);
          setGazeState(newState);
          setEyeTrackAlert(showWarn);
        }
        if ((data.person_count ?? 0) > 1) {
          console.log(`[GAZE] Multi-person detected: ${data.person_count}`);
        }
        setMultiPersonAlert((data.person_count ?? 0) > 1);

        // Enhanced proctoring data from proctoring_service
        // Only update identity if the backend actually ran a verification check
        // (identity is null between checks — don't reset to Pending)
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
      } catch (err) {
        console.error('[GAZE] Poll error:', err?.message || err);
      }
    };

    pollGaze();
    const gazeInterval = setInterval(pollGaze, 2000);
    return () => clearInterval(gazeInterval);
  }, [phase, token, cameraOn, captureVideoFrame]);

  // ── WebSocket for live streaming to HR ─────────────
  useEffect(() => {
    if (phase !== 'interview' || !interviewSessionId || !token) return;

    // In production (Render), WS_BASE points to the backend; in dev, use same host
    let wsUrl;
    if (WS_BASE) {
      wsUrl = `${WS_BASE}/ws/interview/${interviewSessionId}?token=${token}&role=candidate&name=${encodeURIComponent(candidateName)}`;
    } else {
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      wsUrl = `${wsProtocol}//${window.location.host}/ws/interview/${interviewSessionId}?token=${token}&role=candidate&name=${encodeURIComponent(candidateName)}`;
    }

    let ws;
    let reconnectTimer;
    let reconnectAttempts = 0;
    let heartbeatInterval;
    let alive = true; // tracks whether the effect is still active

    const connect = () => {
      if (!alive) return;
      ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('[WS] Connected to interview room, session:', interviewSessionId);
        reconnectAttempts = 0;
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          handleWSMessage(data).catch(e => console.error('[Candidate WS] Message handler error:', e));
        } catch (e) {
          console.error('[Candidate WS] Parse error:', e);
        }
      };

      ws.onclose = () => {
        console.log('[WS] Disconnected');
        clearInterval(heartbeatInterval);
        // Auto-reconnect with exponential backoff (max 10s)
        if (alive && reconnectAttempts < 50) {
          const delay = Math.min(1000 * Math.pow(1.5, reconnectAttempts), 10000);
          reconnectAttempts++;
          console.log(`[WS] Reconnecting in ${Math.round(delay)}ms (attempt ${reconnectAttempts})`);
          reconnectTimer = setTimeout(connect, delay);
        }
      };

      ws.onerror = (e) => {
        console.error('[WS] Error:', e);
      };
    };

    connect();

    return () => {
      alive = false;
      clearTimeout(reconnectTimer);
      clearInterval(heartbeatInterval);
      if (wsRef.current) wsRef.current.close();
    };
  }, [phase, interviewSessionId]);

  // Re-attach camera stream to video element when entering interview or face_registration phase
  useEffect(() => {
    if ((phase === 'interview' || phase === 'face_registration') && videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
      videoRef.current.play().catch(() => {});
    }
  }, [phase]);

  const handleWSMessage = useCallback(async (data) => {
    console.log('[Candidate WS] Received:', data.type, data.from || '');
    switch (data.type) {
      case 'session_ended':
        // HR ended the session — stop everything and show message
        console.log('[Candidate] Session ended by HR');
        setPhase('session_ended');
        break;
      default:
        break;
    }
  }, []);

  // ── Start interview ────────────────────────────────
  const startInterview = async () => {
    if (!candidateName.trim()) {
      toast.error('Please enter your name');
      return;
    }

    // Request fullscreen immediately inside click handler (requires user gesture)
    requestFullscreenSafe();

    setPermissionDenied(false);
    setPermissionError('');

    // ── BLOCK MOBILE DEVICES — screen share not supported ──
    const isMobile = /iPhone|iPad|iPod|Android|webOS|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent)
      || (navigator.maxTouchPoints > 1 && /Macintosh/i.test(navigator.userAgent));
    if (isMobile) {
      setPermissionDenied(true);
      setPermissionError(
        'This proctored interview requires screen sharing, which is not supported on mobile devices. '
        + 'Please join from a laptop or desktop computer using Chrome, Edge, or Firefox.'
      );
      toast.error('Mobile devices are not supported. Please use a laptop or desktop.', { duration: 10000 });
      return;
    }

    // ── Request camera + mic (audio is MANDATORY) ──
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
      // Verify audio track is actually present and live
      const audioTracks = stream.getAudioTracks();
      if (audioTracks.length === 0 || audioTracks[0].readyState === 'ended') {
        stream.getTracks().forEach(t => t.stop());
        throw new Error('No active audio track — microphone required');
      }
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        try { await videoRef.current.play(); } catch (e) { console.log('Video autoplay handled:', e); }
      }
      setCameraOn(true);
      setMicDisconnected(false);
    } catch (err) {
      // Audio is mandatory — do NOT fall back to audio-only or text
      setPermissionDenied(true);
      if (err.name === 'NotAllowedError') {
        setPermissionError(
          'Camera and microphone access is REQUIRED. Audio input is mandatory for this interview. '
          + 'Please allow camera + microphone in your browser settings, then click Start Interview again.'
        );
      } else if (err.name === 'NotFoundError') {
        setPermissionError(
          'No camera or microphone detected. A working microphone is mandatory. '
          + 'Please connect a mic and camera, then try again.'
        );
      } else {
        setPermissionError(
          `Unable to access camera/microphone: ${err.message}. A working microphone is mandatory. `
          + 'Please check your device settings and try again.'
        );
      }
      return;
    }

    // ── Screen share (mandatory on desktop) ──
    if (true) {
      try {
        const screenStream = await navigator.mediaDevices.getDisplayMedia({
          video: { displaySurface: 'monitor' },
          audio: false,
        });
        // Validate: prefer monitor (full screen) share
        const videoTrack = screenStream.getVideoTracks()[0];
        const trackSettings = videoTrack?.getSettings?.() || {};
        if (trackSettings.displaySurface && trackSettings.displaySurface !== 'monitor') {
          screenStream.getTracks().forEach(t => t.stop());
          toast.error('Please share your entire screen (not a window or tab). Try again.');
          setPermissionDenied(true);
          setPermissionError('You must share your entire screen to proceed. Click "Start Interview" again and select the full screen option.');
          return;
        }
        screenStreamRef.current = screenStream;
        setScreenSharing(true);
        videoTrack.onended = () => {
          screenStreamRef.current = null;
          setScreenSharing(false);
          toast.error('Screen sharing stopped! Please re-share your screen.', { duration: 8000 });
          // Re-prompt screen share
          navigator.mediaDevices.getDisplayMedia({
            video: { displaySurface: 'monitor' },
            audio: false,
          }).then(newStream => {
            screenStreamRef.current = newStream;
            setScreenSharing(true);
            newStream.getVideoTracks()[0].onended = () => {
              screenStreamRef.current = null;
              setScreenSharing(false);
              toast.error('Screen sharing stopped again! The HR team has been notified.', { duration: 8000 });
            };
            // Notify HR of updated stream
            if (wsRef.current?.readyState === WebSocket.OPEN) {
              wsRef.current.send(JSON.stringify({
                type: 'stream_ready',
                has_camera: cameraOn,
                has_screen: true,
              }));
            }
          }).catch(() => {
            toast.error('Screen sharing is required for this interview.', { duration: 8000 });
          });
        };
      } catch (err) {
        // Screen share is mandatory — block interview if declined
        toast.error('Screen sharing is required to proceed with the interview.');
        setPermissionDenied(true);
        setPermissionError('Screen sharing is required. Click "Start Interview" again and share your entire screen to proceed.');
        return;
      }
    }

    setLoading(true);
    try {
      const res = await candidateAPI.start(token, { candidate_name: candidateName });
      setSessionId(res.data.session_id);
      setInterviewSessionId(res.data.interview_session_id);
      setCurrentQuestion(res.data.question);
      setCurrentRound(res.data.round || 'Technical');
      setTimeStatus(res.data.time_status);
      setQuestionNumber(res.data.question?.question_number || 1);
      setEvaluation(null);
      setAnswer('');
      setCodeText('');

// ── Join LiveKit Room ──
        try {
          const roomId = `${res.data.interview_session_id}`;
          const userId = `candidate-${token.substring(0, 8)}`; // Create a unique user ID

          const tokenRes = await getToken(roomId, userId);

          await joinAsCandidate(
            tokenRes.token
        );

        if (streamRef.current) {
          const videoTrack = streamRef.current.getVideoTracks()[0];
          const audioTrack = streamRef.current.getAudioTracks()[0];
          await publishCamera(videoTrack, audioTrack);
        }
        if (screenStreamRef.current) {
          const screenTrack = screenStreamRef.current.getVideoTracks()[0];
          await publishScreen(screenTrack);
        }
} catch (livekitErr) {
          console.error('Failed to join LiveKit:', livekitErr);
        toast.error('Failed to connect to proctoring network.');
      }

      // ── Face Registration Phase (skip if resuming — already registered) ──
      if (res.data.resumed) {
        setPhase('interview');
        toast.success('Resuming your interview from where you left off', { duration: 3000 });
      } else {
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
            const resp = await candidateAPI.registerFace(token, frame);
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
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to start interview');
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
      return;
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

      const res = await candidateAPI.submitAnswer(token, payload);
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
        const newRound = res.data.round || currentRound;
        if (newRound !== currentRound) {
          setCurrentRound(newRound);
          setTechScore(res.data.technical_score || null);
          setPhase('round_transition');
          setTimeout(() => {
            setPhase('interview');
            setCurrentQuestion(res.data.next_question);
            setQuestionNumber((prev) => prev + 1);
            setAnswer('');
            answerRef.current = '';
            setCodeText('');
            setEvaluation(null);
          }, 3000);
        } else {
          setTimeout(() => {
            setCurrentQuestion(res.data.next_question);
            setQuestionNumber((prev) => prev + 1);
            setAnswer('');
            answerRef.current = '';
            setCodeText('');
            setEvaluation(null);
          }, 3000);
        }
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to submit answer');
    } finally {
      setLoading(false);
      isSubmittingRef.current = false;
    }
  };

  // Auto-submit triggered by silence detection
  const submitAnswerAuto = useCallback(() => {
    doSubmit(answerRef.current);
  }, [currentQuestion, token, codeText, codeLanguage, currentRound]);

  // Keep submitRef always pointing to the latest auto-submit function
  useEffect(() => { submitRef.current = submitAnswerAuto; }, [submitAnswerAuto]);

  // Manual submit (button click)
  const submitAnswer = () => doSubmit(answer || manualAnswer);

  // ── Format time ────────────────────────────────────
  const formatTime = (timeStatus) => {
    const totalSec = timeStatus?.remaining_seconds ?? Math.round((timeStatus?.remaining_minutes ?? 0) * 60);
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  // ─── Loading / Error ───────────────────────────────
  if (phase === 'loading') {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-50">
        <Loader2 className="animate-spin text-primary-500" size={48} />
      </div>
    );
  }

  if (phase === 'error') {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-50">
        <div className="text-center">
          <div className="text-6xl mb-4">❌</div>
          <h1 className="text-2xl font-bold text-gray-900 mb-2">Invalid Link</h1>
          <p className="text-gray-500">This interview link is invalid or has expired.</p>
        </div>
      </div>
    );
  }

  // ─── Welcome Phase ─────────────────────────────────
  if (phase === 'welcome') {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
        <div className="max-w-lg w-full">
          <div className="bg-white rounded-2xl shadow-lg border border-gray-100 overflow-hidden">
            <div className="gradient-bg p-8 text-center">
              <Briefcase className="mx-auto text-white mb-3" size={40} />
              <h1 className="text-2xl font-bold text-white">{info?.job_role} Interview</h1>
              <p className="text-white/80 mt-1">{info?.company_name}</p>
            </div>

            <div className="p-8 space-y-6">
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div className="bg-gray-50 rounded-lg p-3 text-center">
                  <Clock size={18} className="mx-auto text-primary-500 mb-1" />
                  <span className="text-gray-600">{info?.duration_minutes} min</span>
                </div>
                <div className="bg-gray-50 rounded-lg p-3 text-center">
                  <CheckCircle size={18} className="mx-auto text-primary-500 mb-1" />
                  <span className="text-gray-600">2 Rounds</span>
                </div>
              </div>

              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-sm text-blue-800">
                <p className="font-semibold mb-1">🎤 Voice-Based AI Interview</p>
                <p>The AI will ask questions aloud using text-to-speech. Answer using your microphone — no typing allowed. Audio input is mandatory. Enable your camera for the best experience.</p>
              </div>

              <div className="bg-purple-50 border border-purple-200 rounded-lg p-3 text-sm text-purple-800">
                <p><strong>📺 Screen Sharing:</strong> You will be required to share your entire screen. This allows the HR team to monitor the interview in real-time. Screen sharing is mandatory.</p>
              </div>

              {isMobileDevice && (
                <div className="bg-red-50 border border-red-300 rounded-lg p-4 text-sm text-red-800 flex items-start gap-3">
                  <AlertTriangle size={20} className="text-red-500 mt-0.5 shrink-0" />
                  <div>
                    <p className="font-semibold mb-1">Desktop Required</p>
                    <p>This proctored interview requires screen sharing, which is not available on mobile devices. Please join from a <strong>laptop or desktop computer</strong> using Chrome, Edge, or Firefox.</p>
                  </div>
                </div>
              )}

              <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 text-sm text-yellow-800">
                <p><strong>Two Rounds:</strong> Technical ({info?.technical_cutoff || 70}% cutoff to proceed) → HR</p>
              </div>

              {permissionDenied && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-800 flex items-start gap-3">
                  <AlertTriangle size={20} className="text-red-500 mt-0.5 shrink-0" />
                  <div>
                    <p className="font-semibold mb-1">Permission Required</p>
                    <p>{permissionError}</p>
                  </div>
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Your Full Name</label>
                <div className="relative">
                  <User size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input
                    type="text"
                    value={candidateName}
                    onChange={(e) => setCandidateName(e.target.value)}
                    placeholder="Enter your full name"
                    className="w-full pl-10 pr-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 outline-none"
                    onKeyDown={(e) => e.key === 'Enter' && startInterview()}
                  />
                </div>
              </div>

              {info?.ai_session_status === 'in_progress' && (
                <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-800">
                  <p><strong>📋 Resume Available:</strong> You have an interview in progress. Click below to continue from where you left off.</p>
                </div>
              )}

              <button
                onMouseDown={requestFullscreenSafe}
                onTouchStart={requestFullscreenSafe}
                onClick={startInterview}
                disabled={loading || !candidateName.trim() || isMobileDevice}
                className="w-full gradient-bg text-white py-3 rounded-xl font-semibold flex items-center justify-center space-x-2 hover:opacity-90 transition disabled:opacity-50"
              >
                {loading ? <Loader2 className="animate-spin" size={20} /> : <Send size={18} />}
                <span>{loading ? 'Preparing...' : isMobileDevice ? 'Desktop Required' : info?.ai_session_status === 'in_progress' ? 'Resume Interview' : 'Start Interview'}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ─── Round Transition ──────────────────────────────
  if (phase === 'round_transition') {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
        <div className="max-w-lg w-full">
          <div className="bg-white rounded-2xl shadow-lg border border-gray-100 p-12 text-center">
            <CheckCircle size={64} className="mx-auto text-green-500 mb-4" />
            <h1 className="text-3xl font-bold text-gray-900 mb-2">Technical Round Passed!</h1>
            <p className="text-gray-500 mb-4">
              Score: <span className="font-bold text-green-600">{techScore}%</span> (Cutoff: {info?.technical_cutoff || 70}%)
            </p>
            <p className="text-lg text-primary-600 font-semibold">Proceeding to HR Round...</p>
            <Loader2 className="animate-spin mx-auto mt-4 text-primary-500" size={32} />
          </div>
        </div>
      </div>
    );
  }

  // ─── Failed ────────────────────────────────────────
  if (phase === 'failed') {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
        <div className="max-w-lg w-full">
          <div className="bg-white rounded-2xl shadow-lg border border-gray-100 p-12 text-center">
            <XCircle size={64} className="mx-auto text-red-500 mb-4" />
            <h1 className="text-3xl font-bold text-gray-900 mb-2">Interview Ended</h1>
            <p className="text-gray-500 mb-4">
              Technical Score: <span className="font-bold text-red-600">{techScore}%</span>
            </p>
            <p className="text-gray-600 mb-6">
              Your technical score did not meet the {info?.technical_cutoff || 70}% cutoff for the HR round.
            </p>
            <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-800">
              Your responses have been recorded and will be reviewed by the hiring team.
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ─── Session Ended by HR ───────────────────────────
  if (phase === 'session_ended') {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
        <div className="max-w-lg w-full">
          <div className="bg-white rounded-2xl shadow-lg border border-gray-100 p-12 text-center">
            <LogOut size={64} className="mx-auto text-orange-500 mb-4" />
            <h1 className="text-3xl font-bold text-gray-900 mb-2">Session Ended</h1>
            <p className="text-gray-600 mb-6">
              The interviewer has ended this interview session. Your responses have been recorded.
            </p>
            <div className="bg-orange-50 border border-orange-200 rounded-lg p-4 text-sm text-orange-800">
              Thank you for participating. The hiring team will review your interview.
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ─── Face Registration Phase ───────────────────────
  if (phase === 'face_registration') {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
        <div className="max-w-lg w-full">
          <div className="bg-white rounded-2xl shadow-lg border border-gray-100 p-12 text-center">
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
      </div>
    );
  }

  // ─── Done Phase ────────────────────────────────────
  if (phase === 'done') {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
        <div className="max-w-lg w-full">
          <div className="bg-white rounded-2xl shadow-lg border border-gray-100 p-12 text-center">
            <div className="text-6xl mb-4">🎉</div>
            <h1 className="text-3xl font-bold text-gray-900 mb-2">Interview Complete!</h1>
            <p className="text-gray-500 mb-6">
              Thank you for completing the interview for <strong>{info?.job_role}</strong> at <strong>{info?.company_name}</strong>.
              {endReason === 'time_expired' && ' Time expired — your answers have been recorded.'}
              {endReason === 'manually_ended' && ' You ended the interview early — your answers have been saved.'}
            </p>
            <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-sm text-green-800">
              <CheckCircle size={20} className="inline mr-2" />
              Your interview has been submitted successfully. You may close this page now.
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ─── Interview Phase ───────────────────────────────
  const isCoding = currentQuestion?.is_coding;

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header bar */}
      <div className="bg-white border-b border-gray-200 px-4 py-3">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div>
              <h1 className="text-lg font-semibold text-gray-900">{info?.job_role} Interview</h1>
              <p className="text-sm text-gray-500">{info?.company_name} &bull; AI Interviewer</p>
            </div>
            <span className={`px-3 py-1 rounded-full text-xs font-semibold ${
              currentRound === 'Technical' ? 'bg-blue-100 text-blue-700' : 'bg-purple-100 text-purple-700'
            }`}>
              {currentRound === 'Technical' ? '🔧 Technical' : '🤝 HR'}
            </span>
          </div>

          <div className="flex items-center space-x-3">
            <button
              onClick={() => { setTtsEnabled(!ttsEnabled); synthRef.current.cancel(); }}
              className={`p-2 rounded-lg ${ttsEnabled ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}
            >
              {ttsEnabled ? <Volume2 size={16} /> : <VolumeX size={16} />}
            </button>

            {timeStatus && (
              <div className={`flex items-center space-x-2 px-4 py-2 rounded-xl text-sm font-mono font-semibold ${
                timeStatus.remaining_minutes < 2 ? 'bg-red-100 text-red-700 animate-pulse' :
                timeStatus.remaining_minutes < 5 ? 'bg-yellow-100 text-yellow-700' :
                'bg-gray-100 text-gray-700'
              }`}>
                <Timer size={14} />
                <span>{formatTime(timeStatus)}</span>
              </div>
            )}

            <div className="flex items-center space-x-2 text-sm text-gray-500">
              <User size={16} />
              <span>{candidateName}</span>
            </div>

            {/* Fullscreen toggle */}
            <button
              onClick={toggleFullscreen}
              className="p-2 rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 transition"
              title={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
            >
              {isFullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
            </button>

            {/* End Interview */}
            <button
              onClick={() => setShowEndConfirm(true)}
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold bg-red-50 text-red-600 hover:bg-red-100 transition"
              title="End Interview"
            >
              <LogOut size={14} />
              <span className="hidden sm:inline">End</span>
            </button>
          </div>
        </div>
      </div>

      {/* End Interview Confirmation Modal */}
      {showEndConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-2xl border border-gray-200 p-8 max-w-md w-full mx-4">
            <div className="text-center">
              <div className="w-14 h-14 rounded-full bg-red-100 flex items-center justify-center mx-auto mb-4">
                <LogOut className="text-red-600" size={28} />
              </div>
              <h3 className="text-xl font-bold text-gray-900 mb-2">End Interview?</h3>
              <p className="text-gray-500 text-sm mb-6">
                Are you sure you want to end the interview now? Your answers so far will be saved.
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
        <div className="w-full bg-gray-200 h-1">
          <div
            className={`h-1 transition-all ${
              timeStatus.progress_pct > 80 ? 'bg-red-500' :
              timeStatus.progress_pct > 60 ? 'bg-yellow-500' : 'bg-green-500'
            }`}
            style={{ width: `${timeStatus.progress_pct}%` }}
          />
        </div>
      )}

      <div className="max-w-6xl mx-auto px-4 py-6">
        {/* Wrap-up warning */}
        {currentQuestion?.is_wrap_up && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 mb-4 flex items-center space-x-2 text-sm text-yellow-800">
            <AlertTriangle size={16} />
            <span>Less than 2 minutes remaining. This is your final question.</span>
          </div>
        )}

        <div className="grid lg:grid-cols-3 gap-6">
          {/* Camera + Controls */}
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
              {tabSwitchAlert && (
                <div className="absolute inset-0 flex items-center justify-center bg-purple-900/50 backdrop-blur-[2px]">
                  <div className="bg-purple-600/95 text-white px-4 py-2 rounded-xl text-sm font-semibold flex items-center space-x-2 shadow-lg animate-pulse">
                    <MonitorX size={18} />
                    <span>Tab switch detected!</span>
                  </div>
                </div>
              )}
              {eyeTrackAlert && (
                <div className="absolute bottom-3 left-3 right-3">
                  <div className="bg-red-500/90 text-white px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center space-x-2 animate-pulse">
                    <Eye size={14} />
                    <span>Please look at the screen! Gaze violation detected.</span>
                  </div>
                </div>
              )}
              {multiPersonAlert && (
                <div className="absolute bottom-3 left-3 right-3">
                  <div className="bg-orange-500/90 text-white px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center space-x-2 animate-pulse">
                    <UserX size={14} />
                    <span>Multiple persons detected! Only you should be visible.</span>
                  </div>
                </div>
              )}
              {identityMismatchAlert && (
                <div className="absolute top-3 left-3 right-3">
                  <div className="bg-red-600/95 text-white px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center space-x-2 animate-pulse">
                    <Shield size={14} />
                    <span>Person change detected — different person identified!</span>
                  </div>
                </div>
              )}
              {faceAbsentAlert && !eyeTrackAlert && (
                <div className="absolute bottom-3 left-3 right-3">
                  <div className="bg-yellow-500/90 text-white px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center space-x-2 animate-pulse">
                    <AlertTriangle size={14} />
                    <span>No face detected — please stay visible on camera.</span>
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
                <div className="absolute inset-0 bg-black/40 flex items-center justify-center rounded-2xl">
                  <div className="bg-white rounded-xl p-4 text-center shadow-lg">
                    <Loader2 className="animate-spin mx-auto mb-2 text-cyan-600" size={24} />
                    <p className="text-sm font-semibold text-gray-800">Registering your face...</p>
                    <p className="text-xs text-gray-500 mt-1">Frame {faceRegProgress}/7 — hold still</p>
                    <div className="mt-2 h-1.5 bg-gray-200 rounded-full overflow-hidden w-32 mx-auto">
                      <div className="h-full bg-cyan-500 rounded-full transition-all" style={{ width: `${(faceRegProgress / 7) * 100}%` }} />
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Screen share status */}
            {screenSharing ? (
              <div className="mt-2 flex items-center space-x-2 text-xs text-green-700 bg-green-50 rounded-lg px-3 py-2">
                <Monitor size={14} />
                <span>Screen sharing active</span>
              </div>
            ) : (
              <div className="mt-2 flex items-center space-x-2 text-xs text-red-700 bg-red-50 rounded-lg px-3 py-2">
                <Monitor size={14} />
                <span>Screen sharing not active — HR may flag this</span>
              </div>
            )}

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

            {/* Proctoring Panel */}
            <div className="mt-4 bg-white rounded-xl border border-gray-100 p-4">
              <h3 className="font-semibold mb-3 flex items-center gap-2 text-sm text-gray-700">
                <Shield className="text-cyan-600" size={14} />
                Proctoring
              </h3>
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500 flex items-center gap-1"><Eye size={10} /> Gaze Violations</span>
                  <span className={`text-xs font-bold ${proctoringStats.gazeViolations === 0 ? 'text-green-600' : proctoringStats.gazeViolations < 5 ? 'text-yellow-600' : 'text-red-600'}`}>
                    {proctoringStats.gazeViolations}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500 flex items-center gap-1"><UserX size={10} /> Multi-Person</span>
                  <span className={`text-xs font-bold ${proctoringStats.multiPersonAlerts === 0 ? 'text-green-600' : 'text-red-600'}`}>
                    {proctoringStats.multiPersonAlerts}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500 flex items-center gap-1"><MonitorX size={10} /> Tab Switches</span>
                  <span className={`text-xs font-bold ${proctoringStats.tabSwitches === 0 ? 'text-green-600' : proctoringStats.tabSwitches < 3 ? 'text-yellow-600' : 'text-red-600'}`}>
                    {proctoringStats.tabSwitches}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500 flex items-center gap-1"><Clock size={10} /> Away Time</span>
                  <span className="text-xs font-bold text-gray-700">
                    {Math.round(proctoringStats.totalAwayTime)}s
                  </span>
                </div>
                {/* Identity Verification */}
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500 flex items-center gap-1"><Shield size={10} /> Identity</span>
                  <span className={`text-xs font-bold ${identityVerified === null ? 'text-gray-400' : identityVerified ? 'text-green-600' : 'text-red-600'}`}>
                    {identityVerified === null ? 'Pending' : identityVerified ? 'Verified' : 'Mismatch!'}
                  </span>
                </div>
                {/* Suspicious Objects */}
                {suspiciousObjects.length > 0 && (
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-gray-500 flex items-center gap-1"><AlertTriangle size={10} /> Objects</span>
                    <span className="text-xs font-bold text-orange-600">{suspiciousObjects.map(o => typeof o === 'string' ? o : (o.type || 'object').replace('_', ' ')).join(', ')}</span>
                  </div>
                )}
                {/* Risk Score */}
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500 flex items-center gap-1"><Shield size={10} /> Risk</span>
                  <span className={`text-xs font-bold ${riskVerdict === 'SAFE' ? 'text-green-600' : riskVerdict === 'SUSPICIOUS' ? 'text-yellow-600' : 'text-red-600'}`}>
                    {riskVerdict} ({riskScore})
                  </span>
                </div>
                {/* Integrity indicator */}
                {(() => {
                  const score = Math.max(0, 100 - (proctoringStats.gazeViolations * 3) - (proctoringStats.multiPersonAlerts * 15) - (proctoringStats.tabSwitches * 10) - (proctoringStats.totalAwayTime * 0.5));
                  return (
                    <div className="mt-2 bg-gray-50 rounded-lg p-2">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs text-gray-500">Integrity Score</span>
                        <span className={`text-xs font-bold ${score >= 80 ? 'text-green-600' : score >= 50 ? 'text-yellow-600' : 'text-red-600'}`}>
                          {Math.round(score)}%
                        </span>
                      </div>
                      <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden">
                        <div className={`h-full rounded-full transition-all duration-500 ${score >= 80 ? 'bg-green-500' : score >= 50 ? 'bg-yellow-500' : 'bg-red-500'}`} style={{ width: `${score}%` }} />
                      </div>
                    </div>
                  );
                })()}
              </div>
            </div>
          </div>

          {/* Question & Answer */}
          <div className="lg:col-span-2 space-y-5">
            {/* Question info */}
            <div className="flex items-center justify-between text-sm text-gray-500">
              <span>Question #{questionNumber}</span>
              <span className={`capitalize px-3 py-1 rounded-full font-medium ${
                currentQuestion?.difficulty === 'hard' ? 'bg-red-100 text-red-700' :
                currentQuestion?.difficulty === 'easy' ? 'bg-green-100 text-green-700' :
                'bg-yellow-100 text-yellow-700'
              }`}>
                {currentQuestion?.difficulty}
              </span>
            </div>

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
                        <span>Coding</span>
                      </span>
                    )}
                  </div>
                  <p className="text-gray-700 text-lg leading-relaxed">{currentQuestion?.question}</p>
                </div>
              </div>
            </div>

            {/* Answer: Code editor or Voice transcript */}
            {isCoding ? (
              <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
                <div className="flex items-center justify-between mb-3">
                  <label className="block text-sm font-medium text-gray-700">Your Code Solution</label>
                  <select
                    value={codeLanguage}
                    onChange={(e) => setCodeLanguage(e.target.value)}
                    className="px-3 py-1 border border-gray-300 rounded-lg text-sm"
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
                          // Shift+Tab: dedent current line
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
                        // Extra indent after : { ( [
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
                    {speechSupported && (
                      <button
                        onClick={toggleRecording}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition ${
                          isRecording ? 'bg-red-100 text-red-600 hover:bg-red-200' : 'bg-indigo-100 text-indigo-700 hover:bg-indigo-200'
                        }`}
                        title={isRecording ? 'Pause mic' : 'Resume mic'}
                      >
                        {isRecording ? <MicOff size={14} /> : <Mic size={14} />}
                        {isRecording ? 'Pause' : 'Resume'}
                      </button>
                    )}
                  </div>
                </div>
                {/* Voice transcript display */}
                <div className={`w-full min-h-[80px] px-4 py-3 border rounded-lg text-gray-700 text-base leading-relaxed ${
                  micDisconnected ? 'border-red-400 bg-red-50/50' :
                  isRecording ? 'border-green-400 bg-green-50/50' : isSpeaking ? 'border-blue-300 bg-blue-50/30' : 'border-gray-200 bg-gray-50'
                }`}>
                  {answer || (
                    <span className="text-gray-400 italic">
                      {micDisconnected ? '⚠️ Microphone disconnected — please reconnect to continue' :
                       isSpeaking ? 'AI is speaking... listen to the question' :
                       isRecording ? '🎤 Listening... speak your answer naturally' :
                       'Microphone paused — click Resume to speak'}
                    </span>
                  )}
                </div>
                {/* Mic disconnected warning */}
                {micDisconnected && (
                  <div className="mt-2 bg-red-50 border border-red-200 rounded-lg p-3 flex items-center space-x-2 text-sm text-red-800">
                    <AlertTriangle size={16} className="text-red-500 flex-shrink-0" />
                    <span>Microphone disconnected! Reconnect your mic to continue the interview. Typing is not allowed.</span>
                  </div>
                )}
                {isRecording && !isSpeaking && !micDisconnected && (
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

            {/* Evaluation */}
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
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
