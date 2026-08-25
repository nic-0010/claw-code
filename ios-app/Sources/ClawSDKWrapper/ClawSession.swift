import ClawIosSDK
import Foundation

// MARK: - Public async/await wrapper

/// A conversation session with Claude, designed for use in SwiftUI apps.
///
/// Usage:
/// ```swift
/// let session = try ClawSession(
///     apiKey: "sk-ant-...",
///     enableWebTools: true,
///     searchApiKey: "tvly-...",
///     enableMemory: true,
///     memoryPath: documentsPath,
///     agentMode: .research
/// )
/// let text = try await session.send("Analyze the AI agent market in 2026")
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
        enableRagMode: Bool = false,
        enableWebTools: Bool = false,
        enableMemory: Bool = false,
        searchApiKey: String? = nil,
        firecrawlApiKey: String? = nil,
        memoryPath: String? = nil,
        agentMode: AgentMode = .general,
        enableFinancialTools: Bool = false,
        financialServerUrl: String? = nil
    ) throws {
        let config = ClawIosConfig(
            apiKey: apiKey,
            model: model,
            systemPrompt: systemPrompt,
            baseUrl: nil,
            enableFileTools: enableFileTools,
            enableRagMode: enableRagMode,
            enableWebTools: enableWebTools,
            enableMemory: enableMemory,
            searchApiKey: searchApiKey,
            firecrawlApiKey: firecrawlApiKey,
            memoryPath: memoryPath,
            agentMode: agentMode,
            enableFinancialTools: enableFinancialTools,
            financialServerUrl: financialServerUrl
        )
        self.inner = try ClawIosSession(config: config)
    }

    /// Switch the agent specialization mode without clearing conversation history.
    public func setMode(_ mode: AgentMode) {
        inner.setAgentMode(mode: mode)
    }

    /// Send a user message and return the full assistant reply.
    @discardableResult
    public func send(_ text: String) async throws -> String {
        let userMsg = ClawMessage(role: .user, text: text)
        messages.append(userMsg)
        let assistantMsg = ClawMessage(role: .assistant, text: "")
        messages.append(assistantMsg)
        isThinking = true
        defer { isThinking = false }

        let result: TurnResult = try await Task.detached(priority: .userInitiated) { [inner] in
            try inner.sendTurn(prompt: text)
        }.value

        if let idx = messages.indices.last {
            messages[idx].text = result.text
        }
        return result.text
    }

    /// Stream an assistant reply chunk-by-chunk via an AsyncThrowingStream.
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
                defer { Task { @MainActor in self?.isThinking = false } }
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

// MARK: - Convenience factory

public extension ClawSession {
    /// Create a fully autonomous session with web search, memory, and a chosen mode.
    /// Pass the app's Documents directory path for persistent memory storage.
    static func autonomous(
        apiKey: String,
        searchApiKey: String,
        documentsPath: String,
        firecrawlApiKey: String? = nil,
        mode: AgentMode = .general
    ) throws -> ClawSession {
        try ClawSession(
            apiKey: apiKey,
            enableWebTools: true,
            enableMemory: true,
            searchApiKey: searchApiKey,
            firecrawlApiKey: firecrawlApiKey,
            memoryPath: documentsPath,
            agentMode: mode
        )
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
