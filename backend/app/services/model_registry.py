"""
Shared model registry — provides singleton instances of heavy ML models
to prevent duplicate loading across services.

Includes Gemini multi-key + model fallback chain:
  1. Try all models under API Key 1
  2. If all models exhausted (quota/rate-limit), switch to API Key 2
  3. Repeat until a key succeeds or all keys exhausted

Usage:
    from app.services.model_registry import model_registry
    embedding = model_registry.embedding_model.encode("hello")
    text = await model_registry.llm_generate(prompt, system, fast=True)
"""

import time
import asyncio
import logging
from typing import Optional, List

from google import genai

from app.core.config import settings

logger = logging.getLogger(__name__)


class ModelRegistry:
    """Lazy-loading singleton registry for shared ML models.

    Gemini multi-key fallback:
    - Each API key gets its own client instance
    - On quota / rate-limit errors (429, 503, RESOURCE_EXHAUSTED),
      the registry tries the next model in the fallback list
    - If ALL models under one key are exhausted, it rotates to the next key
    - Interview context is preserved across key switches (stateless API calls)
    """

    # Error substrings that indicate quota / rate-limit exhaustion
    _QUOTA_ERROR_MARKERS = (
        "429", "resource_exhausted", "rate limit", "quota",
        "too many requests", "503", "overloaded", "capacity",
        "rate_limit_exceeded", "limit reached",
    )

    def __init__(self):
        self._embedding_model = None
        self._gemini_clients: List = []  # List of genai.Client instances
        self._active_key_idx = 0

        # API call tracking
        self._api_call_count = 0
        self._api_call_success = 0
        self._api_call_fail = 0
        self._last_call_ts: Optional[float] = None
        self._last_error: Optional[str] = None
        self._last_error_type: Optional[str] = None

        # Build ordered model list: primary first, then fallbacks
        self._model_chain = [settings.GEMINI_MODEL]
        if settings.GEMINI_FALLBACK_MODELS:
            for m in settings.GEMINI_FALLBACK_MODELS.split(","):
                m = m.strip()
                if m and m not in self._model_chain:
                    self._model_chain.append(m)

        # Build ordered API key list: primary first, then fallbacks
        self._api_keys: List[str] = []
        if settings.GEMINI_API_KEY:
            self._api_keys.append(settings.GEMINI_API_KEY)
        if settings.GEMINI_FALLBACK_API_KEYS:
            for k in settings.GEMINI_FALLBACK_API_KEYS.split(","):
                k = k.strip()
                if k and k not in self._api_keys:
                    self._api_keys.append(k)

        # Track which model is currently active + cooldown per model per key
        self._active_model_idx = 0
        self._model_cooldowns: dict = {}  # (key_idx, model) -> timestamp
        self._key_cooldowns: dict = {}    # key_idx -> timestamp
        self._cooldown_seconds = 60

    # ── SentenceTransformer (single instance, ~90 MB) ────────────
    @property
    def embedding_model(self):
        if self._embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
                logger.info("ModelRegistry: SentenceTransformer loaded (shared)")
            except Exception as e:
                logger.warning(f"ModelRegistry: SentenceTransformer unavailable: {e}")
        return self._embedding_model

    # ── Gemini clients (one per API key) ─────────────────────────
    def _get_client(self, key_idx: int):
        """Get or create a Gemini client for the given key index."""
        while len(self._gemini_clients) <= key_idx:
            self._gemini_clients.append(None)

        if self._gemini_clients[key_idx] is None:
            api_key = self._api_keys[key_idx]
            try:
                print(f"[ModelRegistry] Creating Gemini client for key #{key_idx + 1} "
                      f"(prefix={api_key[:8]}...)")
                self._gemini_clients[key_idx] = genai.Client(api_key=api_key)
                print(f"[ModelRegistry] Gemini client #{key_idx + 1} created successfully")
                logger.info(f"ModelRegistry: Gemini client #{key_idx + 1} created")
            except Exception as e:
                print(f"[ModelRegistry] Gemini client #{key_idx + 1} creation FAILED: {e}")
                logger.warning(f"ModelRegistry: Gemini client #{key_idx + 1} unavailable: {e}")
        return self._gemini_clients[key_idx]

    @property
    def gemini_client(self):
        """Return the currently active Gemini client."""
        if not self._api_keys:
            print(f"[ModelRegistry] GEMINI_API_KEY is empty (len=0) — LLM calls will fail")
            logger.error(
                "ModelRegistry: GEMINI_API_KEY is empty — LLM calls will fail. "
                "Set GEMINI_API_KEY in backend/.env"
            )
            return None
        return self._get_client(self._active_key_idx)

    @property
    def active_model(self) -> str:
        """Return the currently active model name."""
        return self._model_chain[self._active_model_idx]

    @property
    def active_key_index(self) -> int:
        """Return the index of the currently active API key (1-based for display)."""
        return self._active_key_idx + 1

    @property
    def total_keys(self) -> int:
        return len(self._api_keys)

    def _is_quota_error(self, error: Exception) -> bool:
        """Check if an exception indicates a quota / rate-limit problem."""
        err_str = str(error).lower()
        if any(marker in err_str for marker in self._QUOTA_ERROR_MARKERS):
            return True
        status = getattr(error, "status_code", None) or getattr(
            getattr(error, "response", None), "status_code", None
        )
        if status in (429, 503):
            return True
        return False

    def _is_auth_error(self, error: Exception) -> bool:
        """Check if an exception indicates an authentication failure (bad API key)."""
        status = getattr(error, "status_code", None) or getattr(
            getattr(error, "response", None), "status_code", None
        )
        if status == 401:
            return True
        err_str = str(error).lower()
        return any(m in err_str for m in ("401", "invalid api key", "invalid_api_key",
                                           "api_key_invalid", "authentication", "unauthorized"))

    async def llm_generate(
        self,
        prompt: str,
        system: str = "",
        fast: bool = False,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Call Gemini API with automatic model + key fallback.

        Strategy:
        1. For each API key (starting with active):
           a. Try each model in the chain
           b. On quota error -> try next model
           c. If all models exhausted -> try next key
        2. On auth error for a key -> skip that key entirely
        3. Returns empty string only if ALL keys x ALL models fail

        Interview context is NOT lost on key switch — all context is in
        the prompt itself, so switching keys mid-interview is seamless.
        """
        if not self._api_keys:
            print(f"[llm_generate] ABORT: No API keys configured — GEMINI_API_KEY missing")
            logger.error("Gemini error: GEMINI_API_KEY not configured")
            return ""

        if max_tokens is None:
            max_tokens = 512 if fast else 2048

        # Build key order: active first, then others
        key_order = [self._active_key_idx]
        for i in range(len(self._api_keys)):
            if i not in key_order:
                key_order.append(i)

        now = time.time()
        last_error = None

        print(f"[llm_generate] {len(self._api_keys)} keys, {len(self._model_chain)} models, "
              f"prompt_len={len(prompt)}")

        for key_idx in key_order:
            # Skip keys on cooldown (unless it's the only one left)
            cooldown_until = self._key_cooldowns.get(key_idx, 0)
            if now < cooldown_until and len(key_order) > 1:
                remaining_keys = [k for k in key_order if now >= self._key_cooldowns.get(k, 0)]
                if remaining_keys:
                    continue

            client = self._get_client(key_idx)
            if client is None:
                continue

            # Build model order for this key
            models_to_try = []
            tried = set()
            active = self._model_chain[self._active_model_idx]
            cd_key = (key_idx, active)
            if now >= self._model_cooldowns.get(cd_key, 0):
                models_to_try.append(active)
                tried.add(active)
            for m in self._model_chain:
                if m not in tried:
                    cd_key = (key_idx, m)
                    if now >= self._model_cooldowns.get(cd_key, 0):
                        models_to_try.append(m)
                        tried.add(m)
            # Add cooldown models as last resort
            for m in self._model_chain:
                if m not in tried:
                    models_to_try.append(m)
                    tried.add(m)

            all_models_failed = True
            for model_name in models_to_try:
                try:
                    self._api_call_count += 1
                    self._last_call_ts = time.time()
                    print(f"[llm_generate] Key #{key_idx + 1}, model={model_name}, "
                          f"max_tokens={max_tokens} (call #{self._api_call_count})")

                    # Build Gemini contents — system instruction merged into prompt
                    contents = system + "\n\n" + prompt if system else prompt

                    response = await asyncio.to_thread(
                        client.models.generate_content,
                        model=model_name,
                        contents=contents,
                        config={
                            "temperature": 0.7,
                            "max_output_tokens": max_tokens,
                        },
                    )

                    text = response.text if response and response.text else ""
                    self._api_call_success += 1
                    print(f"[llm_generate] Gemini OK key=#{key_idx + 1} model={model_name} "
                          f"len={len(text)} (success #{self._api_call_success})")

                    if text:
                        self._active_key_idx = key_idx
                        idx = self._model_chain.index(model_name)
                        if idx != self._active_model_idx:
                            self._active_model_idx = idx
                    all_models_failed = False
                    return text

                except Exception as e:
                    self._api_call_fail += 1
                    last_error = e
                    self._last_error = str(e)[:500]
                    self._last_error_type = type(e).__name__
                    print(f"[llm_generate] EXCEPTION key=#{key_idx + 1} model={model_name}: "
                          f"{self._last_error_type}: {self._last_error}")

                    if self._is_auth_error(e):
                        logger.error(f"Gemini AUTH ERROR key #{key_idx + 1}: {e}")
                        print(f"[llm_generate] Key #{key_idx + 1} auth failed, skipping to next key")
                        break  # Break model loop, try next key

                    elif self._is_quota_error(e) or getattr(e, 'status_code', None) in (403, 429, 503):
                        logger.warning(f"ModelRegistry: Quota/rate error on key #{key_idx + 1} "
                                       f"model={model_name}: {e}")
                        self._model_cooldowns[(key_idx, model_name)] = now + self._cooldown_seconds
                        continue  # Try next model under same key

                    else:
                        logger.error(f"Gemini error key #{key_idx + 1} model={model_name}: {e}")
                        continue

            # If all models under this key failed, put key on cooldown
            if all_models_failed:
                self._key_cooldowns[key_idx] = now + self._cooldown_seconds
                print(f"[llm_generate] All models exhausted for key #{key_idx + 1}, "
                      f"cooldown {self._cooldown_seconds}s")

        # All keys x all models exhausted
        print(f"[llm_generate] All {len(self._api_keys)} keys x "
              f"{len(self._model_chain)} models exhausted. Last error: {last_error}")
        logger.error(f"Gemini error: All keys and models exhausted. Last error: {last_error}")
        return ""

    def warm_up(self):
        """Eagerly load all models (call during app startup)."""
        _ = self.embedding_model
        _ = self.gemini_client
        logger.info(f"ModelRegistry: Model chain = {self._model_chain}, "
                     f"API keys = {len(self._api_keys)}")

    def get_stats(self) -> dict:
        """Return API call statistics for diagnostics."""
        import datetime as _dt
        return {
            "gemini_keys_configured": len(self._api_keys),
            "gemini_primary_key_set": bool(settings.GEMINI_API_KEY),
            "gemini_client_ready": self.gemini_client is not None,
            "active_model": self.active_model,
            "active_key_index": self.active_key_index,
            "total_keys": self.total_keys,
            "model_chain": self._model_chain,
            "api_calls_total": self._api_call_count,
            "api_calls_success": self._api_call_success,
            "api_calls_failed": self._api_call_fail,
            "last_call_at": (
                _dt.datetime.fromtimestamp(self._last_call_ts).isoformat()
                if self._last_call_ts else None
            ),
            "last_error": self._last_error,
            "last_error_type": self._last_error_type,
        }


model_registry = ModelRegistry()
