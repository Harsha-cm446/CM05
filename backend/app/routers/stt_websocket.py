"""
WebSocket endpoint for real-time Speech-to-Text using Vosk.

The frontend streams raw PCM 16-bit mono 16kHz audio chunks via WebSocket.
The server feeds them to Vosk and returns partial/final transcriptions in real time.

Protocol:
  Client → Server:  binary frames (raw PCM 16-bit LE mono, 16000 Hz)
                     OR JSON: {"type": "config", "sample_rate": 16000}
                     OR JSON: {"type": "eof"}  — signals end of speech

  Server → Client:  JSON: {"type": "partial", "text": "hello wor"}
                     JSON: {"type": "final",   "text": "hello world"}
                     JSON: {"type": "error",   "message": "..."}
                     JSON: {"type": "ready",   "engine": "vosk"}
"""

import json
import sys
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

# Add ai-engine to path so we can import speech_to_text
_ai_engine_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "ai-engine")
if os.path.isdir(_ai_engine_dir):
    sys.path.insert(0, os.path.abspath(_ai_engine_dir))

try:
    from speech_to_text import (
        VOSK_AVAILABLE,
        create_vosk_recognizer,
        transcribe_audio_chunk,
        finalize_vosk,
        get_vosk_model,
    )
except ImportError:
    VOSK_AVAILABLE = False
    create_vosk_recognizer = None
    transcribe_audio_chunk = None
    finalize_vosk = None
    get_vosk_model = None


@router.websocket("/ws/stt")
async def stt_websocket(websocket: WebSocket):
    """
    Real-time speech-to-text WebSocket endpoint.

    1. Client connects
    2. Server sends {"type": "ready", "engine": "vosk"}
    3. Client sends binary audio frames (PCM 16-bit LE, mono, 16kHz)
    4. Server responds with partial and final transcription JSON
    5. Client sends {"type": "eof"} when done → server sends final result
    """
    await websocket.accept()

    if not VOSK_AVAILABLE:
        await websocket.send_json({
            "type": "error",
            "message": "Vosk STT engine not available on server. Install vosk: pip install vosk",
        })
        await websocket.close(code=4000)
        return

    sample_rate = 16000
    recognizer = create_vosk_recognizer(sample_rate)

    if recognizer is None:
        await websocket.send_json({
            "type": "error",
            "message": "Failed to initialize Vosk recognizer. Model may not be downloaded yet.",
        })
        await websocket.close(code=4000)
        return

    # Signal readiness
    await websocket.send_json({"type": "ready", "engine": "vosk"})

    full_text = ""  # accumulate all final text segments

    try:
        while True:
            message = await websocket.receive()

            # Binary frame — raw PCM audio data
            if "bytes" in message and message["bytes"]:
                audio_data = message["bytes"]
                result = transcribe_audio_chunk(recognizer, audio_data)

                if result["is_final"] and result["text"]:
                    full_text += (" " + result["text"]) if full_text else result["text"]
                    await websocket.send_json({
                        "type": "final",
                        "text": result["text"],
                        "full_text": full_text.strip(),
                    })
                elif result["partial"]:
                    await websocket.send_json({
                        "type": "partial",
                        "text": result["partial"],
                        "full_text": (full_text + " " + result["partial"]).strip(),
                    })

            # Text frame — JSON command
            elif "text" in message and message["text"]:
                try:
                    data = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type", "")

                if msg_type == "config":
                    # Client wants to change sample rate — create new recognizer
                    new_rate = int(data.get("sample_rate", 16000))
                    if new_rate != sample_rate:
                        sample_rate = new_rate
                        recognizer = create_vosk_recognizer(sample_rate)
                        full_text = ""
                        await websocket.send_json({
                            "type": "ready",
                            "engine": "vosk",
                            "sample_rate": sample_rate,
                        })

                elif msg_type == "eof":
                    # End of speech — flush final result
                    final = finalize_vosk(recognizer)
                    if final["text"]:
                        full_text += (" " + final["text"]) if full_text else final["text"]
                    await websocket.send_json({
                        "type": "final",
                        "text": final.get("text", ""),
                        "full_text": full_text.strip(),
                        "done": True,
                    })
                    # Reset recognizer for next utterance
                    recognizer = create_vosk_recognizer(sample_rate)
                    full_text = ""

                elif msg_type == "reset":
                    # Reset for a new question
                    recognizer = create_vosk_recognizer(sample_rate)
                    full_text = ""
                    await websocket.send_json({"type": "ready", "engine": "vosk"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
