"""
AI Interview Platform — Optimized Main Application
────────────────────────────────────────────────────
  • AI models warm-loaded at startup for < 3s interview start
  • Gemini API (gemini-2.5-flash) with multi-key fallback for LLM inference
  • CORS allows all origins for public access
  • Bind to 0.0.0.0 for network-wide access
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import connect_to_mongo, close_mongo_connection
from app.routers import auth, interviews, mock_interview, websocket, candidate_interview, practice_mode, analytics, data_collection, stt_websocket, gpu_admin, agora_token
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

    # Train RL adaptation agent at startup so PPO policy is active
    # Uses run_in_executor to keep the async event loop responsive
    # 200 episodes: ~1-2s on CPU, sufficient for PPO convergence
    try:
        import asyncio as _asyncio
        from app.services.rl_adaptation_service import rl_adaptation_service as _rl
        _loop = _asyncio.get_event_loop()
        await _loop.run_in_executor(None, _rl.train_agent, 200)
        print("✅ RL adaptation agent trained and ready")
    except Exception as e:
        print(f"⚠️ RL agent training failed (non-fatal): {e}")

    # Startup diagnostics — log Gemini key status so Azure logs show if it's configured
    gemini_key = settings.GEMINI_API_KEY
    print(f"🔑 GEMINI_API_KEY configured: {bool(gemini_key)}, length: {len(gemini_key) if gemini_key else 0}")
    if gemini_key:
        print(f"   Key prefix: {gemini_key[:8]}...")
    else:
        print(f"   ⚠️ GEMINI_API_KEY is EMPTY — questions will use static fallbacks!")
        import os
        all_env_keys = [k for k in os.environ if 'GEMINI' in k.upper()]
        print(f"   Environment vars containing 'GEMINI': {all_env_keys}")

    # vLLM fallback status
    if settings.VLLM_ENABLED:
        print(f"🖥️  vLLM GPU fallback: ENABLED via Modal (endpoint={settings.VLLM_ENDPOINT}, "
              f"model={settings.VLLM_MODEL})")
    else:
        print(f"ℹ️  vLLM GPU fallback: disabled (deploy modal_vllm.py and set VLLM_ENABLED=true)")


    # Pre-download and cache the Vosk STT model at startup
    # so it's ready instantly when the first interview starts
    try:
        import importlib.util
        import os
        _repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        _speech_to_text_path = os.path.join(_repo_root, "ai-engine", "speech_to_text.py")

        get_vosk_model = None
        VOSK_AVAILABLE = False
        if os.path.isfile(_speech_to_text_path):
            _spec = importlib.util.spec_from_file_location("speech_to_text", _speech_to_text_path)
            if _spec and _spec.loader:
                _speech_to_text = importlib.util.module_from_spec(_spec)
                _spec.loader.exec_module(_speech_to_text)
                get_vosk_model = getattr(_speech_to_text, "get_vosk_model", None)
                VOSK_AVAILABLE = bool(getattr(_speech_to_text, "VOSK_AVAILABLE", False))

        if VOSK_AVAILABLE:
            print("⏳ Pre-loading Vosk STT model (this may take a moment on first run)...")
            model = get_vosk_model() if get_vosk_model else None
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
app.include_router(gpu_admin.router)
app.include_router(agora_token.router)


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
        "llm_model": settings.GEMINI_MODEL,
    }


@app.get("/api/diagnostics/gemini")
async def gemini_diagnostics():
    """Show Gemini API call statistics for this server instance."""
    from app.services.model_registry import model_registry
    return model_registry.get_stats()


@app.get("/api/diagnostics/gemini-test")
async def gemini_test():
    """Live test: generate a sample question via Gemini to verify the API key works."""
    from app.services.model_registry import model_registry
    import time as _time
    pre_stats = model_registry.get_stats()
    if not pre_stats["gemini_primary_key_set"]:
        return {
            "status": "error",
            "error": "GEMINI_API_KEY is not configured. Set it as an environment variable.",
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
            "key_used": model_registry.active_key_index,
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


@app.get("/api/diagnostics/gemini-raw")
async def gemini_raw_test():
    """Raw Gemini SDK test — bypasses llm_generate error handling to expose exact errors."""
    import asyncio, time as _time, traceback
    from app.core.config import settings
    from google import genai

    result = {"gemini_key_len": len(settings.GEMINI_API_KEY) if settings.GEMINI_API_KEY else 0}
    if not settings.GEMINI_API_KEY:
        result["error"] = "GEMINI_API_KEY is empty"
        return result
    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        result["client_created"] = True
    except Exception as e:
        result["client_error"] = f"{type(e).__name__}: {e}"
        return result
    t0 = _time.time()
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.GEMINI_MODEL,
            contents="Say hello in one word",
            config={"temperature": 0.1, "max_output_tokens": 200},
        )
        elapsed = round(_time.time() - t0, 2)
        text = response.text if response and response.text else ""
        result["status"] = "ok" if text else "empty_response"
        result["response"] = text
        result["elapsed_seconds"] = elapsed
        result["model"] = settings.GEMINI_MODEL
    except Exception as e:
        elapsed = round(_time.time() - t0, 2)
        result["status"] = "error"
        result["error"] = str(e)
        result["error_type"] = type(e).__name__
        result["traceback"] = traceback.format_exc()[-500:]
        result["elapsed_seconds"] = elapsed
        result["model"] = settings.GEMINI_MODEL
    return result


@app.get("/api/diagnostics/gemini-models")
async def gemini_models_test():
    """Try every model in the fallback chain across ALL keys and report which work."""
    import asyncio, time as _time
    from app.core.config import settings
    from google import genai

    if not settings.GEMINI_API_KEY:
        return {"error": "GEMINI_API_KEY is empty"}

    # Collect all keys
    all_keys = [settings.GEMINI_API_KEY]
    if settings.GEMINI_FALLBACK_API_KEYS:
        for k in settings.GEMINI_FALLBACK_API_KEYS.split(","):
            k = k.strip()
            if k and k not in all_keys:
                all_keys.append(k)

    # Collect all models
    models = [settings.GEMINI_MODEL]
    if settings.GEMINI_FALLBACK_MODELS:
        for m in settings.GEMINI_FALLBACK_MODELS.split(","):
            m = m.strip()
            if m and m not in models:
                models.append(m)

    results = {}
    for ki, api_key in enumerate(all_keys, 1):
        client = genai.Client(api_key=api_key)
        for model_name in models:
            combo = f"K{ki}+{model_name}"
            t0 = _time.time()
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model_name,
                    contents="Say hello in one word",
                    config={"temperature": 0.1, "max_output_tokens": 10},
                )
                text = response.text if response and response.text else ""
                results[combo] = {
                    "status": "ok" if text else "empty",
                    "response": text.strip()[:50],
                    "elapsed": round(_time.time() - t0, 2),
                }
            except Exception as e:
                err = str(e)[:200]
                status = "quota" if any(m in err.lower() for m in ("429", "resource_exhausted", "quota", "rate limit")) else "error"
                results[combo] = {
                    "status": status,
                    "error": err,
                    "error_type": type(e).__name__,
                    "elapsed": round(_time.time() - t0, 2),
                }

    working = [c for c, r in results.items() if r["status"] == "ok"]
    return {
        "keys_tested": len(all_keys),
        "models_tested": len(models),
        "combos_tested": len(results),
        "working": working,
        "working_count": len(working),
        "results": results,
    }


@app.get("/api/diagnostics/openrouter-probe")
async def openrouter_probe(models: str = ""):
    """Test arbitrary OpenRouter models (comma-separated in query param)."""
    import asyncio
    import time as _time
    from app.core.config import settings
    if not settings.OPENROUTER_API_KEY:
        return {"error": "OPENROUTER_API_KEY is empty"}
    if not models:
        return {"error": "Pass ?models=model1,model2"}
    model_list = [m.strip() for m in models.split(",") if m.strip()]
    try:
        from openai import OpenAI
        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=settings.OPENROUTER_API_KEY)
    except Exception as e:
        return {"error": str(e)}
    results = {}
    for model_name in model_list:
        t0 = _time.time()
        try:
            response = await asyncio.to_thread(
                client.chat.completions.create, model=model_name,
                messages=[{"role": "user", "content": "Say hello in one word"}],
                max_tokens=100, temperature=0.1,
            )
            text = (response.choices[0].message.content or "").strip() if response and response.choices else ""
            results[model_name] = {"status": "ok" if text else "empty", "response": text[:50], "elapsed": round(_time.time() - t0, 2)}
        except Exception as e:
            results[model_name] = {"status": "error", "error": str(e)[:200], "elapsed": round(_time.time() - t0, 2)}
    working = [m for m, r in results.items() if r["status"] == "ok"]
    return {"working": working, "working_count": len(working), "results": results}


@app.get("/api/diagnostics/openrouter")
async def openrouter_test():
    """Test OpenRouter API key and each fallback model."""
    import asyncio
    import time as _time
    from app.core.config import settings

    if not settings.OPENROUTER_API_KEY:
        return {"error": "OPENROUTER_API_KEY is empty"}

    models = []
    if settings.OPENROUTER_FALLBACK_MODELS:
        for m in settings.OPENROUTER_FALLBACK_MODELS.split(","):
            m = m.strip()
            if m:
                models.append(m)

    if not models:
        return {"error": "OPENROUTER_FALLBACK_MODELS is empty"}

    try:
        from openai import OpenAI
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.OPENROUTER_API_KEY,
        )
    except Exception as e:
        return {"error": f"Failed to create OpenRouter client: {e}"}

    results = {}
    for model_name in models:
        t0 = _time.time()
        try:
            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=model_name,
                messages=[{"role": "user", "content": "Say hello in one word"}],
                max_tokens=100,
                temperature=0.1,
            )
            text = ""
            if response and response.choices and len(response.choices) > 0:
                text = (response.choices[0].message.content or "").strip()
            results[model_name] = {
                "status": "ok" if text else "empty",
                "response": text.strip()[:50],
                "elapsed": round(_time.time() - t0, 2),
            }
        except Exception as e:
            err = str(e)[:200]
            results[model_name] = {
                "status": "error",
                "error": err,
                "error_type": type(e).__name__,
                "elapsed": round(_time.time() - t0, 2),
            }

    working = [m for m, r in results.items() if r["status"] == "ok"]
    return {
        "openrouter_key_set": True,
        "models_tested": len(models),
        "working": working,
        "working_count": len(working),
        "results": results,
    }


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
