from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional

import json

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from streaming import StreamingDeps, attach_audio_ws

OPENCLAW_BASE_URL = os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:18789").rstrip("/")
OPENCLAW_TOKEN = os.getenv("OPENCLAW_TOKEN", "").strip()
OPENCLAW_AGENT_ID = os.getenv("OPENCLAW_AGENT_ID", "main").strip() or "main"
OPENCLAW_MODEL = os.getenv("OPENCLAW_MODEL", f"openclaw:{OPENCLAW_AGENT_ID}").strip() or "openclaw"
OPENCLAW_TIMEOUT_SECONDS = float(os.getenv("OPENCLAW_TIMEOUT_SECONDS", "60"))

DEFAULT_ORIGINS = "http://localhost:5173"
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", DEFAULT_ORIGINS).split(",")]

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
ELEVENLABS_BASE_URL = os.getenv("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io").rstrip("/")
ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2").strip()
ELEVENLABS_OUTPUT_FORMAT = os.getenv("ELEVENLABS_OUTPUT_FORMAT", "pcm_16000").strip()
ELEVENLABS_OPTIMIZE_LATENCY = os.getenv("ELEVENLABS_OPTIMIZE_LATENCY", "").strip()
ELEVENLABS_DEFAULT_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "").strip()

WHISPER_HTTP_URL = os.getenv("WHISPER_HTTP_URL", "").strip()
WHISPER_HTTP_API_KEY = os.getenv("WHISPER_HTTP_API_KEY", "").strip()
WHISPER_CMD = os.getenv("WHISPER_CMD", "whisper").strip()
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base").strip()
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "").strip()
AVATAR_CACHE_TTL_SECONDS = float(os.getenv("AVATAR_CACHE_TTL_SECONDS", "300"))
AVATAR_SOURCE = os.getenv("AVATAR_SOURCE", "auto").strip().lower()
_avatar_presets_env = (os.getenv("AVATAR_PRESETS_PATH") or "").strip()
AVATAR_PRESETS_PATH = (
    Path(_avatar_presets_env)
    if _avatar_presets_env
    else Path(__file__).with_name("avatars.json")
)

app = FastAPI(title="OpenClaw Project Client", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin for origin in ALLOWED_ORIGINS if origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@dataclass
class Project:
    project_id: str
    name: str
    session_key: str
    created_at: float
    avatar_id: str | None = None


@dataclass
class Avatar:
    avatar_id: str
    name: str
    voice_id: str


projects: Dict[str, Project] = {}
_avatar_cache: list[Avatar] = []
_avatar_cache_at: float = 0.0


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    avatar_id: Optional[str] = Field(default=None, alias="avatarId")


class ProjectUpdate(BaseModel):
    avatar_id: Optional[str] = Field(default=None, alias="avatarId")


class ProjectView(BaseModel):
    id: str
    name: str
    session_key: str
    created_at: float
    avatar_id: Optional[str] = Field(default=None, alias="avatarId")


class AvatarView(BaseModel):
    id: str
    name: str
    voice_id: str = Field(..., alias="voiceId")


class ChatRequest(BaseModel):
    project_id: str = Field(..., alias="projectId")
    message: str
    instructions: Optional[str] = None
    avatar_id: Optional[str] = Field(default=None, alias="avatarId")


class ChatResponse(BaseModel):
    reply: str


def make_session_key(project_id: str) -> str:
    cleaned = project_id.strip().lower()
    return f"agent:{OPENCLAW_AGENT_ID}:proj:{cleaned}"


def get_project(project_id: str) -> Project:
    project = projects.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _cache_expired() -> bool:
    if AVATAR_CACHE_TTL_SECONDS <= 0:
        return True
    return (time.time() - _avatar_cache_at) > AVATAR_CACHE_TTL_SECONDS


def _normalize_avatar_entry(entry: dict) -> Optional[Avatar]:
    avatar_id = str(entry.get("id") or entry.get("avatarId") or entry.get("voiceId") or "").strip()
    name = str(entry.get("name") or "").strip()
    voice_id = str(entry.get("voiceId") or entry.get("voice_id") or avatar_id).strip()
    if not avatar_id or not name or not voice_id:
        return None
    return Avatar(avatar_id=avatar_id, name=name, voice_id=voice_id)


def _load_avatar_presets() -> list[Avatar]:
    if not AVATAR_PRESETS_PATH.exists():
        return []
    try:
        raw = json.loads(AVATAR_PRESETS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    avatars: list[Avatar] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        avatar = _normalize_avatar_entry(entry)
        if avatar:
            avatars.append(avatar)
    return avatars


async def _fetch_elevenlabs_voices() -> list[Avatar]:
    if not ELEVENLABS_API_KEY:
        return []
    url = f"{ELEVENLABS_BASE_URL}/v1/voices"
    timeout = httpx.Timeout(15.0)
    headers = {"xi-api-key": ELEVENLABS_API_KEY}
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url, headers=headers)
    resp.raise_for_status()
    payload = resp.json()
    voices = payload.get("voices", [])
    avatars: list[Avatar] = []
    if isinstance(voices, list):
        for voice in voices:
            if not isinstance(voice, dict):
                continue
            voice_id = str(voice.get("voice_id") or "").strip()
            name = str(voice.get("name") or "").strip()
            if not voice_id or not name:
                continue
            avatars.append(Avatar(avatar_id=voice_id, name=name, voice_id=voice_id))
    return avatars


async def resolve_avatars() -> list[Avatar]:
    global _avatar_cache, _avatar_cache_at
    if _avatar_cache and not _cache_expired():
        return _avatar_cache

    if AVATAR_SOURCE == "file":
        avatars = _load_avatar_presets()
    elif AVATAR_SOURCE == "elevenlabs":
        avatars = await _fetch_elevenlabs_voices()
    else:
        avatars = []
        if ELEVENLABS_API_KEY:
            try:
                avatars = await _fetch_elevenlabs_voices()
            except httpx.HTTPError:
                avatars = []
        if not avatars:
            avatars = _load_avatar_presets()

    _avatar_cache = avatars
    _avatar_cache_at = time.time()
    return avatars


async def resolve_avatar(avatar_id: Optional[str]) -> Optional[Avatar]:
    if not avatar_id:
        return None
    avatars = await resolve_avatars()
    for avatar in avatars:
        if avatar.avatar_id == avatar_id:
            return avatar
    return None


def openclaw_headers(session_key: str) -> Dict[str, str]:
    headers: Dict[str, str] = {
        "x-openclaw-session-key": session_key,
        "x-openclaw-agent-id": OPENCLAW_AGENT_ID,
    }
    if OPENCLAW_TOKEN:
        headers["Authorization"] = f"Bearer {OPENCLAW_TOKEN}"
    return headers


def extract_output_text(payload: dict) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    output = payload.get("output")
    if not isinstance(output, list):
        return ""
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for part in item.get("content", []) or []:
                if not isinstance(part, dict):
                    continue
                if part.get("type") in {"output_text", "text"}:
                    text = part.get("text")
                    if isinstance(text, str):
                        chunks.append(text)
    return "".join(chunks)


@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "openclaw_base_url": OPENCLAW_BASE_URL,
            "openclaw_agent": OPENCLAW_AGENT_ID,
            "model": OPENCLAW_MODEL,
            "avatars_source": AVATAR_SOURCE,
        }
    )


@app.get("/api/avatars", response_model=list[AvatarView])
async def list_avatars() -> list[AvatarView]:
    avatars = await resolve_avatars()
    return [
        AvatarView(id=avatar.avatar_id, name=avatar.name, voiceId=avatar.voice_id)
        for avatar in avatars
    ]


@app.get("/api/projects", response_model=list[ProjectView])
async def list_projects() -> list[ProjectView]:
    return [
        ProjectView(
            id=project.project_id,
            name=project.name,
            session_key=project.session_key,
            created_at=project.created_at,
            avatarId=project.avatar_id,
        )
        for project in projects.values()
    ]


@app.post("/api/projects", response_model=ProjectView)
async def create_project(payload: ProjectCreate) -> ProjectView:
    avatars = await resolve_avatars()
    avatar_id = payload.avatar_id
    if avatar_id:
        avatar = await resolve_avatar(avatar_id)
        if not avatar:
            raise HTTPException(status_code=400, detail="Unknown avatarId")
    elif avatars:
        avatar_id = avatars[0].avatar_id

    project_id = uuid.uuid4().hex
    session_key = make_session_key(project_id)
    project = Project(
        project_id=project_id,
        name=payload.name.strip(),
        session_key=session_key,
        created_at=time.time(),
        avatar_id=avatar_id,
    )
    projects[project_id] = project
    return ProjectView(
        id=project.project_id,
        name=project.name,
        session_key=project.session_key,
        created_at=project.created_at,
        avatarId=project.avatar_id,
    )


@app.patch("/api/projects/{project_id}", response_model=ProjectView)
async def update_project(project_id: str, payload: ProjectUpdate) -> ProjectView:
    project = get_project(project_id)
    if payload.avatar_id is not None:
        avatar = await resolve_avatar(payload.avatar_id)
        if not avatar:
            raise HTTPException(status_code=400, detail="Unknown avatarId")
        project.avatar_id = avatar.avatar_id
    return ProjectView(
        id=project.project_id,
        name=project.name,
        session_key=project.session_key,
        created_at=project.created_at,
        avatarId=project.avatar_id,
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    project = get_project(payload.project_id)
    if payload.avatar_id and payload.avatar_id != project.avatar_id:
        avatar = await resolve_avatar(payload.avatar_id)
        if not avatar:
            raise HTTPException(status_code=400, detail="Unknown avatarId")
        project.avatar_id = avatar.avatar_id
    request_payload: dict = {
        "model": OPENCLAW_MODEL,
        "input": payload.message,
    }
    if payload.instructions:
        request_payload["instructions"] = payload.instructions

    url = f"{OPENCLAW_BASE_URL}/v1/responses"
    headers = openclaw_headers(project.session_key)

    timeout = httpx.Timeout(OPENCLAW_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(url, headers=headers, json=request_payload)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"OpenClaw request failed: {exc}") from exc

    data = resp.json()
    reply = extract_output_text(data)
    return ChatResponse(reply=reply)


async def stream_openclaw_events(
    url: str,
    headers: Dict[str, str],
    payload: dict,
) -> Iterable[str]:
    timeout = httpx.Timeout(OPENCLAW_TIMEOUT_SECONDS, read=None)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                if line.startswith("data:"):
                    yield f"{line}\n\n"
                else:
                    yield f"data: {line}\n\n"


@app.post("/api/chat/stream")
async def chat_stream(payload: ChatRequest) -> StreamingResponse:
    project = get_project(payload.project_id)
    if payload.avatar_id and payload.avatar_id != project.avatar_id:
        avatar = await resolve_avatar(payload.avatar_id)
        if not avatar:
            raise HTTPException(status_code=400, detail="Unknown avatarId")
        project.avatar_id = avatar.avatar_id
    request_payload: dict = {
        "model": OPENCLAW_MODEL,
        "input": payload.message,
        "stream": True,
    }
    if payload.instructions:
        request_payload["instructions"] = payload.instructions

    url = f"{OPENCLAW_BASE_URL}/v1/responses"
    headers = openclaw_headers(project.session_key)

    return StreamingResponse(
        stream_openclaw_events(url, headers, request_payload),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


attach_audio_ws(
    app,
    StreamingDeps(
        openclaw_base_url=OPENCLAW_BASE_URL,
        openclaw_model=OPENCLAW_MODEL,
        openclaw_timeout_seconds=OPENCLAW_TIMEOUT_SECONDS,
        openclaw_headers=openclaw_headers,
        get_project=get_project,
        resolve_avatar=resolve_avatar,
        elevenlabs_api_key=ELEVENLABS_API_KEY,
        elevenlabs_base_url=ELEVENLABS_BASE_URL,
        elevenlabs_model_id=ELEVENLABS_MODEL_ID,
        elevenlabs_output_format=ELEVENLABS_OUTPUT_FORMAT,
        elevenlabs_optimize_latency=ELEVENLABS_OPTIMIZE_LATENCY,
        elevenlabs_default_voice_id=ELEVENLABS_DEFAULT_VOICE_ID,
        whisper_http_url=WHISPER_HTTP_URL,
        whisper_http_api_key=WHISPER_HTTP_API_KEY,
        whisper_cmd=WHISPER_CMD,
        whisper_model=WHISPER_MODEL,
        whisper_language=WHISPER_LANGUAGE,
    ),
)
