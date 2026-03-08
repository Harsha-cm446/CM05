import os
from pathlib import Path

from pydantic_settings import BaseSettings

# Resolve .env path reliably regardless of working directory.
# Priority: backend/.env (next to this file) → project-root .env → CWD .env
_THIS_DIR = Path(__file__).resolve().parent            # backend/app/core/
_BACKEND_DIR = _THIS_DIR.parent.parent                 # backend/
_PROJECT_DIR = _BACKEND_DIR.parent                     # ai-interview-platform/

_ENV_CANDIDATES = [
    _BACKEND_DIR / ".env",       # backend/.env  (most common)
    _PROJECT_DIR / ".env",       # project-root .env
    Path.cwd() / ".env",         # current working directory
]
_ENV_FILE = next((p for p in _ENV_CANDIDATES if p.is_file()), ".env")


class Settings(BaseSettings):
    # MongoDB
    MONGODB_URL: str = "mongodb://localhost:27017"
    DATABASE_NAME: str = "ai_interview_platform"

    # JWT
    JWT_SECRET_KEY: str = "change-me-to-a-long-random-secret-string"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours

    # Email — SMTP only (works reliably from Azure and all hosting platforms)
    # For Gmail: SMTP_HOST=smtp.gmail.com, SMTP_PORT=587, use App Password
    # For Outlook: SMTP_HOST=smtp.office365.com, SMTP_PORT=587
    # For Azure Communication Services: SMTP_HOST=smtp.azurecomm.net, SMTP_PORT=587
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAIL_FROM: str = ""

    # Gemini LLM (multi-key fallback)
    GEMINI_API_KEY: str = ""
    GEMINI_FALLBACK_API_KEYS: str = ""  # comma-separated extra keys from different accounts
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_FALLBACK_MODELS: str = "gemini-3-flash-preview,gemini-3.1-flash-lite-preview,gemini-2.5-flash-lite,gemini-3.1-pro-preview,gemini-2.5-pro"

    # Frontend
    FRONTEND_URL: str = "http://localhost:5173"
    # Public URL for emails/links (set to your machine's IP or ngrok URL)
    # e.g. http://192.168.1.100:5173 or https://abc123.ngrok.io
    PUBLIC_URL: str = ""

    class Config:
        env_file = str(_ENV_FILE)


settings = Settings()

# Startup diagnostic — print only if Gemini key is missing
if not settings.GEMINI_API_KEY:
    print(f"⚠️  GEMINI_API_KEY is empty! Searched .env files: {[str(p) for p in _ENV_CANDIDATES]}")
    print(f"   Resolved .env: {_ENV_FILE}")
else:
    print(f"✅ Config loaded from {_ENV_FILE} (Gemini key: {settings.GEMINI_API_KEY[:8]}...)")
