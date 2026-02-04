import AVFoundation

final class AudioPlayback {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let format = AVAudioFormat(
        commonFormat: .pcmFormatInt16,
        sampleRate: 16_000,
        channels: 1,
        interleaved: false
    )

    private var started = false

    init() {
        if let format = format {
            engine.attach(player)
            engine.connect(player, to: engine.mainMixerNode, format: format)
        }
    }

    func start() throws {
        guard !started else { return }
        if engine.isRunning { return }
        try engine.start()
        player.play()
        started = true
    }

    func stop() {
        player.stop()
        engine.stop()
        started = false
    }

    func enqueuePcm(_ data: Data) {
        guard let format = format else { return }
        let frameCount = AVAudioFrameCount(data.count / MemoryLayout<Int16>.size)
        guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount) else { return }
        buffer.frameLength = frameCount
        guard let channel = buffer.int16ChannelData else { return }

        data.withUnsafeBytes { raw in
            guard let base = raw.bindMemory(to: Int16.self).baseAddress else { return }
            channel[0].assign(from: base, count: Int(frameCount))
        }

        player.scheduleBuffer(buffer, completionHandler: nil)
    }
}
