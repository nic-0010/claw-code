uniffi::setup_scaffolding!();

mod client;
mod tools;

use std::sync::{Arc, Mutex};

use client::IosApiClient;
use runtime::{ConversationRuntime, PermissionMode, PermissionPolicy, Session};
use tools::{ios_tool_definitions, IosToolExecutor};

// ── Public types exposed to Swift ──────────────────────────────────────────

/// Configuration for a Claw iOS session.
#[derive(uniffi::Record, Clone, Debug)]
pub struct ClawIosConfig {
    pub api_key: String,
    pub model: String,
    pub system_prompt: Option<String>,
    pub base_url: Option<String>,
    pub enable_file_tools: bool,
}

/// A single streaming event produced during a conversation turn.
#[derive(uniffi::Enum, Clone, Debug)]
pub enum IosEvent {
    /// Incremental text chunk from the model.
    TextDelta { text: String },
    /// The model requested a tool call.
    ToolUse { id: String, name: String, input: String },
    /// Token usage at end of turn.
    Usage { input_tokens: u64, output_tokens: u64 },
}

/// Result returned from a completed conversation turn.
#[derive(uniffi::Record, Clone, Debug)]
pub struct TurnResult {
    /// All events emitted during this turn, in order.
    pub events: Vec<IosEvent>,
    /// Full assistant response text (concatenation of all TextDelta events).
    pub text: String,
    /// Number of conversation messages in the session after this turn.
    pub message_count: u64,
}

/// Error returned by SDK operations.
#[derive(Debug, thiserror::Error, uniffi::Error)]
pub enum IosError {
    #[error("Configuration error: {msg}")]
    Config { msg: String },
    #[error("API error: {msg}")]
    Api { msg: String },
    #[error("Runtime error: {msg}")]
    Runtime { msg: String },
}

// ── ClawIosSession ──────────────────────────────────────────────────────────

/// A stateful conversation session. History persists across calls to `sendTurn`.
///
/// ```swift
/// let cfg = ClawIosConfig(apiKey: "sk-ant-...", model: "claude-opus-4-6",
///                         systemPrompt: nil, baseUrl: nil, enableFileTools: false)
/// let session = try ClawIosSession(config: cfg)
/// let result  = try session.sendTurn(prompt: "Hello!")
/// print(result.text)
/// ```
#[derive(uniffi::Object)]
pub struct ClawIosSession {
    config: ClawIosConfig,
    session: Mutex<Session>,
}

#[uniffi::export]
impl ClawIosSession {
    /// Create a new empty session with the given configuration.
    #[uniffi::constructor]
    pub fn new(config: ClawIosConfig) -> Result<Arc<Self>, IosError> {
        Ok(Arc::new(Self {
            config,
            session: Mutex::new(Session::new()),
        }))
    }

    /// Run one conversation turn synchronously. Blocks until the full response
    /// (including any tool calls) is complete. Call from a Swift `Task` or
    /// background `DispatchQueue` to avoid blocking the main thread.
    pub fn send_turn(&self, prompt: String) -> Result<TurnResult, IosError> {
        let session_snapshot = self
            .session
            .lock()
            .map_err(|e| IosError::Runtime {
                msg: format!("session lock poisoned: {e}"),
            })?
            .clone();

        let tool_defs = if self.config.enable_file_tools {
            ios_tool_definitions()
        } else {
            Vec::new()
        };

        // Collect events into a shared buffer that the client writes to.
        let event_buf: Arc<Mutex<Vec<IosEvent>>> = Arc::new(Mutex::new(Vec::new()));

        let api_client = IosApiClient::new(
            &self.config.api_key,
            self.config.base_url.as_deref(),
            api::resolve_model_alias(&self.config.model).to_string(),
            tool_defs,
            Arc::clone(&event_buf),
        )
        .map_err(|msg| IosError::Config { msg })?;

        let tool_executor = IosToolExecutor::new();
        let policy = PermissionPolicy::new(PermissionMode::DangerFullAccess);
        let system_prompt = self
            .config
            .system_prompt
            .as_deref()
            .map(|s| vec![s.to_string()])
            .unwrap_or_default();

        let mut runtime = ConversationRuntime::new(
            session_snapshot,
            api_client,
            tool_executor,
            policy,
            system_prompt,
        );

        runtime
            .run_turn(&prompt, None)
            .map_err(|e| IosError::Runtime { msg: e.to_string() })?;

        // Persist updated session.
        if let Ok(mut guard) = self.session.lock() {
            *guard = runtime.session().clone();
        }

        let events = event_buf.lock().map(|g| g.clone()).unwrap_or_default();
        let text = events
            .iter()
            .filter_map(|e| {
                if let IosEvent::TextDelta { text } = e {
                    Some(text.as_str())
                } else {
                    None
                }
            })
            .collect::<String>();

        let message_count = self
            .session
            .lock()
            .map(|s| s.messages.len() as u64)
            .unwrap_or(0);

        Ok(TurnResult {
            events,
            text,
            message_count,
        })
    }

    /// Number of messages currently stored in this session.
    pub fn message_count(&self) -> u64 {
        self.session
            .lock()
            .map(|s| s.messages.len() as u64)
            .unwrap_or(0)
    }

    /// Erase the conversation history and start fresh.
    pub fn clear_history(&self) {
        if let Ok(mut guard) = self.session.lock() {
            *guard = Session::new();
        }
    }
}
