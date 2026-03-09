"""
AI-Powered Interview Proctoring & Identity Verification Service
═══════════════════════════════════════════════════════════════════
Production-grade proctoring system for real-time interview monitoring.

Architecture:
  ┌──────────────────────────────────────────────────────────────────┐
  │                  ProctorSession (per-interview)                 │
  │  ┌─────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │
  │  │FaceRegistry │ │IdentityVerify│ │ObjectDetectionEngine     │ │
  │  │(registration)│ │(continuous)  │ │(YOLO: person, phone, etc)│ │
  │  └─────────────┘ └──────────────┘ └──────────────────────────┘ │
  │  ┌─────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │
  │  │FaceAbsence  │ │AttentionMon  │ │RiskScoringEngine         │ │
  │  │Monitor      │ │(head pose)   │ │(cumulative risk score)   │ │
  │  └─────────────┘ └──────────────┘ └──────────────────────────┘ │
  │  ┌─────────────────────────────┐ ┌──────────────────────────┐  │
  │  │ViolationLogger             │ │IntegrityReportGenerator   │  │
  │  │(structured JSON log)       │ │(end-of-interview report)  │  │
  │  └─────────────────────────────┘ └──────────────────────────┘  │
  └──────────────────────────────────────────────────────────────────┘

Modules:
  1. Candidate Registration — capture reference face embeddings at start
  2. Face Embedding Generator — DeepFace (Facenet / ArcFace)
  3. Continuous Face Verification — cosine similarity every 3-5s
  4. Person Detection — YOLOv8 person count
  5. Suspicious Object Detection — phone, book, laptop, tablet
  6. Face Absence Monitoring — no face > 10s
  7. Attention Monitoring — head pose via facial landmarks
  8. Risk Scoring Engine — cumulative cheating risk score
  9. Violation Logger — structured log with snapshots
  10. Interview Integrity Report Generator
"""

import time
import math
import base64
import logging
from typing import Dict, Any, List, Optional, Tuple
from collections import deque
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass, field

import numpy as np

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

# ── DeepFace for face embeddings ──────────────────────────────────────
try:
    from deepface import DeepFace
    DEEPFACE_AVAILABLE = True
except (ImportError, ValueError, Exception) as e:
    DeepFace = None
    DEEPFACE_AVAILABLE = False

# ── YOLOv8 for object detection ──────────────────────────────────────
try:
    from ultralytics import YOLO
    _yolo_model = YOLO("yolov8n.pt")
    YOLO_AVAILABLE = True
except Exception:
    _yolo_model = None
    YOLO_AVAILABLE = False

logger = logging.getLogger("ProctorService")
logger.setLevel(logging.INFO)

# ── COCO class IDs for suspicious objects ────────────────────────────
# https://docs.ultralytics.com/datasets/detect/coco/
COCO_PERSON = 0
COCO_CELL_PHONE = 67
COCO_BOOK = 73
COCO_LAPTOP = 63
COCO_REMOTE = 65     # often confused with phone
COCO_TV = 62         # can act as tablet proxy
COCO_MOUSE = 64
COCO_KEYBOARD = 66

SUSPICIOUS_CLASSES = {
    COCO_CELL_PHONE: "cell_phone",
    COCO_BOOK: "book",
    COCO_REMOTE: "remote_device",
    COCO_TV: "second_screen",
}

# Only the candidate's own laptop (class 63) is expected — flag extra
# laptops only when person count > 1 or laptop count > 1
LAPTOP_CLASS = COCO_LAPTOP

# ── Risk score weights ───────────────────────────────────────────────
RISK_WEIGHTS = {
    "face_mismatch":     50,
    "multiple_persons":  40,
    "phone_detected":    30,
    "face_absent":       20,
    "suspicious_object": 20,
    "attention_away":    10,
    "tab_switch":        15,
}

HIGH_RISK_THRESHOLD = 50


def _sanitize_for_json(obj):
    """Recursively convert numpy types to native Python types for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


# ══════════════════════════════════════════════════════════════════════
# Data Classes
# ══════════════════════════════════════════════════════════════════════

@dataclass
class ViolationEntry:
    """Structured log entry for a proctoring violation."""
    timestamp: str
    violation_type: str
    confidence_score: float
    risk_points: int
    details: str
    frame_thumbnail: Optional[str] = None  # small base64 JPEG (optional)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "timestamp": self.timestamp,
            "violation_type": self.violation_type,
            "confidence_score": round(self.confidence_score, 2),
            "risk_points": self.risk_points,
            "details": self.details,
        }
        if self.frame_thumbnail:
            d["frame_thumbnail"] = self.frame_thumbnail
        return d


@dataclass
class DetectionResult:
    """Result from YOLO object detection on a single frame."""
    person_count: int = 0
    suspicious_objects: List[Dict[str, Any]] = field(default_factory=list)
    bounding_boxes: List[Dict[str, Any]] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════
# Module 1 & 2: Face Registration + Embedding Generator
# ══════════════════════════════════════════════════════════════════════

class FaceEmbeddingEngine:
    """
    Generate face embeddings using DeepFace with Facenet backend.

    Supports:
      - Single-frame embedding extraction
      - Multi-frame registration (average embedding)
      - Cosine similarity comparison
    """

    MODEL_NAME = "Facenet512"  # 512-dim embeddings, excellent balance of speed + accuracy
    _FALLBACK_MODEL = "Facenet"

    def __init__(self):
        self._model_name = self.MODEL_NAME
        self._embedding_dim = 512
        # Warm up on first call (lazy)
        self._warmed_up = False

    def extract_embedding(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """Extract a face embedding from an OpenCV BGR frame.

        Returns a 1-D numpy array (embedding vector) or None if no face found.
        """
        if not DEEPFACE_AVAILABLE or frame is None:
            return None

        try:
            embeddings = DeepFace.represent(
                img_path=frame,
                model_name=self._model_name,
                enforce_detection=False,
                detector_backend="opencv",  # fastest detector
            )

            if isinstance(embeddings, list) and len(embeddings) > 0:
                vec = embeddings[0].get("embedding")
                if vec:
                    return np.array(vec, dtype=np.float32)
            return None

        except Exception as exc:
            # Try fallback model once
            if self._model_name != self._FALLBACK_MODEL:
                logger.warning(f"Facenet512 failed, falling back to Facenet: {exc}")
                self._model_name = self._FALLBACK_MODEL
                return self.extract_embedding(frame)
            logger.error(f"Embedding extraction failed: {exc}")
            return None

    def extract_embedding_b64(self, frame_b64: str) -> Optional[np.ndarray]:
        """Extract embedding from a base64-encoded JPEG frame."""
        frame = self._decode_frame(frame_b64)
        if frame is None:
            return None
        return self.extract_embedding(frame)

    @staticmethod
    def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
        """Compute cosine similarity between two embedding vectors."""
        if vec_a is None or vec_b is None:
            return 0.0
        norm_a = np.linalg.norm(vec_a)
        norm_b = np.linalg.norm(vec_b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))

    @staticmethod
    def _decode_frame(frame_b64: str) -> Optional[np.ndarray]:
        """Decode base64 JPEG to OpenCV BGR frame."""
        if not CV2_AVAILABLE:
            return None
        try:
            img_bytes = base64.b64decode(frame_b64)
            nparr = np.frombuffer(img_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            return frame
        except Exception:
            return None


# ══════════════════════════════════════════════════════════════════════
# Module 5: Suspicious Object Detection (YOLO)
# ══════════════════════════════════════════════════════════════════════

class ObjectDetectionEngine:
    """
    YOLOv8-based object detection for persons and suspicious items.

    Detects:
      - person (count)
      - cell_phone, book, remote_device, second_screen
      - extra laptops (only flagged when > 1)

    Falls back to Haar cascade face count when YOLO is unavailable.
    """

    CONFIDENCE_THRESHOLD = 0.40
    PERSON_CONFIDENCE = 0.55
    # Minimum bounding box area as fraction of frame area to count as a person
    # Filters out tiny/partial detections (clothes on chair, posters, etc.)
    PERSON_MIN_AREA_RATIO = 0.02

    def __init__(self):
        self._face_cascade = None
        if CV2_AVAILABLE:
            try:
                self._face_cascade = cv2.CascadeClassifier(
                    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                )
            except Exception:
                pass

    def detect(self, frame: np.ndarray) -> DetectionResult:
        """Run detection on an OpenCV frame. Returns DetectionResult."""
        result = DetectionResult()

        if frame is None:
            return result

        if YOLO_AVAILABLE and _yolo_model is not None:
            return self._yolo_detect(frame)

        # Fallback: Haar cascade for face/person count only
        return self._haar_fallback(frame)

    def detect_b64(self, frame_b64: str) -> DetectionResult:
        """Run detection on a base64-encoded JPEG frame."""
        frame = self._decode_frame(frame_b64)
        if frame is None:
            return DetectionResult()
        return self.detect(frame)

    def _yolo_detect(self, frame: np.ndarray) -> DetectionResult:
        """Full YOLOv8 detection pipeline."""
        result = DetectionResult()

        try:
            detections = _yolo_model(frame, verbose=False)

            laptop_count = 0
            frame_h, frame_w = frame.shape[:2]
            frame_area = frame_h * frame_w
            min_person_area = frame_area * self.PERSON_MIN_AREA_RATIO

            for r in detections:
                for box in r.boxes:
                    cls_id = int(box.cls[0])
                    conf = float(box.conf[0])
                    xyxy = box.xyxy[0].tolist()

                    bbox_info = {
                        "class_id": cls_id,
                        "class_name": _yolo_model.names.get(cls_id, str(cls_id)),
                        "confidence": round(conf, 3),
                        "bbox": [round(c, 1) for c in xyxy],
                    }

                    # Person detection — require minimum bbox area to avoid
                    # false positives from clothes, posters, partial detections
                    if cls_id == COCO_PERSON and conf >= self.PERSON_CONFIDENCE:
                        bbox_w = xyxy[2] - xyxy[0]
                        bbox_h = xyxy[3] - xyxy[1]
                        bbox_area = bbox_w * bbox_h
                        if bbox_area >= min_person_area:
                            result.person_count += 1
                            result.bounding_boxes.append(bbox_info)

                    # Suspicious objects
                    elif cls_id in SUSPICIOUS_CLASSES and conf >= self.CONFIDENCE_THRESHOLD:
                        obj_name = SUSPICIOUS_CLASSES[cls_id]
                        result.suspicious_objects.append({
                            "type": obj_name,
                            "confidence": round(conf, 3),
                            "bbox": [round(c, 1) for c in xyxy],
                        })
                        result.bounding_boxes.append(bbox_info)

                    # Laptop detection (flag if > 1)
                    elif cls_id == LAPTOP_CLASS and conf >= self.CONFIDENCE_THRESHOLD:
                        laptop_count += 1
                        result.bounding_boxes.append(bbox_info)

            # Extra laptop = suspicious
            if laptop_count > 1:
                result.suspicious_objects.append({
                    "type": "extra_laptop",
                    "confidence": 0.8,
                    "count": laptop_count,
                })

        except Exception as exc:
            logger.error(f"YOLO detection error: {exc}")

        return result

    def _haar_fallback(self, frame: np.ndarray) -> DetectionResult:
        """Fallback person count using Haar cascade face detection."""
        result = DetectionResult()
        if self._face_cascade is None:
            return result

        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self._face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=3, minSize=(40, 40)
            )
            result.person_count = len(faces)
        except Exception:
            pass

        return result

    @staticmethod
    def _decode_frame(frame_b64: str) -> Optional[np.ndarray]:
        if not CV2_AVAILABLE:
            return None
        try:
            img_bytes = base64.b64decode(frame_b64)
            nparr = np.frombuffer(img_bytes, np.uint8)
            return cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        except Exception:
            return None


# ══════════════════════════════════════════════════════════════════════
# Module 6: Face Absence Monitor
# ══════════════════════════════════════════════════════════════════════

class FaceAbsenceMonitor:
    """
    Monitors whether the candidate's face is continuously visible.

    Fires a 'face_absent' event when no face is detected for > threshold seconds.
    Handles edge cases: temporary occlusion, low lighting, camera glitches.
    """

    def __init__(self, absence_threshold_sec: float = 10.0, grace_frames: int = 3):
        self._threshold = absence_threshold_sec
        self._grace_frames = grace_frames  # allow this many missed frames before starting timer
        self._absence_start: Optional[float] = None
        self._consecutive_missing: int = 0
        self._total_absence_sec: float = 0.0
        self._absence_events: int = 0

    def update(self, face_detected: bool) -> Dict[str, Any]:
        """Update with latest face detection result.

        Returns dict with:
          - face_absent: bool (currently absent)
          - absence_duration_sec: float (current absence duration)
          - triggered: bool (just crossed threshold)
          - total_absence_sec: float (cumulative)
        """
        now = time.time()

        if face_detected:
            # Face is back — reset
            if self._absence_start is not None:
                duration = now - self._absence_start
                self._total_absence_sec += duration
            self._absence_start = None
            self._consecutive_missing = 0
            return {
                "face_absent": False,
                "absence_duration_sec": 0,
                "triggered": False,
                "total_absence_sec": round(self._total_absence_sec, 1),
            }

        # Face not detected
        self._consecutive_missing += 1

        # Grace period — tolerate a few missed frames (camera glitch, blink, etc.)
        if self._consecutive_missing <= self._grace_frames:
            return {
                "face_absent": False,
                "absence_duration_sec": 0,
                "triggered": False,
                "total_absence_sec": round(self._total_absence_sec, 1),
            }

        # Start absence timer
        if self._absence_start is None:
            self._absence_start = now

        duration = now - self._absence_start
        triggered = False

        # Check if just crossed threshold
        if duration >= self._threshold:
            # Only fire once per extended absence
            pre_thresh = duration - (now - self._absence_start if self._absence_start else 0)
            check_period = 2.0  # Check every 2 seconds after threshold
            if int(duration / check_period) > int((duration - check_period) / check_period):
                triggered = True
                self._absence_events += 1

        return {
            "face_absent": True,
            "absence_duration_sec": round(duration, 1),
            "triggered": duration >= self._threshold,
            "total_absence_sec": round(self._total_absence_sec + duration, 1),
        }

    @property
    def total_absence_time(self) -> float:
        return self._total_absence_sec

    @property
    def absence_event_count(self) -> int:
        return self._absence_events


# ══════════════════════════════════════════════════════════════════════
# Module 7: Attention Monitor (Head Pose Estimation)
# ══════════════════════════════════════════════════════════════════════

class AttentionMonitor:
    """
    Track head direction using facial landmarks from the face region.

    Detects: looking left, looking right, looking down, excessive movement.
    Uses face and eye position relative to frame center as proxy for head pose.
    """

    def __init__(self, window_size: int = 15, away_threshold: float = 0.35):
        self._window: deque = deque(maxlen=window_size)
        self._away_threshold = away_threshold  # face offset from center
        self._away_count = 0
        self._total_checks = 0
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

    def analyze(self, frame: np.ndarray) -> Dict[str, Any]:
        """Analyze head direction from an OpenCV frame.

        Returns:
          - direction: 'center' | 'left' | 'right' | 'down' | 'up' | 'absent'
          - attention_score: 0-100 (100 = fully attentive)
          - looking_away: bool
          - excessive_movement: bool
        """
        if not CV2_AVAILABLE or self._face_cascade is None or frame is None:
            return self._default_result()

        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self._face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=3, minSize=(40, 40)
            )

            if len(faces) == 0:
                self._window.append("absent")
                self._total_checks += 1
                self._away_count += 1
                return {
                    "direction": "absent",
                    "attention_score": 0,
                    "looking_away": True,
                    "excessive_movement": self._check_excessive_movement(),
                }

            # Primary face
            fx, fy, fw, fh = faces[0]
            frame_h, frame_w = frame.shape[:2]

            # Compute face center offset
            face_cx = (fx + fw / 2) / frame_w  # 0-1, 0.5 = center
            face_cy = (fy + fh / 2) / frame_h

            # Determine direction
            direction = "center"
            horizontal_offset = face_cx - 0.5
            vertical_offset = face_cy - 0.5

            if abs(horizontal_offset) > self._away_threshold:
                direction = "right" if horizontal_offset > 0 else "left"
            elif vertical_offset > 0.3:
                direction = "down"
            elif vertical_offset < -0.25:
                direction = "up"

            # Eye detection for refinement
            if self._eye_cascade is not None:
                eye_roi = gray[fy:fy + int(fh * 0.65), fx:fx + fw]
                eyes = self._eye_cascade.detectMultiScale(
                    eye_roi, scaleFactor=1.05, minNeighbors=3, minSize=(15, 15)
                )
                if len(eyes) == 0 and direction == "center":
                    # Face centered but no eyes — possibly looking down
                    direction = "down"

            self._window.append(direction)
            self._total_checks += 1
            looking_away = direction not in ("center",)

            if looking_away:
                self._away_count += 1

            # Attention score from recent window
            recent = list(self._window)
            center_count = sum(1 for d in recent if d == "center")
            attention_score = (center_count / max(len(recent), 1)) * 100

            return {
                "direction": direction,
                "attention_score": round(attention_score, 1),
                "looking_away": looking_away,
                "excessive_movement": self._check_excessive_movement(),
            }

        except Exception as exc:
            logger.error(f"Attention analysis error: {exc}")
            return self._default_result()

    def _check_excessive_movement(self) -> bool:
        """Check if there is excessive head movement (rapid direction changes)."""
        if len(self._window) < 5:
            return False
        recent = list(self._window)[-10:]
        transitions = sum(
            1 for i in range(1, len(recent))
            if recent[i] != recent[i - 1] and recent[i] != "absent"
        )
        return transitions >= 5  # 5+ direction changes in last 10 frames

    @property
    def away_percentage(self) -> float:
        if self._total_checks == 0:
            return 0.0
        return (self._away_count / self._total_checks) * 100

    @staticmethod
    def _default_result() -> Dict[str, Any]:
        return {
            "direction": "unknown",
            "attention_score": 50.0,
            "looking_away": False,
            "excessive_movement": False,
        }


# ══════════════════════════════════════════════════════════════════════
# Module 8: Risk Scoring Engine
# ══════════════════════════════════════════════════════════════════════

class RiskScoringEngine:
    """
    Maintains a cumulative cheating risk score for the interview session.

    Scoring:
      Face mismatch     = +50
      Multiple persons  = +40
      Phone detected    = +30
      Face absent       = +20
      Suspicious object = +20
      Looking away      = +10
      Tab switch        = +15

    Thresholds:
      0-29:   SAFE
      30-49:  SUSPICIOUS
      50+:    HIGH_RISK
    """

    def __init__(self):
        self._score: int = 0
        self._history: List[Dict[str, Any]] = []

    def add_risk(self, violation_type: str, confidence: float = 1.0, details: str = "") -> int:
        """Add risk points for a violation.

        Returns: new total risk score.
        """
        base_points = RISK_WEIGHTS.get(violation_type, 10)
        points = int(base_points * min(confidence, 1.0))

        self._score += points
        self._history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "violation_type": violation_type,
            "points_added": points,
            "new_total": self._score,
            "details": details,
        })

        return self._score

    @property
    def score(self) -> int:
        return self._score

    @property
    def verdict(self) -> str:
        if self._score >= HIGH_RISK_THRESHOLD:
            return "HIGH_RISK"
        elif self._score >= 30:
            return "SUSPICIOUS"
        return "SAFE"

    @property
    def is_high_risk(self) -> bool:
        return self._score >= HIGH_RISK_THRESHOLD

    def get_summary(self) -> Dict[str, Any]:
        return {
            "risk_score": self._score,
            "verdict": self.verdict,
            "is_high_risk": self.is_high_risk,
            "risk_history": self._history[-50:],  # Last 50 events
        }


# ══════════════════════════════════════════════════════════════════════
# Module 9: Violation Logger
# ══════════════════════════════════════════════════════════════════════

class ViolationLogger:
    """
    Structured violation logging with optional frame thumbnails.

    Stores entries as ViolationEntry objects with:
      - timestamp, violation_type, confidence_score, risk_points, details
      - frame_thumbnail (small base64 JPEG snapshot)
    """

    MAX_LOG_SIZE = 500

    def __init__(self):
        self._entries: List[ViolationEntry] = []

    def log(
        self,
        violation_type: str,
        confidence: float,
        risk_points: int,
        details: str,
        frame: Optional[np.ndarray] = None,
    ) -> ViolationEntry:
        """Log a violation event. Optionally capture a frame thumbnail."""
        thumbnail = None
        if frame is not None and CV2_AVAILABLE:
            try:
                # Resize to tiny thumbnail to save space
                thumb = cv2.resize(frame, (160, 120))
                _, buf = cv2.imencode('.jpg', thumb, [cv2.IMWRITE_JPEG_QUALITY, 40])
                thumbnail = base64.b64encode(buf).decode('utf-8')
            except Exception:
                pass

        entry = ViolationEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            violation_type=violation_type,
            confidence_score=confidence,
            risk_points=risk_points,
            details=details,
            frame_thumbnail=thumbnail,
        )

        self._entries.append(entry)

        # Prevent unbounded growth
        if len(self._entries) > self.MAX_LOG_SIZE:
            self._entries = self._entries[-self.MAX_LOG_SIZE:]

        logger.info(f"VIOLATION [{violation_type}] conf={confidence:.2f} pts={risk_points} — {details}")
        return entry

    @property
    def entries(self) -> List[ViolationEntry]:
        return self._entries

    @property
    def count(self) -> int:
        return len(self._entries)

    def get_by_type(self, violation_type: str) -> List[ViolationEntry]:
        return [e for e in self._entries if e.violation_type == violation_type]

    def get_timeline(self) -> List[Dict[str, Any]]:
        """Return a timeline of all violations (without thumbnails for compactness)."""
        return [
            {
                "timestamp": e.timestamp,
                "violation_type": e.violation_type,
                "confidence_score": round(e.confidence_score, 2),
                "risk_points": e.risk_points,
                "details": e.details,
            }
            for e in self._entries
        ]


# ══════════════════════════════════════════════════════════════════════
# Module 10: Interview Integrity Report Generator
# ══════════════════════════════════════════════════════════════════════

class IntegrityReportGenerator:
    """Generate an end-of-interview integrity report."""

    @staticmethod
    def generate(
        session_start: float,
        risk_engine: RiskScoringEngine,
        violation_logger: ViolationLogger,
        face_absence_monitor: FaceAbsenceMonitor,
        attention_monitor: AttentionMonitor,
        identity_verifications: int,
        identity_mismatches: int,
        person_alerts: int,
        suspicious_object_events: int,
        tab_switches: int,
    ) -> Dict[str, Any]:
        """Generate the final integrity report.

        Returns a comprehensive report dict.
        """
        now = time.time()
        duration_sec = now - session_start if session_start else 0
        duration_min = duration_sec / 60

        total_violations = violation_logger.count

        # Violation breakdown
        violation_types = {}
        for entry in violation_logger.entries:
            vt = entry.violation_type
            violation_types[vt] = violation_types.get(vt, 0) + 1

        report = {
            "report_generated_at": datetime.now(timezone.utc).isoformat(),
            "interview_duration_minutes": round(duration_min, 1),
            "interview_duration_seconds": round(duration_sec, 0),

            # Identity verification
            "identity": {
                "total_verifications": identity_verifications,
                "mismatches": identity_mismatches,
                "mismatch_rate": round(
                    (identity_mismatches / max(identity_verifications, 1)) * 100, 1
                ),
                "identity_verified": identity_mismatches == 0,
            },

            # Violation summary
            "violations": {
                "total_count": total_violations,
                "breakdown": violation_types,
                "timeline": violation_logger.get_timeline()[-100:],
            },

            # Detailed stats
            "proctoring_stats": {
                "person_alerts": person_alerts,
                "suspicious_objects_detected": suspicious_object_events,
                "tab_switches": tab_switches,
                "face_absence_total_sec": round(face_absence_monitor.total_absence_time, 1),
                "face_absence_events": face_absence_monitor.absence_event_count,
                "attention_away_percentage": round(attention_monitor.away_percentage, 1),
            },

            # Risk assessment
            "risk_assessment": risk_engine.get_summary(),

            # Final verdict
            "final_verdict": risk_engine.verdict,
            "integrity_score": max(0, 100 - risk_engine.score),
        }

        return report


# ══════════════════════════════════════════════════════════════════════
# Main: ProctorSession — orchestrates all modules for one interview
# ══════════════════════════════════════════════════════════════════════

class ProctorSession:
    """
    Per-interview proctoring session that orchestrates all modules.

    Lifecycle:
      1. create session → ProctorSession()
      2. register face → register_face(frame_b64) × 5-10 times
      3. process frame → process_frame(frame_b64) every 2-3 seconds
      4. end session → generate_report()

    Thread-safety: not required — one session per candidate, sequential calls.
    """

    # Identity verification interval
    VERIFY_INTERVAL_SEC = 4.0
    FACE_SIMILARITY_THRESHOLD = 0.55  # Cosine similarity threshold for identity match

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._start_time = time.time()
        self._last_verify_time = 0.0

        # Module instances
        self._embedding_engine = FaceEmbeddingEngine()
        self._object_detector = ObjectDetectionEngine()
        self._absence_monitor = FaceAbsenceMonitor(absence_threshold_sec=10.0)
        self._attention_monitor = AttentionMonitor()
        self._risk_engine = RiskScoringEngine()
        self._violation_logger = ViolationLogger()

        # Reference embeddings (registered at start)
        self._reference_embeddings: List[np.ndarray] = []
        self._reference_embedding: Optional[np.ndarray] = None  # Average

        # Counters
        self._identity_verifications = 0
        self._identity_mismatches = 0
        self._person_alerts = 0
        self._suspicious_object_events = 0
        self._tab_switches = 0
        self._total_frames_processed = 0
        self._registration_complete = False
        # Consecutive multi-person detection counter (avoids single-frame false positives)
        self._consecutive_multi_person = 0
        self._MULTI_PERSON_CONFIRM_FRAMES = 2  # require 2 consecutive detections

        # Cooldowns to avoid duplicate alerts
        self._last_mismatch_time = 0.0
        self._last_person_alert_time = 0.0
        self._last_object_alert_time = 0.0
        self._MISMATCH_COOLDOWN = 15.0   # seconds between identity mismatch alerts
        self._PERSON_COOLDOWN = 10.0
        self._OBJECT_COOLDOWN = 20.0

    # ── Registration ──────────────────────────────────────────────

    def register_face(self, frame_b64: str) -> Dict[str, Any]:
        """Register a face frame for identity baseline.

        Call 5-10 times at the start of the interview.
        Returns registration status.
        """
        embedding = self._embedding_engine.extract_embedding_b64(frame_b64)

        if embedding is None:
            return {
                "registered": False,
                "frames_collected": len(self._reference_embeddings),
                "message": "No face detected in frame — ensure your face is visible",
            }

        self._reference_embeddings.append(embedding)

        # Compute running average
        self._reference_embedding = np.mean(self._reference_embeddings, axis=0)

        # Registration is solid after 3+ embeddings
        if len(self._reference_embeddings) >= 3:
            self._registration_complete = True

        return {
            "registered": True,
            "frames_collected": len(self._reference_embeddings),
            "registration_complete": self._registration_complete,
            "message": f"Face registered ({len(self._reference_embeddings)} frames captured)" +
                       (" — Registration complete!" if self._registration_complete else " — Keep looking at camera"),
        }

    @property
    def is_registered(self) -> bool:
        return self._registration_complete and self._reference_embedding is not None

    # ── Main Processing Pipeline ──────────────────────────────────

    def process_frame(self, frame_b64: str) -> Dict[str, Any]:
        """Process a single video frame through the full proctoring pipeline.

        This is the main entry point, called every 2-3 seconds during the interview.

        Pipeline:
          1. Decode frame
          2. Object detection (YOLO) → person count + suspicious objects
          3. Face absence monitoring
          4. Identity verification (every VERIFY_INTERVAL_SEC)
          5. Attention monitoring (head direction)
          6. Risk score update
          7. Return combined result

        Returns a comprehensive dict with all detection results.
        """
        self._total_frames_processed += 1
        now = time.time()

        # Decode frame
        frame = self._decode_frame(frame_b64)

        # ── 1. Object Detection ──────────────────────────────────
        detection = DetectionResult()
        if frame is not None:
            detection = self._object_detector.detect(frame)

        # Multiple persons — require consecutive detections to avoid false positives
        # (clothes on chairs, posters, etc. can trigger single-frame false positives)
        if detection.person_count > 1:
            self._consecutive_multi_person += 1
        else:
            self._consecutive_multi_person = 0

        if (self._consecutive_multi_person >= self._MULTI_PERSON_CONFIRM_FRAMES
                and (now - self._last_person_alert_time) > self._PERSON_COOLDOWN):
            self._person_alerts += 1
            self._last_person_alert_time = now
            pts = self._risk_engine.add_risk(
                "multiple_persons", confidence=0.9,
                details=f"{detection.person_count} persons detected",
            )
            self._violation_logger.log(
                "multiple_persons", 0.9, RISK_WEIGHTS["multiple_persons"],
                f"{detection.person_count} persons detected in frame",
                frame=frame,
            )

        # Suspicious objects
        if detection.suspicious_objects and (now - self._last_object_alert_time) > self._OBJECT_COOLDOWN:
            self._last_object_alert_time = now
            for obj in detection.suspicious_objects:
                self._suspicious_object_events += 1
                obj_type = obj["type"]
                risk_type = "phone_detected" if obj_type == "cell_phone" else "suspicious_object"
                self._risk_engine.add_risk(
                    risk_type, confidence=obj.get("confidence", 0.5),
                    details=f"Suspicious object detected: {obj_type}",
                )
                self._violation_logger.log(
                    risk_type, obj.get("confidence", 0.5),
                    RISK_WEIGHTS.get(risk_type, 20),
                    f"{obj_type} detected with {obj.get('confidence', 0):.0%} confidence",
                    frame=frame,
                )

        # ── 2. Attention Monitoring (run BEFORE identity verification) ──
        # Running attention first lets us distinguish "looking away" from
        # "different person" — a turned head produces a different embedding
        # but is NOT a person change.
        attention_result = self._attention_monitor.analyze(frame) if frame is not None else self._attention_monitor._default_result()
        is_looking_away = attention_result.get("looking_away", False)

        if attention_result.get("excessive_movement"):
            self._risk_engine.add_risk(
                "attention_away", confidence=0.5,
                details="Excessive head movement detected",
            )
            self._violation_logger.log(
                "attention_away", 0.5, RISK_WEIGHTS["attention_away"],
                "Excessive head movement pattern detected",
                frame=frame,
            )

        # ── 3. Face Presence Detection ──────────────────────────
        face_detected = detection.person_count >= 1  # at least one person
        # Refine: check if we got an embedding (more reliable for face)
        has_face_embedding = False

        # ── 4. Identity Verification (periodic) ─────────────────
        # Skip verification when the candidate is looking away — a turned
        # head naturally produces a different embedding and would cause
        # false "person mismatch" alerts.
        identity_result = None
        can_verify = not is_looking_away and attention_result.get("direction") not in ("absent", "left", "right", "down", "up")
        if self.is_registered and (now - self._last_verify_time) >= self.VERIFY_INTERVAL_SEC:
            if can_verify:
                self._last_verify_time = now
                current_embedding = self._embedding_engine.extract_embedding(frame) if frame is not None else None

                if current_embedding is not None:
                    has_face_embedding = True
                    similarity = self._embedding_engine.cosine_similarity(
                        self._reference_embedding, current_embedding
                    )
                    self._identity_verifications += 1
                    is_match = similarity >= self.FACE_SIMILARITY_THRESHOLD

                    identity_result = {
                        "verified": is_match,
                        "similarity": round(similarity, 3),
                        "threshold": self.FACE_SIMILARITY_THRESHOLD,
                    }

                    if not is_match and (now - self._last_mismatch_time) > self._MISMATCH_COOLDOWN:
                        self._identity_mismatches += 1
                        self._last_mismatch_time = now
                        self._risk_engine.add_risk(
                            "face_mismatch", confidence=1.0 - similarity,
                            details=f"Person change suspected: similarity={similarity:.3f} < threshold={self.FACE_SIMILARITY_THRESHOLD}",
                        )
                        self._violation_logger.log(
                            "face_mismatch", 1.0 - similarity,
                            RISK_WEIGHTS["face_mismatch"],
                            f"Person change detected — face does not match registered candidate (similarity: {similarity:.3f})",
                            frame=frame,
                        )
            else:
                # Looking away — don't verify identity but don't consume the timer
                # so verification runs on the next frame where face is centered
                pass

        # Use embedding result for face detection if available
        if has_face_embedding:
            face_detected = True

        # ── 5. Face Absence Monitoring ──────────────────────────
        absence_result = self._absence_monitor.update(face_detected)

        if absence_result.get("triggered") and absence_result.get("face_absent"):
            dur = absence_result.get("absence_duration_sec", 0)
            self._risk_engine.add_risk(
                "face_absent", confidence=0.8,
                details=f"Candidate left camera for {dur:.0f}s",
            )
            self._violation_logger.log(
                "face_absent", 0.8, RISK_WEIGHTS["face_absent"],
                f"Face absent for {dur:.0f} seconds",
                frame=frame,
            )

        # ── Build Response ──────────────────────────────────────
        return _sanitize_for_json({
            "person_count": detection.person_count,
            "suspicious_objects": detection.suspicious_objects,
            "bounding_boxes": detection.bounding_boxes,
            "face_absent": absence_result.get("face_absent", False),
            "absence_duration_sec": absence_result.get("absence_duration_sec", 0),
            "identity": identity_result,
            "attention": attention_result,
            "risk": {
                "score": self._risk_engine.score,
                "verdict": self._risk_engine.verdict,
                "is_high_risk": self._risk_engine.is_high_risk,
            },
            "total_violations": self._violation_logger.count,
        })

    # ── Tab Switch (called from router) ──────────────────────────

    def log_tab_switch(self, details: str = ""):
        """Log a tab switch violation."""
        self._tab_switches += 1
        self._risk_engine.add_risk(
            "tab_switch", confidence=1.0,
            details=details or "Tab switch detected",
        )
        self._violation_logger.log(
            "tab_switch", 1.0, RISK_WEIGHTS["tab_switch"],
            details or "Candidate switched browser tab / minimized window",
        )

    # ── Report Generation ────────────────────────────────────────

    def generate_report(self) -> Dict[str, Any]:
        """Generate the final integrity report for this session."""
        return _sanitize_for_json(IntegrityReportGenerator.generate(
            session_start=self._start_time,
            risk_engine=self._risk_engine,
            violation_logger=self._violation_logger,
            face_absence_monitor=self._absence_monitor,
            attention_monitor=self._attention_monitor,
            identity_verifications=self._identity_verifications,
            identity_mismatches=self._identity_mismatches,
            person_alerts=self._person_alerts,
            suspicious_object_events=self._suspicious_object_events,
            tab_switches=self._tab_switches,
        ))

    def get_status(self) -> Dict[str, Any]:
        """Get current proctoring status (for live dashboard)."""
        return {
            "session_id": self.session_id,
            "is_registered": self.is_registered,
            "frames_processed": self._total_frames_processed,
            "registration_frames": len(self._reference_embeddings),
            "identity_verifications": self._identity_verifications,
            "identity_mismatches": self._identity_mismatches,
            "person_alerts": self._person_alerts,
            "suspicious_object_events": self._suspicious_object_events,
            "tab_switches": self._tab_switches,
            "risk_score": self._risk_engine.score,
            "risk_verdict": self._risk_engine.verdict,
            "total_violations": self._violation_logger.count,
            "face_absence_total_sec": round(self._absence_monitor.total_absence_time, 1),
        }

    # ── Cleanup ──────────────────────────────────────────────────

    def cleanup(self):
        """Release resources held by this session."""
        self._reference_embeddings.clear()
        self._reference_embedding = None

    # ── Internal ─────────────────────────────────────────────────

    @staticmethod
    def _decode_frame(frame_b64: str) -> Optional[np.ndarray]:
        if not CV2_AVAILABLE or not frame_b64:
            return None
        try:
            img_bytes = base64.b64decode(frame_b64)
            nparr = np.frombuffer(img_bytes, np.uint8)
            return cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        except Exception:
            return None


# ══════════════════════════════════════════════════════════════════════
# Session Manager — singleton that manages all active ProctorSessions
# ══════════════════════════════════════════════════════════════════════

class ProctorSessionManager:
    """
    Global manager for all active proctoring sessions.

    Thread-safe via simple dict; FastAPI runs in async single-thread by default.
    """

    def __init__(self):
        self._sessions: Dict[str, ProctorSession] = {}

    def get_or_create(self, session_id: str) -> ProctorSession:
        """Get existing session or create a new one."""
        if session_id not in self._sessions:
            self._sessions[session_id] = ProctorSession(session_id)
            logger.info(f"Created ProctorSession for {session_id}")
        return self._sessions[session_id]

    def get(self, session_id: str) -> Optional[ProctorSession]:
        """Get existing session or None."""
        return self._sessions.get(session_id)

    def remove(self, session_id: str):
        """Remove and cleanup a session."""
        session = self._sessions.pop(session_id, None)
        if session:
            session.cleanup()
            logger.info(f"Removed ProctorSession for {session_id}")

    @property
    def active_count(self) -> int:
        return len(self._sessions)


# ── Global singleton ─────────────────────────────────────────────────
proctor_manager = ProctorSessionManager()
