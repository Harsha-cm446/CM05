from fastapi import APIRouter, HTTPException, Query
from app.core.config import settings
from livekit import api

router = APIRouter(prefix="/livekit", tags=["LiveKit"])

@router.get("/get-token")
def get_livekit_token(
    user: str = Query(..., description="Unique user or participant ID"),
    room: str = Query(..., description="Room name (e.g. session ID)")
):
    if not settings.LIVEKIT_API_KEY or not settings.LIVEKIT_API_SECRET:
        raise HTTPException(
            status_code=500,
            detail="LIVEKIT_API_KEY or LIVEKIT_API_SECRET is missing from environment."
        )

    try:
        # Create an access token for the participant
        token = api.AccessToken(
            settings.LIVEKIT_API_KEY,
            settings.LIVEKIT_API_SECRET
        )
        token.with_identity(user)
        token.with_name(user)
        # Grant permissions to join the specified room and publish/subscribe
        token.with_grants(api.VideoGrants(
            room_join=True,
            room=room,
            can_publish=True,
            can_subscribe=True
        ))

        jwt_token = token.to_jwt()

        return {
            "token": jwt_token,
            "room": room,
            "user": user
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate LiveKit token: {str(e)}")
