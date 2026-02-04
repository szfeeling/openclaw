import SwiftUI

struct ContentView: View {
    @StateObject private var client = AudioStreamClient()
    @State private var wsUrl = "ws://localhost:8000/ws/audio"
    @State private var projectId = ""
    @State private var avatarId = ""

    var body: some View {
        NavigationView {
            VStack(spacing: 16) {
                TextField("WebSocket URL", text: $wsUrl)
                    .textFieldStyle(.roundedBorder)

                TextField("Project ID", text: $projectId)
                    .textFieldStyle(.roundedBorder)

                TextField("Avatar ID (optional)", text: $avatarId)
                    .textFieldStyle(.roundedBorder)

                HStack(spacing: 12) {
                    Button(client.isConnected ? "Disconnect" : "Connect") {
                        if client.isConnected {
                            client.disconnect()
                        } else if let url = URL(string: wsUrl) {
                            client.connect(url: url)
                        }
                    }

                    Button(client.isRecording ? "Stop" : "Record") {
                        if client.isRecording {
                            client.stopRecording()
                        } else {
                            client.startRecording(projectId: projectId, avatarId: avatarId.isEmpty ? nil : avatarId)
                        }
                    }
                    .disabled(!client.isConnected || projectId.isEmpty)
                }

                VStack(alignment: .leading, spacing: 8) {
                    Text("Status: \(client.status)")
                        .font(.footnote)
                        .foregroundColor(.secondary)

                    Text("Transcript")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Text(client.transcript)
                        .frame(maxWidth: .infinity, alignment: .leading)

                    Text("Assistant")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Text(client.assistantText)
                        .frame(maxWidth: .infinity, alignment: .leading)

                    Text("Viseme: \(String(format: "%.2f", client.visemeValue))")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                .frame(maxWidth: .infinity)
                .padding()
                .background(Color(.secondarySystemBackground))
                .cornerRadius(12)

                Spacer()
            }
            .padding()
            .navigationTitle("MyClient Audio")
        }
    }
}
