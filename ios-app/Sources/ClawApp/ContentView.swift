import SwiftUI
import ClawSDKWrapper

struct ContentView: View {
    @StateObject private var session: ClawSession
    @State private var inputText = ""
    @State private var scrollProxy: ScrollViewProxy?

    init() {
        // Replace with your API key or load it from the Keychain.
        let s = try! ClawSession(
            apiKey: ProcessInfo.processInfo.environment["ANTHROPIC_API_KEY"] ?? "",
            model: "claude-opus-4-6",
            systemPrompt: "You are a helpful assistant running on an iPhone."
        )
        _session = StateObject(wrappedValue: s)
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                messageList
                inputBar
            }
            .navigationTitle("Claw")
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    // MARK: - Message list

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    ForEach(session.messages) { message in
                        MessageBubble(message: message)
                            .id(message.id)
                    }
                    if session.isThinking && session.messages.last?.role == .user {
                        ThinkingIndicator()
                    }
                }
                .padding()
            }
            .onAppear { scrollProxy = proxy }
            .onChange(of: session.messages.count) { _ in
                scrollToBottom(proxy)
            }
        }
    }

    // MARK: - Input bar

    private var inputBar: some View {
        HStack(spacing: 8) {
            TextField("Message", text: $inputText, axis: .vertical)
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

    private var canSend: Bool {
        !inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !session.isThinking
    }

    // MARK: - Actions

    private func sendMessage() {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        inputText = ""

        Task {
            do {
                for try await _ in session.send(text) {
                    // text chunks are already applied inside ClawSession
                }
            } catch {
                session.lastError = error.localizedDescription
            }
        }
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy) {
        if let last = session.messages.last {
            withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
        }
    }
}

// MARK: - Sub-views

private struct MessageBubble: View {
    let message: ClawMessage

    var body: some View {
        HStack {
            if message.role == .user { Spacer(minLength: 60) }
            Text(message.text.isEmpty ? " " : message.text)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(bubbleColor)
                .foregroundStyle(foregroundColor)
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
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

#Preview {
    ContentView()
}
