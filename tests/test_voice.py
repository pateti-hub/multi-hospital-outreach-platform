import pytest

from outreach.voice import PipecatVoiceGateway, VoiceGatewayError


class Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class Client:
    def __init__(self, payload: dict):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, *args, **kwargs) -> Response:
        return Response(self.payload)


async def test_voice_gateway_returns_bounded_webrtc_session(monkeypatch) -> None:
    monkeypatch.setattr(
        "outreach.voice.httpx.AsyncClient",
        lambda **kwargs: Client(
            {
                "room_url": "https://synthetic.daily.co/outreach",
                "token": "synthetic-token",
            }
        ),
    )

    result = await PipecatVoiceGateway().create_session(
        "https://voice.example.test",
        task_id="synthetic-task",
    )

    assert result["transport"] == "daily-webrtc"
    assert result["room_url"].startswith("https://")
    assert result["expires_at"]


async def test_voice_gateway_rejects_invalid_provider_response(monkeypatch) -> None:
    monkeypatch.setattr(
        "outreach.voice.httpx.AsyncClient",
        lambda **kwargs: Client({"unexpected": True}),
    )

    with pytest.raises(VoiceGatewayError, match="invalid session"):
        await PipecatVoiceGateway().create_session(
            "https://voice.example.test",
            task_id="synthetic-task",
        )


async def test_voice_gateway_accepts_pipecat_runner_field_names(monkeypatch) -> None:
    monkeypatch.setattr(
        "outreach.voice.httpx.AsyncClient",
        lambda **kwargs: Client(
            {
                "dailyRoom": "https://synthetic.daily.co/outreach",
                "dailyToken": "synthetic-token",
                "sessionId": "synthetic-session",
            }
        ),
    )

    result = await PipecatVoiceGateway().create_session(
        "https://voice.example.test",
        task_id="synthetic-task",
    )

    assert result["room_url"] == "https://synthetic.daily.co/outreach"
