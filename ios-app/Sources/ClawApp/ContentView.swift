import SwiftUI
import ClawSDKWrapper

struct ContentView: View {
    @StateObject private var session: ClawSession
    @State private var inputText = ""
    @State private var exportMessage: ClawMessage?
    @State private var selectedMode: AgentMode = .general

    private static let documentsPath =
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)
            .first?.path ?? NSTemporaryDirectory()

    init() {
        let env = ProcessInfo.processInfo.environment
        let s = try! ClawSession.autonomous(
            apiKey: env["ANTHROPIC_API_KEY"] ?? "",
            searchApiKey: env["TAVILY_API_KEY"] ?? "",
            documentsPath: Self.documentsPath,
            firecrawlApiKey: env["FIRECRAWL_API_KEY"],
            mode: .general
        )
        _session = StateObject(wrappedValue: s)
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                modePicker
                messageList
                if let error = session.lastError {
                    Text(error)
                        .foregroundStyle(.red)
                        .font(.caption)
                        .padding(.horizontal)
                        .onTapGesture { session.lastError = nil }
                }
                inputBar
            }
            .navigationTitle("Claw")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button { session.reset() } label: {
                        Image(systemName: "square.and.pencil")
                    }
                }
            }
        }
        .sheet(item: $exportMessage) { msg in
            ShareSheet(items: [ClawPDFExporter.export(text: msg.text, title: modeName)])
        }
    }

    // MARK: - Mode picker

    private var modePicker: some View {
        Picker("Mode", selection: $selectedMode) {
            Text("General").tag(AgentMode.general)
            Text("Research").tag(AgentMode.research)
            Text("Writing").tag(AgentMode.writing)
            Text("Analysis").tag(AgentMode.analysis)
        }
        .pickerStyle(.segmented)
        .padding(.horizontal)
        .padding(.vertical, 6)
        .background(Color(.secondarySystemBackground))
        .onChange(of: selectedMode) { mode in
            session.setMode(mode)
        }
    }

    private var modeName: String {
        switch selectedMode {
        case .general:  return "Claw Response"
        case .research: return "Research Report"
        case .writing:  return "Document"
        case .analysis: return "Analysis"
        }
    }

    // MARK: - Message list

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    ForEach(session.messages) { message in
                        MessageBubble(message: message) {
                            if message.role == .assistant { exportMessage = message }
                        }
                        .id(message.id)
                    }
                    if session.isThinking && session.messages.last?.role == .user {
                        ThinkingIndicator()
                            .padding(.leading, 16)
                    }
                }
                .padding()
            }
            .onChange(of: session.messages.count) { _ in
                if let last = session.messages.last {
                    withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                }
            }
        }
    }

    // MARK: - Input bar

    private var inputBar: some View {
        HStack(spacing: 8) {
            TextField(placeholder, text: $inputText, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(1...5)
                .disabled(session.isThinking)

            Button(action: sendMessage) {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.title2)
                    .foregroundStyle(canSend ? .blue : .gray)
            }
            .disabled(!canSend)
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
        .background(.regularMaterial)
    }

    private var placeholder: String {
        switch selectedMode {
        case .general:  return "Message"
        case .research: return "What do you want to research?"
        case .writing:  return "What do you want me to write?"
        case .analysis: return "What do you want me to analyze?"
        }
    }

    private var canSend: Bool {
        !inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !session.isThinking
    }

    // MARK: - Actions

    private func sendMessage() {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        inputText = ""
        Task {
            do {
                for try await _ in session.stream(text) {}
            } catch {
                session.lastError = error.localizedDescription
            }
        }
    }
}

// MARK: - Sub-views

private struct MessageBubble: View {
    let message: ClawMessage
    let onExport: () -> Void

    var body: some View {
        HStack(alignment: .bottom, spacing: 6) {
            if message.role == .user { Spacer(minLength: 60) }

            VStack(alignment: message.role == .user ? .trailing : .leading, spacing: 4) {
                Text(message.text.isEmpty ? " " : message.text)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(bubbleColor)
                    .foregroundStyle(foregroundColor)
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))

                if message.role == .assistant && !message.text.isEmpty {
                    Button(action: onExport) {
                        Label("Export PDF", systemImage: "arrow.up.doc")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.leading, 6)
                }
            }

            if message.role == .assistant { Spacer(minLength: 60) }
        }
    }

    private var bubbleColor: Color {
        message.role == .user ? .blue : Color(.secondarySystemBackground)
    }

    private var foregroundColor: Color {
        message.role == .user ? .white : .primary
    }
}

private struct ThinkingIndicator: View {
    @State private var dots = ""
    private let timer = Timer.publish(every: 0.4, on: .main, in: .common).autoconnect()

    var body: some View {
        Text("Claude is thinking\(dots)")
            .foregroundStyle(.secondary)
            .font(.subheadline)
            .onReceive(timer) { _ in
                dots = dots.count < 3 ? dots + "." : ""
            }
    }
}

private struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}

#Preview {
    ContentView()
}
