# myclient MVP 部署与测试说明

本文档覆盖 myclient MVP 的部署与测试流程（后端 + Web 前端 + iOS 语音流式客户端）。

## 目标与范围

- 以 OpenClaw Gateway 作为 LLM 网关。
- 后端负责项目会话、OpenClaw 代理、ASR/TTS 流式转发。
- Web 前端用于创建项目、挑选数字人、文本对话验证。
- iOS 客户端用于录音、WebSocket 语音流式、播放与口型驱动验证。

## 依赖与前提

- OpenClaw Gateway 已启动，且开启 `/v1/responses` HTTP 端点。
- Python 3.11+、Node 22+。
- iOS 需要 Xcode 15+，真机或模拟器均可。
- 可选：
  - Whisper ASR：`WHISPER_HTTP_URL`（OpenAI 兼容接口）或本地 `whisper` CLI。
  - ElevenLabs TTS：`ELEVENLABS_API_KEY`。

## 1) 配置 OpenClaw Gateway

确保 `responses` 端点启用（配置文件示意）：

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

## 2) 后端配置与启动（FastAPI）

1. 准备环境变量：

```bash
cd myclient/backend
cp .env.example .env
```

2. 根据实际情况填写 `.env`（示例字段）：

- `OPENCLAW_BASE_URL`（默认 `http://127.0.0.1:18789`）
- `OPENCLAW_TOKEN`（Gateway auth token）
- `OPENCLAW_AGENT_ID`（默认 `main`）
- `OPENCLAW_MODEL`（默认 `openclaw:main`）
- `ELEVENLABS_API_KEY`（可选，启用 TTS）
- `ELEVENLABS_OUTPUT_FORMAT`（推荐 `pcm_16000`）
- `WHISPER_HTTP_URL`（可选，OpenAI 兼容 Whisper 端点）
- `WHISPER_CMD`（可选，本地 whisper CLI）

后端启动时会自动加载 `myclient/backend/.env`（若 shell 中已设置同名环境变量，则以 shell 为准）。

3. 启动后端：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

后端默认监听 `http://127.0.0.1:8000`，语音流式 WebSocket 在 `ws://127.0.0.1:8000/ws/audio`。

## 2.1) 远程部署（后端）

建议后端部署在 Linux 服务器上，并通过反向代理提供 HTTPS/WSS。

1. 上传代码并准备虚拟环境：

```bash
cd /opt/openclaw/myclient/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

2. 配置 `.env`（与本地一致），并确认以下要点：

- `OPENCLAW_BASE_URL` 指向 Gateway 地址（例如 `http://127.0.0.1:18789` 或内网地址）。
- 若对外提供 HTTPS，前端/客户端需使用 `https://` 与 `wss://`。

3. 使用 systemd 启动（示例）：

```ini
[Unit]
Description=myclient backend
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/openclaw/myclient/backend
EnvironmentFile=/opt/openclaw/myclient/backend/.env
ExecStart=/opt/openclaw/myclient/backend/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

> 说明：MVP 建议单进程运行（WebSocket 会话更稳定）。若需多进程，请在反向代理上保持会话粘滞。

## 2.2) 反向代理与 WSS（Nginx 示例）

```nginx
server {
  listen 443 ssl;
  server_name api.example.com;

  location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 3600;
  }
}
```

## 3) Web 前端启动（Vite）

```bash
cd myclient/frontend
npm install
# 可选：后端不在同一 host/port 时设置（优先级最高）
# export VITE_API_BASE=http://127.0.0.1:8000
# 或者修改运行时配置文件（无需重新构建）
# myclient/frontend/public/app-config.json -> {"apiBase":"http://127.0.0.1:8000"}
npm run dev
```

打开 Vite 提示的地址（通常为 `http://127.0.0.1:5173`）。

## 3.1) 远程部署（前端静态托管）

1. 生产构建：

```bash
cd myclient/frontend
export VITE_API_BASE=https://api.example.com
npm install
npm run build
```

如果不想通过环境变量固化地址，也可在部署时直接修改 `dist/app-config.json`（或构建前修改 `public/app-config.json`）。

2. 将 `dist/` 部署到任意静态托管（Nginx/S3/CDN）。
3. iOS/移动端请使用 `https://` 与 `wss://` 指向后端。

## 3.2) Docker 部署（可选）

以下为最小化示例，适合 MVP 快速验证。你可以将这些文件放在 `myclient/` 目录下。
请将示例内容分别保存为：`myclient/Dockerfile.backend`、`myclient/Dockerfile.frontend`、`myclient/docker-compose.yaml`。

### 后端 Dockerfile（示例）

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY myclient/backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY myclient/backend /app
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 前端 Dockerfile（示例）

```dockerfile
FROM node:22-slim AS build
WORKDIR /app
COPY myclient/frontend/package*.json /app/
RUN npm install
COPY myclient/frontend /app
ARG VITE_API_BASE
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
```

### docker-compose.yaml（示例）

```yaml
services:
  myclient-backend:
    build:
      context: .
      dockerfile: myclient/Dockerfile.backend
    env_file:
      - myclient/backend/.env
    ports:
      - "8000:8000"
    # 若 Gateway 在宿主机，可考虑使用 host 网络或调整 OPENCLAW_BASE_URL
    # network_mode: host

  myclient-frontend:
    build:
      context: .
      dockerfile: myclient/Dockerfile.frontend
      args:
        VITE_API_BASE: "https://api.example.com"
    ports:
      - "8080:80"
```

### 构建与启动

```bash
# 启动
docker compose -f myclient/docker-compose.yaml up --build
```

> 注意：如果 OpenClaw Gateway 不在容器内，需要确保容器能访问到 Gateway 地址。
>
> - macOS/Windows 可用 `http://host.docker.internal:18789`
> - Linux 建议使用 host 网络或配置网关地址可达。

## 4) iOS MVP 测试流程

1. 在 Web 前端创建项目，并选择一个数字人（可选）。
2. 获取 `projectId`：
   - 打开浏览器控制台调用 `GET /api/projects`，或
   - 直接访问 `http://127.0.0.1:8000/api/projects` 查看 JSON。
3. 在 Xcode 新建 SwiftUI App，并将以下文件加入 target：
   - `myclient/ios/AudioRecorder.swift`
   - `myclient/ios/AudioPlayback.swift`
   - `myclient/ios/AudioStreamClient.swift`
   - `myclient/ios/UnityBridge.swift`
   - `myclient/ios/ContentView.swift`
4. 在 **Info.plist** 中添加麦克风权限：
   - `Privacy - Microphone Usage Description`
5. 运行 App：
   - `WebSocket URL` 填 `ws://<backend-host>:8000/ws/audio`（远程建议 `wss://api.example.com/ws/audio`）
   - `Project ID` 填上一步获取的 `projectId`
   - `Avatar ID` 可选（从 `/api/avatars` 获取）
6. 点击 **Connect**，再点击 **Record**，录音后 **Stop**。
   - 期望看到 `Transcript`/`Assistant` 文本更新。
   - 若配置了 ElevenLabs，播放将有 TTS 音频。

## 5) 语音流式协议（WS）

Client → Server（JSON）：

```json
{
  "type": "audio.start",
  "projectId": "<id>",
  "avatarId": "<id>",
  "format": "pcm16",
  "sampleRate": 16000,
  "channels": 1
}
```

之后发送二进制 PCM16 小端音频帧。结束时发送：

```json
{ "type": "audio.stop" }
```

Server → Client（JSON 事件）：

- `asr.start`
- `asr.final`（识别结果）
- `assistant.delta`（OpenClaw 回复增量）
- `assistant.done`
- `tts.start`
- `tts.audio`（base64 音频分片）
- `viseme`（0-1 口型强度，占位实现）
- `tts.done`

## 6) 常见问题排查

- `HTTP 401`：
  - `OPENCLAW_TOKEN` 缺失或无效；
  - `gateway.http.endpoints.responses.enabled` 未开启。
- `asr` 报错：
  - 未配置 `WHISPER_HTTP_URL` 或 `WHISPER_CMD`。
- `tts` 跳过：
  - 未配置 `ELEVENLABS_API_KEY` 或 voiceId 无效。
- iOS 无声音：
  - 确认音频格式为 PCM16、16kHz、单声道；
  - 检查 `ELEVENLABS_OUTPUT_FORMAT=pcm_16000`。

## 7) MVP 验收要点

- Web 文本对话可用（项目会话隔离）。
- iOS 语音录制 → ASR → OpenClaw → TTS 播放链路通。
- `viseme` 事件可用于 Unity 口型驱动（当前为音量占位）。
