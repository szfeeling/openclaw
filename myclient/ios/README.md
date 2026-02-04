# iOS streaming client (sample)

Minimal SwiftUI client for `/ws/audio` streaming. Add these files to your Xcode iOS app.

## Setup

1) Create an iOS app in Xcode (SwiftUI).
2) Add these files to the target:
   - `AudioRecorder.swift`
   - `AudioPlayback.swift`
   - `AudioStreamClient.swift`
   - `UnityBridge.swift`
   - `ContentView.swift` (or copy the view into your app)
3) Add microphone permission to **Info.plist**:

```
Privacy - Microphone Usage Description
```

Example value: `We need access to the microphone for voice input.`

4) Backend requirements:
   - `/ws/audio` running (see `myclient/backend/streaming.py`)
   - `ELEVENLABS_OUTPUT_FORMAT=pcm_16000`

## Usage

- Set `wsUrl` (e.g., `ws://<your-host>:8000/ws/audio`)
- Set `projectId` (from `/api/projects`)
- Optional `avatarId` (from `/api/avatars`)
- Tap **Connect**, then **Record**

## Unity hook

`UnityBridge.updateViseme(_:)` is a stub. Forward `value` to Unity (UnitySendMessage or native bridge).
