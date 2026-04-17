use runtime::{
    edit_file, glob_search, grep_search, read_file, GrepSearchInput, ToolError, ToolExecutor,
};
use serde::Deserialize;

pub struct IosToolExecutor;

impl IosToolExecutor {
    pub fn new() -> Self {
        Self
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
                serde_json::to_string(&result)
                    .map_err(|e| ToolError::new(e.to_string()))
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
                serde_json::to_string(&result)
                    .map_err(|e| ToolError::new(e.to_string()))
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
                serde_json::to_string(&result)
                    .map_err(|e| ToolError::new(e.to_string()))
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
                serde_json::to_string(&result)
                    .map_err(|e| ToolError::new(e.to_string()))
            }

            "grep_search" => {
                let args: GrepSearchInput = serde_json::from_str(input)
                    .map_err(|e| ToolError::new(format!("invalid input: {e}")))?;
                let result = grep_search(&args)
                    .map_err(|e| ToolError::new(e.to_string()))?;
                serde_json::to_string(&result)
                    .map_err(|e| ToolError::new(e.to_string()))
            }

            other => Err(ToolError::new(format!(
                "tool '{other}' is not available on iOS"
            ))),
        }
    }
}

pub fn ios_tool_definitions() -> Vec<api::ToolDefinition> {
    serde_json::from_value(serde_json::json!([
        {
            "name": "read_file",
            "description": "Read the contents of a file at a given path. Returns text content with line numbers.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": { "type": "string", "description": "Absolute path to the file" },
                    "offset": { "type": "integer", "description": "Line number to start reading from (1-based)" },
                    "limit": { "type": "integer", "description": "Maximum number of lines to read" }
                },
                "required": ["path"]
            }
        },
        {
            "name": "write_file",
            "description": "Write content to a file, creating it if it does not exist.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": { "type": "string", "description": "Absolute path to the file" },
                    "content": { "type": "string", "description": "Full content to write" }
                },
                "required": ["path", "content"]
            }
        },
        {
            "name": "edit_file",
            "description": "Replace an exact string in a file with new content.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": { "type": "string", "description": "Absolute path to the file" },
                    "old_string": { "type": "string", "description": "Exact text to find and replace" },
                    "new_string": { "type": "string", "description": "Replacement text" },
                    "replace_all": { "type": "boolean", "description": "Replace all occurrences (default false)" }
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
                    "path": { "type": "string", "description": "Root directory to search in" }
                },
                "required": ["pattern"]
            }
        },
        {
            "name": "grep_search",
            "description": "Search file contents for a regex pattern.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": { "type": "string", "description": "Regex pattern to search for" },
                    "path": { "type": "string", "description": "Directory to search in" },
                    "glob": { "type": "string", "description": "Glob filter for file types, e.g. *.swift" },
                    "output_mode": {
                        "type": "string",
                        "enum": ["content", "files_with_matches", "count"],
                        "description": "How to format results"
                    }
                },
                "required": ["pattern"]
            }
        }
    ]))
    .unwrap_or_default()
}
