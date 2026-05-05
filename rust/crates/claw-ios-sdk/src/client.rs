use std::sync::{Arc, Mutex};

use api::{
    AnthropicClient, ContentBlockDelta, InputContentBlock, InputMessage, MessageRequest,
    OutputContentBlock, StreamEvent, ToolChoice, ToolDefinition, ToolResultContentBlock,
    max_tokens_for_model,
};
use runtime::{
    ApiClient, ApiRequest, AssistantEvent, ContentBlock, ConversationMessage, MessageRole,
    RuntimeError,
};

use crate::IosEvent;

pub struct IosApiClient {
    rt: tokio::runtime::Runtime,
    client: AnthropicClient,
    model: String,
    tool_defs: Vec<ToolDefinition>,
    /// Shared buffer where streaming events are written as they arrive.
    event_buf: Arc<Mutex<Vec<IosEvent>>>,
}

impl IosApiClient {
    pub fn new(
        api_key: &str,
        base_url: Option<&str>,
        model: String,
        tool_defs: Vec<ToolDefinition>,
        event_buf: Arc<Mutex<Vec<IosEvent>>>,
    ) -> Result<Self, String> {
        let rt = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(|e| e.to_string())?;

        let mut client = AnthropicClient::new(api_key);
        if let Some(url) = base_url {
            client = client.with_base_url(url);
        }

        Ok(Self {
            rt,
            client,
            model,
            tool_defs,
            event_buf,
        })
    }
}

impl ApiClient for IosApiClient {
    fn stream(&mut self, request: ApiRequest) -> Result<Vec<AssistantEvent>, RuntimeError> {
        let message_request = MessageRequest {
            model: self.model.clone(),
            max_tokens: max_tokens_for_model(&self.model),
            messages: convert_messages(&request.messages),
            system: (!request.system_prompt.is_empty())
                .then(|| request.system_prompt.join("\n\n")),
            tools: (!self.tool_defs.is_empty()).then(|| self.tool_defs.clone()),
            tool_choice: (!self.tool_defs.is_empty()).then_some(ToolChoice::Auto),
            stream: true,
            ..Default::default()
        };

        let event_buf = Arc::clone(&self.event_buf);
        let client = self.client.clone();

        self.rt.block_on(async move {
            let mut stream = client
                .stream_message(&message_request)
                .await
                .map_err(|e| RuntimeError::new(e.to_string()))?;

            let mut events: Vec<AssistantEvent> = Vec::new();
            let mut pending_tool: Option<(String, String, String)> = None;
            let mut saw_stop = false;

            loop {
                let next = stream
                    .next_event()
                    .await
                    .map_err(|e| RuntimeError::new(e.to_string()))?;

                let Some(event) = next else { break };

                match event {
                    StreamEvent::ContentBlockStart(start) => {
                        if let OutputContentBlock::ToolUse { id, name, .. } = start.content_block {
                            pending_tool = Some((id, name, String::new()));
                        }
                    }

                    StreamEvent::ContentBlockDelta(delta) => match delta.delta {
                        ContentBlockDelta::TextDelta { text } => {
                            if !text.is_empty() {
                                if let Ok(mut buf) = event_buf.lock() {
                                    buf.push(IosEvent::TextDelta { text: text.clone() });
                                }
                                events.push(AssistantEvent::TextDelta(text));
                            }
                        }
                        ContentBlockDelta::InputJsonDelta { partial_json } => {
                            if let Some((_, _, input)) = &mut pending_tool {
                                input.push_str(&partial_json);
                            }
                        }
                        _ => {}
                    },

                    StreamEvent::ContentBlockStop(_) => {
                        if let Some((id, name, input)) = pending_tool.take() {
                            if let Ok(mut buf) = event_buf.lock() {
                                buf.push(IosEvent::ToolUse {
                                    id: id.clone(),
                                    name: name.clone(),
                                    input: input.clone(),
                                });
                            }
                            events.push(AssistantEvent::ToolUse { id, name, input });
                        }
                    }

                    StreamEvent::MessageDelta(delta) => {
                        let usage = delta.usage.token_usage();
                        if let Ok(mut buf) = event_buf.lock() {
                            buf.push(IosEvent::Usage {
                                input_tokens: u64::from(usage.input_tokens),
                                output_tokens: u64::from(usage.output_tokens),
                            });
                        }
                        events.push(AssistantEvent::Usage(usage));
                    }

                    StreamEvent::MessageStop(_) => {
                        saw_stop = true;
                        events.push(AssistantEvent::MessageStop);
                    }

                    _ => {}
                }
            }

            if !saw_stop
                && events.iter().any(|e| {
                    matches!(e, AssistantEvent::TextDelta(t) if !t.is_empty())
                        || matches!(e, AssistantEvent::ToolUse { .. })
                })
            {
                events.push(AssistantEvent::MessageStop);
            }

            Ok(events)
        })
    }
}

fn convert_messages(messages: &[ConversationMessage]) -> Vec<InputMessage> {
    messages
        .iter()
        .filter_map(|message| {
            let role = match message.role {
                MessageRole::System | MessageRole::User | MessageRole::Tool => "user",
                MessageRole::Assistant => "assistant",
            };
            let content = message
                .blocks
                .iter()
                .map(|block| match block {
                    ContentBlock::Text { text } => InputContentBlock::Text { text: text.clone() },
                    ContentBlock::ToolUse { id, name, input } => InputContentBlock::ToolUse {
                        id: id.clone(),
                        name: name.clone(),
                        input: serde_json::from_str(input)
                            .unwrap_or_else(|_| serde_json::json!({ "raw": input })),
                    },
                    ContentBlock::ToolResult {
                        tool_use_id,
                        output,
                        is_error,
                        ..
                    } => InputContentBlock::ToolResult {
                        tool_use_id: tool_use_id.clone(),
                        content: vec![ToolResultContentBlock::Text {
                            text: output.clone(),
                        }],
                        is_error: *is_error,
                    },
                })
                .collect::<Vec<_>>();
            (!content.is_empty()).then(|| InputMessage {
                role: role.to_string(),
                content,
            })
        })
        .collect()
}
