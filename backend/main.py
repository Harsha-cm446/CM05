"""
AI Interview Platform — Optimized Main Application
────────────────────────────────────────────────────
  • AI models warm-loaded at startup for < 3s interview start
  • Groq API (llama-3.3-70b-versatile) for LLM inference
  • CORS allows all origins for public access
  • Bind to 0.0.0.0 for network-wide access
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import connect_to_mongo, close_mongo_connection
from app.routers import auth, interviews, mock_interview, websocket, candidate_interview, practice_mode, analytics, data_collection, stt_websocket
from app.services.ai_service import ai_service


# ── Lifespan (startup + shutdown) ─────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP
    await connect_to_mongo()
    # Warm up AI models so first interview starts in < 3 seconds
    try:
        await ai_service.warm_up()
    except Exception as e:
        print(f"⚠️ AI warm-up failed (non-fatal): {e}")

    # Startup diagnostics — log Groq key status so Azure logs show if it's configured
    groq_key = settings.GROQ_API_KEY
    print(f"🔑 GROQ_API_KEY configured: {bool(groq_key)}, length: {len(groq_key) if groq_key else 0}")
    if groq_key:
        print(f"   Key prefix: {groq_key[:8]}...")
    else:
        print(f"   ⚠️ GROQ_API_KEY is EMPTY — questions will use static fallbacks!")
        import os
        all_env_keys = [k for k in os.environ if 'GROQ' in k.upper()]
        print(f"   Environment vars containing 'GROQ': {all_env_keys}")


    # Pre-download and cache the Vosk STT model at startup
    # so it's ready instantly when the first interview starts
    try:
        import sys, os
        _ai_engine_dir = os.path.join(os.path.dirname(__file__), "ai-engine")
        if os.path.isdir(_ai_engine_dir):
            sys.path.insert(0, os.path.abspath(_ai_engine_dir))
        from speech_to_text import get_vosk_model, VOSK_AVAILABLE
        if VOSK_AVAILABLE:
            print("⏳ Pre-loading Vosk STT model (this may take a moment on first run)...")
            model = get_vosk_model()
            if model:
                print("✅ Vosk STT model ready")
            else:
                print("⚠️ Vosk STT model failed to load (STT will use fallback)")
        else:
            print("ℹ️ Vosk not installed — STT will use Web Speech API fallback")
    except Exception as e:
        print(f"⚠️ Vosk pre-load failed (non-fatal): {e}")

    print("🚀 AI Interview Platform ready")
    yield
    # SHUTDOWN
    try:
        await ai_service.shutdown()
    except Exception:
        pass
    await close_mongo_connection()


app = FastAPI(
    title="AI Interview Platform",
    description="AI-Based Realistic HR Interview Simulator & Recruitment Platform",
    version="2.0.0",
    lifespan=lifespan,
)

# ── CORS — allow frontend origin + local dev ─────────
origins = ["*"]
if settings.FRONTEND_URL:
    origins = [
        settings.FRONTEND_URL,
        "http://localhost:5173",
        "http://localhost:3000",
    ]
    # Also allow any Render subdomain
    if ".onrender.com" not in (settings.FRONTEND_URL or ""):
        origins.append("https://*.onrender.com")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────
app.include_router(auth.router)
app.include_router(interviews.router)
app.include_router(mock_interview.router)
app.include_router(candidate_interview.router)
app.include_router(websocket.router)
app.include_router(practice_mode.router)
app.include_router(analytics.router)
app.include_router(data_collection.router)
app.include_router(stt_websocket.router)


# ── Health check ──────────────────────────────────────

@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "AI Interview Platform API",
        "ai_ready": ai_service._warmed_up,
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "ai_warmed": ai_service._warmed_up,
        "llm_model": settings.GROQ_MODEL,
    }


@app.get("/api/diagnostics/groq")
async def groq_diagnostics():
    """Show Groq API call statistics for this server instance."""
    from app.services.model_registry import model_registry
    return model_registry.get_stats()


@app.get("/api/diagnostics/groq-test")
async def groq_test():
    """Live test: generate a sample question via Groq to verify the API key works."""
    from app.services.model_registry import model_registry
    import time as _time
    pre_stats = model_registry.get_stats()
    if not pre_stats["groq_key_configured"]:
        return {
            "status": "error",
            "error": "GROQ_API_KEY is not configured. Set it as an environment variable.",
            **pre_stats,
        }
    t0 = _time.time()
    try:
        result = await model_registry.llm_generate(
            prompt='Generate a short interview question for a software engineer. Return JSON: {"question": "..."}',
            system="Return valid JSON only.",
            fast=True,
            max_tokens=150,
        )
        elapsed = round(_time.time() - t0, 2)
        post_stats = model_registry.get_stats()
        return {
            "status": "ok" if result else "empty_response",
            "response_length": len(result),
            "response_preview": result[:300] if result else None,
            "elapsed_seconds": elapsed,
            "model_used": model_registry.active_model,
            **post_stats,
        }
    except Exception as e:
        elapsed = round(_time.time() - t0, 2)
        post_stats = model_registry.get_stats()
        return {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__,
            "elapsed_seconds": elapsed,
            **post_stats,
        }


@app.get("/api/diagnostics/groq-raw")
async def groq_raw_test():
    """Raw Groq SDK test — bypasses llm_generate error handling to expose exact errors."""
    import asyncio, time as _time, traceback
    from app.core.config import settings
    result = {"groq_key_len": len(settings.GROQ_API_KEY) if settings.GROQ_API_KEY else 0}
    if not settings.GROQ_API_KEY:
        result["error"] = "GROQ_API_KEY is empty"
        return result
    try:
        from groq import Groq
        client = Groq(api_key=settings.GROQ_API_KEY)
        result["client_created"] = True
    except Exception as e:
        result["client_error"] = f"{type(e).__name__}: {e}"
        return result
    t0 = _time.time()
    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": "Say hello in one word"}],
            temperature=0.1,
            max_tokens=10,
        )
        elapsed = round(_time.time() - t0, 2)
        text = response.choices[0].message.content if response.choices else ""
        result["status"] = "ok" if text else "empty_choices"
        result["response"] = text
        result["elapsed_seconds"] = elapsed
        result["model"] = settings.GROQ_MODEL
        result["choices_count"] = len(response.choices) if response.choices else 0
    except Exception as e:
        elapsed = round(_time.time() - t0, 2)
        result["status"] = "error"
        result["error"] = str(e)
        result["error_type"] = type(e).__name__
        result["traceback"] = traceback.format_exc()[-500:]
        result["elapsed_seconds"] = elapsed
        result["model"] = settings.GROQ_MODEL
    return result
@app.get("/api/diagnostics/proctoring")
async def proctoring_diagnostics():
    """Check whether proctoring dependencies (DeepFace, YOLO, OpenCV) are available."""
    from app.services.proctoring_service import (
        DEEPFACE_AVAILABLE, YOLO_AVAILABLE, CV2_AVAILABLE, proctor_manager
    )
    active_sessions = {}
    for sid in list(proctor_manager._sessions.keys()):
        sess = proctor_manager.get(sid)
        if sess:
            active_sessions[sid] = sess.get_status()
    return {
        "deepface_available": DEEPFACE_AVAILABLE,
        "yolo_available": YOLO_AVAILABLE,
        "cv2_available": CV2_AVAILABLE,
        "identity_verification_enabled": DEEPFACE_AVAILABLE and CV2_AVAILABLE,
        "object_detection_enabled": YOLO_AVAILABLE,
        "active_sessions_count": proctor_manager.active_count,
        "active_sessions": active_sessions,
    }


# ── Run directly: python main.py ─────────────────────
if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
    )
