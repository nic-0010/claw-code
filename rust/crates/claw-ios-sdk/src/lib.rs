uniffi::setup_scaffolding!();

mod client;
mod memory;
mod tools;

use std::sync::{Arc, Mutex};

use client::IosApiClient;
use runtime::{ConversationRuntime, PermissionMode, PermissionPolicy, Session};
use tools::{ios_file_tool_definitions, web_tool_definitions, IosToolExecutor};

// ── System prompts ────────────────────────────────────────────────────────────

const RAG_SYSTEM_PROMPT: &str = "\
You have access to read_file, glob_search, and grep_search tools.\n\
When answering questions about documents or files:\n\
1. First use glob_search to find relevant files\n\
2. Use grep_search to locate specific sections\n\
3. Read only the relevant chunks with read_file (use offset and limit)\n\
4. Answer based only on what the documents say\n\
5. If unsure, say \"I don't know\" rather than guessing";

const WEB_TOOLS_SYSTEM_PROMPT: &str = "\
You have access to web_search and fetch_url tools for real-time information retrieval.\n\
When answering questions that require current data, news, prices, or research:\n\
1. Use web_search to find relevant sources and get a synthesized answer\n\
2. Use fetch_url to read full content from specific pages when needed\n\
3. Cross-reference multiple sources for accuracy\n\
4. Always cite sources with their URLs in your response\n\
5. For complex tasks like business plans or financial analysis, search for recent data first";

const MEMORY_SYSTEM_PROMPT: &str = "\
You have access to memory_save, memory_search, memory_list, and memory_delete tools.\n\
Use persistent memory to:\n\
- Save important user preferences, project details, and key facts with memory_save\n\
- Check existing memories before asking the user for information they may have shared before\n\
- Proactively save new information that will be useful in future sessions";

const RESEARCH_MODE_PROMPT: &str = "\
You are an expert research assistant.\n\
For any research task:\n\
1. Search multiple angles with web_search before forming conclusions\n\
2. Use fetch_url to read primary sources in full\n\
3. Cross-reference and flag contradictions between sources\n\
4. Structure findings with: Summary → Key Facts → Sources → Open Questions\n\
5. Always cite URLs";

const WRITING_MODE_PROMPT: &str = "\
You are an expert writer and document specialist.\n\
When creating documents:\n\
1. Search for current data and market figures before writing\n\
2. Structure content with clear headings and logical flow\n\
3. For business plans: Executive Summary → Market Analysis → Value Proposition → Revenue Model → Go-to-Market → Financial Projections\n\
4. For prospectuses and reports: use formal, data-backed language\n\
5. Produce complete, publication-ready documents — never truncate";

const ANALYSIS_MODE_PROMPT: &str = "\
You are a data analyst and financial expert.\n\
When analyzing information:\n\
1. Search for benchmark data and comparable cases\n\
2. Show calculations step by step\n\
3. Present data in structured tables where helpful\n\
4. Quantify assumptions and uncertainty explicitly\n\
5. Conclude with ranked, actionable recommendations";

// ── Public types exposed to Swift ─────────────────────────────────────────────

/// Agent specialization mode — changes the system prompt for each session.
#[derive(uniffi::Enum, Clone, Debug)]
pub enum AgentMode {
    /// Default balanced assistant.
    General,
    /// Optimized for multi-source web research with citations.
    Research,
    /// Optimized for producing complete documents and business plans.
    Writing,
    /// Optimized for data analysis, calculations, and financial reasoning.
    Analysis,
}

/// Configuration for a Claw iOS session.
#[derive(uniffi::Record, Clone, Debug)]
pub struct ClawIosConfig {
    pub api_key: String,
    pub model: String,
    pub system_prompt: Option<String>,
    pub base_url: Option<String>,
    /// Enable file tools: read_file, write_file, edit_file, glob_search, grep_search.
    pub enable_file_tools: bool,
    /// Enable RAG mode: activates file tools + a retrieval-oriented system prompt.
    pub enable_rag_mode: bool,
    /// Enable web tools: web_search (Tavily) + fetch_url (Jina or Firecrawl).
    pub enable_web_tools: bool,
    /// Enable persistent memory tools: memory_save/search/list/delete.
    pub enable_memory: bool,
    /// Tavily API key (required when enable_web_tools is true).
    pub search_api_key: Option<String>,
    /// Firecrawl API key — when set, fetch_url uses Firecrawl instead of Jina.
    /// Firecrawl handles JS-rendered pages better. Get one at firecrawl.dev.
    pub firecrawl_api_key: Option<String>,
    /// Path where claw_memory.json is stored (use the app's Documents directory).
    pub memory_path: Option<String>,
    /// Agent mode — sets a specialized system prompt.
    pub agent_mode: AgentMode,
}

/// A single streaming event produced during a conversation turn.
#[derive(uniffi::Enum, Clone, Debug)]
pub enum IosEvent {
    TextDelta { text: String },
    ToolUse { id: String, name: String, input: String },
    Usage { input_tokens: u64, output_tokens: u64 },
}

/// Result returned from a completed conversation turn.
#[derive(uniffi::Record, Clone, Debug)]
pub struct TurnResult {
    pub events: Vec<IosEvent>,
    pub text: String,
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

// ── ClawIosSession ────────────────────────────────────────────────────────────

/// A stateful conversation session. History persists across calls to `send_turn`.
#[derive(uniffi::Object)]
pub struct ClawIosSession {
    config: ClawIosConfig,
    agent_mode: Mutex<AgentMode>,
    session: Mutex<Session>,
}

#[uniffi::export]
impl ClawIosSession {
    #[uniffi::constructor]
    pub fn new(config: ClawIosConfig) -> Result<Arc<Self>, IosError> {
        let initial_mode = config.agent_mode.clone();
        Ok(Arc::new(Self {
            config,
            agent_mode: Mutex::new(initial_mode),
            session: Mutex::new(Session::new()),
        }))
    }

    /// Switch the agent specialization mode without clearing history.
    pub fn set_agent_mode(&self, mode: AgentMode) {
        if let Ok(mut guard) = self.agent_mode.lock() {
            *guard = mode;
        }
    }

    /// Run one conversation turn synchronously. Call from a Swift Task to avoid
    /// blocking the main thread.
    pub fn send_turn(&self, prompt: String) -> Result<TurnResult, IosError> {
        let session_snapshot = self
            .session
            .lock()
            .map_err(|e| IosError::Runtime { msg: format!("lock poisoned: {e}") })?
            .clone();

        // Assemble tool definitions based on config.
        let mut tool_defs = Vec::new();
        if self.config.enable_file_tools || self.config.enable_rag_mode {
            tool_defs.extend(ios_file_tool_definitions());
        }
        if self.config.enable_web_tools {
            tool_defs.extend(web_tool_definitions());
        }
        if self.config.enable_memory {
            tool_defs.extend(memory::tool_definitions());
        }

        let event_buf: Arc<Mutex<Vec<IosEvent>>> = Arc::new(Mutex::new(Vec::new()));

        let api_client = IosApiClient::new(
            &self.config.api_key,
            self.config.base_url.as_deref(),
            api::resolve_model_alias(&self.config.model).to_string(),
            tool_defs,
            Arc::clone(&event_buf),
        )
        .map_err(|msg| IosError::Config { msg })?;

        let tool_executor = IosToolExecutor::new(
            self.config.search_api_key.clone(),
            self.config.firecrawl_api_key.clone(),
            self.config.memory_path.clone(),
        );

        let policy = PermissionPolicy::new(PermissionMode::DangerFullAccess);

        // Build system prompt stack.
        let mut system_prompt: Vec<String> = self
            .config
            .system_prompt
            .as_deref()
            .map(|s| vec![s.to_string()])
            .unwrap_or_default();

        // Inject persistent memories before everything else.
        if self.config.enable_memory {
            if let Some(ctx) = memory::as_context(self.config.memory_path.as_deref()) {
                system_prompt.insert(0, ctx);
            }
        }

        // Capability prompts.
        if self.config.enable_rag_mode {
            system_prompt.push(RAG_SYSTEM_PROMPT.to_string());
        }
        if self.config.enable_web_tools {
            system_prompt.push(WEB_TOOLS_SYSTEM_PROMPT.to_string());
        }
        if self.config.enable_memory {
            system_prompt.push(MEMORY_SYSTEM_PROMPT.to_string());
        }

        // Agent mode specialization.
        let mode = self.agent_mode.lock().map(|g| g.clone()).unwrap_or(AgentMode::General);
        match mode {
            AgentMode::Research => system_prompt.push(RESEARCH_MODE_PROMPT.to_string()),
            AgentMode::Writing  => system_prompt.push(WRITING_MODE_PROMPT.to_string()),
            AgentMode::Analysis => system_prompt.push(ANALYSIS_MODE_PROMPT.to_string()),
            AgentMode::General  => {}
        }

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

        if let Ok(mut guard) = self.session.lock() {
            *guard = runtime.session().clone();
        }

        let events = event_buf.lock().map(|g| g.clone()).unwrap_or_default();
        let text = events
            .iter()
            .filter_map(|e| if let IosEvent::TextDelta { text } = e { Some(text.as_str()) } else { None })
            .collect::<String>();

        let message_count = self.session.lock().map(|s| s.messages.len() as u64).unwrap_or(0);

        Ok(TurnResult { events, text, message_count })
    }

    pub fn message_count(&self) -> u64 {
        self.session.lock().map(|s| s.messages.len() as u64).unwrap_or(0)
    }

    pub fn clear_history(&self) {
        if let Ok(mut guard) = self.session.lock() {
            *guard = Session::new();
        }
    }
}
