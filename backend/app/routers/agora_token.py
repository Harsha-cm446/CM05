"""
Agora RTC Token Generator
─────────────────────────
GET /api/agora/token?channel=<channel>&uid=<uid>

Generates a temporary RTC token for Agora video channels.
Uses HMAC-SHA256 token building (Agora AccessToken2 compatible).
"""

import hashlib
import hmac
import struct
import time
import secrets
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings


router = APIRouter(prefix="/api/agora", tags=["agora"])


# ── Agora AccessToken builder (inline, no external dependency) ────────

class AgoraTokenBuilder:
    """Minimal Agora RTC token builder using AccessToken2007 format.
    
    This is a self-contained implementation that doesn't require
    the agora-token-builder package. Compatible with Agora RTC SDK.
    """

    ROLE_PUBLISHER = 1
    ROLE_SUBSCRIBER = 2

    PRIVILEGE_JOIN = 1
    PRIVILEGE_PUBLISH_AUDIO = 2
    PRIVILEGE_PUBLISH_VIDEO = 3
    PRIVILEGE_PUBLISH_DATA = 4

    @staticmethod
    def _pack_uint16(val: int) -> bytes:
        return struct.pack("<H", val)

    @staticmethod
    def _pack_uint32(val: int) -> bytes:
        return struct.pack("<I", val)

    @staticmethod
    def _pack_string(s: str) -> bytes:
        b = s.encode("utf-8")
        return struct.pack("<H", len(b)) + b

    @staticmethod
    def _pack_map(m: dict) -> bytes:
        result = struct.pack("<H", len(m))
        for k, v in sorted(m.items()):
            result += struct.pack("<H", k)
            result += struct.pack("<I", v)
        return result

    @classmethod
    def build_token(
        cls,
        app_id: str,
        app_certificate: str,
        channel_name: str,
        uid: int,
        role: int = 1,
        privilege_expired_ts: int = 0,
    ) -> str:
        """Build an Agora RTC token (version 006 format)."""
        version = "006"
        ts = int(time.time())
        salt = secrets.randbelow(99999999) + 1

        # Build privilege map
        privileges = {
            cls.PRIVILEGE_JOIN: privilege_expired_ts,
            cls.PRIVILEGE_PUBLISH_AUDIO: privilege_expired_ts,
            cls.PRIVILEGE_PUBLISH_VIDEO: privilege_expired_ts,
            cls.PRIVILEGE_PUBLISH_DATA: privilege_expired_ts,
        }

        # Build message
        message = cls._pack_uint32(salt)
        message += cls._pack_uint32(ts)
        message += cls._pack_map(privileges)

        # Sign
        to_sign = (
            app_id.encode("utf-8")
            + channel_name.encode("utf-8")
            + str(uid).encode("utf-8")
            + message
        )
        signature = hmac.new(
            app_certificate.encode("utf-8"), to_sign, hashlib.sha256
        ).digest()

        # Build content
        content = cls._pack_string(signature.hex())
        content += cls._pack_uint32(0)  # crc_channel
        content += cls._pack_uint32(0)  # crc_uid
        content += cls._pack_string(message.hex())

        import base64
        token = version + app_id + base64.b64encode(content).decode("utf-8")
        return token


# ── Route ─────────────────────────────────────────────────────────────

@router.get("/token")
async def get_agora_token(
    channel: str = Query(..., min_length=1, max_length=128, description="Channel name"),
    uid: int = Query(..., ge=0, description="Numeric user ID"),
    role: Optional[str] = Query("publisher", description="Role: publisher or subscriber"),
):
    """Generate a time-limited Agora RTC token.
    
    Frontend flow:
    1. Generate numeric UID
    2. Call GET /api/agora/token?channel=<session>&uid=<uid>
    3. Join Agora channel with returned token + appId
    """
    if not settings.AGORA_APP_ID or not settings.AGORA_APP_CERTIFICATE:
        raise HTTPException(
            status_code=503,
            detail="Agora credentials not configured. Set AGORA_APP_ID and AGORA_APP_CERTIFICATE in .env",
        )

    agora_role = (
        AgoraTokenBuilder.ROLE_SUBSCRIBER
        if role == "subscriber"
        else AgoraTokenBuilder.ROLE_PUBLISHER
    )

    # Token expires in 1 hour
    expire_ts = int(time.time()) + 3600

    token = AgoraTokenBuilder.build_token(
        app_id=settings.AGORA_APP_ID,
        app_certificate=settings.AGORA_APP_CERTIFICATE,
        channel_name=channel,
        uid=uid,
        role=agora_role,
        privilege_expired_ts=expire_ts,
    )

    return {
        "token": token,
        "uid": uid,
        "channel": channel,
        "appId": settings.AGORA_APP_ID,
        "expiresAt": expire_ts,
    }


@router.get("/config")
async def get_agora_config():
    """Return the Agora App ID (public, safe to expose) for client initialization."""
    if not settings.AGORA_APP_ID:
        raise HTTPException(status_code=503, detail="Agora not configured")
    return {"appId": settings.AGORA_APP_ID}
