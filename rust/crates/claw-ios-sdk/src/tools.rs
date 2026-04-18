use runtime::{
    edit_file, glob_search, grep_search, read_file, GrepSearchInput, ToolError, ToolExecutor,
};
use serde::Deserialize;

pub struct IosToolExecutor {
    search_api_key: Option<String>,
}

impl IosToolExecutor {
    pub fn new(search_api_key: Option<String>) -> Self {
        Self { search_api_key }
    }
}

impl ToolExecutor for IosToolExecutor {
    fn execute(&mut self, tool_name: &str, input: &str) -> Result<String, ToolError> {
        match tool_name {
            "read_file" => {
                #[derive(Deserialize)]
                struct Args {
                    path: String,
                    offset: Option<usize>,
                    limit: Option<usize>,
                }
                let args: Args = serde_json::from_str(input)
                    .map_err(|e| ToolError::new(format!("invalid input: {e}")))?;
                let result = read_file(&args.path, args.offset, args.limit)
                    .map_err(|e| ToolError::new(e.to_string()))?;
                serde_json::to_string(&result).map_err(|e| ToolError::new(e.to_string()))
            }

            "write_file" => {
                #[derive(Deserialize)]
                struct Args {
                    path: String,
                    content: String,
                }
                let args: Args = serde_json::from_str(input)
                    .map_err(|e| ToolError::new(format!("invalid input: {e}")))?;
                let result = runtime::write_file(&args.path, &args.content)
                    .map_err(|e| ToolError::new(e.to_string()))?;
                serde_json::to_string(&result).map_err(|e| ToolError::new(e.to_string()))
            }

            "edit_file" => {
                #[derive(Deserialize)]
                struct Args {
                    path: String,
                    old_string: String,
                    new_string: String,
                    replace_all: Option<bool>,
                }
                let args: Args = serde_json::from_str(input)
                    .map_err(|e| ToolError::new(format!("invalid input: {e}")))?;
                let result = edit_file(
                    &args.path,
                    &args.old_string,
                    &args.new_string,
                    args.replace_all.unwrap_or(false),
                )
                .map_err(|e| ToolError::new(e.to_string()))?;
                serde_json::to_string(&result).map_err(|e| ToolError::new(e.to_string()))
            }

            "glob_search" => {
                #[derive(Deserialize)]
                struct Args {
                    pattern: String,
                    path: Option<String>,
                }
                let args: Args = serde_json::from_str(input)
                    .map_err(|e| ToolError::new(format!("invalid input: {e}")))?;
                let result = glob_search(&args.pattern, args.path.as_deref())
                    .map_err(|e| ToolError::new(e.to_string()))?;
                serde_json::to_string(&result).map_err(|e| ToolError::new(e.to_string()))
            }

            "grep_search" => {
                let args: GrepSearchInput = serde_json::from_str(input)
                    .map_err(|e| ToolError::new(format!("invalid input: {e}")))?;
                let result =
                    grep_search(&args).map_err(|e| ToolError::new(e.to_string()))?;
                serde_json::to_string(&result).map_err(|e| ToolError::new(e.to_string()))
            }

            "web_search" => {
                #[derive(Deserialize)]
                struct Args {
                    query: String,
                    num_results: Option<u32>,
                }
                let args: Args = serde_json::from_str(input)
                    .map_err(|e| ToolError::new(format!("invalid input: {e}")))?;
                let api_key = self.search_api_key.as_deref().unwrap_or("");
                if api_key.is_empty() {
                    return Err(ToolError::new(
                        "search_api_key is required for web_search (get one at tavily.com)",
                    ));
                }
                web_search(&args.query, args.num_results.unwrap_or(5), api_key)
            }

            "fetch_url" => {
                #[derive(Deserialize)]
                struct Args {
                    url: String,
                    timeout_secs: Option<u64>,
                }
                let args: Args = serde_json::from_str(input)
                    .map_err(|e| ToolError::new(format!("invalid input: {e}")))?;
                fetch_url(&args.url, args.timeout_secs.unwrap_or(30))
            }

            other => Err(ToolError::new(format!(
                "tool '{other}' is not available on iOS"
            ))),
        }
    }
}

// ── Async helper ─────────────────────────────────────────────────────────────

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

// ── Web tools ─────────────────────────────────────────────────────────────────

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
            return Err(format!("Tavily API error {status}: {text}"));
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

fn fetch_url(url: &str, timeout_secs: u64) -> Result<String, ToolError> {
    // Jina Reader converts any URL (including JS-rendered pages) to clean text.
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
        if text.len() > 50_000 {
            Ok(format!(
                "{}\n\n[Content truncated at 50,000 characters]",
                &text[..50_000]
            ))
        } else {
            Ok(text)
        }
    })
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
                    "path":   { "type": "string",  "description": "Absolute path to the file" },
                    "offset": { "type": "integer", "description": "Line to start from (1-based)" },
                    "limit":  { "type": "integer", "description": "Maximum lines to read" }
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

