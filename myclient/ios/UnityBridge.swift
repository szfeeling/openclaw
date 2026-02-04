import Foundation

final class UnityBridge {
    static let shared = UnityBridge()

    private init() {}

    func updateViseme(_ value: Double) {
        // TODO: forward to Unity (UnitySendMessage or native bridge)
        _ = value
    }
}
