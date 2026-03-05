"""
AI Engine – Speech-to-Text using Vosk (FREE, local, real-time streaming)
with faster-whisper as fallback for batch transcription.

Why Vosk over OpenAI Whisper?
  • Real-time streaming support (word-by-word)
  • Works accurately with normal speech volume & pace
  • Lightweight — no GPU required
  • Free & fully offline
  • Low latency (~100ms)

faster-whisper (CTranslate2-based) is used as a secondary engine
for file-based batch transcription with higher accuracy.
"""

import tempfile
import base64
import os
import json
import wave

# ── Vosk (primary — real-time streaming) ──────────────

try:
    from vosk import Model as VoskModel, KaldiRecognizer, SetLogLevel
    SetLogLevel(-1)  # suppress Vosk logs
    VOSK_AVAILABLE = True
except ImportError:
    VOSK_AVAILABLE = False

_vosk_model = None
VOSK_MODEL_PATH = os.environ.get("VOSK_MODEL_PATH", "")
# Default model name to download if no path specified
VOSK_MODEL_NAME = os.environ.get("VOSK_MODEL_NAME", "vosk-model-en-us-0.22")


def get_vosk_model():
    """Load and cache the Vosk speech recognition model."""
    global _vosk_model
    if _vosk_model is not None:
        return _vosk_model
    if not VOSK_AVAILABLE:
        return None

    try:
        if VOSK_MODEL_PATH and os.path.isdir(VOSK_MODEL_PATH):
            _vosk_model = VoskModel(VOSK_MODEL_PATH)
        else:
            # Vosk auto-downloads the model if not present
            _vosk_model = VoskModel(model_name=VOSK_MODEL_NAME)
        print(f"✅ Vosk model loaded: {VOSK_MODEL_NAME}")
        return _vosk_model
    except Exception as e:
        print(f"⚠️ Vosk model load failed: {e}")
        return None


def create_vosk_recognizer(sample_rate: int = 16000):
    """Create a new Vosk recognizer for streaming audio."""
    model = get_vosk_model()
    if model is None:
        return None
    rec = KaldiRecognizer(model, sample_rate)
    rec.SetWords(True)           # include word-level timestamps
    rec.SetPartialWords(True)    # include partial results
    return rec


def transcribe_audio_chunk(recognizer, audio_data: bytes) -> dict:
    """
    Feed an audio chunk to the Vosk recognizer.
    Returns partial or final result.

    audio_data: raw PCM 16-bit mono audio bytes
    """
    if recognizer is None:
        return {"text": "", "partial": "", "is_final": False}

    if recognizer.AcceptWaveform(audio_data):
        result = json.loads(recognizer.Result())
        return {
            "text": result.get("text", ""),
            "partial": "",
            "is_final": True,
            "words": result.get("result", []),
        }
    else:
        partial = json.loads(recognizer.PartialResult())
        return {
            "text": "",
            "partial": partial.get("partial", ""),
            "is_final": False,
        }


def finalize_vosk(recognizer) -> dict:
    """Get the final result from Vosk recognizer (call at end of stream)."""
    if recognizer is None:
        return {"text": "", "is_final": True}
    result = json.loads(recognizer.FinalResult())
    return {
        "text": result.get("text", ""),
        "is_final": True,
        "words": result.get("result", []),
    }


# ── faster-whisper (secondary — batch file transcription) ──────

try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False

_fw_model = None
# Model size: tiny, base, small, medium, large-v3
# "small" gives the best accuracy-to-speed balance for free/local use
FW_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "small")


def get_faster_whisper_model():
    """Load and cache the faster-whisper model for batch transcription."""
    global _fw_model
    if _fw_model is not None:
        return _fw_model
    if not FASTER_WHISPER_AVAILABLE:
        return None
    try:
        _fw_model = WhisperModel(
            FW_MODEL_SIZE,
            device="cpu",
            compute_type="int8",  # fastest on CPU
        )
        print(f"✅ faster-whisper model loaded: {FW_MODEL_SIZE}")
        return _fw_model
    except Exception as e:
        print(f"⚠️ faster-whisper load failed: {e}")
        return None


# ── Legacy Whisper fallback ────────────────────────────

try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

_whisper_model = None


def get_whisper_model():
    global _whisper_model
    if _whisper_model is None and WHISPER_AVAILABLE:
        _whisper_model = whisper.load_model("base")
    return _whisper_model


# ── Public API — Batch transcription ──────────────────

def transcribe_audio_base64(audio_b64: str, language: str = "en") -> dict:
    """Transcribe base64-encoded audio to text using best available engine."""
    try:
        audio_bytes = base64.b64decode(audio_b64)

        # Save to temp WAV file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            temp_path = f.name

        result = transcribe_audio_file(temp_path, language)
        os.unlink(temp_path)
        return result

    except Exception as e:
        return {"text": "", "error": str(e)}


def transcribe_audio_file(file_path: str, language: str = "en") -> dict:
    """
    Transcribe an audio file using the best available engine.
    Priority: faster-whisper > Vosk > legacy whisper
    """

    # 1) Try faster-whisper (best accuracy for batch)
    if FASTER_WHISPER_AVAILABLE:
        try:
            model = get_faster_whisper_model()
            if model:
                segments, info = model.transcribe(
                    file_path,
                    language=language,
                    beam_size=5,
                    vad_filter=True,          # Voice Activity Detection — filters silence/noise
                    vad_parameters=dict(
                        min_silence_duration_ms=300,
                        speech_pad_ms=200,
                    ),
                )
                text = " ".join(seg.text.strip() for seg in segments)
                return {
                    "text": text,
                    "language": info.language,
                    "engine": "faster-whisper",
                }
        except Exception as e:
            print(f"faster-whisper error: {e}")

    # 2) Try Vosk (full-file mode)
    if VOSK_AVAILABLE:
        try:
            rec = create_vosk_recognizer(16000)
            if rec:
                text = _vosk_transcribe_file(file_path, rec)
                if text:
                    return {"text": text, "language": language, "engine": "vosk"}
        except Exception as e:
            print(f"Vosk file transcription error: {e}")

    # 3) Fallback to legacy OpenAI whisper
    if WHISPER_AVAILABLE:
        try:
            model = get_whisper_model()
            result = model.transcribe(file_path, language=language)
            return {
                "text": result.get("text", "").strip(),
                "language": result.get("language", language),
                "engine": "whisper-legacy",
            }
        except Exception as e:
            print(f"Legacy whisper error: {e}")

    return {"text": "", "error": "No speech recognition engine available"}


def _vosk_transcribe_file(file_path: str, recognizer) -> str:
    """Transcribe a WAV file using Vosk recognizer."""
    import subprocess

    # Convert to 16kHz mono WAV using ffmpeg if needed
    converted_path = file_path + ".16k.wav"
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", file_path,
                "-ar", "16000", "-ac", "1", "-f", "wav",
                converted_path
            ],
            capture_output=True, timeout=30,
        )
        use_path = converted_path
    except Exception:
        use_path = file_path

    try:
        with wave.open(use_path, "rb") as wf:
            while True:
                data = wf.readframes(4000)
                if len(data) == 0:
                    break
                recognizer.AcceptWaveform(data)

        result = json.loads(recognizer.FinalResult())
        return result.get("text", "")
    finally:
        if os.path.exists(converted_path):
            os.unlink(converted_path)


# ── Status ─────────────────────────────────────────────

if __name__ == "__main__":
    print("AI Engine – Speech-to-Text Module")
    print(f"  Vosk:           {'✅' if VOSK_AVAILABLE else '❌'}")
    print(f"  faster-whisper: {'✅' if FASTER_WHISPER_AVAILABLE else '❌'}")
    print(f"  Whisper legacy: {'✅' if WHISPER_AVAILABLE else '❌'}")
