import ClawIosSDK
import Foundation

// MARK: - Public async/await wrapper

/// A conversation session with Claude, designed for use in SwiftUI apps.
///
/// Usage:
/// ```swift
/// let session = try ClawSession(apiKey: "sk-ant-...", model: "claude-opus-4-6")
/// let result  = try await session.send("Hello!")
/// print(result)
/// ```
@MainActor
public final class ClawSession: ObservableObject {
    @Published public var messages: [ClawMessage] = []
    @Published public var isThinking = false
    @Published public var lastError: String?

    private let inner: ClawIosSession

    public init(
        apiKey: String,
        model: String = "claude-opus-4-6",
        systemPrompt: String? = nil,
        enableFileTools: Bool = false,
        enableRagMode: Bool = false
    ) throws {
        let config = ClawIosConfig(
            apiKey: apiKey,
            model: model,
            systemPrompt: systemPrompt,
            baseUrl: nil,
            enableFileTools: enableFileTools,
            enableRagMode: enableRagMode
        )
        self.inner = try ClawIosSession(config: config)
    }

    /// Send a user message and return the full assistant reply.
    /// The session history is updated automatically.
    ///
    /// This method runs the blocking Rust call on a background thread
    /// so it is safe to await from the main actor.
    @discardableResult
    public func send(_ text: String) async throws -> String {
        let userMsg = ClawMessage(role: .user, text: text)
        messages.append(userMsg)

        // Placeholder for the assistant reply (updated below)
        let assistantMsg = ClawMessage(role: .assistant, text: "")
        messages.append(assistantMsg)
        isThinking = true

        defer { isThinking = false }

        let result: TurnResult = try await Task.detached(priority: .userInitiated) { [inner] in
            try inner.sendTurn(prompt: text)
        }.value

        // Update the placeholder with the real text
        if let idx = messages.indices.last {
            messages[idx].text = result.text
        }

        return result.text
    }

    /// Stream an assistant reply chunk-by-chunk via an AsyncStream.
    ///
    /// Since the Rust layer is synchronous, the chunks are delivered
    /// all at once when the turn completes. The stream still yields
    /// each event separately so the UI can be updated progressively
    /// without changes once true streaming is wired up.
    public func stream(_ text: String) -> AsyncThrowingStream<String, Error> {
        AsyncThrowingStream { continuation in
            let userMsg = ClawMessage(role: .user, text: text)
            let assistantMsg = ClawMessage(role: .assistant, text: "")

            Task { @MainActor in
                self.messages.append(userMsg)
                self.messages.append(assistantMsg)
                self.isThinking = true
            }

            Task.detached(priority: .userInitiated) { [weak self, inner = self.inner] in
                defer {
                    Task { @MainActor in self?.isThinking = false }
                }

                do {
                    let result = try inner.sendTurn(prompt: text)

                    for event in result.events {
                        if case .textDelta(let chunk) = event {
                            continuation.yield(chunk)
                            Task { @MainActor in
                                if let idx = self?.messages.indices.last {
                                    self?.messages[idx].text += chunk
                                }
                            }
                        }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
        }
    }

    /// Erase the full conversation history.
    public func reset() {
        inner.clearHistory()
        messages.removeAll()
    }
}

// MARK: - Message model

public struct ClawMessage: Identifiable {
    public let id = UUID()
    public let role: Role
    public var text: String

    public enum Role { case user, assistant }

    public init(role: Role, text: String) {
        self.role = role
        self.text = text
    }
}

// MARK: - Errors

public enum ClawError: LocalizedError {
    case apiError(String)

    public var errorDescription: String? {
        switch self {
        case .apiError(let msg): return msg
        }
    }
}
