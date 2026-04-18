use runtime::{
    edit_file, glob_search, grep_search, read_file, GrepSearchInput, ToolError, ToolExecutor,
};
use serde::Deserialize;

use crate::memory;

pub struct IosToolExecutor {
    search_api_key: Option<String>,
    firecrawl_api_key: Option<String>,
    memory_path: Option<String>,
}

impl IosToolExecutor {
    pub fn new(
        search_api_key: Option<String>,
        firecrawl_api_key: Option<String>,
        memory_path: Option<String>,
    ) -> Self {
        Self { search_api_key, firecrawl_api_key, memory_path }
    }
}

impl ToolExecutor for IosToolExecutor {
    fn execute(&mut self, tool_name: &str, input: &str) -> Result<String, ToolError> {
        match tool_name {
            // ── File tools ────────────────────────────────────────────────

            "read_file" => {
                #[derive(Deserialize)]
                struct Args { path: String, offset: Option<usize>, limit: Option<usize> }
                let args: Args = serde_json::from_str(input)
                    .map_err(|e| ToolError::new(format!("invalid input: {e}")))?;
                let result = read_file(&args.path, args.offset, args.limit)
                    .map_err(|e| ToolError::new(e.to_string()))?;
                serde_json::to_string(&result).map_err(|e| ToolError::new(e.to_string()))
            }

            "write_file" => {
                #[derive(Deserialize)]
                struct Args { path: String, content: String }
                let args: Args = serde_json::from_str(input)
                    .map_err(|e| ToolError::new(format!("invalid input: {e}")))?;
                let result = runtime::write_file(&args.path, &args.content)
                    .map_err(|e| ToolError::new(e.to_string()))?;
                serde_json::to_string(&result).map_err(|e| ToolError::new(e.to_string()))
            }

            "edit_file" => {
                #[derive(Deserialize)]
                struct Args {
                    path: String, old_string: String, new_string: String,
                    replace_all: Option<bool>,
                }
                let args: Args = serde_json::from_str(input)
                    .map_err(|e| ToolError::new(format!("invalid input: {e}")))?;
                let result = edit_file(
                    &args.path, &args.old_string, &args.new_string,
                    args.replace_all.unwrap_or(false),
                )
                .map_err(|e| ToolError::new(e.to_string()))?;
                serde_json::to_string(&result).map_err(|e| ToolError::new(e.to_string()))
            }

            "glob_search" => {
                #[derive(Deserialize)]
                struct Args { pattern: String, path: Option<String> }
                let args: Args = serde_json::from_str(input)
                    .map_err(|e| ToolError::new(format!("invalid input: {e}")))?;
                let result = glob_search(&args.pattern, args.path.as_deref())
                    .map_err(|e| ToolError::new(e.to_string()))?;
                serde_json::to_string(&result).map_err(|e| ToolError::new(e.to_string()))
            }

            "grep_search" => {
                let args: GrepSearchInput = serde_json::from_str(input)
                    .map_err(|e| ToolError::new(format!("invalid input: {e}")))?;
                let result = grep_search(&args).map_err(|e| ToolError::new(e.to_string()))?;
                serde_json::to_string(&result).map_err(|e| ToolError::new(e.to_string()))
            }

            // ── Web tools ─────────────────────────────────────────────────

            "web_search" => {
                #[derive(Deserialize)]
                struct Args { query: String, num_results: Option<u32> }
                let args: Args = serde_json::from_str(input)
                    .map_err(|e| ToolError::new(format!("invalid input: {e}")))?;
                let api_key = self.search_api_key.as_deref().unwrap_or("");
                if api_key.is_empty() {
                    return Err(ToolError::new("search_api_key required (get one at tavily.com)"));
                }
                web_search(&args.query, args.num_results.unwrap_or(5), api_key)
            }

            "fetch_url" => {
                #[derive(Deserialize)]
                struct Args { url: String, timeout_secs: Option<u64> }
                let args: Args = serde_json::from_str(input)
                    .map_err(|e| ToolError::new(format!("invalid input: {e}")))?;
                fetch_url(&args.url, args.timeout_secs.unwrap_or(30),
                    self.firecrawl_api_key.as_deref())
            }

            // ── Memory tools ──────────────────────────────────────────────

            "memory_save" => {
                #[derive(Deserialize)]
                struct Args { key: String, value: String }
                let args: Args = serde_json::from_str(input)
                    .map_err(|e| ToolError::new(format!("invalid input: {e}")))?;
                memory::save(self.memory_path.as_deref(), &args.key, &args.value)
                    .map_err(ToolError::new)
            }

            "memory_search" => {
                #[derive(Deserialize)]
                struct Args { query: String }
                let args: Args = serde_json::from_str(input)
                    .map_err(|e| ToolError::new(format!("invalid input: {e}")))?;
                Ok(memory::search(self.memory_path.as_deref(), &args.query))
            }

            "memory_list" => Ok(memory::list(self.memory_path.as_deref())),

            "memory_delete" => {
                #[derive(Deserialize)]
                struct Args { key: String }
                let args: Args = serde_json::from_str(input)
                    .map_err(|e| ToolError::new(format!("invalid input: {e}")))?;
                memory::delete(self.memory_path.as_deref(), &args.key)
                    .map_err(ToolError::new)
            }

            other => Err(ToolError::new(format!("tool '{other}' is not available on iOS"))),
        }
    }
}

// ── Async helper ──────────────────────────────────────────────────────────────

fn run_async<F>(fut: F) -> Result<String, ToolError>
where
    F: std::future::Future<Output = Result<String, String>>,
{
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|e| ToolError::new(e.to_string()))?
        .block_on(fut)
        .map_err(ToolError::new)
}

// ── Web implementations ───────────────────────────────────────────────────────

fn web_search(query: &str, num_results: u32, api_key: &str) -> Result<String, ToolError> {
    let query = query.to_string();
    let api_key = api_key.to_string();
    run_async(async move {
        let client = reqwest::Client::new();
        let body = serde_json::json!({
            "api_key": api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": num_results,
            "include_answer": true,
        });

        let resp = client
            .post("https://api.tavily.com/search")
            .json(&body)
            .send()
            .await
            .map_err(|e| e.to_string())?;

        if !resp.status().is_success() {
            let status = resp.status();
            let text = resp.text().await.unwrap_or_default();
            return Err(format!("Tavily error {status}: {text}"));
        }

        let json: serde_json::Value = resp.json().await.map_err(|e| e.to_string())?;
        let mut out = String::new();

        if let Some(answer) = json["answer"].as_str().filter(|s| !s.is_empty()) {
            out.push_str(&format!("Answer: {answer}\n\n"));
        }
        if let Some(results) = json["results"].as_array() {
            for (i, r) in results.iter().enumerate() {
                let title = r["title"].as_str().unwrap_or("");
                let url = r["url"].as_str().unwrap_or("");
                let content = r["content"].as_str().unwrap_or("");
                out.push_str(&format!("[{}] {}\n{}\n{}\n\n", i + 1, title, url, content));
            }
        }
        Ok(out)
    })
}

fn fetch_url(url: &str, timeout_secs: u64, firecrawl_key: Option<&str>) -> Result<String, ToolError> {
    if let Some(key) = firecrawl_key {
        fetch_via_firecrawl(url, timeout_secs, key)
    } else {
        fetch_via_jina(url, timeout_secs)
    }
}

fn fetch_via_jina(url: &str, timeout_secs: u64) -> Result<String, ToolError> {
    let jina_url = format!("https://r.jina.ai/{url}");
    run_async(async move {
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(timeout_secs))
            .build()
            .map_err(|e| e.to_string())?;

        let resp = client
            .get(&jina_url)
            .header("Accept", "text/plain")
            .header("X-Return-Format", "text")
            .send()
            .await
            .map_err(|e| e.to_string())?;

        if !resp.status().is_success() {
            return Err(format!("fetch failed: HTTP {}", resp.status()));
        }

        let text = resp.text().await.map_err(|e| e.to_string())?;
        Ok(truncate(text, 50_000))
    })
}

fn fetch_via_firecrawl(url: &str, timeout_secs: u64, api_key: &str) -> Result<String, ToolError> {
    let url = url.to_string();
    let api_key = api_key.to_string();
    run_async(async move {
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(timeout_secs))
            .build()
            .map_err(|e| e.to_string())?;

        let body = serde_json::json!({ "url": url, "formats": ["markdown"] });
        let resp = client
            .post("https://api.firecrawl.dev/v1/scrape")
            .header("Authorization", format!("Bearer {api_key}"))
            .json(&body)
            .send()
            .await
            .map_err(|e| e.to_string())?;

        if !resp.status().is_success() {
            return Err(format!("Firecrawl error: HTTP {}", resp.status()));
        }

        let json: serde_json::Value = resp.json().await.map_err(|e| e.to_string())?;
        let markdown = json["data"]["markdown"].as_str().unwrap_or("").to_string();
        Ok(truncate(markdown, 50_000))
    })
}

fn truncate(s: String, max: usize) -> String {
    if s.len() > max {
        format!("{}\n\n[Content truncated at {max} characters]", &s[..max])
    } else {
        s
    }
}

// ── Tool definitions ──────────────────────────────────────────────────────────

pub fn ios_file_tool_definitions() -> Vec<api::ToolDefinition> {
    serde_json::from_value(serde_json::json!([
        {
            "name": "read_file",
            "description": "Read the contents of a file. Returns text with line numbers.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path":   { "type": "string",  "description": "Absolute path" },
                    "offset": { "type": "integer", "description": "Start line (1-based)" },
                    "limit":  { "type": "integer", "description": "Max lines to read" }
                },
                "required": ["path"]
            }
        },
        {
            "name": "write_file",
            "description": "Write content to a file, creating it if needed.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path":    { "type": "string", "description": "Absolute path" },
                    "content": { "type": "string", "description": "Full content to write" }
                },
                "required": ["path", "content"]
            }
        },
        {
            "name": "edit_file",
            "description": "Replace an exact string in a file.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path":        { "type": "string",  "description": "Absolute path" },
                    "old_string":  { "type": "string",  "description": "Exact text to replace" },
                    "new_string":  { "type": "string",  "description": "Replacement text" },
                    "replace_all": { "type": "boolean", "description": "Replace all occurrences" }
                },
                "required": ["path", "old_string", "new_string"]
            }
        },
        {
            "name": "glob_search",
            "description": "Find files matching a glob pattern.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": { "type": "string", "description": "Glob pattern, e.g. **/*.swift" },
                    "path":    { "type": "string", "description": "Root directory" }
                },
                "required": ["pattern"]
            }
        },
        {
            "name": "grep_search",
            "description": "Search file contents with a regex pattern.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern":     { "type": "string", "description": "Regex pattern" },
                    "path":        { "type": "string", "description": "Directory to search" },
                    "glob":        { "type": "string", "description": "File filter, e.g. *.swift" },
                    "output_mode": {
                        "type": "string",
                        "enum": ["content", "files_with_matches", "count"]
                    }
                },
                "required": ["pattern"]
            }
        }
    ]))
    .unwrap_or_default()
}

pub fn web_tool_definitions() -> Vec<api::ToolDefinition> {
    serde_json::from_value(serde_json::json!([
        {
            "name": "web_search",
            "description": "Search the web for current information using Tavily. Returns a synthesized answer plus source URLs and content snippets.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query":       { "type": "string",  "description": "The search query" },
                    "num_results": { "type": "integer", "description": "Results to return (1-10, default 5)" }
                },
                "required": ["query"]
            }
        },
        {
            "name": "fetch_url",
            "description": "Fetch and extract the full text from any URL, including JavaScript-rendered pages. Use after web_search to read complete articles or documentation.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "url":          { "type": "string",  "description": "The URL to fetch" },
                    "timeout_secs": { "type": "integer", "description": "Timeout in seconds (default 30)" }
                },
                "required": ["url"]
            }
        }
    ]))
    .unwrap_or_default()
}
