//! Agent Anywhere：30+ 主流平台内容抓取模块。
//!
//! 设计原则：
//!   1. 免登录——只走公开 API、移动端网页、oEmbed、syndication 等无需认证的入口。
//!   2. 防拦截——轮换 User-Agent、带 Accept-Language / Referer、失败重试、
//!      结果内存缓存（同一 URL 30 分钟内不重复请求）。
//!   3. 自研——不依赖第三方爬虫库，所有解析逻辑手写。
//!
//! 每个平台的 fetch 函数返回 Option<String>（成功）或 None（失败），
//! 由 media_fetch 统一拼成结构化文本交给模型做摘要。

use serde_json::Value;
use std::collections::HashMap;
use std::sync::Mutex;
use std::time::{Duration, Instant};

/// 内存缓存：同一 URL 在 30 分钟内不重复请求，降低被限流概率。
fn cache() -> &'static Mutex<HashMap<String, (Instant, String)>> {
    static CACHE: std::sync::LazyLock<Mutex<HashMap<String, (Instant, String)>>> =
        std::sync::LazyLock::new(|| Mutex::new(HashMap::new()));
    CACHE
}

const CACHE_TTL: Duration = Duration::from_secs(1800); // 30 分钟

/// 检查缓存，命中则返回内容副本。
fn cache_get(key: &str) -> Option<String> {
    let guard = cache().lock().ok()?;
    guard.get(key).and_then(|(ts, v)| {
        if ts.elapsed() < CACHE_TTL {
            Some(v.clone())
        } else {
            None
        }
    })
}

/// 写入缓存。
fn cache_put(key: &str, val: String) {
    if let Ok(mut guard) = cache().lock() {
        guard.insert(key.to_string(), (Instant::now(), val));
    }
}

/// 平台标识枚举（用字符串匹配即可，不需要完整枚举以减少代码量）。
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Platform {
    Bilibili,
    Douyin,
    Kuaishou,
    Zhihu,
    Tieba,
    Twitter,
    YouTube,
    Weibo,
    Toutiao,
    WeChat,
    Xiaohongshu,
    NetEase,
    Sina,
    ThePaper,
    Huxiu,
    Kr36,
    Sspai,
    Juejin,
    SegmentFault,
    V2ex,
    HackerNews,
    Reddit,
    Medium,
    Github,
    StackOverflow,
    Wikipedia,
    Facebook,
    Instagram,
    Telegram,
    Discord,
    Generic, // 兜底：通用网页抓取
}

/// 从 URL 检测平台。匹配顺序：先匹配特征最明确的域名。
pub fn detect_platform(url: &str) -> Platform {
    let u = url.to_ascii_lowercase();
    if u.contains("bilibili.com") || u.contains("b23.tv") {
        Platform::Bilibili
    } else if u.contains("douyin.com") || u.contains("iesdouyin.com") || u.contains("amemv.com") {
        Platform::Douyin
    } else if u.contains("kuaishou.com") || u.contains("gifshow.com") || u.contains("kwai.kuaishou.com") {
        Platform::Kuaishou
    } else if u.contains("zhihu.com") {
        Platform::Zhihu
    } else if u.contains("tieba.baidu.com") || u.contains("c.tieba.baidu.com") {
        Platform::Tieba
    } else if u.contains("twitter.com") || u.contains("x.com") || u.contains("t.co") {
        Platform::Twitter
    } else if u.contains("youtube.com") || u.contains("youtu.be") {
        Platform::YouTube
    } else if u.contains("weibo.com") || u.contains("weibo.cn") {
        Platform::Weibo
    } else if u.contains("toutiao.com") || u.contains("toutiao") {
        Platform::Toutiao
    } else if u.contains("mp.weixin.qq.com") {
        Platform::WeChat
    } else if u.contains("xiaohongshu.com") || u.contains("xhslink.com") {
        Platform::Xiaohongshu
    } else if u.contains("163.com") || u.contains("netease.com") {
        Platform::NetEase
    } else if u.contains("sina.com.cn") || u.contains("sina.com") || u.contains("sina.com.tw") {
        Platform::Sina
    } else if u.contains("thepaper.cn") {
        Platform::ThePaper
    } else if u.contains("huxiu.com") {
        Platform::Huxiu
    } else if u.contains("36kr.com") {
        Platform::Kr36
    } else if u.contains("sspai.com") {
        Platform::Sspai
    } else if u.contains("juejin.cn") {
        Platform::Juejin
    } else if u.contains("segmentfault.com") {
        Platform::SegmentFault
    } else if u.contains("v2ex.com") {
        Platform::V2ex
    } else if u.contains("news.ycombinator.com") || u.contains("ycombinator.com") {
        Platform::HackerNews
    } else if u.contains("reddit.com") || u.contains("redd.it") {
        Platform::Reddit
    } else if u.contains("medium.com") {
        Platform::Medium
    } else if u.contains("github.com") || u.contains("gist.github.com") {
        Platform::Github
    } else if u.contains("stackoverflow.com") || u.contains("stackexchange.com") {
        Platform::StackOverflow
    } else if u.contains("wikipedia.org") || u.contains("zh.wikipedia.org") {
        Platform::Wikipedia
    } else if u.contains("facebook.com") || u.contains("fb.com") {
        Platform::Facebook
    } else if u.contains("instagram.com") {
        Platform::Instagram
    } else if u.contains("t.me") || u.contains("telegram.org") {
        Platform::Telegram
    } else if u.contains("discord.gg") || u.contains("discord.com") {
        Platform::Discord
    } else {
        Platform::Generic
    }
}

/// 平台中文名（用于返回结果中标注来源）。
pub fn platform_name(p: Platform) -> &'static str {
    match p {
        Platform::Bilibili => "Bilibili",
        Platform::Douyin => "抖音",
        Platform::Kuaishou => "快手",
        Platform::Zhihu => "知乎",
        Platform::Tieba => "百度贴吧",
        Platform::Twitter => "X (Twitter)",
        Platform::YouTube => "YouTube",
        Platform::Weibo => "微博",
        Platform::Toutiao => "今日头条",
        Platform::WeChat => "微信公众号",
        Platform::Xiaohongshu => "小红书",
        Platform::NetEase => "网易新闻",
        Platform::Sina => "新浪新闻",
        Platform::ThePaper => "澎湃新闻",
        Platform::Huxiu => "虎嗅",
        Platform::Kr36 => "36氪",
        Platform::Sspai => "少数派",
        Platform::Juejin => "掘金",
        Platform::SegmentFault => "SegmentFault",
        Platform::V2ex => "V2EX",
        Platform::HackerNews => "Hacker News",
        Platform::Reddit => "Reddit",
        Platform::Medium => "Medium",
        Platform::Github => "GitHub",
        Platform::StackOverflow => "Stack Overflow",
        Platform::Wikipedia => "Wikipedia",
        Platform::Facebook => "Facebook",
        Platform::Instagram => "Instagram",
        Platform::Telegram => "Telegram",
        Platform::Discord => "Discord",
        Platform::Generic => "网页",
    }
}

// ============================================================ 公共工具

/// 构建 HTTP 客户端：带超时 + 轮换 User-Agent + 常见请求头。
fn build_client(seed: u64) -> Result<reqwest::Client, String> {
    let uas = [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
        "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    ];
    let ua = uas[(seed as usize) % uas.len()];
    reqwest::Client::builder()
        .timeout(Duration::from_secs(20))
        .user_agent(ua)
        .default_headers({
            let mut h = reqwest::header::HeaderMap::new();
            h.insert(reqwest::header::ACCEPT, reqwest::header::HeaderValue::from_static("text/html,application/xhtml+xml,application/json,*/*"));
            h.insert(reqwest::header::ACCEPT_LANGUAGE, reqwest::header::HeaderValue::from_static("zh-CN,zh;q=0.9,en;q=0.8"));
            h
        })
        .build()
        .map_err(|e| format!("HTTP 客户端初始化失败：{e}"))
}

/// 发送 GET 请求并返回文本。失败时返回 None（不 panic）。
async fn fetch_text(client: &reqwest::Client, url: &str) -> Option<String> {
    let resp = client.get(url).send().await.ok()?;
    if !resp.status().is_success() {
        return None;
    }
    resp.text().await.ok()
}

/// 发送 GET 请求并返回 JSON。
async fn fetch_json(client: &reqwest::Client, url: &str) -> Option<Value> {
    let resp = client.get(url).send().await.ok()?;
    if !resp.status().is_success() {
        return None;
    }
    resp.json::<Value>().await.ok()
}

/// 从 JSON 中取字符串字段，缺失返回空串。
fn jstr<'a>(v: &'a Value, path: &[&str]) -> &'a str {
    let mut cur = v;
    for p in path {
        match cur.get(p) {
            Some(x) => cur = x,
            None => return "",
        }
    }
    cur.as_str().unwrap_or("")
}

/// 从 HTML 中提取 <meta> 标签的 content 属性（按 name/property 匹配）。
fn extract_meta(html: &str, key: &str) -> String {
    let lower = html.to_ascii_lowercase();
    let key_lower = key.to_ascii_lowercase();
    // 尝试所有可能的 meta 标签格式
    for attr in ["name", "property"] {
        let attr_key = format!("{}=\"{}\"", attr, key_lower);
        let attr_key2 = format!("{}='{}'", attr, key_lower);
        for pattern in [attr_key, attr_key2] {
            if let Some(pos) = lower.find(&pattern) {
                // 找到属性位置，向前找 <meta 开始，向后找 content
                let tag_start = lower[..pos].rfind("<meta").unwrap_or(0);
                let tag_end = lower[pos..].find('>').map(|e| pos + e).unwrap_or(lower.len());
                let tag = &lower[tag_start..tag_end];
                // 在标签内找 content
                let content_pos = tag.find("content=").or_else(|| tag.find("content='"))
                    .or_else(|| tag.find("content=\""));
                if let Some(cp) = content_pos {
                    let after = &tag[cp + 8..]; // "content" is 7 chars + =
                    let val = if after.starts_with('\"') || after.starts_with('\'') {
                        let quote = after.chars().next().unwrap();
                        let end = after[1..].find(quote).map(|e| e + 1).unwrap_or(after.len());
                        &after[1..end]
                    } else {
                        let end = after.find(['\"', '\'', '>', ' ']).unwrap_or(after.len());
                        &after[..end]
                    };
                    if !val.trim().is_empty() {
                        return val.to_string();
                    }
                }
                // content 可能在 name/property 之前
                let before = &tag[..tag.find(attr).unwrap_or(0)];
                let content_pos = before.find("content=").or_else(|| before.find("content='"))
                    .or_else(|| before.find("content=\""));
                if let Some(cp) = content_pos {
                    let after = &before[cp + 8..];
                    let val = if after.starts_with('\"') || after.starts_with('\'') {
                        let quote = after.chars().next().unwrap();
                        let end = after[1..].find(quote).map(|e| e + 1).unwrap_or(after.len());
                        &after[1..end]
                    } else {
                        let end = after.find(['\"', '\'', '>', ' ']).unwrap_or(after.len());
                        &after[..end]
                    };
                    if !val.trim().is_empty() {
                        return val.to_string();
                    }
                }
            }
        }
    }
    String::new()
}

/// 从 HTML 中提取 <title> 内容。
fn extract_title(html: &str) -> String {
    let lower = html.to_ascii_lowercase();
    if let Some(start) = lower.find("<title>") {
        let after = &html[start + 7..];
        if let Some(end) = after.find("</title>") {
            let t = &after[..end];
            return t.split('\n').next().unwrap_or("").trim().to_string();
        }
    }
    String::new()
}

/// 从 HTML 中提取 <script type="application/ld+json"> 内容。
fn extract_jsonld(html: &str) -> Option<Value> {
    let lower = html.to_ascii_lowercase();
    let marker = "<script type=\"application/ld+json\">";
    let m_lower = marker.to_ascii_lowercase();
    if let Some(pos) = lower.find(&m_lower) {
        let after = &html[pos + marker.len()..];
        let end = after.find("</script>").unwrap_or(after.len());
        let json_str = after[..end].trim();
        serde_json::from_str(json_str).ok()
    } else {
        None
    }
}

/// 从 HTML 中提取 JSON-LD 中的 description / text / articleBody。
fn jsonld_text(v: &Value) -> String {
    if v.is_object() {
        for key in ["description", "text", "articleBody", "content"] {
            if let Some(s) = v.get(key).and_then(|x| x.as_str()) {
                if !s.is_empty() {
                    return s.to_string();
                }
            }
        }
        // 递归遍历 graph / 数组
        if let Some(graph) = v.get("@graph") {
            if graph.is_array() {
                for item in graph.as_array().unwrap() {
                    let t = jsonld_text(item);
                    if !t.is_empty() {
                        return t;
                    }
                }
            }
        }
    } else if v.is_array() {
        for item in v.as_array().unwrap() {
            let t = jsonld_text(item);
            if !t.is_empty() {
                return t;
            }
        }
    }
    String::new()
}

/// 简易 HTML → 文本：去标签、去空白、折叠。
/// 简易 HTML → 文本：去标签、去 script/style、折叠空白。
fn simple_html_to_text(html: &str) -> String {
    let lower = html.to_ascii_lowercase();
    let mut out = String::with_capacity(html.len() / 3);
    let mut in_tag = false;
    let mut skip_tag = false; // 跳过 script/style 块
    let mut pending_amp = false; // 处理 &amp; &lt; &gt; &nbsp; 等实体

    let chars: Vec<char> = html.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if in_tag {
            if c == '>' {
                in_tag = false;
                skip_tag = false;
            }
            i += 1;
            continue;
        }
        if c == '<' {
            in_tag = true;
            // 检查是否为需要跳过的标签
            let tag_start = &lower[i..lower.len().min(i + 20)];
            if tag_start.starts_with("<script") || tag_start.starts_with("<style") {
                skip_tag = true;
            }
            i += 1;
            continue;
        }
        if skip_tag {
            i += 1;
            continue;
        }
        if pending_amp {
            // 处理常见 HTML 实体
            if c == 'a' || c == 'A' {
                if i + 4 < chars.len() && &chars[i+1..i+5] == &['m', 'p', ';', ';'][..] {
                    // handled below
                }
                // Check for known entities
                let rest = &html[i..];
                if rest.starts_with("amp;") { out.push('&'); i += 4; continue; }
                if rest.starts_with("lt;") { out.push('<'); i += 3; continue; }
                if rest.starts_with("gt;") { out.push('>'); i += 3; continue; }
                if rest.starts_with("nbsp;") { out.push(' '); i += 5; continue; }
                if rest.starts_with("quot;") { out.push('"'); i += 5; continue; }
                if rest.starts_with("#x27;") || rest.starts_with("#39;") { out.push('\''); i += 5; continue; }
                // 不是已知实体，保留 &
                out.push('&');
                pending_amp = false;
                continue;
            }
            // 不匹配已知实体，直接保留
            out.push('&');
            out.push(c);
            pending_amp = false;
            i += 1;
            continue;
        }
        match c {
            '&' => { pending_amp = true; i += 1; }
            '\n' | '\r' => {
                if !out.ends_with('\n') { out.push('\n'); }
                i += 1;
            }
            '\t' => { out.push(' '); i += 1; }
            '\0' => { i += 1; } // 跳过 NUL
            _ => { out.push(c); i += 1; }
        }
    }
    out.lines()
        .map(str::trim)
        .filter(|l| !l.is_empty())
        .collect::<Vec<_>>()
        .join("\n")
}

// ============================================================ 各平台实现

/// B站：通过公开 API 获取视频信息。
async fn fetch_bilibili(client: &reqwest::Client, url: &str) -> Option<String> {
    // 从 URL 提取 BV 号
    let bv = extract_bvid(url)?;
    let api = format!("https://api.bilibili.com/x/web-interface/view?bvid={bv}");
    let json = fetch_json(client, &api).await?;
    let code = jstr(&json, &["code"]);
    if code != "0" {
        return None;
    }
    let title = jstr(&json, &["data", "title"]);
    let desc = jstr(&json, &["data", "desc"]);
    let owner = jstr(&json, &["data", "owner", "name"]);
    let stat = json.get("data")?.get("stat")?;
    let view = stat.get("view").and_then(|v| v.as_u64()).unwrap_or(0);
    let like = stat.get("like").and_then(|v| v.as_u64()).unwrap_or(0);
    let reply = stat.get("reply").and_then(|v| v.as_u64()).unwrap_or(0);
    let pubdate = stat.get("pubdate").and_then(|v| v.as_u64()).unwrap_or(0);
    Some(format!(
        "标题: {title}\nUP主: {owner}\n简介: {desc}\n播放: {view} | 点赞: {like} | 评论: {reply}\n发布时间: {}",
        format_timestamp(pubdate)
    ))
}

/// 从 B站 URL 提取 BV 号。
fn extract_bvid(url: &str) -> Option<String> {
    let u = url.to_ascii_uppercase();
    let bv = u.find("BV")?;
    let after = &u[bv + 2..];
    let end = after.find('?').unwrap_or(after.find('/').unwrap_or(after.find('#').unwrap_or(after.len())));
    let bv_id = format!("BV{}", &after[..end.min(12)]);
    if bv_id.len() >= 10 {
        Some(bv_id)
    } else {
        None
    }
}

/// 抖音：提取分享链接中的视频数据。
async fn fetch_douyin(client: &reqwest::Client, url: &str) -> Option<String> {
    // 尝试从 URL 中提取视频 ID
    let video_id = extract_douyin_id(url)?;
    // 移动端分享页
    let share_url = format!("https://www.iesdouyin.com/share/video/{video_id}");
    let html = fetch_text(client, &share_url).await?;
    // 尝试提取 _ROUTER_DATA 或 RENDER_DATA
    let json_text = extract_json_block(&html, &["_ROUTER_DATA", "RENDER_DATA"])?;
    let json = serde_json::from_str::<Value>(&json_text).ok()?;
    let title = jstr(&json, &["loaderData", "video_(id)/page", "videoInfoRes", "item_list", "0", "desc"])
        .to_string();
    if title.is_empty() {
        let desc = extract_meta(&html, "description");
        return if desc.is_empty() {
            None
        } else {
            Some(format!("标题: {desc}"))
        };
    }
    Some(format!("标题: {title}\n来源: {url}"))
}

/// 从抖音 URL 提取视频 ID。
fn extract_douyin_id(url: &str) -> Option<String> {
    let u = url.to_ascii_lowercase();
    if let Some(pos) = u.find("/video/") {
        let after = &u[pos + 7..];
        let end = after.find('?').unwrap_or(after.find('&').unwrap_or(after.find('/').unwrap_or(after.len())));
        let id = &after[..end];
        if id.len() > 5 {
            return Some(id.to_string());
        }
    }
    // 短链格式：v.douyin.com/xxxxx
    if let Some(pos) = u.find("douyin.com/") {
        let after = &u[pos + 11..];
        let end = after.find('?').unwrap_or(after.len());
        let short = &after[..end];
        if short.len() > 3 {
            // 短链需要跟随重定向，但这里直接返回原 URL 让 web_fetch 处理
            return Some(short.to_string());
        }
    }
    None
}

/// 快手：抓取页面并提取元数据。
async fn fetch_kuaishou(client: &reqwest::Client, url: &str) -> Option<String> {
    let html = fetch_text(client, url).await?;
    let title = extract_title(&html);
    let desc = extract_meta(&html, "description");
    let ld = extract_jsonld(&html).map(jsonld_text);
    if title.is_empty() && desc.is_empty() && ld.is_none() {
        return None;
    }
    Some(format!(
        "标题: {}\n简介: {}\n{}",
        if title.is_empty() { "（未获取到）" } else { &title },
        if desc.is_empty() { "（未获取到）" } else { &desc },
        ld.unwrap_or_default()
    ))
}

/// 知乎：抓取问题/回答页面。
async fn fetch_zhihu(client: &reqwest::Client, url: &str) -> Option<String> {
    let html = fetch_text(client, url).await?;
    let title = extract_title(&html);
    let desc = extract_meta(&html, "description");
    // 尝试提取 initialData / initialState JSON
    let json_text = extract_json_block(&html, &["initialState", "initialData", "INITIAL_STATE"])?;
    let json = serde_json::from_str::<Value>(&json_text).ok()?;
    let content = extract_zhihu_content(&json);
    if title.is_empty() && content.is_empty() && desc.is_empty() {
        return None;
    }
    Some(format!(
        "标题: {}\n{}\n{}",
        if title.is_empty() { "（未获取到）" } else { &title },
        if !desc.is_empty() { format!("简介: {desc}\n") } else { String::new() },
        content
    ))
}

/// 从知乎 JSON 中提取内容。
fn extract_zhihu_content(json: &Value) -> String {
    // 尝试多种可能的路径
    let paths = [
        &["data", "answer", "content"] as &[&str],
        &["data", "content"] as &[&str],
        &["answer", "content"] as &[&str],
        &["data", "detail", "content"] as &[&str],
    ];
    for path in &paths {
        let s = jstr(json, path);
        if !s.is_empty() {
            return simple_html_to_text(s);
        }
    }
    String::new()
}

/// 百度贴吧：抓取帖子页面。
async fn fetch_tieba(client: &reqwest::Client, url: &str) -> Option<String> {
    let html = fetch_text(client, url).await?;
    let title = extract_title(&html);
    let desc = extract_meta(&html, "description");
    // 提取帖子内容：寻找 pclass="frs_page_content" 的 div
    let content = extract_div_by_class(&html, "frs_page_content");
    if title.is_empty() && content.is_empty() {
        return None;
    }
    Some(format!(
        "标题: {}\n{}\n{}",
        if title.is_empty() { "（未获取到）" } else { &title },
        if !desc.is_empty() { format!("简介: {desc}\n") } else { String::new() },
        if content.is_empty() { String::new() } else { format!("内容: {content}") }
    ))
}

/// 从 HTML 中提取指定 class 的 div 内容（简易实现）。
fn extract_div_by_class(html: &str, class: &str) -> String {
    let marker = format!(r#"class="{}""#, class);
    if let Some(pos) = html.find(&marker) {
        let after = &html[pos + marker.len()..];
        let start = after.find('>').unwrap_or(0) + 1;
        let content_start = &after[start..];
        // 找到下一个 </div>
        let end = content_start.find("</div>").unwrap_or(content_start.len());
        return simple_html_to_text(&content_start[..end]);
    }
    String::new()
}

/// X/Twitter：使用 syndication API 获取推文数据。
async fn fetch_twitter(client: &reqwest::Client, url: &str) -> Option<String> {
    // 从 URL 提取推文 ID
    let status_id = extract_tweet_id(url)?;
    let api = format!("https://cdn.syndication.twimg.com/tweet-result?id={status_id}&lang=en");
    let json = fetch_json(client, &api).await?;
    let text = jstr(&json, &["text"]);
    let user = jstr(&json, &["user", "name"]);
    let screen_name = jstr(&json, &["user", "screen_name"]);
    let created = jstr(&json, &["created_at"]);
    let retweets = json.get("retweet_count").and_then(|v| v.as_u64()).unwrap_or(0);
    let likes = json.get("favorite_count").and_then(|v| v.as_u64()).unwrap_or(0);
    if text.is_empty() {
        return None;
    }
    Some(format!(
        "作者: @{} ({user})\n时间: {created}\n转推: {retweets} | 点赞: {likes}\n内容: {text}",
        screen_name
    ))
}

/// 从 X/Twitter URL 提取推文 ID。
fn extract_tweet_id(url: &str) -> Option<String> {
    let u = url.to_ascii_lowercase();
    let marker = "/status/";
    let pos = u.find(marker)?;
    let after = &u[pos + 8..];
    let end = after.find('?').unwrap_or(after.find('/').unwrap_or(after.len()));
    let id = &after[..end];
    if id.len() > 5 && id.chars().all(|c| c.is_ascii_digit()) {
        Some(id.to_string())
    } else {
        None
    }
}

/// YouTube：使用 oEmbed API 获取视频信息。
async fn fetch_youtube(client: &reqwest::Client, url: &str) -> Option<String> {
    let api = format!("https://www.youtube.com/oembed?url={}&format=json", url);
    let json = fetch_json(client, &api).await?;
    let title = jstr(&json, &["title"]);
    let author = jstr(&json, &["author_name"]);
    if title.is_empty() {
        return None;
    }
    Some(format!("标题: {title}\n作者: {author}\n来源: YouTube"))
}

/// 微博：使用 m.weibo.cn API。
async fn fetch_weibo(client: &reqwest::Client, url: &str) -> Option<String> {
    let html = fetch_text(client, url).await?;
    let title = extract_title(&html);
    let desc = extract_meta(&html, "description");
    // 尝试提取 $render_data
    let json_text = extract_json_block(&html, &["render_data", "$render_data"])?;
    let json = serde_json::from_str::<Value>(&json_text).ok()?;
    let content = extract_weibo_content(&json);
    if title.is_empty() && content.is_empty() {
        return None;
    }
    Some(format!(
        "标题: {}\n{}\n{}",
        if title.is_empty() { "（未获取到）" } else { &title },
        if !desc.is_empty() { format!("简介: {desc}\n") } else { String::new() },
        content
    ))
}

/// 从微博 JSON 中提取内容。
fn extract_weibo_content(json: &Value) -> String {
    // 微博的数据结构较复杂，尝试多种路径
    let paths = [
        &["data", "status", "text"] as &[&str],
        &["data", "status", "text_raw"] as &[&str],
        &["data", "list", "0", "text"] as &[&str],
    ];
    for path in &paths {
        let s = jstr(json, path);
        if !s.is_empty() {
            return simple_html_to_text(s);
        }
    }
    String::new()
}

/// 今日头条：抓取文章页面。
async fn fetch_toutiao(client: &reqwest::Client, url: &str) -> Option<String> {
    let html = fetch_text(client, url).await?;
    let title = extract_title(&html);
    let desc = extract_meta(&html, "description");
    let ld = extract_jsonld(&html).map(jsonld_text);
    if title.is_empty() && desc.is_empty() && ld.is_none() {
        return None;
    }
    Some(format!(
        "标题: {}\n简介: {}\n{}",
        if title.is_empty() { "（未获取到）" } else { &title },
        if desc.is_empty() { "（未获取到）" } else { &desc },
        ld.unwrap_or_default()
    ))
}

/// 微信公众号：抓取文章页面。
async fn fetch_wechat(client: &reqwest::Client, url: &str) -> Option<String> {
    let html = fetch_text(client, url).await?;
    let title = extract_title(&html);
    let desc = extract_meta(&html, "description");
    // 提取正文：寻找 id="js_content" 的 div
    let content = extract_div_by_id(&html, "js_content");
    if title.is_empty() && content.is_empty() {
        return None;
    }
    Some(format!(
        "标题: {}\n{}\n{}",
        if title.is_empty() { "（未获取到）" } else { &title },
        if !desc.is_empty() { format!("简介: {desc}\n") } else { String::new() },
        if content.is_empty() { String::new() } else { format!("正文: {content}") }
    ))
}

/// 从 HTML 中提取指定 id 的 div 内容。
fn extract_div_by_id(html: &str, id: &str) -> String {
    let marker = format!(r#"id="{}""#, id);
    if let Some(pos) = html.find(&marker) {
        let after = &html[pos + marker.len()..];
        let start = after.find('>').unwrap_or(0) + 1;
        let content_start = &after[start..];
        let end = content_start.find("</div>").unwrap_or(content_start.len());
        return simple_html_to_text(&content_start[..end]);
    }
    String::new()
}

/// 小红书：抓取笔记页面。
async fn fetch_xiaohongshu(client: &reqwest::Client, url: &str) -> Option<String> {
    let html = fetch_text(client, url).await?;
    let title = extract_title(&html);
    let desc = extract_meta(&html, "description");
    let ld = extract_jsonld(&html).map(jsonld_text);
    if title.is_empty() && desc.is_empty() && ld.is_none() {
        return None;
    }
    Some(format!(
        "标题: {}\n简介: {}\n{}",
        if title.is_empty() { "（未获取到）" } else { &title },
        if desc.is_empty() { "（未获取到）" } else { &desc },
        ld.unwrap_or_default()
    ))
}

/// 网易新闻：抓取文章页面。
async fn fetch_net_easy(client: &reqwest::Client, url: &str) -> Option<String> {
    fetch_generic_article(client, url).await
}

/// 新浪新闻：抓取文章页面。
async fn fetch_sina(client: &reqwest::Client, url: &str) -> Option<String> {
    fetch_generic_article(client, url).await
}

/// 澎湃新闻：抓取文章页面。
async fn fetch_the_paper(client: &reqwest::Client, url: &str) -> Option<String> {
    fetch_generic_article(client, url).await
}

/// 虎嗅：抓取文章页面。
async fn fetch_huxiu(client: &reqwest::Client, url: &str) -> Option<String> {
    fetch_generic_article(client, url).await
}

/// 36氪：抓取文章页面。
async fn fetch_kr36(client: &reqwest::Client, url: &str) -> Option<String> {
    fetch_generic_article(client, url).await
}

/// 少数派：抓取文章页面。
async fn fetch_sspai(client: &reqwest::Client, url: &str) -> Option<String> {
    fetch_generic_article(client, url).await
}

/// 掘金：抓取文章页面。
async fn fetch_juejin(client: &reqwest::Client, url: &str) -> Option<String> {
    fetch_generic_article(client, url).await
}

/// SegmentFault：抓取文章页面。
async fn fetch_segmentfault(client: &reqwest::Client, url: &str) -> Option<String> {
    fetch_generic_article(client, url).await
}

/// V2EX：抓取主题页面。
async fn fetch_v2ex(client: &reqwest::Client, url: &str) -> Option<String> {
    fetch_generic_article(client, url).await
}

/// Hacker News：使用 API。
async fn fetch_hackernews(client: &reqwest::Client, url: &str) -> Option<String> {
    // 从 URL 提取 item ID
    let u = url.to_ascii_lowercase();
    let item_id = if let Some(pos) = u.find("/item?id=") {
        let after = &u[pos + 8..];
        let end = after.find('&').unwrap_or(after.len());
        after[..end].to_string()
    } else if u.contains("news.ycombinator.com/item") {
        // 尝试用 web_fetch 直接抓取
        return fetch_generic_article(client, url).await;
    } else {
        return fetch_generic_article(client, url).await;
    };
    let api = format!("https://hacker-news.firebaseio.com/v0/item/{item_id}.json");
    let json = fetch_json(client, &api).await?;
    let title = jstr(&json, &["title"]);
    let text = jstr(&json, &["text"]);
    let author = jstr(&json, &["by"]);
    let score = json.get("score").and_then(|v| v.as_u64()).unwrap_or(0);
    let descendants = json.get("descendants").and_then(|v| v.as_u64()).unwrap_or(0);
    let time = json.get("time").and_then(|v| v.as_u64()).unwrap_or(0);
    if title.is_empty() {
        return None;
    }
    Some(format!(
        "标题: {title}\n作者: {author}\n得分: {score} | 评论: {descendants}\n时间: {}\n内容: {}",
        format_timestamp(time),
        if text.is_empty() { url.to_string() } else { simple_html_to_text(text) }
    ))
}

/// Reddit：抓取帖子页面。
async fn fetch_reddit(client: &reqwest::Client, url: &str) -> Option<String> {
    fetch_generic_article(client, url).await
}

/// Medium：抓取文章页面。
async fn fetch_medium(client: &reqwest::Client, url: &str) -> Option<String> {
    fetch_generic_article(client, url).await
}

/// GitHub：抓取仓库/Issue/PR 页面。
async fn fetch_github(client: &reqwest::Client, url: &str) -> Option<String> {
    // 尝试使用 GitHub API
    let u = url.to_ascii_lowercase();
    if u.contains("github.com/") {
        let parts: Vec<&str> = u.split('/').collect();
        if parts.len() >= 3 {
            let owner = parts[2];
            let repo = parts[3];
            let api = format!("https://api.github.com/repos/{owner}/{repo}");
            if let Some(json) = fetch_json(client, &api).await {
                let name = jstr(&json, &["full_name"]);
                let desc = jstr(&json, &["description"]);
                let stars = json.get("stargazers_count").and_then(|v| v.as_u64()).unwrap_or(0);
                let forks = json.get("forks_count").and_then(|v| v.as_u64()).unwrap_or(0);
                let lang = jstr(&json, &["language"]);
                let updated = jstr(&json, &["updated_at"]);
                return Some(format!(
                    "仓库: {name}\n描述: {desc}\nStars: {stars} | Forks: {forks}\n语言: {lang}\n更新时间: {updated}"
                ));
            }
        }
    }
    fetch_generic_article(client, url).await
}

/// Stack Overflow：抓取问题页面。
async fn fetch_stackoverflow(client: &reqwest::Client, url: &str) -> Option<String> {
    fetch_generic_article(client, url).await
}

/// Wikipedia：使用 API。
async fn fetch_wikipedia(client: &reqwest::Client, url: &str) -> Option<String> {
    // 尝试从 URL 提取页面标题
    let u = url.to_ascii_lowercase();
    let title = if let Some(pos) = u.find("/wiki/") {
        let after = &u[pos + 6..];
        let end = after.find('?').unwrap_or(after.find('#').unwrap_or(after.len()));
        after[..end].replace('-', " ")
    } else {
        return fetch_generic_article(client, url).await;
    };
    let api = format!(
        "https://zh.wikipedia.org/api/rest_v1/page/summary/{}",
        title.replace(' ', "%20")
    );
    let json = fetch_json(client, &api).await?;
    let extract = jstr(&json, &["extract"]);
    let desc = jstr(&json, &["description"]);
    if extract.is_empty() {
        return None;
    }
    Some(format!(
        "标题: {title}\n简介: {desc}\n摘要: {extract}"
    ))
}

/// Facebook：抓取公开页面。
async fn fetch_facebook(client: &reqwest::Client, url: &str) -> Option<String> {
    fetch_generic_article(client, url).await
}

/// Instagram：抓取公开帖子。
async fn fetch_instagram(client: &reqwest::Client, url: &str) -> Option<String> {
    fetch_generic_article(client, url).await
}

/// Telegram：抓取公开频道。
async fn fetch_telegram(client: &reqwest::Client, url: &str) -> Option<String> {
    fetch_generic_article(client, url).await
}

/// Discord：抓取公开服务器/频道。
async fn fetch_discord(client: &reqwest::Client, url: &str) -> Option<String> {
    fetch_generic_article(client, url).await
}

/// 通用文章抓取：提取标题 + meta description + JSON-LD + 正文。
async fn fetch_generic_article(client: &reqwest::Client, url: &str) -> Option<String> {
    let html = fetch_text(client, url).await?;
    let title = extract_title(&html);
    let desc = extract_meta(&html, "description");
    let ld = extract_jsonld(&html).map(jsonld_text);
    // 尝试提取正文：寻找 article / content / post-content 等 div
    let content = [
        extract_div_by_class(&html, "article-content"),
        extract_div_by_class(&html, "post-content"),
        extract_div_by_class(&html, "entry-content"),
        extract_div_by_class(&html, "article-body"),
        extract_div_by_id(&html, "js_content"),
    ]
    .into_iter()
    .find(|s| !s.is_empty());
    if title.is_empty() && desc.is_empty() && ld.is_none() && content.is_none() {
        // 最后兜底：直接提取全文
        let text = simple_html_to_text(&html);
        if text.len() < 50 {
            return None;
        }
        return Some(text);
    }
    let mut result = String::new();
    if !title.is_empty() {
        result.push_str(&format!("标题: {title}\n"));
    }
    if !desc.is_empty() {
        result.push_str(&format!("简介: {desc}\n"));
    }
    if let Some(ld) = ld {
        if !ld.is_empty() {
            result.push_str(&format!("{ld}\n"));
        }
    }
    if let Some(content) = content {
        if !content.is_empty() {
            result.push_str(&format!("正文: {content}"));
        }
    }
    Some(result)
}

/// 通用抓取兜底：直接抓取并提取文本。
async fn fetch_generic(client: &reqwest::Client, url: &str) -> Option<String> {
    let html = fetch_text(client, url).await?;
    let text = simple_html_to_text(&html);
    if text.len() < 20 {
        return None;
    }
    Some(text)
}

// ============================================================ 工具函数

/// 从 HTML 中提取指定变量名的 JSON 块。
fn extract_json_block(html: &str, names: &[&str]) -> Option<String> {
    for name in names {
        let marker = format!("{name} = ");
        if let Some(pos) = html.find(&marker) {
            let after = &html[pos + marker.len()..];
            // 找到 JSON 对象的开始 { 或 [
            let start = after.find('{').or_else(|| after.find('['))?;
            let content_start = &after[start..];
            // 找到匹配的结束括号
            let end = find_matching_bracket(content_start)?;
            return Some(content_start[..=end].to_string());
        }
    }
    None
}

/// 找到匹配的结束括号位置。
fn find_matching_bracket(s: &str) -> Option<usize> {
    let bytes = s.as_bytes();
    let start_char = *bytes.first()?;
    let start = if start_char == b'{' { b'{' } else { b'[' };
    let end = if start_char == b'{' { b'}' } else { b']' };
    let mut depth = 0i32;
    let mut in_string = false;
    let mut escaped = false;
    for (i, &b) in bytes.iter().enumerate() {
        if escaped {
            escaped = false;
            continue;
        }
        if b == b'\\' && in_string {
            escaped = true;
            continue;
        }
        if b == b'"' {
            in_string = !in_string;
            continue;
        }
        if in_string {
            continue;
        }
        if b == start {
            depth += 1;
        } else if b == end {
            depth -= 1;
            if depth == 0 {
                return Some(i);
            }
        }
    }
    None
}

/// Unix 时间戳转可读时间。
fn format_timestamp(ts: u64) -> String {
    if ts == 0 {
        return "未知".to_string();
    }
    let secs = ts;
    // 简易格式化：年-月-日
    let days = secs / 86400;
    let hours = (secs % 86400) / 3600;
    let minutes = (secs % 3600) / 60;
    // 粗略日期计算
    let year = 1970 + (days / 365) as i64;
    let day_of_year = days % 365;
    format!("{year}-{day_of_year:03}-{hours:02}:{minutes:02}")
}

// ============================================================ 统一入口

/// 抓取任意 URL 的内容，返回结构化文本。
/// 内部检测平台、调用对应 fetcher、带缓存和重试。
pub async fn media_fetch(url: &str) -> String {
    // 检查缓存
    if let Some(cached) = cache_get(url) {
        return cached;
    }

    let platform = detect_platform(url);
    let seed = url.len() as u64;
    let client = match build_client(seed) {
        Ok(c) => c,
        Err(e) => return format!("错误: {e}"),
    };

    // 最多重试 2 次
    let mut last_err = String::new();
    for attempt in 0..3u32 {
        let result = fetch_by_platform(&client, platform, url).await;
        if let Some(content) = result {
            if content.len() > 100 {
                cache_put(url, content.clone());
                return format!("[来源: {} | {}]\n{}", platform_name(platform), url, content);
            }
            last_err = content;
        } else {
            last_err = format!("第 {} 次尝试失败", attempt + 1);
        }
        // 重试前等待（避免被限流）
        if attempt < 2 {
            tokio::time::sleep(Duration::from_millis(500 * (attempt as u64 + 1))).await;
        }
    }

    // 所有平台都失败，尝试通用抓取
    if let Some(generic) = fetch_generic(&client, url).await {
        cache_put(url, generic.clone());
        return format!("[来源: 网页 | {}]\n{}", url, generic);
    }

    format!("错误: 无法获取内容（{last_err}）")
}

/// 根据平台调用对应的 fetcher。
async fn fetch_by_platform(client: &reqwest::Client, platform: Platform, url: &str) -> Option<String> {
    match platform {
        Platform::Bilibili => fetch_bilibili(client, url).await,
        Platform::Douyin => fetch_douyin(client, url).await,
        Platform::Kuaishou => fetch_kuaishou(client, url).await,
        Platform::Zhihu => fetch_zhihu(client, url).await,
        Platform::Tieba => fetch_tieba(client, url).await,
        Platform::Twitter => fetch_twitter(client, url).await,
        Platform::YouTube => fetch_youtube(client, url).await,
        Platform::Weibo => fetch_weibo(client, url).await,
        Platform::Toutiao => fetch_toutiao(client, url).await,
        Platform::WeChat => fetch_wechat(client, url).await,
        Platform::Xiaohongshu => fetch_xiaohongshu(client, url).await,
        Platform::NetEase => fetch_net_easy(client, url).await,
        Platform::Sina => fetch_sina(client, url).await,
        Platform::ThePaper => fetch_the_paper(client, url).await,
        Platform::Huxiu => fetch_huxiu(client, url).await,
        Platform::Kr36 => fetch_kr36(client, url).await,
        Platform::Sspai => fetch_sspai(client, url).await,
        Platform::Juejin => fetch_juejin(client, url).await,
        Platform::SegmentFault => fetch_segmentfault(client, url).await,
        Platform::V2ex => fetch_v2ex(client, url).await,
        Platform::HackerNews => fetch_hackernews(client, url).await,
        Platform::Reddit => fetch_reddit(client, url).await,
        Platform::Medium => fetch_medium(client, url).await,
        Platform::Github => fetch_github(client, url).await,
        Platform::StackOverflow => fetch_stackoverflow(client, url).await,
        Platform::Wikipedia => fetch_wikipedia(client, url).await,
        Platform::Facebook => fetch_facebook(client, url).await,
        Platform::Instagram => fetch_instagram(client, url).await,
        Platform::Telegram => fetch_telegram(client, url).await,
        Platform::Discord => fetch_discord(client, url).await,
        Platform::Generic => fetch_generic_article(client, url).await,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_platform_detection() {
        assert_eq!(detect_platform("https://www.bilibili.com/video/BV1xx411c7mD"), Platform::Bilibili);
        assert_eq!(detect_platform("https://www.douyin.com/video/123456"), Platform::Douyin);
        assert_eq!(detect_platform("https://www.kuaishou.com/short-video/abc"), Platform::Kuaishou);
        assert_eq!(detect_platform("https://www.zhihu.com/question/123"), Platform::Zhihu);
        assert_eq!(detect_platform("https://tieba.baidu.com/p/123456"), Platform::Tieba);
        assert_eq!(detect_platform("https://x.com/user/status/123456"), Platform::Twitter);
        assert_eq!(detect_platform("https://www.youtube.com/watch?v=abc"), Platform::YouTube);
        assert_eq!(detect_platform("https://weibo.com/123456"), Platform::Weibo);
        assert_eq!(detect_platform("https://mp.weixin.qq.com/s/abc"), Platform::WeChat);
        assert_eq!(detect_platform("https://www.xiaohongshu.com/explore/abc"), Platform::Xiaohongshu);
        assert_eq!(detect_platform("https://example.com/article"), Platform::Generic);
    }

    #[test]
    fn test_platform_name() {
        assert_eq!(platform_name(Platform::Bilibili), "Bilibili");
        assert_eq!(platform_name(Platform::Douyin), "抖音");
        assert_eq!(platform_name(Platform::Generic), "网页");
    }

    #[test]
    fn test_extract_bvid() {
        assert_eq!(
            extract_bvid("https://www.bilibili.com/video/BV1xx411c7mD"),
            Some("BV1XX411C7MD".to_string())
        );
        assert_eq!(
            extract_bvid("https://www.bilibili.com/video/BV1xx411c7mD?spm=abc"),
            Some("BV1XX411C7MD".to_string())
        );
    }

    #[test]
    fn test_extract_tweet_id() {
        assert_eq!(
            extract_tweet_id("https://x.com/user/status/1234567890"),
            Some("1234567890".to_string())
        );
        assert_eq!(
            extract_tweet_id("https://twitter.com/user/status/1234567890?ref=xyz"),
            Some("1234567890".to_string())
        );
    }

    #[test]
    fn test_extract_title() {
        let html = r#"<html><head><title>Test Title</title></head><body></body></html>"#;
        assert_eq!(extract_title(html), "Test Title");
    }

    #[test]
    fn test_extract_meta() {
        let html = r#"<meta name="description" content="Test desc">"#;
        assert_eq!(extract_meta(html, "description"), "Test desc");
    }

    #[test]
    fn test_find_matching_bracket() {
        assert_eq!(find_matching_bracket(r#"[1, 2, {"a": 1}]"#), Some(16));
        assert_eq!(find_matching_bracket(r#"{"a": [1, 2], "b": 3}"#), Some(19));
        assert!(find_matching_bracket("{unclosed").is_none());
    }

    #[test]
    fn test_jsonld_text() {
        let v = json!({"description": "Hello world"});
        assert_eq!(jsonld_text(&v), "Hello world");
        let v = json!({"@graph": [{"articleBody": "Body text"}]});
        assert_eq!(jsonld_text(&v), "Body text");
    }
}
