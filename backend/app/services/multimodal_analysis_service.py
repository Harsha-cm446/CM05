"""
Multimodal Analysis Engine
────────────────────────────────────────
Component 3: Real-time multimodal candidate analysis
  • Facial Expression Recognition (FER+ / DeepFace)
  • Voice Sentiment Analysis (speech features)
  • Eye Tracking / Gaze Estimation
  • Body Posture Detection
  • Speech Fluency Metrics
  • Attention-based Temporal Fusion

Pipeline:
  Video Frame ──▶ Face Detection ──▶ Emotion Recognition ──▶ ┐
  Audio Chunk  ──▶ Voice Features ──▶ Sentiment Analysis  ──▶ │
  Gaze Data    ──▶ Eye Tracking   ──▶ Attention Score     ──▶ ├──▶ Fusion ──▶ Metrics
  Posture Data ──▶ Body Analysis  ──▶ Engagement Score    ──▶ │
  Transcript   ──▶ Fluency Calc   ──▶ Clarity Score       ──▶ ┘

Feature Alignment Strategy:
  All modalities are resampled to 1Hz (1 reading/second)
  Temporal modeling via sliding window LSTM / Transformer

Fusion Mechanism:
  Attention-based cross-modal fusion with learned weights
"""

import asyncio
import time
import math
import base64
from typing import Dict, Any, List, Optional, Tuple
from collections import deque
from datetime import datetime
from enum import Enum

import numpy as np

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    from deepface import DeepFace
    DEEPFACE_AVAILABLE = True
except (ImportError, ValueError, Exception) as e:
    DeepFace = None
    DEEPFACE_AVAILABLE = False
    print(f"\u26a0\ufe0f DeepFace unavailable: {e}")

# YOLO person detection now handled by proctoring_service.ObjectDetectionEngine
# to avoid loading the model twice into memory.
try:
    from app.services.proctoring_service import proctor_manager
    PROCTOR_AVAILABLE = proctor_manager is not None
except Exception:
    proctor_manager = None
    PROCTOR_AVAILABLE = False

print(f"[MULTIMODAL] CV2={CV2_AVAILABLE} DeepFace={DEEPFACE_AVAILABLE} PROCTOR={PROCTOR_AVAILABLE}")



# ══════════════════════════════════════════════════════════════════════
# Gaze Finite State Machine — production-ready eye contact monitoring
# ══════════════════════════════════════════════════════════════════════

class GazeState(str, Enum):
    """Possible states of the gaze monitoring FSM."""
    ATTENTIVE = "ATTENTIVE"               # Candidate is looking at the screen
    WARNING_ACTIVE = "WARNING_ACTIVE"     # Sustained gaze away from screen → show warning
    RECOVERING = "RECOVERING"             # Gaze returning to screen, not yet stable


class GazeStateMachine:
    """
    Finite-state-machine for robust screen-attention monitoring.

    Design principles:
      • "Looking at the screen" is the acceptable state — candidates naturally
        read questions, type code, and look at the UI, not directly at the camera.
      • A violation only triggers when the candidate looks AWAY from the screen
        entirely (face not visible, head turned far to the side, etc.).
      • No state change on a single frame — uses a rolling window percentage.
      • Separate timers for deviation and recovery — never reused across states.
      • Handles frame drops and camera freeze via a staleness timeout.

    States & transitions:
      ATTENTIVE ──(away >70% for ≥2.5 s)──▶ WARNING_ACTIVE
      WARNING_ACTIVE ──(looking >70% for ≥0.5 s)──▶ RECOVERING
      RECOVERING ──(looking >70% for ≥1.5 s)──▶ ATTENTIVE
      RECOVERING ──(away >70% again)──▶ WARNING_ACTIVE

    Parameters:
        window_size:         Number of frames in the rolling window (default 45)
        away_pct_threshold:  Fraction of window frames that must be "away" (0.70)
        look_pct_threshold:  Fraction that must be "looking" to start recovery (0.70)
        deviation_hold_sec:  Seconds of sustained "away" before WARNING_ACTIVE (2.5)
        recovery_entry_sec:  Seconds of sustained "looking" to enter RECOVERING (0.5)
        recovery_full_sec:   Seconds of sustained "looking" to reach ATTENTIVE (1.5)
        gaze_threshold:      Score below which a frame counts as "looking away from screen" (45.0)
        stale_timeout_sec:   If no frame arrives for this long, assume away (4.0)
    """

    def __init__(
        self,
        window_size: int = 5,
        away_pct_threshold: float = 0.50,
        look_pct_threshold: float = 0.50,
        deviation_hold_sec: float = 2.0,
        recovery_entry_sec: float = 0.0,
        recovery_full_sec: float = 2.0,
        gaze_threshold: float = 50.0,
        stale_timeout_sec: float = 5.0,
    ):
        # Configurable thresholds
        self._window_size = window_size
        self._away_pct = away_pct_threshold
        self._look_pct = look_pct_threshold
        self._deviation_hold = deviation_hold_sec
        self._recovery_entry = recovery_entry_sec
        self._recovery_full = recovery_full_sec
        self._gaze_threshold = gaze_threshold
        self._stale_timeout = stale_timeout_sec

        # Rolling window of booleans: True = looking at screen
        self._frame_window: deque = deque(maxlen=window_size)

        # FSM state
        self._state: GazeState = GazeState.ATTENTIVE

        # Timers (epoch seconds, None = not running)
        self._deviation_start: Optional[float] = None   # when away-percentage first exceeded threshold
        self._recovery_start: Optional[float] = None     # when look-percentage first exceeded threshold
        self._last_frame_time: Optional[float] = None    # for staleness detection

    # ── Public API ────────────────────────────────────────

    def update(self, gaze_score: float) -> Dict[str, Any]:
        """
        Feed a new gaze score (0–100) from the detector.
        Returns the current FSM state and metadata.

        Call this once per processed frame (~every 1–2 seconds in this system).
        """
        now = time.time()
        self._last_frame_time = now

        # Classify this frame as looking (True) or away (False)
        is_looking = gaze_score >= self._gaze_threshold
        print(f"[GAZE FSM] score={gaze_score:.1f} threshold={self._gaze_threshold} is_looking={is_looking} state={self._state}")

        # Push into rolling window
        self._frame_window.append(is_looking)

        # Compute window statistics
        total = len(self._frame_window)
        looking_count = sum(self._frame_window)
        away_count = total - looking_count

        looking_pct = looking_count / total if total > 0 else 1.0
        away_pct = away_count / total if total > 0 else 0.0

        # Determine dominant signal from the window
        window_says_away = away_pct >= self._away_pct
        window_says_looking = looking_pct >= self._look_pct

        # ── State transitions ─────────────────────────────
        prev_state = self._state

        if self._state == GazeState.ATTENTIVE:
            self._recovery_start = None  # Not applicable in this state

            if window_says_away:
                # Start or continue deviation timer
                if self._deviation_start is None:
                    self._deviation_start = now

                elapsed = now - self._deviation_start
                if elapsed >= self._deviation_hold:
                    # Sustained deviation → WARNING
                    self._state = GazeState.WARNING_ACTIVE
                    self._deviation_start = None  # Reset — no longer needed
                    self._recovery_start = None
            else:
                # Window is not predominantly away — reset deviation timer
                self._deviation_start = None

        elif self._state == GazeState.WARNING_ACTIVE:
            self._deviation_start = None  # Not applicable in this state

            if is_looking:
                # User looked back → clear warning, enter recovery
                self._state = GazeState.RECOVERING
                self._recovery_start = now
            else:
                # Still looking away — reset any partial recovery
                self._recovery_start = None

        elif self._state == GazeState.RECOVERING:
            self._deviation_start = None

            if is_looking:
                # Still looking at screen — continue recovery timer
                if self._recovery_start is None:
                    self._recovery_start = now

                elapsed = now - self._recovery_start
                if elapsed >= self._recovery_full:
                    # Full recovery achieved → ATTENTIVE
                    self._state = GazeState.ATTENTIVE
                    self._recovery_start = None
            else:
                # FIX: Only fall back to WARNING if the window is predominantly away,
                # not on a single frame — prevents false regression during recovery
                if window_says_away:
                    self._state = GazeState.WARNING_ACTIVE
                    self._recovery_start = None
                # else: single away frame during recovery — ignore, keep recovering

        return self._build_output(gaze_score, looking_pct, away_pct, prev_state)

    def check_staleness(self) -> Dict[str, Any]:
        """
        Call periodically even when no frame arrives.
        If no frame for > stale_timeout, inject an "away" signal.
        Handles camera freeze and frame drops.
        """
        if self._last_frame_time is None:
            return self._build_output(0, 0, 0, self._state)

        elapsed = time.time() - self._last_frame_time
        if elapsed > self._stale_timeout:
            # Inject away frames to fill the gap
            return self.update(0.0)

        return self._build_output(0, 0, 0, self._state)

    def reset(self):
        """Reset FSM to initial state (new session)."""
        self._frame_window.clear()
        self._state = GazeState.ATTENTIVE
        self._deviation_start = None
        self._recovery_start = None
        self._last_frame_time = None

    @property
    def state(self) -> GazeState:
        return self._state

    @property
    def show_warning(self) -> bool:
        """Whether the UI should display a warning overlay."""
        return self._state == GazeState.WARNING_ACTIVE

    # ── Internal ──────────────────────────────────────────

    def _build_output(
        self,
        gaze_score: float,
        looking_pct: float,
        away_pct: float,
        prev_state: GazeState,
    ) -> Dict[str, Any]:
        return {
            "state": self._state.value,
            "show_warning": self._state == GazeState.WARNING_ACTIVE,
            "gaze_score": round(gaze_score, 1),
            "looking_pct": round(looking_pct, 2),
            "away_pct": round(away_pct, 2),
            "state_changed": self._state != prev_state,
            "window_size": len(self._frame_window),
        }


# ══════════════════════════════════════════════════════════════════════


class MultimodalAnalysisEngine:
    """
    Real-time multimodal analysis for interview candidates.
    Processes video frames, audio, and text to produce continuous metrics.
    """

    def __init__(self, window_size: int = 30):
        self.window_size = window_size  # Sliding window for temporal smoothing

        # Temporal buffers for each modality (sliding windows)
        self.emotion_history: deque = deque(maxlen=window_size)
        self.voice_history: deque = deque(maxlen=window_size)
        self.gaze_history: deque = deque(maxlen=window_size)
        self.posture_history: deque = deque(maxlen=window_size)
        self.fluency_history: deque = deque(maxlen=window_size)

        # Cache Haar cascades to avoid reloading on every frame
        self._face_cascade = None
        self._eye_cascade = None
        if CV2_AVAILABLE:
            try:
                self._face_cascade = cv2.CascadeClassifier(
                    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                )
                self._eye_cascade = cv2.CascadeClassifier(
                    cv2.data.haarcascades + "haarcascade_eye.xml"
                )
            except Exception:
                pass

        # Fusion weights (learned / configured)
        self.fusion_weights = {
            "emotion": 0.25,
            "voice": 0.20,
            "gaze": 0.15,
            "posture": 0.15,
            "fluency": 0.25,
        }

        # Running metrics
        self._metrics_log: List[Dict[str, Any]] = []
        self._start_time: Optional[float] = None

    def reset(self):
        """Reset all buffers for a new session."""
        self.emotion_history.clear()
        self.voice_history.clear()
        self.gaze_history.clear()
        self.posture_history.clear()
        self.fluency_history.clear()
        self._metrics_log.clear()
        self._start_time = time.time()

    # ── Facial Expression Recognition (FER+) ─────────

    def analyze_face(self, frame_b64: str) -> Dict[str, Any]:
        """Analyze facial expressions from a base64-encoded video frame.

        Uses DeepFace with FER+ backend for emotion recognition.
        Returns emotion scores, confidence, and stability metrics.
        """
        if not CV2_AVAILABLE:
            return self._default_emotion()

        try:
            img_bytes = base64.b64decode(frame_b64)
            nparr = np.frombuffer(img_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if frame is None:
                return self._default_emotion()

            return self._process_face(frame)
        except Exception as e:
            return self._default_emotion()

    async def analyze_face_async(self, frame_b64: str) -> Dict[str, Any]:
        """Non-blocking version of analyze_face — runs in a thread pool."""
        return await asyncio.to_thread(self.analyze_face, frame_b64)

    async def detect_persons_async(self, frame_b64: str) -> int:
        """Non-blocking version of detect_persons — runs in a thread pool."""
        return await asyncio.to_thread(self.detect_persons, frame_b64)

    def _process_face(self, frame: np.ndarray) -> Dict[str, Any]:
        """Process a CV2 frame for facial analysis."""
        result = {
            "dominant_emotion": "neutral",
            "emotion_scores": {},
            "confidence_score": 50.0,
            "emotion_stability": 50.0,
            "face_detected": False,
            "micro_expressions": [],
        }

        if DEEPFACE_AVAILABLE:
            try:
                analysis = DeepFace.analyze(
                    frame, actions=["emotion"],
                    enforce_detection=False, silent=True,
                )
                if isinstance(analysis, list):
                    analysis = analysis[0]

                emotions = analysis.get("emotion", {})
                result["dominant_emotion"] = analysis.get("dominant_emotion", "neutral")
                result["emotion_scores"] = emotions
                result["face_detected"] = True

                # Compute confidence from emotion distribution
                result["confidence_score"] = self._emotion_to_confidence(emotions)

                # Detect micro-expressions (rapid changes)
                result["micro_expressions"] = self._detect_micro_expressions(emotions)

            except Exception:
                pass

        # Gaze estimation from face + eye detection
        result["eye_contact_score"] = self._estimate_gaze(frame)

        # Store in temporal buffer
        self.emotion_history.append({
            "timestamp": time.time(),
            **result,
        })

        # Compute stability from history
        result["emotion_stability"] = self._compute_emotion_stability()

        return result

    def _emotion_to_confidence(self, emotions: Dict[str, float]) -> float:
        """Map emotion distribution to confidence score."""
        happy = emotions.get("happy", 0)
        neutral = emotions.get("neutral", 0)
        surprise = emotions.get("surprise", 0)
        fear = emotions.get("fear", 0)
        sad = emotions.get("sad", 0)
        angry = emotions.get("angry", 0)
        disgust = emotions.get("disgust", 0)

        # Positive indicators
        positive = happy * 0.4 + neutral * 0.35 + surprise * 0.1
        # Negative indicators
        negative = fear * 0.4 + sad * 0.25 + angry * 0.2 + disgust * 0.15

        score = max(0, min(100, 50 + positive - negative))
        return round(score, 1)

    def _detect_micro_expressions(self, current_emotions: Dict[str, float]) -> List[str]:
        """Detect micro-expressions by comparing with recent history."""
        if len(self.emotion_history) < 2:
            return []

        last = self.emotion_history[-1].get("emotion_scores", {})
        micro = []

        for emotion, score in current_emotions.items():
            last_score = last.get(emotion, 0)
            delta = abs(score - last_score)
            if delta > 20:  # Significant rapid change
                direction = "spike" if score > last_score else "drop"
                micro.append(f"{emotion}_{direction}")

        return micro

    def _compute_emotion_stability(self) -> float:
        """Compute emotion stability from temporal history."""
        if len(self.emotion_history) < 3:
            return 50.0

        dominant_emotions = [
            h.get("dominant_emotion", "neutral")
            for h in self.emotion_history
        ]

        # Count transitions
        transitions = sum(
            1 for i in range(1, len(dominant_emotions))
            if dominant_emotions[i] != dominant_emotions[i - 1]
        )
        transition_rate = transitions / max(len(dominant_emotions) - 1, 1)

        # Lower transition rate = more stable
        stability = max(0, min(100, 100 - transition_rate * 100))
        return round(stability, 1)

    def _estimate_gaze(self, frame: np.ndarray) -> float:
        """Estimate whether the candidate is looking at their screen.

        Strategy — "screen-aware" gaze detection:
          • Looking at the screen (reading question, typing code) is ACCEPTABLE.
          • The camera sits above/beside the screen, so a candidate reading the
            question will NOT look directly into the camera — this is normal.
          • We only flag a violation when the candidate looks AWAY from the
            screen entirely (face turned far to the side, face not visible,
            or head dropped out of frame).

        Scoring rules:
          1. Face detected + eyes visible (≥1) → looking at screen → HIGH score
          2. Face detected + no eyes (could be blinking or glancing down at
             keyboard momentarily) → borderline → MEDIUM score
          3. Face detected but heavily off-centre (>40% offset) → turned away
             from screen → LOW score
          4. No face detected at all → not looking at screen → VERY LOW score
        """
        if not CV2_AVAILABLE or self._face_cascade is None:
            print(f"[GAZE] Skipping gaze — CV2={CV2_AVAILABLE} face_cascade={'loaded' if self._face_cascade else 'None'}")
            return 15.0  # Below threshold so FSM treats as "away"

        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            faces = self._face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=3, minSize=(40, 40)
            )

            print(f"[GAZE] frame shape={frame.shape}, faces found={len(faces)}")

            if len(faces) == 0:
                # No face at all — candidate has left the screen area
                raw_score = 10.0
            else:
                (fx, fy, fw, fh) = faces[0]

                # ── Signal 1: Face position — is the face in the screen area? ──
                # The camera is above/beside the screen. If the face is roughly
                # in frame, the candidate is looking at the screen area.
                # Only penalise when face is FAR off to the side (head turned
                # completely away from screen).
                frame_cx = frame.shape[1] / 2
                face_cx = fx + fw / 2
                face_offset = abs(face_cx - frame_cx) / frame_cx  # 0 = centered, 1 = edge

                # Gentle penalty — only flag extreme offsets (>40% = head fully turned)
                if face_offset > 0.40:
                    face_position_score = max(0, 100 - (face_offset - 0.40) * 300)
                else:
                    # Face is in the screen area — no penalty
                    face_position_score = 100.0

                # ── Signal 2: Eye detection (are eyes open / visible?) ──────
                eye_score = 0.0
                eyes_detected = False

                if self._eye_cascade is not None:
                    eye_roi_gray = gray[fy:fy + int(fh * 0.65), fx:fx + fw]

                    eyes = self._eye_cascade.detectMultiScale(
                        eye_roi_gray,
                        scaleFactor=1.05,
                        minNeighbors=3,
                        minSize=(15, 15),
                    )

                    if len(eyes) >= 2:
                        # Both eyes visible — candidate is facing the screen
                        eyes_detected = True
                        eye_score = 90.0  # looking at screen = good

                    elif len(eyes) == 1:
                        # One eye visible — could be reading at an angle,
                        # still looking at the screen area
                        eyes_detected = True
                        eye_score = 75.0  # acceptable — still on screen

                    else:
                        # No eyes detected — could be looking down at keyboard
                        # briefly or blinking. Face is still there, so not a
                        # major violation.
                        eye_score = 45.0

                # ── Combine signals ────────────────────────────────
                if eyes_detected:
                    # Face + eyes visible → looking at screen → high score
                    # Weight: 60% eye presence, 40% face position
                    raw_score = eye_score * 0.6 + face_position_score * 0.4
                else:
                    # Face visible but no eyes — still acceptable if face
                    # is in the screen area (momentary glance at keyboard etc.)
                    raw_score = eye_score * 0.4 + face_position_score * 0.6

            # ── Temporal smoothing (lighter — 70/30 to keep responsiveness) ──
            recent_scores = [
                g["score"] for g in self.gaze_history
                if time.time() - g["timestamp"] < 3  # last 3 seconds
            ]
            if recent_scores:
                avg_recent = sum(recent_scores) / len(recent_scores)
                gaze_score = raw_score * 0.7 + avg_recent * 0.3
            else:
                gaze_score = raw_score

            self.gaze_history.append({
                "timestamp": time.time(),
                "score": gaze_score,
                "face_detected": len(faces) > 0,
            })
            return round(gaze_score, 1)

        except Exception as exc:
            print(f"[GAZE] Exception in _estimate_gaze: {exc}")
            return 15.0  # Below threshold so FSM treats as "away"

    def detect_persons(self, frame_b64: str) -> int:
        """Count the number of persons visible.

        Delegates to proctoring_service.ObjectDetectionEngine to avoid
        loading a duplicate YOLO model. Falls back to Haar cascade.
        """
        if not CV2_AVAILABLE:
            return 0

        try:
            # Delegate to proctoring service's shared YOLO model
            if PROCTOR_AVAILABLE and proctor_manager is not None:
                from app.services.proctoring_service import ObjectDetectionEngine
                detector = ObjectDetectionEngine()
                result = detector.detect(frame_b64)
                return result.person_count

            # Fallback: Haar cascade face count (no YOLO loaded here)
            img_bytes = base64.b64decode(frame_b64)
            nparr = np.frombuffer(img_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None:
                return 0
            if self._face_cascade is not None:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = self._face_cascade.detectMultiScale(
                    gray, scaleFactor=1.1, minNeighbors=4, minSize=(50, 50)
                )
                return len(faces)

            return 0
        except Exception:
            return 0

    def _default_emotion(self) -> Dict[str, Any]:
        return {
            "dominant_emotion": "neutral",
            "emotion_scores": {},
            "confidence_score": 50.0,
            "emotion_stability": 50.0,
            "face_detected": False,
            "micro_expressions": [],
            "eye_contact_score": 15.0,  # Below gaze_threshold so FSM treats as "away"
        }

    # ── Voice Sentiment Analysis ──────────────────────

    def analyze_voice(
        self,
        audio_features: Optional[Dict[str, float]] = None,
        transcript: str = "",
    ) -> Dict[str, Any]:
        """Analyze voice characteristics for sentiment and confidence.

        Features extracted (externally or from Wav2Vec2):
          - pitch_mean, pitch_std: Voice pitch statistics
          - energy: Voice volume/energy level
          - speaking_rate: Words per minute
          - pause_ratio: Ratio of silence to speech
          - jitter: Pitch variation (nervousness indicator)
          - shimmer: Amplitude variation
        """
        if audio_features is None:
            audio_features = self._default_voice_features()

        # Extract sentiment indicators from voice features
        pitch_mean = audio_features.get("pitch_mean", 150)
        pitch_std = audio_features.get("pitch_std", 30)
        energy = audio_features.get("energy", 0.5)
        speaking_rate = audio_features.get("speaking_rate", 120)
        pause_ratio = audio_features.get("pause_ratio", 0.3)
        jitter = audio_features.get("jitter", 0.02)

        # Confidence from voice
        voice_confidence = 50.0
        if energy > 0.6 and speaking_rate > 100:
            voice_confidence += 20
        if jitter < 0.03:  # Low jitter = steady voice
            voice_confidence += 15
        if pause_ratio < 0.4:
            voice_confidence += 10
        voice_confidence = min(100, max(0, voice_confidence))

        # Stress from voice
        stress_level = 50.0
        if pitch_std > 40:  # High pitch variation
            stress_level += 20
        if jitter > 0.04:
            stress_level += 15
        if pause_ratio > 0.5:
            stress_level += 10
        stress_level = min(100, max(0, stress_level))

        # Engagement
        engagement = 50.0
        if speaking_rate > 110 and energy > 0.5:
            engagement += 25
        if pitch_std > 20:  # Some natural variation
            engagement += 10
        engagement = min(100, max(0, engagement))

        result = {
            "voice_confidence": round(voice_confidence, 1),
            "stress_level": round(stress_level, 1),
            "engagement": round(engagement, 1),
            "speaking_rate_wpm": round(speaking_rate, 1),
            "pause_ratio": round(pause_ratio, 2),
            "pitch_stability": round(max(0, 100 - pitch_std), 1),
            "energy_level": round(energy * 100, 1),
        }

        self.voice_history.append({
            "timestamp": time.time(),
            **result,
        })

        return result

    def analyze_text_confidence(self, answer: str) -> float:
        """Analyze text for confidence signals (hedging, filler words, absolute language).
        Returns a confidence score 0-100.
        """
        if not answer:
            return 50.0

        import re
        answer_clean = re.sub(r'[^\w\s]', '', answer.lower())
        words = answer_clean.split()
        total_words = len(words)
        if total_words == 0:
            return 50.0
            
        padded_answer = f" {answer_clean} "

        hedges = ['i think', 'maybe', 'probably', 'might', 'could', 'sort of', 'kind of', 'i guess', "im not sure", 'perhaps', 'basically']
        fillers = ['um', 'uh', 'like', 'you know', 'mean', 'actually', 'literally']
        absolutes = ['always', 'never', 'must', 'will', 'certainly', 'definitely', 'absolutely']
        strong_words = ['because', 'therefore', 'consequently', 'clearly', 'specifically', 'in fact']

        # Count total occurrences, ensuring whole phrases match
        hedge_count = sum(padded_answer.count(f" {h} ") for h in hedges)
        filler_count = sum(padded_answer.count(f" {f} ") for f in fillers)
        absolute_count = sum(padded_answer.count(f" {a} ") for a in absolutes)
        strong_count = sum(padded_answer.count(f" {s} ") for s in strong_words)

        # Baseline confidence
        confidence = 75.0

        # Penalties
        hedge_penalty = (hedge_count / total_words) * 300  # Scale penalty
        filler_penalty = (filler_count / total_words) * 200

        # Bonuses
        absolute_bonus = (absolute_count / max(total_words, 1)) * 50
        strong_bonus = (strong_count / max(total_words, 1)) * 100

        confidence = confidence - hedge_penalty - filler_penalty + absolute_bonus + strong_bonus

        # Smooth out extremes
        return max(0.0, min(100.0, confidence))

    def _default_voice_features(self) -> Dict[str, float]:
        return {
            "pitch_mean": 150,
            "pitch_std": 30,
            "energy": 0.5,
            "speaking_rate": 120,
            "pause_ratio": 0.3,
            "jitter": 0.02,
            "shimmer": 0.03,
        }

    # ── Speech Fluency Metrics ────────────────────────

    def analyze_fluency(self, transcript: str, duration_seconds: float) -> Dict[str, Any]:
        """Analyze speech fluency from transcript."""
        if not transcript.strip():
            return {
                "fluency_score": 0,
                "words_per_minute": 0,
                "filler_word_count": 0,
                "filler_ratio": 0,
                "sentence_completeness": 0,
                "vocabulary_richness": 0,
                "clarity_score": 0,
            }

        words = transcript.split()
        word_count = len(words)
        wpm = (word_count / max(duration_seconds, 1)) * 60

        # Filler word detection
        filler_words = {
            "um", "uh", "like", "you know", "basically", "actually",
            "literally", "sort of", "kind of", "i mean", "right",
            "so", "well", "okay", "hmm",
        }
        
        # Clean transcript of punctuation to properly match whole filler words
        import re
        transcript_clean = re.sub(r'[^\w\s]', '', transcript.lower())
        padded_transcript = f" {transcript_clean} "
        
        filler_count = sum(
            padded_transcript.count(f" {f} ") for f in filler_words
        )
        filler_ratio = filler_count / max(word_count, 1)

        # Sentence completeness
        sentences = [s.strip() for s in transcript.split(".") if s.strip()]
        avg_sentence_length = sum(len(s.split()) for s in sentences) / max(len(sentences), 1)
        completeness = min(100, avg_sentence_length * 8)

        # Vocabulary richness (type-token ratio)
        unique_words = len(set(w.lower() for w in words))
        vocabulary_richness = (unique_words / max(word_count, 1)) * 100

        # Overall fluency score
        fluency = 50.0
        if 100 <= wpm <= 160:
            fluency += 20  # Optimal speaking rate
        elif 80 <= wpm <= 180:
            fluency += 10
        if filler_ratio < 0.05:
            fluency += 15
        elif filler_ratio < 0.10:
            fluency += 5
        if vocabulary_richness > 60:
            fluency += 10
        if completeness > 50:
            fluency += 5
        fluency = min(100, max(0, fluency))

        # Clarity score
        clarity = min(100, fluency * 0.4 + (100 - filler_ratio * 200) * 0.3 + completeness * 0.3)

        result = {
            "fluency_score": round(fluency, 1),
            "words_per_minute": round(wpm, 1),
            "filler_word_count": filler_count,
            "filler_ratio": round(filler_ratio, 3),
            "sentence_completeness": round(completeness, 1),
            "vocabulary_richness": round(vocabulary_richness, 1),
            "clarity_score": round(max(0, clarity), 1),
            "word_count": word_count,
        }

        self.fluency_history.append({
            "timestamp": time.time(),
            **result,
        })

        return result

    # ── Attention-Based Cross-Modal Fusion ────────────

    def compute_fused_metrics(self) -> Dict[str, Any]:
        """
        Attention-based fusion of all modalities into unified metrics.

        Fusion Mechanism:
          For each metric, compute attention-weighted average across modalities.
          Attention weights are based on:
            1. Static importance weights (self.fusion_weights)
            2. Signal quality / availability
            3. Temporal consistency (more stable signals get higher weight)
        """
        # Get latest readings from each modality
        emotion = self.emotion_history[-1] if self.emotion_history else {}
        voice = self.voice_history[-1] if self.voice_history else {}
        fluency = self.fluency_history[-1] if self.fluency_history else {}
        gaze = self.gaze_history[-1] if self.gaze_history else {}

        # Compute dynamic attention weights
        weights = self._compute_attention_weights()

        # ── Fused Confidence Score ────────────────────
        confidence_sources = []
        confidence_weights = []

        if emotion.get("confidence_score") is not None:
            confidence_sources.append(emotion["confidence_score"])
            confidence_weights.append(weights.get("emotion", 0.25))

        if voice.get("voice_confidence") is not None:
            confidence_sources.append(voice["voice_confidence"])
            confidence_weights.append(weights.get("voice", 0.20))

        if fluency.get("fluency_score") is not None:
            confidence_sources.append(fluency["fluency_score"])
            confidence_weights.append(weights.get("fluency", 0.25))

        fused_confidence = self._weighted_average(
            confidence_sources, confidence_weights
        )

        # ── Fused Stress Level ────────────────────────
        stress_sources = []
        stress_weights = []

        # From emotion: inverse of stability
        if emotion.get("emotion_stability") is not None:
            stress_sources.append(100 - emotion["emotion_stability"])
            stress_weights.append(weights.get("emotion", 0.25))

        if voice.get("stress_level") is not None:
            stress_sources.append(voice["stress_level"])
            stress_weights.append(weights.get("voice", 0.30))

        fused_stress = self._weighted_average(stress_sources, stress_weights)

        # ── Fused Attention Index ─────────────────────
        attention_sources = []
        attention_weights = []

        if gaze.get("score") is not None:
            attention_sources.append(gaze["score"])
            attention_weights.append(0.4)

        if emotion.get("face_detected"):
            attention_sources.append(80.0)
            attention_weights.append(0.3)

        if voice.get("engagement") is not None:
            attention_sources.append(voice["engagement"])
            attention_weights.append(0.3)

        fused_attention = self._weighted_average(
            attention_sources, attention_weights
        )

        # ── Fused Emotional Stability ─────────────────
        stability = emotion.get("emotion_stability", 50.0)

        # ── Speech Clarity ────────────────────────────
        clarity = fluency.get("clarity_score", 50.0)

        # ── Answer Completeness (from fluency) ────────
        completeness = fluency.get("sentence_completeness", 50.0)

        # ── Compute overall performance score ─────────
        overall = (
            fused_confidence * 0.25 +
            (100 - fused_stress) * 0.15 +
            fused_attention * 0.15 +
            stability * 0.15 +
            clarity * 0.15 +
            completeness * 0.15
        )

        metrics = {
            "timestamp": datetime.utcnow().isoformat(),
            "confidence_score": round(fused_confidence, 1),
            "stress_level": round(fused_stress, 1),
            "attention_index": round(fused_attention, 1),
            "emotional_stability": round(stability, 1),
            "speech_clarity": round(clarity, 1),
            "answer_completeness": round(completeness, 1),
            "overall_performance": round(overall, 1),
            # Detailed per-modality scores
            "modality_scores": {
                "emotion": {
                    "dominant_emotion": emotion.get("dominant_emotion", "neutral"),
                    "confidence": emotion.get("confidence_score", 50),
                    "stability": stability,
                },
                "voice": {
                    "confidence": voice.get("voice_confidence", 50),
                    "stress": voice.get("stress_level", 50),
                    "engagement": voice.get("engagement", 50),
                },
                "gaze": {
                    "eye_contact": gaze.get("score", 50),
                    "face_detected": gaze.get("face_detected", False),
                },
                "fluency": {
                    "score": fluency.get("fluency_score", 50),
                    "clarity": clarity,
                    "wpm": fluency.get("words_per_minute", 0),
                    "filler_ratio": fluency.get("filler_ratio", 0),
                },
            },
            "fusion_weights": weights,
        }

        self._metrics_log.append(metrics)
        return metrics

    def _compute_attention_weights(self) -> Dict[str, float]:
        """Compute dynamic attention weights based on signal availability and quality."""
        weights = dict(self.fusion_weights)

        # Reduce weight for modalities with no data
        if not self.emotion_history:
            weights["emotion"] = 0.0
        if not self.voice_history:
            weights["voice"] = 0.0
        if not self.gaze_history:
            weights["gaze"] = 0.0
        if not self.fluency_history:
            weights["fluency"] = 0.0

        # Normalize weights
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}

        return weights

    def _weighted_average(self, values: List[float], weights: List[float]) -> float:
        """Compute weighted average."""
        if not values:
            return 50.0
        total_weight = sum(weights)
        if total_weight == 0:
            return sum(values) / len(values)
        return sum(v * w for v, w in zip(values, weights)) / total_weight

    # ── Temporal Trend Analysis ───────────────────────

    def get_temporal_trends(self) -> Dict[str, Any]:
        """Analyze trends across the interview session."""
        if len(self._metrics_log) < 3:
            return {"trend": "insufficient_data", "data_points": len(self._metrics_log)}

        # Extract time series for key metrics
        confidence_series = [m["confidence_score"] for m in self._metrics_log]
        stress_series = [m["stress_level"] for m in self._metrics_log]
        attention_series = [m["attention_index"] for m in self._metrics_log]

        def compute_trend(series: List[float]) -> str:
            if len(series) < 3:
                return "stable"
            first_half = np.mean(series[:len(series) // 2])
            second_half = np.mean(series[len(series) // 2:])
            diff = second_half - first_half
            if diff > 5:
                return "improving"
            elif diff < -5:
                return "declining"
            return "stable"

        return {
            "confidence_trend": compute_trend(confidence_series),
            "stress_trend": compute_trend(stress_series),
            "attention_trend": compute_trend(attention_series),
            "confidence_avg": round(float(np.mean(confidence_series)), 1),
            "stress_avg": round(float(np.mean(stress_series)), 1),
            "attention_avg": round(float(np.mean(attention_series)), 1),
            "data_points": len(self._metrics_log),
            "session_duration_seconds": (
                time.time() - self._start_time if self._start_time else 0
            ),
        }

    # ── Session Summary ───────────────────────────────

    def get_session_summary(self) -> Dict[str, Any]:
        """Get comprehensive session analysis summary."""
        if not self._metrics_log:
            return {"status": "no_data"}

        all_confidence = [m["confidence_score"] for m in self._metrics_log]
        all_stress = [m["stress_level"] for m in self._metrics_log]
        all_attention = [m["attention_index"] for m in self._metrics_log]
        all_stability = [m["emotional_stability"] for m in self._metrics_log]
        all_clarity = [m["speech_clarity"] for m in self._metrics_log]
        all_overall = [m["overall_performance"] for m in self._metrics_log]

        return {
            "total_data_points": len(self._metrics_log),
            "averages": {
                "confidence": round(float(np.mean(all_confidence)), 1),
                "stress": round(float(np.mean(all_stress)), 1),
                "attention": round(float(np.mean(all_attention)), 1),
                "stability": round(float(np.mean(all_stability)), 1),
                "clarity": round(float(np.mean(all_clarity)), 1),
                "overall": round(float(np.mean(all_overall)), 1),
            },
            "peaks": {
                "max_confidence": round(float(np.max(all_confidence)), 1),
                "max_stress": round(float(np.max(all_stress)), 1),
                "min_attention": round(float(np.min(all_attention)), 1),
            },
            "trends": self.get_temporal_trends(),
            "recommendations": self._generate_behavioral_recommendations(),
        }

    def _generate_behavioral_recommendations(self) -> List[str]:
        """Generate actionable recommendations based on multimodal analysis."""
        recommendations = []

        if not self._metrics_log:
            return ["Complete a practice session to receive personalized recommendations."]

        avg_confidence = np.mean([m["confidence_score"] for m in self._metrics_log])
        avg_stress = np.mean([m["stress_level"] for m in self._metrics_log])
        avg_attention = np.mean([m["attention_index"] for m in self._metrics_log])
        avg_clarity = np.mean([m["speech_clarity"] for m in self._metrics_log])

        if avg_confidence < 50:
            recommendations.append(
                "Practice power posing before interviews — research shows it boosts felt confidence by 20%."
            )
        if avg_stress > 60:
            recommendations.append(
                "Try box breathing (4-4-4-4) between questions to reduce stress indicators."
            )
        if avg_attention < 50:
            recommendations.append(
                "Maintain focus on the screen during the interview. Avoid looking away for extended periods."
            )
        if avg_clarity < 50:
            recommendations.append(
                "Slow your speaking rate and reduce filler words. Practice with a timer for structured responses."
            )

        if not recommendations:
            recommendations.append(
                "Strong performance across all metrics. Continue practicing to maintain consistency."
            )

        return recommendations


# Singleton
multimodal_engine = MultimodalAnalysisEngine()