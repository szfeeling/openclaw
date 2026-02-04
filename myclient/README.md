# OpenClaw Project Client (myclient)

Small demo app that maps each project to its own OpenClaw session key.

## What it does

- One project = one session key (`agent:<agentId>:proj:<projectId>`).
- Frontend shows a task/project list and a chat panel per project.
- Backend proxies to OpenClaw `/v1/responses` and supports streaming SSE.

## Prereqs

1) Enable OpenClaw OpenResponses HTTP endpoint:

```json5
{
  gateway: {
    http: {
      endpoints: {
        responses: { enabled: true },
      },
    },
  },
}
```

2) Ensure the Gateway auth token is available.

## Backend (Python)

Environment variables (see `.env.example`):

- `OPENCLAW_BASE_URL` (default `http://127.0.0.1:18789`)
- `OPENCLAW_TOKEN` (Gateway auth token)
- `OPENCLAW_AGENT_ID` (default `main`)
- `OPENCLAW_MODEL` (default `openclaw:main`)
- `ELEVENLABS_API_KEY` (optional; enables live voice list)
- `AVATAR_SOURCE` (`auto` | `elevenlabs` | `file`)
- `AVATAR_PRESETS_PATH` (optional; defaults to `backend/avatars.json`)
- `WHISPER_HTTP_URL` (optional; OpenAI-compatible Whisper endpoint)
- `WHISPER_CMD` (optional; local `whisper` CLI)
- `ELEVENLABS_MODEL_ID` (default `eleven_multilingual_v2`)
- `ELEVENLABS_OUTPUT_FORMAT` (default `pcm_16000`)

```bash
cd myclient/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure env
cp .env.example .env
# Edit .env to point at your OpenClaw Gateway + token

uvicorn app:app --reload --port 8000
```

## Frontend (Node)

```bash
cd myclient/frontend
npm install

# Optional: API base override
# export VITE_API_BASE=http://localhost:8000

npm run dev
```

Open the Vite URL (usually http://localhost:5173).

## Notes

- Session isolation is by project id; the backend always sends a stable session key.
- If you want per-project file isolation too, use multiple OpenClaw agents (one per project).
- Streaming uses `/api/chat/stream` and passes through OpenResponses SSE events.
- Avatar presets live at `myclient/backend/avatars.json` when `AVATAR_SOURCE=file`.

## Mobile audio streaming (WebSocket)

Endpoint: `ws://localhost:8000/ws/audio`

Client → Server (JSON frames):

```json
{ "type": "audio.start", "projectId": "<id>", "avatarId": "<id>", "format": "pcm16", "sampleRate": 16000, "channels": 1 }
```

Then send binary PCM chunks. When done:

```json
{ "type": "audio.stop" }
```

Server → Client (JSON frames):

- `asr.start`
- `asr.final`
- `assistant.delta`
- `assistant.done`
- `tts.start`
- `tts.audio` (base64 chunk)
- `viseme` (simple amplitude-based value)
- `tts.done`

ASR uses either `WHISPER_HTTP_URL` (OpenAI-compatible) or the local `whisper` CLI. If neither is configured, the server returns an error event.
