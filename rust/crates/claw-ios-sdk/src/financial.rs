/// HTTP client for the financial tool server (tool_server.py).
/// Each function calls a POST endpoint and returns the plain-text result.

use runtime::ToolError;

pub fn call_tool(server_url: &str, tool: &str, body: serde_json::Value) -> Result<String, ToolError> {
    let url = format!("{}/tool/{}", server_url.trim_end_matches('/'), tool);

    let run = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|e| ToolError::new(e.to_string()))?;

    run.block_on(async move {
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(60))
            .build()
            .map_err(|e| ToolError::new(e.to_string()))?;

        let resp = client
            .post(&url)
            .json(&body)
            .send()
            .await
            .map_err(|e| ToolError::new(format!("financial server unreachable: {e}")))?;

        if !resp.status().is_success() {
            let status = resp.status();
            let text = resp.text().await.unwrap_or_default();
            return Err(ToolError::new(format!("financial server error {status}: {text}")));
        }

        let json: serde_json::Value = resp
            .json()
            .await
            .map_err(|e| ToolError::new(e.to_string()))?;

        // Server ritorna {"result": "..."} oppure {"error": "..."}
        if let Some(err) = json["error"].as_str() {
            return Err(ToolError::new(err.to_string()));
        }
        Ok(json["result"].as_str().unwrap_or("").to_string())
    })
}

pub fn tool_definitions() -> Vec<api::ToolDefinition> {
    serde_json::from_value(serde_json::json!([
        {
            "name": "get_stock_price",
            "description": "Get the current price and key metrics for a stock or ETF ticker (e.g. AAPL, VWCE.DE).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": { "type": "string", "description": "Stock or ETF ticker symbol" }
                },
                "required": ["ticker"]
            }
        },
        {
            "name": "get_etf_info",
            "description": "Get detailed information about an ETF: TER, asset class, geographic exposure, AUM.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": { "type": "string", "description": "ETF ticker symbol, e.g. VWCE.DE" }
                },
                "required": ["ticker"]
            }
        },
        {
            "name": "confronta_portafoglio",
            "description": "Compare multiple ETFs or stocks side by side: performance, fees, exposure, risk metrics.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "tickers": {
                        "type": "array",
                        "items": { "type": "string" },
                        "description": "List of ticker symbols to compare, e.g. [\"VWCE.DE\", \"XDWD.DE\", \"ISPA.MI\"]"
                    }
                },
                "required": ["tickers"]
            }
        }
    ]))
    .unwrap_or_default()
}
