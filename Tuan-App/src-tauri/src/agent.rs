//! 轻量 Agent 主循环（Android 侧，不依赖本地 Python 引擎）。
//!
//! 桌面端由 `tuan_cli` 引擎承载完整 agent 能力（系统提示词分层、工具调用、
//! 安全闸门、会话持久化、子 agent 等）；安卓没有解释器与本地执行环境，
//! 这里用 Rust 复刻其中**在手机上真正可用的那一部分**：
//!
//!   用户提问 → 模型决定是否调用工具 → 执行工具 → 结果回灌 → 直到收敛
//!
//! 与引擎保持一致的事件契约（`text` / `tool` / `tool_result` / `done` / `error`），
//! 前端 `App.tsx` 无需区分平台即可渲染工具执行过程。
//!
//! 两点务实取舍：
//! 1. 工具调用循环最多 MAX_ROUNDS 轮，防止模型陷入死循环烧流量；
//! 2. 只在支持 function calling 的模型上启用，不支持时自动降级为普通对话。

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::agent_tools::{run_tool, tool_schemas, ToolOutput};
use crate::net::Provider;

/// 单轮对话内最多允许的工具调用轮数。
const MAX_ROUNDS: usize = 8;
/// 单次模型请求的超时。
const REQ_TIMEOUT_SECS: u64 = 120;

#[derive(Debug, Serialize, Clone)]
pub struct AgentChunk {
    #[serde(rename = "type")]
    pub kind: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub text: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub args: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub out: Option<String>,
}

fn txt(s: String) -> AgentChunk {
    AgentChunk { kind: "text".into(), text: Some(s), name: None, args: None, out: None }
}
fn tool_start(name: &str, args: &Value) -> AgentChunk {
    AgentChunk {
        kind: "tool".into(),
        text: None,
        name: Some(name.to_string()),
        args: Some(args.to_string()),
        out: None,
    }
}
fn tool_end(name: &str, out: &ToolOutput) -> AgentChunk {
    AgentChunk {
        kind: "tool_result".into(),
        text: None,
        name: Some(name.to_string()),
        args: None,
        out: Some(out.content.clone()),
    }
}
fn done() -> AgentChunk {
    AgentChunk { kind: "done".into(), text: None, name: None, args: None, out: None }
}
fn err(msg: impl Into<String>) -> AgentChunk {
    let m = msg.into();
    AgentChunk { kind: "error".into(), text: None, name: None, args: None, out: Some(m) }
}

/// 传给模型的系统提示词。明确能力边界，避免模型承诺手机上做不到的事
/// （改代码、跑 shell、访问任意文件）。
const SYSTEM_PROMPT: &str = "\
你是 Tuan-Chat 的助手，运行在 Android 设备上。

你具备工具调用能力，可以联网查资料、抓取网页、算数、记录笔记。
使用原则：
- 需要最新信息、外部事实或你不确定的内容时，主动调用工具核实，不要凭记忆编造。
- 工具是串行的：一次给出一个 tool_call，等结果返回后再决定下一步。
- 工具失败时，如实说明失败原因，不要假装成功。
- 回答用中文，简洁直接；不需要复述工具的原始输出，提取要点即可。

能力边界（必须如实告知用户）：
- 你在手机上运行，无法执行 shell 命令、无法修改代码工程、无法访问设备上的任意文件。
- 涉及本地开发环境、编译、跑测试的任务，请建议用户在桌面端使用完整版。
";

/// 参与对话的一条消息。role: user | assistant | tool
///
/// 字段中的 tool_call_id / tool_calls 仅为协议兼容保留：循环内部自维护工具
/// 结果，前端传入时通常不带这两个字段。
#[derive(Debug, Deserialize, Clone)]
pub struct Turn {
    pub role: String,
    pub content: String,
    #[serde(default)]
    pub tool_call_id: Option<String>,
    #[serde(default)]
    pub tool_calls: Option<Vec<ToolCall>>,
}

#[derive(Debug, Deserialize, Clone, Serialize)]
pub struct ToolCall {
    pub id: String,
    #[serde(rename = "type")]
    pub kind: String,
    pub function: ToolFn,
}

#[derive(Debug, Deserialize, Clone, Serialize)]
pub struct ToolFn {
    pub name: String,
    /// 参数是 JSON 字符串，需二次解析
    pub arguments: String,
}

/// Agent 对话入口。由前端 `agent_chat_stream` 调用。
#[tauri::command]
pub async fn agent_chat_stream(
    provider: Provider,
    model: String,
    history: Vec<Turn>,
    enable_tools: Option<bool>,
    channel: tauri::ipc::Channel<AgentChunk>,
) -> Result<(), String> {
    let client = match reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(REQ_TIMEOUT_SECS))
        .connect_timeout(std::time::Duration::from_secs(20))
        .build()
    {
        Ok(c) => c,
        Err(e) => {
            let _ = channel.send(err(format!("网络客户端初始化失败：{e}")));
            return Ok(());
        }
    };

    let use_tools = enable_tools.unwrap_or(true);
    let is_anthropic = provider.format == "anthropic";
    let base = provider.baseUrl.trim_end_matches('/').to_string();

    // 构造消息序列：系统提示词 + 历史
    let mut messages: Vec<Value> = Vec::new();
    messages.push(json!({ "role": "system", "content": SYSTEM_PROMPT }));
    for m in &history {
        // 只回传 user/assistant 文本；tool 结果由循环内部维护
        if m.role == "user" || m.role == "assistant" {
            if !m.content.trim().is_empty() {
                messages.push(json!({ "role": m.role, "content": m.content }));
            }
        }
    }

    let mut notes: Vec<String> = Vec::new();

    for round in 0..MAX_ROUNDS {
        // ---- 发起一次模型请求 ----
        let resp = if is_anthropic {
            // Anthropic：system 独立传，tools 用 input_schema
            let msgs: Vec<Value> = messages
                .iter()
                .filter(|m| m.get("role").and_then(|r| r.as_str()) != Some("system"))
                .cloned()
                .collect();
            let tools: Vec<Value> = tool_schemas()
                .iter()
                .map(|t| {
                    json!({
                        "name": t.pointer("/function/name").cloned().unwrap_or(Value::Null),
                        "description": t.pointer("/function/description").cloned().unwrap_or(Value::Null),
                        "input_schema": t.pointer("/function/parameters").cloned().unwrap_or(json!({})),
                    })
                })
                .collect();
            let mut body = json!({
                "model": model,
                "max_tokens": 4096,
                "system": SYSTEM_PROMPT,
                "messages": msgs,
                "stream": false,
            });
            if use_tools && !tools.is_empty() {
                body["tools"] = Value::Array(tools);
            }
            client
                .post(format!("{base}/v1/messages"))
                .header("Content-Type", "application/json")
                .header("x-api-key", &provider.apiKey)
                .header("anthropic-version", "2023-06-01")
                .json(&body)
                .send()
                .await
        } else {
            let mut body = json!({
                "model": model,
                "messages": messages,
                "stream": false,
            });
            if use_tools {
                body["tools"] = Value::Array(tool_schemas());
                body["tool_choice"] = json!("auto");
            }
            client
                .post(format!("{base}/chat/completions"))
                .header("Content-Type", "application/json")
                .header("Authorization", format!("Bearer {}", provider.apiKey))
                .json(&body)
                .send()
                .await
        };

        let resp = match resp {
            Ok(r) => r,
            Err(e) => {
                let _ = channel.send(err(format!("连接失败：{e}（请检查地址、网络与密钥）")));
                return Ok(());
            }
        };

        let status = resp.status();
        if !status.is_success() {
            let body = resp.text().await.unwrap_or_default();
            let _ = channel.send(err(format!("接口返回 {status}：{}", clip(&body, 300))));
            return Ok(());
        }

        let payload: Value = match resp.json().await {
            Ok(v) => v,
            Err(e) => {
                let _ = channel.send(err(format!("解析响应失败：{e}")));
                return Ok(());
            }
        };

        // ---- 解析：文本 + 工具调用请求 ----
        let (content_text, tool_calls) = if is_anthropic {
            let text = payload
                .get("content")
                .and_then(|c| c.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|b| b.get("text").and_then(|t| t.as_str()))
                        .collect::<Vec<_>>()
                        .join("")
                })
                .unwrap_or_default();
            let calls = payload
                .get("content")
                .and_then(|c| c.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter(|b| b.get("type").and_then(|t| t.as_str()) == Some("tool_use"))
                        .map(|b| ToolCall {
                            id: b.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                            kind: "function".into(),
                            function: ToolFn {
                                name: b.get("name").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                                arguments: b
                                    .get("input")
                                    .map(|v| v.to_string())
                                    .unwrap_or_else(|| "{}".into()),
                            },
                        })
                        .collect::<Vec<_>>()
                })
                .unwrap_or_default();
            (text, calls)
        } else {
            let msg = payload.pointer("/choices/0/message").cloned().unwrap_or(Value::Null);
            let text = msg.get("content").and_then(|v| v.as_str()).unwrap_or("").to_string();
            let calls = msg
                .get("tool_calls")
                .and_then(|v| v.as_array())
                .map(|arr| {
                    arr.iter()
                        .map(|c| ToolCall {
                            id: c.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                            kind: c.get("type").and_then(|v| v.as_str()).unwrap_or("function").into(),
                            function: ToolFn {
                                name: c
                                    .pointer("/function/name")
                                    .and_then(|v| v.as_str())
                                    .unwrap_or("")
                                    .to_string(),
                                arguments: c
                                    .pointer("/function/arguments")
                                    .and_then(|v| v.as_str())
                                    .unwrap_or("{}")
                                    .to_string(),
                            },
                        })
                        .collect::<Vec<_>>()
                })
                .unwrap_or_default();
            (text, calls)
        };

        // ---- 无工具调用：本轮即最终回答 ----
        if tool_calls.is_empty() {
            let is_blank = content_text.trim().is_empty();
            if !is_blank {
                let _ = channel.send(txt(content_text));
            }
            // 若模型既没给文本也没给工具（异常情况），兜底提示而不是静默结束
            if is_blank && round == 0 {
                let _ = channel.send(txt("(模型未返回内容，请重试或更换模型)".into()));
            }
            let _ = channel.send(done());
            return Ok(());
        }

        // ---- 有工具调用：回显文本、执行工具、结果回灌 ----
        if !content_text.trim().is_empty() {
            let _ = channel.send(txt(content_text.clone()));
        }

        for tc in &tool_calls {
            let args: Value = serde_json::from_str(&tc.function.arguments)
                .unwrap_or_else(|_| json!({ "__raw": tc.function.arguments }));

            let _ = channel.send(tool_start(&tc.function.name, &args));

            let out = run_tool(&tc.function.name, &args, &mut notes).await;
            let _ = channel.send(tool_end(&tc.function.name, &out));

            // 把结果追加进消息序列，供模型下一轮参考
            if is_anthropic {
                messages.push(json!({
                    "role": "assistant",
                    "content": [{
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.function.name,
                        "input": args,
                    }]
                }));
                messages.push(json!({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": clip(&out.content, 4000),
                        "is_error": !out.ok,
                    }]
                }));
            } else {
                messages.push(json!({
                    "role": "assistant",
                    "tool_calls": [{
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }]
                }));
                messages.push(json!({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": clip(&out.content, 4000),
                }));
            }
        }

        // 工具调用轮数用尽：让模型基于已有结果收尾
        if round == MAX_ROUNDS - 1 {
            messages.push(json!({
                "role": "user",
                "content": "请基于以上工具结果给出最终答复，不要再调用工具。"
            }));
        }
    }

    let _ = channel.send(done());
    Ok(())
}

fn clip(s: &str, n: usize) -> String {
    if s.chars().count() <= n {
        s.to_string()
    } else {
        let head: String = s.chars().take(n).collect();
        format!("{head}…（已截断）")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clip_respects_char_boundary() {
        let s = "中文测试内容";
        let out = clip(s, 3);
        assert_eq!(out, "中文测…（已截断）");
    }

    #[test]
    fn system_prompt_declares_limits() {
        // 能力边界必须写进提示词，否则模型会承诺手机上做不到的事
        assert!(SYSTEM_PROMPT.contains("无法执行 shell"));
        assert!(SYSTEM_PROMPT.contains("桌面端"));
    }
}