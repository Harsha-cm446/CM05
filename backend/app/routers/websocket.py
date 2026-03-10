import json
from datetime import datetime
from typing import Dict, Set

from bson import ObjectId
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.database import get_database

router = APIRouter()


class ConnectionManager:
    """
    Manages WebSocket connections for interview rooms.
    
    HR is a silent observer — candidates never see HR join/leave and
    cannot detect HR presence. The AI conducts the interview; HR only watches.
    """

    def __init__(self):
        # room_id -> {connection_id: websocket}
        self.rooms: Dict[str, Dict[str, WebSocket]] = {}
        # room_id -> list of HR websockets
        self.hr_connections: Dict[str, Dict[str, WebSocket]] = {}
        # connection_id -> participant info
        self.participant_info: Dict[str, dict] = {}
        # room_id -> {conn_id: {has_camera, has_screen, name}} — persisted stream status
        self.stream_status: Dict[str, Dict[str, dict]] = {}

    async def join_room(self, room_id: str, conn_id: str, ws: WebSocket, role: str, info: dict):
        await ws.accept()
        if room_id not in self.rooms:
            self.rooms[room_id] = {}

        self.rooms[room_id][conn_id] = ws
        self.participant_info[conn_id] = {**info, "role": role, "conn_id": conn_id}

        if role == "hr":
            # Track HR connections separately — HR is invisible to candidates
            if room_id not in self.hr_connections:
                self.hr_connections[room_id] = {}
            self.hr_connections[room_id][conn_id] = ws

            # Send room state to HR with all participants AND their stream status
            await ws.send_json({
                "type": "room_state",
                "participants": self._get_participants(room_id, include_hr=True),
                "stream_status": self.stream_status.get(room_id, {}),
                "your_id": conn_id,
            })
            # Do NOT broadcast HR join to candidates — HR is invisible
        else:
            # Candidate joined — notify only HR watchers (not other candidates)
            await self._send_to_hr(room_id, {
                "type": "user_joined",
                "conn_id": conn_id,
                "role": role,
                "info": info,
                "participants": self._get_participants(room_id, include_hr=False),
            })

            # Send room state to candidate — exclude HR from participant list
            await ws.send_json({
                "type": "room_state",
                "participants": self._get_participants(room_id, include_hr=False),
                "your_id": conn_id,
            })

    async def leave_room(self, room_id: str, conn_id: str):
        info = self.participant_info.pop(conn_id, {})
        is_hr = info.get("role") == "hr"

        if room_id in self.rooms:
            self.rooms[room_id].pop(conn_id, None)
            if not self.rooms[room_id]:
                del self.rooms[room_id]

        # Clean up stream status for this connection
        if room_id in self.stream_status:
            self.stream_status[room_id].pop(conn_id, None)
            if not self.stream_status[room_id]:
                del self.stream_status[room_id]

        if is_hr:
            # Remove from HR connections — silent, no broadcast
            if room_id in self.hr_connections:
                self.hr_connections[room_id].pop(conn_id, None)
                if not self.hr_connections[room_id]:
                    del self.hr_connections[room_id]
        else:
            # Candidate left — notify HR only
            await self._send_to_hr(room_id, {
                "type": "user_left",
                "conn_id": conn_id,
                "info": info,
                "participants": self._get_participants(room_id, include_hr=False),
            })

    def update_stream_status(self, room_id: str, conn_id: str, name: str, has_camera: bool, has_screen: bool):
        """Persist stream status so HR can query it on (re)connect."""
        if room_id not in self.stream_status:
            self.stream_status[room_id] = {}
        self.stream_status[room_id][conn_id] = {
            "name": name,
            "has_camera": has_camera,
            "has_screen": has_screen,
        }

    async def _send_to_hr(self, room_id: str, message: dict):
        """Send a message only to HR observers in the room."""
        if room_id not in self.hr_connections:
            return
        dead = []
        for cid, ws in self.hr_connections[room_id].items():
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(cid)
        for cid in dead:
            self.hr_connections[room_id].pop(cid, None)

    async def broadcast(self, room_id: str, message: dict, exclude: str = None):
        """Broadcast to all connections in the room (including HR)."""
        if room_id not in self.rooms:
            return
        dead = []
        for cid, ws in self.rooms[room_id].items():
            if cid == exclude:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(cid)
        for cid in dead:
            self.rooms[room_id].pop(cid, None)

    async def send_to(self, room_id: str, target_id: str, message: dict):
        ws = self.rooms.get(room_id, {}).get(target_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception:
                pass

    def _get_participants(self, room_id: str, include_hr: bool = False) -> list:
        """Get participant list. By default, excludes HR to keep them invisible."""
        if room_id not in self.rooms:
            return []
        return [
            self.participant_info.get(cid, {"conn_id": cid})
            for cid in self.rooms[room_id]
            if include_hr or self.participant_info.get(cid, {}).get("role") != "hr"
        ]


manager = ConnectionManager()


@router.websocket("/ws/interview/{room_id}")
async def interview_websocket(websocket: WebSocket, room_id: str):
    """
    WebSocket endpoint for interview rooms.
    
    Query params:
      - token: unique candidate token or JWT for HR
      - role: 'candidate' or 'hr'
      - name: display name
    """
    params = websocket.query_params
    token = params.get("token", "")
    role = params.get("role", "candidate")
    name = params.get("name", "Anonymous")

    db = get_database()
    conn_id = token or f"{role}_{id(websocket)}"

    # Validate candidate token if candidate
    if role == "candidate" and token:
        candidate = await db.candidates.find_one({"unique_token": token})
        if not candidate:
            await websocket.close(code=4001, reason="Invalid token")
            return
        # Mark as joined
        await db.candidates.update_one(
            {"unique_token": token},
            {"$set": {"status": "joined", "joined_at": datetime.utcnow()}},
        )
        name = candidate.get("email", name)

    info = {"name": name, "email": params.get("email", ""), "token": token}

    try:
        await manager.join_room(room_id, conn_id, websocket, role, info)

        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "webrtc_offer":
                await manager.send_to(room_id, data["target"], {
                    "type": "webrtc_offer",
                    "offer": data["offer"],
                    "from": conn_id,
                })

            elif msg_type == "webrtc_answer":
                await manager.send_to(room_id, data["target"], {
                    "type": "webrtc_answer",
                    "answer": data["answer"],
                    "from": conn_id,
                })

            elif msg_type == "ice_candidate":
                await manager.send_to(room_id, data["target"], {
                    "type": "ice_candidate",
                    "candidate": data["candidate"],
                    "from": conn_id,
                })

            elif msg_type == "request_stream":
                # HR requests a candidate's stream
                await manager.send_to(room_id, data["target"], {
                    "type": "request_stream",
                    "from": conn_id,
                })

            elif msg_type == "stream_ready":
                # Candidate signals they have streams available — persist and notify HR
                has_camera = data.get("has_camera", False)
                has_screen = data.get("has_screen", False)
                manager.update_stream_status(room_id, conn_id, name, has_camera, has_screen)
                await manager._send_to_hr(room_id, {
                    "type": "stream_ready",
                    "from": conn_id,
                    "name": name,
                    "has_camera": has_camera,
                    "has_screen": has_screen,
                })

            elif msg_type == "request_all_streams":
                # HR requests current stream status of all candidates
                status = manager.stream_status.get(room_id, {})
                await manager.send_to(room_id, conn_id, {
                    "type": "all_stream_status",
                    "streams": status,
                })
                # Also ask all candidates to re-send stream_ready (in case status is stale)
                if room_id in manager.rooms:
                    for cid in list(manager.rooms[room_id].keys()):
                        p_info = manager.participant_info.get(cid, {})
                        if p_info.get("role") != "hr":
                            await manager.send_to(room_id, cid, {
                                "type": "request_stream_status",
                                "from": conn_id,
                            })

            elif msg_type == "ping":
                # Heartbeat / keep-alive
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        await manager.leave_room(room_id, conn_id)
    except Exception as e:
        print(f"WebSocket error: {e}")
        await manager.leave_room(room_id, conn_id)
