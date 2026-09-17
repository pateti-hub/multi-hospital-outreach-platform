from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx


class VoiceGatewayError(RuntimeError):
    pass


class PipecatVoiceGateway:
    """PHI-minimized gateway to the existing Pipecat/Daily WebRTC service."""

    async def create_session(self, service_url: str, *, task_id: str) -> dict:
        expiration = int((datetime.now(UTC) + timedelta(minutes=30)).timestamp())
        payload = {
            "transport": "daily",
            "createDailyRoom": True,
            "dailyRoomProperties": {
                "enable_chat": False,
                "start_video_off": True,
                "exp": expiration,
                "eject_at_room_exp": True,
            },
            "dailyMeetingTokenProperties": {
                "exp": expiration,
                "is_owner": False,
            },
            "body": {
                "channel": "multi-hospital-outreach",
                "taskReference": task_id,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"{service_url.rstrip('/')}/start",
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise VoiceGatewayError("Voice provider is unavailable") from error
        room_url = result.get("room_url") or result.get("roomUrl")
        token = result.get("token")
        if not room_url or not token:
            raise VoiceGatewayError("Voice provider returned an invalid session")
        return {
            "room_url": room_url,
            "token": token,
            "expires_at": datetime.fromtimestamp(expiration, UTC).isoformat(),
            "transport": "daily-webrtc",
        }


voice_gateway = PipecatVoiceGateway()
