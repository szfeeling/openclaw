import AVFoundation

final class AudioRecorder {
    private let engine = AVAudioEngine()
    private var converter: AVAudioConverter?
    private var onPcmData: ((Data) -> Void)?

    private let targetFormat = AVAudioFormat(
        commonFormat: .pcmFormatInt16,
        sampleRate: 16_000,
        channels: 1,
        interleaved: false
    )

    func start(onPcmData: @escaping (Data) -> Void) throws {
        self.onPcmData = onPcmData

        guard let targetFormat = targetFormat else {
            throw NSError(domain: "AudioRecorder", code: -1, userInfo: [NSLocalizedDescriptionKey: "Invalid target format"])
        }

        let input = engine.inputNode
        let inputFormat = input.outputFormat(forBus: 0)
        converter = AVAudioConverter(from: inputFormat, to: targetFormat)

        input.installTap(onBus: 0, bufferSize: 1024, format: inputFormat) { [weak self] buffer, _ in
            self?.handleBuffer(buffer)
        }

        try engine.start()
    }

    func stop() {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        onPcmData = nil
        converter = nil
    }

    private func handleBuffer(_ buffer: AVAudioPCMBuffer) {
        guard let converter = converter, let targetFormat = targetFormat else { return }
        guard let pcmBuffer = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: buffer.frameCapacity) else {
            return
        }

        var error: NSError?
        let status = converter.convert(to: pcmBuffer, error: &error) { _, outStatus in
            outStatus.pointee = .haveData
            return buffer
        }

        if status == .error || error != nil { return }
        guard let channelData = pcmBuffer.int16ChannelData else { return }
        let frameLength = Int(pcmBuffer.frameLength)
        let byteCount = frameLength * MemoryLayout<Int16>.size
        let data = Data(bytes: channelData[0], count: byteCount)
        onPcmData?(data)
    }
}
