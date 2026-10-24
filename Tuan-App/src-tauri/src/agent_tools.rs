//! 轻量 Agent 工具集（Android 侧）。
//!
//! 与桌面引擎 `tuan_cli/tools/` 的差异：只保留在安卓沙箱内真正可用的工具。
//! 手机没有 shell、没有任意路径读写、没有本地进程，因此不移植 code/shell/
//! backend_dev/image_gen 等依赖本地执行环境的工具。
//!
//! 收录标准：纯网络 / 纯计算 / 应用沙箱内文件，三者都不需要额外权限。
//! 每个工具都返回结构化结果（ok / error），并对输出做长度截断，
//! 避免大段内容挤爆移动端内存与上下文窗口。

use serde_json::{json, Value};

/// 工具执行结果。与引擎侧 `ToolResult` 对齐 status 语义，
/// 前端 `App.tsx` 依赖 `tool_result.out` 的内容判定成功/失败。
pub struct ToolOutput {
    pub ok: bool,
    pub content: String,
}

impl ToolOutput {
    fn ok(content: impl Into<String>) -> Self {
        Self { ok: true, content: content.into() }
    }
    fn err(msg: impl Into<String>) -> Self {
        Self { ok: false, content: msg.into() }
    }
}

/// 单个工具的输出上限。移动端上下文与内存都吃紧，超出部分截断。
const MAX_OUT: usize = 4000;
/// HTTP 抓取的最大字节数，防止拉进超大页面。
const MAX_HTTP_BYTES: usize = 200_000;

/// 工具的 JSON Schema 定义，随请求发给模型（OpenAI tools / Anthropic tools）。
pub fn tool_schemas() -> Vec<Value> {
    vec![
        json!({
            "type": "function",
            "function": {
                "name": "web_fetch",
                "description": "抓取一个网页或接口的文本内容并返回。用于查阅最新资料、读取文档或接口数据。支持 http/https。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": { "type": "string", "description": "要抓取的 URL，必须以 http:// 或 https:// 开头" }
                    },
                    "required": ["url"]
                }
            }
        }),
        json!({
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "联网搜索，返回若干条结果的标题、链接与摘要。当需要事实性信息、时效信息或不确定的内容时使用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": { "type": "string", "description": "搜索关键词" },
                        "count": { "type": "integer", "description": "返回结果条数，默认 5，最大 10" }
                    },
                    "required": ["query"]
                }
            }
        }),
        json!({
            "type": "function",
            "function": {
                "name": "calc",
                "description": "计算数学表达式，支持 + - * / % ^ 与括号，如 (1+2)*3^2。可用于精确算术，不要靠心算。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": { "type": "string", "description": "数学表达式，如 2*(3+4)/5" }
                    },
                    "required": ["expression"]
                }
            }
        }),
        json!({
            "type": "function",
            "function": {
                "name": "note",
                "description": "把一条信息记录到当前对话的笔记里。当用户明确要求\"记下来/保存/提醒我\"时使用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": { "type": "string", "description": "要记录的文本" }
                    },
                    "required": ["content"]
                }
            }
        }),
    ]
}

fn truncate(s: &str, n: usize) -> String {
    if s.chars().count() <= n {
        s.to_string()
    } else {
        let head: String = s.chars().take(n).collect();
        format!("{head}…（内容已截断）")
    }
}

/// 极简 HTML → 文本：去脚本/样式/标签，保留可读正文。
fn html_to_text(html: &str) -> String {
    let mut out = String::with_capacity(html.len() / 2);
    let mut depth_ignore = 0usize; // 处于 script/style 内
    let lower = html.to_ascii_lowercase();

    let bytes: Vec<char> = html.chars().collect();
    let lower_chars: Vec<char> = lower.chars().collect();
    let mut i = 0usize;
    let mut in_tag = false;

    while i < bytes.len() {
        let c = bytes[i];
        if in_tag {
            // 标签内部，判断是否为 script/style 起始
            if depth_ignore == 0 {
                let tail: String = lower_chars[i..(i + 8).min(lower_chars.len())].iter().collect();
                if tail.starts_with("script") || tail.starts_with("style") {
                    depth_ignore = 1;
                }
            }
            if c == '>' {
                in_tag = false;
                if depth_ignore > 0 {
                    depth_ignore += 1;
                }
            }
            i += 1;
            continue;
        }
        if c == '<' {
            in_tag = true;
            // 结束 script/style：看到 </ 就退出忽略态
            if depth_ignore == 1 {
                // 已在标签内，由上面的 '>' 逻辑处理
            }
            i += 1;
            continue;
        }
        if depth_ignore > 0 {
            i += 1;
            continue;
        }
        match c {
            '<' => {}
            '&' => {
                // 常见实体的最小解码
                let rest: String = bytes[i..(i + 8).min(bytes.len())].iter().collect();
                let rep = if rest.starts_with("&amp;") {
                    Some("&")
                } else if rest.starts_with("&lt;") {
                    Some("<")
                } else if rest.starts_with("&gt;") {
                    Some(">")
                } else if rest.starts_with("&quot;") {
                    Some("\"")
                } else if rest.starts_with("&nbsp;") {
                    Some(" ")
                } else {
                    None
                };
                match rep {
                    Some(r) => {
                        out.push_str(r);
                        i += if r.len() == 1 { 5 } else { r.len() + 2 };
                    }
                    None => {
                        out.push('&');
                        i += 1;
                    }
                }
            }
            _ => {
                out.push(c);
                i += 1;
            }
        }
    }

    // 折叠空白
    out.lines()
        .map(str::trim)
        .filter(|l| !l.is_empty())
        .collect::<Vec<_>>()
        .join("\n")
}

/// 百分号解码（仅用于解包 DuckDuckGo 的跳转链接）。
///
/// 不引入 `percent-encoding` / `url` 依赖：整个函数只为处理搜索结果里的
/// `uddg=` 参数，安卓侧少一个依赖就少一份包体与编译时间。
/// 未解码的 `%` 原样保留，不算错误——最坏情况是链接不可用。
fn percent_decode(s: &str) -> String {
    let b = s.as_bytes();
    let mut out: Vec<u8> = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() {
            let hex = |c: u8| -> Option<u8> {
                match c {
                    b'0'..=b'9' => Some(c - b'0'),
                    b'a'..=b'f' => Some(c - b'a' + 10),
                    b'A'..=b'F' => Some(c - b'A' + 10),
                    _ => None,
                }
            };
            if let (Some(h), Some(l)) = (hex(b[i + 1]), hex(b[i + 2])) {
                out.push(h * 16 + l);
                i += 3;
                continue;
            }
        }
        out.push(b[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// 把 DuckDuckGo 的跳转链接还原成真实 URL。
///
/// DDG 的 HTML 端点返回的是 `//duckduckgo.com/l/?uddg=<encoded>` 这种中转地址，
/// 直接交给模型是无效链接（既不能点，也无法再被 web_fetch 抓取）。
fn unwrap_ddg_redirect(href: &str) -> String {
    let raw = if let Some(rest) = href.strip_prefix("//duckduckgo.com/l/") {
        rest
    } else if let Some(rest) = href.strip_prefix("https://duckduckgo.com/l/") {
        rest
    } else if let Some(rest) = href.strip_prefix("http://duckduckgo.com/l/") {
        rest
    } else if href.starts_with("http://") || href.starts_with("https://") {
        return href.to_string();
    } else {
        // 协议相对链接补全
        return format!("https:{href}");
    };

    // 在查询串里找 uddg=
    if let Some(idx) = raw.find("uddg=") {
        let tail = &raw[idx + 5..];
        let end = tail.find('&').unwrap_or(tail.len());
        let decoded = percent_decode(&tail[..end]);
        if decoded.starts_with("http") {
            return decoded;
        }
    }
    // 没有 uddg 参数时退化为直接补全协议
    format!("https://duckduckgo.com/l/{raw}")
}

/// 执行单个工具。`notes` 用于 note 工具累积（调用方持有）。
pub async fn run_tool(
    name: &str,
    args: &Value,
    notes: &mut Vec<String>,
) -> ToolOutput {
    match name {
        "web_fetch" => {
            let Some(url) = args.get("url").and_then(|v| v.as_str()) else {
                return ToolOutput::err("缺少参数 url");
            };
            if !url.starts_with("http://") && !url.starts_with("https://") {
                return ToolOutput::err("url 必须以 http:// 或 https:// 开头");
            }
            let client = match reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(20))
                .user_agent("Mozilla/5.0 (Linux; Android) Tuan-Chat/0.1")
                .build()
            {
                Ok(c) => c,
                Err(e) => return ToolOutput::err(format!("网络客户端初始化失败：{e}")),
            };
            match client.get(url).send().await {
                Ok(resp) => {
                    let status = resp.status();
                    if !status.is_success() {
                        return ToolOutput::err(format!("抓取失败：HTTP {status}"));
                    }
                    let ct = resp
                        .headers()
                        .get(reqwest::header::CONTENT_TYPE)
                        .and_then(|v| v.to_str().ok())
                        .unwrap_or("")
                        .to_ascii_lowercase();
                    let body = match resp.text().await {
                        Ok(b) => b,
                        Err(e) => return ToolOutput::err(format!("读取响应失败：{e}")),
                    };
                    let body = if body.len() > MAX_HTTP_BYTES {
                        format!("{}…（响应过大已截断）", &body[..MAX_HTTP_BYTES])
                    } else {
                        body
                    };
                    let text = if ct.contains("html") || body.trim_start().starts_with('<') {
                        html_to_text(&body)
                    } else {
                        body
                    };
                    ToolOutput::ok(truncate(text.trim(), MAX_OUT))
                }
                Err(e) => ToolOutput::err(format!("请求失败：{e}")),
            }
        }
        "web_search" => {
            let Some(query) = args.get("query").and_then(|v| v.as_str()) else {
                return ToolOutput::err("缺少参数 query");
            };
            let count = args
                .get("count")
                .and_then(|v| v.as_u64())
                .unwrap_or(5)
                .clamp(1, 10) as usize;

            // 用 DuckDuckGo 的 HTML 端点做无 key 搜索。
            // 说明：这是移动端能免密钥落地的方案；若后续接入正式搜索 API，
            // 只需替换此处实现，工具契约（入参/返回）对模型不变。
            let client = match reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(20))
                .user_agent("Mozilla/5.0 (Linux; Android) Tuan-Chat/0.1")
                .build()
            {
                Ok(c) => c,
                Err(e) => return ToolOutput::err(format!("网络客户端初始化失败：{e}")),
            };
            let resp = client
                .get("https://html.duckduckgo.com/html/")
                .query(&[("q", query)])
                .send()
                .await;
            let html = match resp {
                Ok(r) if r.status().is_success() => r.text().await.unwrap_or_default(),
                Ok(r) => return ToolOutput::err(format!("搜索失败：HTTP {}", r.status())),
                Err(e) => return ToolOutput::err(format!("搜索请求失败：{e}")),
            };

            // 抽取结果条目：<a class="result__a" href="...">标题</a>
            // 紧随其后的是 <a class="result__snippet">摘要</a>。
            // 只取标题也够用，但带上摘要能显著减少模型"再抓一次网页"的轮次。
            let mut items: Vec<String> = Vec::new();
            let mut rest = html.as_str();
            while items.len() < count {
                let Some(pos) = rest.find("result__a") else { break };
                let after = &rest[pos..];
                let Some(href_start) = after.find("href=\"") else { break };
                let href_val = &after[href_start + 6..];
                let Some(href_end) = href_val.find('"') else { break };
                let href = &href_val[..href_end];
                let Some(text_start) = after.find('>') else { break };
                let tail = &after[text_start + 1..];
                let Some(text_end) = tail.find("</a>") else { break };
                let title = html_to_text(&tail[..text_end]);
                rest = &tail[text_end + 4..];

                if title.trim().is_empty() {
                    continue;
                }
                let url = unwrap_ddg_redirect(href);

                // 摘要：在剩余 HTML 里找下一个 result__snippet，取到下一个标签为止
                let snippet = rest
                    .find("result__snippet")
                    .and_then(|p| {
                        let seg = &rest[p..];
                        let a = seg.find('>')?;
                        let t = &seg[a + 1..];
                        let b = t.find("</a>").unwrap_or(t.len());
                        Some(html_to_text(&t[..b.min(600)]))
                    })
                    .unwrap_or_default();

                let mut entry = format!("{}. {}\n   URL: {}", items.len() + 1, title.trim(), url);
                if !snippet.trim().is_empty() {
                    entry.push_str(&format!("\n   摘要: {}", snippet.trim()));
                }
                items.push(entry);
            }

            if items.is_empty() {
                ToolOutput::err("未获得搜索结果（可能是网络受限或该源暂不可用）")
            } else {
                ToolOutput::ok(truncate(&items.join("\n"), MAX_OUT))
            }
        }
        "calc" => {
            let Some(expr) = args.get("expression").and_then(|v| v.as_str()) else {
                return ToolOutput::err("缺少参数 expression");
            };
            match eval_math(expr) {
                Ok(v) => ToolOutput::ok(format!("{expr} = {v}")),
                Err(e) => ToolOutput::err(format!("计算失败：{e}")),
            }
        }
        "note" => {
            let Some(content) = args.get("content").and_then(|v| v.as_str()) else {
                return ToolOutput::err("缺少参数 content");
            };
            notes.push(content.to_string());
            ToolOutput::ok(format!("已记录（第 {} 条）：{}", notes.len(), content.trim()))
        }
        other => ToolOutput::err(format!("未知工具：{other}")),
    }
}

// ---------------------------------------------------------------- 计算器

/// 递归下降表达式求值，支持 + - * / % ^ 与一元负号、括号。
fn eval_math(src: &str) -> Result<f64, String> {
    let chars: Vec<char> = src.chars().filter(|c| !c.is_whitespace()).collect();
    let mut pos = 0usize;
    let v = parse_expr(&chars, &mut pos)?;
    if pos != chars.len() {
        return Err("表达式尾部有多余字符".into());
    }
    if !v.is_finite() {
        return Err("结果不是有限数".into());
    }
    // 整数结果不带小数尾巴
    if (v - v.round()).abs() < 1e-10 {
        Ok(v.round())
    } else {
        Ok((v * 1e10).round() / 1e10)
    }
}

fn parse_expr(c: &[char], p: &mut usize) -> Result<f64, String> {
    let mut v = parse_term(c, p)?;
    while *p < c.len() {
        match c[*p] {
            '+' => {
                *p += 1;
                v += parse_term(c, p)?;
            }
            '-' => {
                *p += 1;
                v -= parse_term(c, p)?;
            }
            _ => break,
        }
    }
    Ok(v)
}

fn parse_term(c: &[char], p: &mut usize) -> Result<f64, String> {
    let mut v = parse_pow(c, p)?;
    while *p < c.len() {
        match c[*p] {
            '*' => {
                *p += 1;
                v *= parse_pow(c, p)?;
            }
            '/' => {
                *p += 1;
                let d = parse_pow(c, p)?;
                if d == 0.0 {
                    return Err("除以零".into());
                }
                v /= d;
            }
            '%' => {
                *p += 1;
                let d = parse_pow(c, p)?;
                if d == 0.0 {
                    return Err("模零".into());
                }
                v %= d;
            }
            _ => break,
        }
    }
    Ok(v)
}

fn parse_pow(c: &[char], p: &mut usize) -> Result<f64, String> {
    let base = parse_unary(c, p)?;
    if *p < c.len() && c[*p] == '^' {
        *p += 1;
        let exp = parse_pow(c, p)?; // 右结合
        Ok(base.powf(exp))
    } else {
        Ok(base)
    }
}

fn parse_unary(c: &[char], p: &mut usize) -> Result<f64, String> {
    if *p < c.len() && c[*p] == '-' {
        *p += 1;
        return Ok(-parse_unary(c, p)?);
    }
    if *p < c.len() && c[*p] == '+' {
        *p += 1;
        return parse_unary(c, p);
    }
    parse_atom(c, p)
}

fn parse_atom(c: &[char], p: &mut usize) -> Result<f64, String> {
    if *p >= c.len() {
        return Err("表达式不完整".into());
    }
    if c[*p] == '(' {
        *p += 1;
        let v = parse_expr(c, p)?;
        if *p >= c.len() || c[*p] != ')' {
            return Err("括号不匹配".into());
        }
        *p += 1;
        return Ok(v);
    }
    let start = *p;
    while *p < c.len() && (c[*p].is_ascii_digit() || c[*p] == '.') {
        *p += 1;
    }
    if start == *p {
        return Err(format!("无法识别的字符 {:?}", c[*p]));
    }
    let s: String = c[start..*p].iter().collect();
    s.parse::<f64>().map_err(|_| format!("无效数字：{s}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn math_precedence_and_parens() {
        assert_eq!(eval_math("1+2*3").unwrap(), 7.0);
        assert_eq!(eval_math("(1+2)*3").unwrap(), 9.0);
        assert_eq!(eval_math("2^3^2").unwrap(), 512.0); // 右结合
        assert_eq!(eval_math("-5+3").unwrap(), -2.0);
        assert_eq!(eval_math("7%4").unwrap(), 3.0);
        assert_eq!(eval_math("10/4").unwrap(), 2.5);
    }

    #[test]
    fn math_rejects_bad_input() {
        assert!(eval_math("1/0").is_err());
        assert!(eval_math("(1+2").is_err());
        assert!(eval_math("1+").is_err());
        assert!(eval_math("1+a").is_err());
    }

    #[test]
    fn html_strips_scripts_and_tags() {
        let h = "<html><head><style>.a{}</style><script>var x=1;</script></head>"
            .to_string()
            + "<body><h1>Title</h1><p>Hello &amp; world</p></body></html>";
        let t = html_to_text(&h);
        assert!(!t.contains("var x"), "脚本内容应被剔除");
        assert!(!t.contains(".a{"), "样式内容应被剔除");
        assert!(t.contains("Title"));
        assert!(t.contains("Hello & world"), "实体应被解码: {t}");
    }

    #[test]
    fn schemas_are_valid_json() {
        for s in tool_schemas() {
            assert!(s.get("function").and_then(|f| f.get("name")).is_some());
        }
        assert_eq!(tool_schemas().len(), 4);
    }

    #[test]
    fn percent_decode_handles_utf8_and_bad_input() {
        assert_eq!(percent_decode("a%20b"), "a b");
        // 中文 URL 的 UTF-8 百分号序列
        assert_eq!(percent_decode("%E4%B8%AD%E6%96%87"), "中文");
        // 非法 / 截断的百分号序列应原样保留，不能 panic
        assert_eq!(percent_decode("100%"), "100%");
        assert_eq!(percent_decode("%zz"), "%zz");
        assert_eq!(percent_decode("%4"), "%4");
    }

    #[test]
    fn ddg_redirect_is_unwrapped() {
        // DDG 的中转链接必须还原成真实地址，否则模型拿到的 URL 无法使用
        assert_eq!(
            unwrap_ddg_redirect("//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa%3Fx%3D1%26y%3D2"),
            "https://example.com/a?x=1&y=2"
        );
        assert_eq!(
            unwrap_ddg_redirect("https://duckduckgo.com/l/?uddg=https%3A%2F%2Frust-lang.org"),
            "https://rust-lang.org"
        );
        // 已是直链时原样返回
        assert_eq!(
            unwrap_ddg_redirect("https://example.com/x"),
            "https://example.com/x"
        );
        // 其他协议相对链接补全协议
        assert_eq!(unwrap_ddg_redirect("//example.com/p"), "https://example.com/p");
        // 没有 uddg 参数时不报错，退化为可读地址
        assert!(unwrap_ddg_redirect("//duckduckgo.com/l/?q=x").starts_with("https://"));
    }
}