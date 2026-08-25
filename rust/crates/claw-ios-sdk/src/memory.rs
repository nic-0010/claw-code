use serde::{Deserialize, Serialize};

const MAX_ENTRIES: usize = 200;

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct MemoryEntry {
    pub key: String,
    pub value: String,
    pub ts: u64, // unix seconds
}

fn memory_file(base: Option<&str>) -> String {
    format!("{}/claw_memory.json", base.unwrap_or("/tmp"))
}

fn now() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

pub fn load(base: Option<&str>) -> Vec<MemoryEntry> {
    std::fs::read_to_string(memory_file(base))
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

fn persist(base: Option<&str>, entries: &[MemoryEntry]) -> Result<(), String> {
    let json = serde_json::to_string_pretty(entries).map_err(|e| e.to_string())?;
    std::fs::write(memory_file(base), json).map_err(|e| e.to_string())
}

pub fn save(base: Option<&str>, key: &str, value: &str) -> Result<String, String> {
    let mut entries = load(base);
    if let Some(e) = entries.iter_mut().find(|e| e.key == key) {
        e.value = value.to_string();
        e.ts = now();
    } else {
        entries.push(MemoryEntry { key: key.to_string(), value: value.to_string(), ts: now() });
    }
    if entries.len() > MAX_ENTRIES {
        // drop oldest
        entries.sort_by_key(|e| e.ts);
        entries.drain(0..entries.len() - MAX_ENTRIES);
    }
    persist(base, &entries)?;
    Ok(format!("Saved: {key} = {value}"))
}

pub fn search(base: Option<&str>, query: &str) -> String {
    let q = query.to_lowercase();
    let matches: Vec<String> = load(base)
        .into_iter()
        .filter(|e| e.key.to_lowercase().contains(&q) || e.value.to_lowercase().contains(&q))
        .map(|e| format!("{}: {}", e.key, e.value))
        .collect();
    if matches.is_empty() {
        format!("No memories found for '{query}'")
    } else {
        matches.join("\n")
    }
}

pub fn list(base: Option<&str>) -> String {
    let entries = load(base);
    if entries.is_empty() {
        "Memory is empty.".to_string()
    } else {
        let lines: Vec<String> = entries.iter().map(|e| format!("{}: {}", e.key, e.value)).collect();
        format!("{} memories:\n{}", lines.len(), lines.join("\n"))
    }
}

pub fn delete(base: Option<&str>, key: &str) -> Result<String, String> {
    let mut entries = load(base);
    let before = entries.len();
    entries.retain(|e| e.key != key);
    persist(base, &entries)?;
    if entries.len() < before {
        Ok(format!("Deleted: {key}"))
    } else {
        Ok(format!("Key not found: {key}"))
    }
}

/// Build a context block to prepend to the system prompt.
pub fn as_context(base: Option<&str>) -> Option<String> {
    let entries = load(base);
    if entries.is_empty() {
        return None;
    }
    let lines: Vec<String> = entries.iter().map(|e| format!("- {}: {}", e.key, e.value)).collect();
    Some(format!("## Memory from previous sessions\n{}", lines.join("\n")))
}

pub fn tool_definitions() -> Vec<api::ToolDefinition> {
    serde_json::from_value(serde_json::json!([
        {
            "name": "memory_save",
            "description": "Save an important fact to persistent memory so it is available in future conversations. Use for user preferences, project details, key decisions.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "key":   { "type": "string", "description": "Short identifier, e.g. 'user_name', 'project_goal'" },
                    "value": { "type": "string", "description": "The information to remember" }
                },
                "required": ["key", "value"]
            }
        },
        {
            "name": "memory_search",
            "description": "Search persistent memory for facts matching a keyword.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": { "type": "string", "description": "Keyword to search in memory keys and values" }
                },
                "required": ["query"]
            }
        },
        {
            "name": "memory_list",
            "description": "List all facts currently stored in persistent memory.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "memory_delete",
            "description": "Remove a specific fact from persistent memory by key.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "key": { "type": "string", "description": "The key to delete" }
                },
                "required": ["key"]
            }
        }
    ]))
    .unwrap_or_default()
}
