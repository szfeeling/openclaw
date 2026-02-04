import AVFoundation
import Combine
import Foundation

@MainActor
final class AudioStreamClient: ObservableObject {
    @Published var status: String = "Disconnected"
    @Published var transcript: String = ""
    @Published var assistantText: String = ""
    @Published var isConnected: Bool = false
    @Published var isRecording: Bool = false
    @Published var visemeValue: Double = 0

    private var task: URLSessionWebSocketTask?
    private let recorder = AudioRecorder()
    private let playback = AudioPlayback()
    private var cancellables = Set<AnyCancellable>()

    func connect(url: URL) {
        disconnect()
        let session = URLSession(configuration: .default)
        let task = session.webSocketTask(with: url)
        self.task = task
        task.resume()
        isConnected = true
        status = "Connected"
        listen()
    }

    func disconnect() {
        stopRecording()
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        isConnected = false
        status = "Disconnected"
    }

    func startRecording(projectId: String, avatarId: String?) {
        guard let task = task else { return }
        assistantText = ""
        transcript = ""

        configureAudioSession()

        let payload: [String: Any] = [
            "type": "audio.start",
            "projectId": projectId,
            "avatarId": avatarId as Any,
            "format": "pcm16",
            "sampleRate": 16000,
            "channels": 1
        ]
        sendJson(task: task, payload: payload)

        do {
            try playback.start()
            try recorder.start { [weak self] data in
                guard let self = self else { return }
                self.sendBinary(data)
            }
            isRecording = true
            status = "Recording"
        } catch {
            status = "Audio start failed: \(error.localizedDescription)"
        }
    }

    func stopRecording() {
        guard let task = task, isRecording else { return }
        recorder.stop()
        playback.stop()
        sendJson(task: task, payload: ["type": "audio.stop"])
        isRecording = false
        status = "Processing"
    }

    private func sendBinary(_ data: Data) {
        task?.send(.data(data)) { [weak self] error in
            if let error = error {
                DispatchQueue.main.async {
                    self?.status = "Send failed: \(error.localizedDescription)"
                }
            }
        }
    }

    private func sendJson(task: URLSessionWebSocketTask, payload: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let text = String(data: data, encoding: .utf8) else { return }
        task.send(.string(text)) { [weak self] error in
            if let error = error {
                DispatchQueue.main.async {
                    self?.status = "Send failed: \(error.localizedDescription)"
                }
            }
        }
    }

    private func listen() {
        task?.receive { [weak self] result in
            guard let self = self else { return }
            switch result {
            case .failure(let error):
                DispatchQueue.main.async {
                    self.status = "WS error: \(error.localizedDescription)"
                    self.isConnected = false
                }
            case .success(let message):
                self.handleMessage(message)
                self.listen()
            }
        }
    }

    private func handleMessage(_ message: URLSessionWebSocketTask.Message) {
        switch message {
        case .string(let text):
            guard let data = text.data(using: .utf8) else { return }
            handleJson(data)
        case .data(let data):
            handleJson(data)
        @unknown default:
            break
        }
    }

    private func handleJson(_ data: Data) {
        guard let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = payload["type"] as? String else { return }

        switch type {
        case "asr.final":
            transcript = payload["text"] as? String ?? transcript
            status = "ASR done"
        case "assistant.delta":
            let delta = payload["text"] as? String ?? ""
            assistantText.append(delta)
        case "assistant.done":
            status = "Reply done"
        case "tts.start":
            status = "Speaking"
        case "tts.audio":
            guard let base64 = payload["data"] as? String,
                  let audioData = Data(base64Encoded: base64) else { return }
            playback.enqueuePcm(audioData)
        case "viseme":
            if let value = payload["value"] as? Double {
                visemeValue = value
                UnityBridge.shared.updateViseme(value)
            }
        case "tts.done":
            status = "Idle"
        case "error":
            status = payload["message"] as? String ?? "Error"
        default:
            break
        }
    }

    private func configureAudioSession() {
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker, .allowBluetooth])
            try session.setActive(true)
        } catch {
            status = "Audio session error: \(error.localizedDescription)"
        }
    }
}
