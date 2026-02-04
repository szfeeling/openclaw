from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState


@dataclass
class StreamingDeps:
    openclaw_base_url: str
    openclaw_model: str
    openclaw_timeout_seconds: float
    openclaw_headers: Callable[[str], dict]
    get_project: Callable[[str], Any]
    resolve_avatar: Callable[[Optional[str]], Any]
    elevenlabs_api_key: str
    elevenlabs_base_url: str
    elevenlabs_model_id: str
    elevenlabs_output_format: str
    elevenlabs_optimize_latency: str
    elevenlabs_default_voice_id: str
    whisper_http_url: str
    whisper_http_api_key: str
    whisper_cmd: str
    whisper_model: str
    whisper_language: str


@dataclass
class AudioStreamState:
    project_id: Optional[str] = None
    avatar_id: Optional[str] = None
    sample_rate: int = 16000
    channels: int = 1
    audio_format: str = "pcm16"
    language: Optional[str] = None
    buffer: bytearray = field(default_factory=bytearray)
    cancelled: bool = False
    running: bool = False

    def reset(self) -> None:
        self.project_id = None
        self.avatar_id = None
        self.sample_rate = 16000
        self.channels = 1
        self.audio_format = "pcm16"
        self.language = None
        self.buffer = bytearray()
        self.cancelled = False
        self.running = False


async def send_ws_event(ws: WebSocket, payload: dict) -> None:
    if ws.client_state != WebSocketState.CONNECTED:
        return
    await ws.send_text(json.dumps(payload, ensure_ascii=True))


def resolve_pcm_sample_rate(format_name: str) -> int:
    normalized = format_name.strip().lower()
    if normalized.startswith("pcm_"):
        suffix = normalized.replace("pcm_", "", 1)
        if suffix.isdigit():
            return int(suffix)
    return 16000


async def write_wav_to_temp(pcm_bytes: bytes, sample_rate: int, channels: int) -> str:
    def _write() -> str:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tmp.close()
        with wave.open(tmp.name, "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm_bytes)
        return tmp.name

    return await asyncio.to_thread(_write)


async def transcribe_with_http(deps: StreamingDeps, audio_path: str, language: Optional[str]) -> str:
    if not deps.whisper_http_url:
        raise RuntimeError("WHISPER_HTTP_URL not configured")
    url = deps.whisper_http_url.rstrip("/")
    if not url.endswith("/v1/audio/transcriptions"):
        url = f"{url}/v1/audio/transcriptions"

    headers = {}
    if deps.whisper_http_api_key:
        headers["Authorization"] = f"Bearer {deps.whisper_http_api_key}"

    data = {"model": "whisper-1"}
    if language:
        data["language"] = language

    timeout = httpx.Timeout(60.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        with open(audio_path, "rb") as handle:
            files = {"file": ("audio.wav", handle, "audio/wav")}
            resp = await client.post(url, headers=headers, data=data, files=files)
    resp.raise_for_status()
    payload = resp.json()
    text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str):
        raise RuntimeError("Whisper HTTP response missing text")
    return text


async def transcribe_with_whisper_cli(
    deps: StreamingDeps, audio_path: str, language: Optional[str]
) -> str:
    if not deps.whisper_cmd:
        raise RuntimeError("WHISPER_CMD not configured")
    if shutil.which(deps.whisper_cmd) is None:
        raise RuntimeError(f"whisper command not found: {deps.whisper_cmd}")

    def _run() -> str:
        with tempfile.TemporaryDirectory() as tmpdir:
            args = [
                deps.whisper_cmd,
                audio_path,
                "--model",
                deps.whisper_model,
                "--output_format",
                "json",
                "--output_dir",
                tmpdir,
            ]
            if language:
                args.extend(["--language", language])
            result = subprocess.run(args, check=False, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "whisper command failed")
            base = os.path.splitext(os.path.basename(audio_path))[0]
            output_path = os.path.join(tmpdir, f"{base}.json")
            if not os.path.exists(output_path):
                raise RuntimeError("whisper output not found")
            payload = json.loads(open(output_path, "r", encoding="utf-8").read())
            text = payload.get("text") if isinstance(payload, dict) else None
            if not isinstance(text, str):
                raise RuntimeError("whisper output missing text")
            return text

    return await asyncio.to_thread(_run)


async def transcribe_audio(
    deps: StreamingDeps, pcm_bytes: bytes, sample_rate: int, channels: int, language: Optional[str]
) -> str:
    if not pcm_bytes:
        return ""
    wav_path = await write_wav_to_temp(pcm_bytes, sample_rate, channels)
    try:
        if deps.whisper_http_url:
            return await transcribe_with_http(deps, wav_path, language)
        return await transcribe_with_whisper_cli(deps, wav_path, language)
    finally:
        try:
            os.unlink(wav_path)
        except OSError:
            pass


async def stream_openclaw_reply(deps: StreamingDeps, session_key: str, text: str, ws: WebSocket) -> str:
    url = f"{deps.openclaw_base_url}/v1/responses"
    headers = deps.openclaw_headers(session_key)
    body = {"model": deps.openclaw_model, "input": text, "stream": True}

    assistant_text = ""
    timeout = httpx.Timeout(deps.openclaw_timeout_seconds, read=None)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, headers=headers, json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line.replace("data:", "", 1).strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "response.output_text.delta":
                    delta = event.get("delta")
                    if isinstance(delta, str):
                        assistant_text += delta
                        await send_ws_event(ws, {"type": "assistant.delta", "text": delta})
                if event.get("type") == "response.output_text.done":
                    done_text = event.get("text")
                    if isinstance(done_text, str):
                        assistant_text = done_text
    await send_ws_event(ws, {"type": "assistant.done", "text": assistant_text})
    return assistant_text


def pcm_peak_level(pcm_bytes: bytes) -> float:
    if not pcm_bytes:
        return 0.0
    peak = 0
    for idx in range(0, len(pcm_bytes) - 1, 2):
        sample = int.from_bytes(pcm_bytes[idx : idx + 2], "little", signed=True)
        peak = max(peak, abs(sample))
    return min(1.0, peak / 32768.0)


def resolve_voice_id(avatar: Any, fallback: str) -> str:
    if avatar is None:
        return fallback
    voice_id = getattr(avatar, "voice_id", None)
    return voice_id or fallback


async def stream_elevenlabs_tts(deps: StreamingDeps, text: str, voice_id: str, ws: WebSocket) -> None:
    if not deps.elevenlabs_api_key:
        await send_ws_event(ws, {"type": "tts.skipped", "reason": "missing_api_key"})
        return
    if not voice_id:
        await send_ws_event(ws, {"type": "tts.skipped", "reason": "missing_voice_id"})
        return

    url = f"{deps.elevenlabs_base_url}/v1/text-to-speech/{voice_id}/stream"
    params = {}
    if deps.elevenlabs_optimize_latency:
        params["optimize_streaming_latency"] = deps.elevenlabs_optimize_latency

    payload = {
        "text": text,
        "model_id": deps.elevenlabs_model_id,
        "output_format": deps.elevenlabs_output_format,
    }

    headers = {
        "xi-api-key": deps.elevenlabs_api_key,
        "Content-Type": "application/json",
    }
    accept = "audio/pcm" if deps.elevenlabs_output_format.startswith("pcm_") else "audio/mpeg"
    headers["Accept"] = accept

    await send_ws_event(
        ws,
        {
            "type": "tts.start",
            "voiceId": voice_id,
            "format": deps.elevenlabs_output_format,
        },
    )

    sample_rate = resolve_pcm_sample_rate(deps.elevenlabs_output_format)
    total_samples = 0

    timeout = httpx.Timeout(60.0, read=None)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, params=params, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                if not chunk:
                    continue
                encoded = base64.b64encode(chunk).decode("ascii")
                await send_ws_event(
                    ws,
                    {
                        "type": "tts.audio",
                        "format": deps.elevenlabs_output_format,
                        "sampleRate": sample_rate,
                        "data": encoded,
                    },
                )
                if deps.elevenlabs_output_format.startswith("pcm_"):
                    total_samples += len(chunk) // 2
                    level = pcm_peak_level(chunk)
                    await send_ws_event(
                        ws,
                        {
                            "type": "viseme",
                            "value": level,
                            "atMs": int(total_samples / sample_rate * 1000),
                        },
                    )

    await send_ws_event(ws, {"type": "tts.done"})


def attach_audio_ws(app: FastAPI, deps: StreamingDeps) -> None:
    @app.websocket("/ws/audio")
    async def audio_ws(ws: WebSocket) -> None:
        await ws.accept()
        state = AudioStreamState()

        try:
            while True:
                message = await ws.receive()
                if "text" in message and message["text"] is not None:
                    try:
                        payload = json.loads(message["text"])
                    except json.JSONDecodeError:
                        await send_ws_event(ws, {"type": "error", "message": "invalid_json"})
                        continue

                    msg_type = payload.get("type")
                    if msg_type == "audio.start":
                        if state.running:
                            await send_ws_event(ws, {"type": "error", "message": "session_busy"})
                            continue
                        state.reset()
                        state.project_id = payload.get("projectId")
                        state.avatar_id = payload.get("avatarId")
                        state.sample_rate = int(payload.get("sampleRate") or 16000)
                        state.channels = int(payload.get("channels") or 1)
                        state.audio_format = str(payload.get("format") or "pcm16")
                        state.language = payload.get("language") or deps.whisper_language or None
                        await send_ws_event(ws, {"type": "audio.started"})
                    elif msg_type == "audio.stop":
                        if not state.project_id:
                            await send_ws_event(ws, {"type": "error", "message": "audio_not_started"})
                            continue
                        state.running = True
                        try:
                            project = deps.get_project(state.project_id)
                            if state.avatar_id:
                                avatar = await deps.resolve_avatar(state.avatar_id)
                                if not avatar:
                                    await send_ws_event(
                                        ws, {"type": "error", "message": "unknown_avatar"}
                                    )
                                    state.running = False
                                    continue
                                project.avatar_id = avatar.avatar_id
                            else:
                                avatar = (
                                    await deps.resolve_avatar(project.avatar_id)
                                    if getattr(project, "avatar_id", None)
                                    else None
                                )

                            await send_ws_event(ws, {"type": "asr.start"})
                            transcript = await transcribe_audio(
                                deps,
                                bytes(state.buffer),
                                state.sample_rate,
                                state.channels,
                                state.language,
                            )
                            await send_ws_event(ws, {"type": "asr.final", "text": transcript})

                            if transcript:
                                assistant_text = await stream_openclaw_reply(
                                    deps, project.session_key, transcript, ws
                                )
                                voice_id = resolve_voice_id(
                                    avatar, deps.elevenlabs_default_voice_id
                                )
                                if assistant_text.strip():
                                    await stream_elevenlabs_tts(deps, assistant_text, voice_id, ws)
                            else:
                                await send_ws_event(ws, {"type": "assistant.done", "text": ""})
                        except Exception as exc:
                            await send_ws_event(ws, {"type": "error", "message": str(exc)})
                        finally:
                            state.reset()
                    elif msg_type == "audio.cancel":
                        state.cancelled = True
                        state.reset()
                        await send_ws_event(ws, {"type": "audio.cancelled"})
                    else:
                        await send_ws_event(ws, {"type": "error", "message": "unknown_event"})
                elif "bytes" in message and message["bytes"] is not None:
                    if not state.project_id:
                        await send_ws_event(ws, {"type": "error", "message": "audio_not_started"})
                        continue
                    state.buffer.extend(message["bytes"])
                else:
                    await send_ws_event(ws, {"type": "error", "message": "unsupported_message"})
        except WebSocketDisconnect:
            return
