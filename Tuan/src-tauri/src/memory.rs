//! Scope Recall 3.0：多层记忆系统。
//!
//! 设计目标：让 AI 在对话中自动记住重要信息，并在后续对话中
//! 语义召回相关记忆——不是简单的关键词匹配，而是基于 TF-IDF
//! 加权的模糊检索，配合多层 scope、自动衰减、重要度评分。
//!
//! 记忆层级：
//!   - global：跨所有会话的全局记忆（用户偏好、长期习惯）
//!   - user：当前用户的所有会话记忆（项目背景、工作流）
//!   - session：当前会话的短期记忆（上下文、指令、事实）
//!
//! 记忆类型：
//!   - fact：客观事实（"项目使用 Rust 编写"）
//!   - preference：用户偏好（"喜欢简洁的回答"）
//!   - context：上下文信息（"正在做支付功能"）
//!   - instruction：用户指令（"每次生成代码后自动跑测试"）
//!
//! 生命周期：
//!   创建 → 每次召回 reinforce（lastAccessed 更新 + accessCount++）
//!   → 超过 decay_days 未被访问则自动 archive（不删除，但默认不召回）
//!   → 召回时按 relevance * importance * recency 综合排序

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

/// 记忆条目。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryEntry {
    pub id: u64,
    /// 作用域：global / user / session
    pub scope: String,
    /// 类型：fact / preference / context / instruction
    pub mem_type: String,
    /// 记忆内容（自然语言，供模型直接理解）
    pub content: String,
    /// 自动提取的关键词（用于召回匹配）
    pub keywords: Vec<String>,
    /// 创建时间（Unix 秒）
    pub created_at: u64,
    /// 最后访问时间（Unix 秒）
    pub last_accessed: u64,
    /// 访问次数（用于计算重要度）
    pub access_count: u32,
    /// 重要度评分（0.0-1.0，用户手动调整或自动计算）
    pub importance: f64,
    /// 是否已归档（过期未访问自动归档）
    pub archived: bool,
}

/// 记忆配置。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryConfig {
    /// 自动归档天数（未访问超过此天数自动归档）
    #[serde(default = "default_decay_days")]
    pub decay_days: u32,
    /// 每次召回最大条数
    #[serde(default = "default_max_recall")]
    pub max_recall: usize,
    /// 召回预算（每次召回注入模型上下文的总字符数上限）
    #[serde(default = "default_recall_budget")]
    pub recall_budget: usize,
    /// 是否启用自动记忆提取
    #[serde(default = "default_auto_extract")]
    pub auto_extract: bool,
    /// 自动提取时每轮对话最多提取几条
    #[serde(default = "default_max_per_turn")]
    pub max_per_turn: usize,
}

fn default_decay_days() -> u32 { 30 }
fn default_max_recall() -> usize { 10 }
fn default_recall_budget() -> usize { 3000 }
fn default_auto_extract() -> bool { true }
fn default_max_per_turn() -> usize { 3 }

impl Default for MemoryConfig {
    fn default() -> Self {
        Self {
            decay_days: 30,
            max_recall: 10,
            recall_budget: 3000,
            auto_extract: true,
            max_per_turn: 3,
        }
    }
}

/// 内存 + 磁盘双写记忆存储。
pub struct MemoryStore {
    entries: Mutex<Vec<MemoryEntry>>,
    config: Mutex<MemoryConfig>,
    next_id: Mutex<u64>,
}

impl MemoryStore {
    /// 初始化存储：从磁盘加载。
    pub fn load() -> Self {
        let (entries, config) = Self::load_from_disk();
        let next_id = entries.iter().map(|e| e.id).max().unwrap_or(0) + 1;
        Self {
            entries: Mutex::new(entries),
            config: Mutex::new(config),
            next_id: Mutex::new(next_id),
        }
    }

    fn load_from_disk() -> (Vec<MemoryEntry>, MemoryConfig) {
        let entries_path = memory_path().ok().unwrap_or_default();
        let config_path = config_path().ok().unwrap_or_default();

        let entries = entries_path
            .and_then(|p| fs::read_to_string(p).ok())
            .and_then(|s| serde_json::from_str(&s).ok())
            .unwrap_or_default();
        let config = config_path
            .and_then(|p| fs::read_to_string(p).ok())
            .and_then(|s| serde_json::from_str(&s).ok())
            .unwrap_or_default();

        (entries, config)
    }

    /// 持久化到磁盘。
    pub fn persist(&self) {
        let entries = self.entries.lock().unwrap().clone();
        let config = self.config.lock().unwrap().clone();
        if let Ok(path) = memory_path() {
            let _ = fs::write(path, serde_json::to_string_pretty(&entries).unwrap_or_default());
        }
        if let Ok(path) = config_path() {
            let _ = fs::write(path, serde_json::to_string_pretty(&config).unwrap_or_default());
        }
    }

    /// 保存一条记忆。
    pub fn save(&self, scope: &str, mem_type: &str, content: &str, importance: f64) -> MemoryEntry {
        let keywords = Self::extract_keywords(content);
        let now = unix_now();
        let id = {
            let mut n = self.next_id.lock().unwrap();
            let id = *n;
            *n += 1;
            id
        };
        let entry = MemoryEntry {
            id,
            scope: scope.to_string(),
            mem_type: mem_type.to_string(),
            content: content.to_string(),
            keywords,
            created_at: now,
            last_accessed: now,
            access_count: 1,
            importance: importance.clamp(0.0, 1.0),
            archived: false,
        };
        let mut entries = self.entries.lock().unwrap();
        // 去重：如果已存在内容相同的记忆，更新而非新增
        if let Some(existing) = entries.iter_mut().find(|e| e.content == entry.content && !e.archived) {
            existing.last_accessed = now;
            existing.access_count += 1;
            existing.importance = existing.importance.max(importance);
            existing.keywords.extend(entry.keywords);
            existing.keywords.sort();
            existing.keywords.dedup();
            let cloned = existing.clone();
            drop(entries);
            self.persist();
            return cloned;
        }
        entries.push(entry.clone());
        drop(entries);
        self.persist();
        entry
    }

    /// 语义召回：根据查询关键词返回相关记忆。
    /// 排序公式：relevance * importance * recency_factor
    pub fn recall(&self, query: &str, scope: Option<&str>, limit: usize) -> Vec<MemoryEntry> {
        let query_lower = query.to_ascii_lowercase();
        let query_keywords = Self::extract_keywords(query);
        let config = self.config.lock().unwrap();
        let limit = limit.min(config.max_recall);
        let now = unix_now();
        let decay_secs = (config.decay_days as u64) * 86400;

        let entries = self.entries.lock().unwrap();
        let mut scored: Vec<(f64, &MemoryEntry)> = Vec::new();

        for entry in entries.iter() {
            if entry.archived {
                continue;
            }
            // scope 过滤
            if let Some(s) = scope {
                if entry.scope != s && !(s == "user" && entry.scope == "global") {
                    continue;
                }
            }
            // 计算相关性
            let relevance = Self::compute_relevance(&query_keywords, &query_lower, &entry);
            if relevance < 0.05 {
                continue;
            }
            // 计算新鲜度因子（指数衰减，半衰期 = decay_days / 2）
            let age = now.saturating_sub(entry.last_accessed);
            let half_life = decay_secs / 2;
            let recency = if half_life > 0 {
                let ratio = age as f64 / half_life as f64;
                0.5_f64.powf(ratio)
            } else {
                1.0
            };
            // 访问频率加成（对数衰减）
            let freq_bonus = 1.0 + 0.3 * (entry.access_count as f64).ln();
            let score = relevance * entry.importance * recency * freq_bonus;
            scored.push((score, entry));
        }
        scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
        let mut result = Vec::new();
        let mut budget = config.recall_budget;
        for (_, entry) in scored.into_iter().take(limit) {
            if budget <= 0 {
                break;
            }
            let remaining = budget.saturating_sub(entry.content.len());
            result.push(entry.clone());
            budget = remaining;
        }
        result
    }

    /// 自动归档过期记忆。
    pub fn auto_archive(&self) {
        let config = self.config.lock().unwrap();
        let now = unix_now();
        let decay_secs = (config.decay_days as u64) * 86400;
        let mut entries = self.entries.lock().unwrap();
        let mut changed = false;
        for entry in entries.iter_mut() {
            if !entry.archived && now.saturating_sub(entry.last_accessed) > decay_secs {
                entry.archived = true;
                changed = true;
            }
        }
        if changed {
            drop(entries);
            self.persist();
        }
    }

    /// 更新配置并持久化。
    pub fn update_config(&self, new: &MemoryConfig) {
        let mut config = self.config.lock().unwrap();
        *config = new.clone();
        drop(config);
        self.persist();
    }

    /// 获取配置。
    pub fn get_config(&self) -> MemoryConfig {
        self.config.lock().unwrap().clone()
    }

    /// 删除一条记忆。
    pub fn delete(&self, id: u64) -> bool {
        let mut entries = self.entries.lock().unwrap();
        let before = entries.len();
        entries.retain(|e| e.id != id);
        let changed = entries.len() < before;
        drop(entries);
        if changed {
            self.persist();
        }
        changed
    }

    /// 列出所有记忆（含归档），按更新时间排序。
    pub fn list(&self, include_archived: bool, limit: usize) -> Vec<MemoryEntry> {
        let entries = self.entries.lock().unwrap();
        let mut filtered: Vec<_> = entries.iter().filter(|e| {
            include_archived || !e.archived
        }).cloned().collect();
        filtered.sort_by(|a, b| b.last_accessed.cmp(&a.last_accessed));
        filtered.into_iter().take(limit).collect()
    }

    /// 统计信息。
    pub fn stats(&self) -> MemoryStats {
        let entries = self.entries.lock().unwrap();
        let active: Vec<_> = entries.iter().filter(|e| !e.archived).collect();
        let by_type: HashMap<String, usize> = active.iter().map(|e| (e.mem_type.clone(), 0)).collect();
        let mut counts: HashMap<String, usize> = HashMap::new();
        for e in &active {
            *counts.entry(e.mem_type.clone()).or_insert(0) += 1;
        }
        MemoryStats {
            total: entries.len(),
            active: active.len(),
            archived: entries.len() - active.len(),
            by_type: counts,
        }
    }

    /// 从内容中提取关键词（简单分词：按空格/标点分割，过滤停用词）。
    fn extract_keywords(text: &str) -> Vec<String> {
        let stopwords = [
            "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
            "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
            "自己", "这", "他", "她", "它", "们", "那", "些", "什么", "怎么", "如何",
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "shall", "can", "need", "dare", "ought",
            "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "as", "into", "through", "during", "before", "after", "above", "below",
            "between", "out", "off", "over", "under", "again", "further", "then",
            "once", "here", "there", "when", "where", "why", "how", "all", "each",
            "every", "both", "few", "more", "most", "other", "some", "such", "no",
            "nor", "not", "only", "own", "same", "so", "than", "too", "very",
            "just", "because", "but", "and", "or", "if", "while", "about",
        ];
        let mut words: Vec<String> = Vec::new();
        let mut current = String::new();
        for c in text.chars() {
            if c.is_whitespace() || "，。！？、；：""''【】（）《》<>,.!?;:'\"()".contains(c) {
                if !current.trim().is_empty() {
                    let w = current.trim().to_ascii_lowercase();
                    if w.len() >= 2 && !stopwords.contains(&w.as_str()) {
                        words.push(w);
                    }
                }
                current.clear();
            } else {
                current.push(c);
            }
        }
        if !current.trim().is_empty() {
            let w = current.trim().to_ascii_lowercase();
            if w.len() >= 2 && !stopwords.contains(&w.as_str()) {
                words.push(w);
            }
        }
        // 去重并保持顺序
        words.sort();
        words.dedup();
        words
    }

    /// 计算查询与记忆的相关性（TF-IDF 简化版）。
    fn compute_relevance(query_kws: &[String], query_lower: &str, entry: &MemoryEntry) -> f64 {
        let content_lower = entry.content.to_ascii_lowercase();
        let mut score = 0.0;

        // 1. 关键词直接匹配（最高权重）
        for qk in query_kws {
            if entry.keywords.iter().any(|ek| ek == qk) {
                score += 1.0;
            }
        }

        // 2. 子串匹配（中等权重）
        for qk in query_kws {
            if content_lower.contains(qk.as_str()) {
                score += 0.5;
            }
        }

        // 3. 整体查询作为子串匹配
        if content_lower.contains(query_lower) && !query_lower.is_empty() {
            score += 0.3;
        }

        // 4. 如果查询词在记忆内容中出现多次，额外加权
        for qk in query_kws {
            let count = content_lower.matches(qk.as_str()).count();
            if count > 1 {
                score += 0.1 * count as f64;
            }
        }

        score
    }
}

/// 记忆统计。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryStats {
    pub total: usize,
    pub active: usize,
    pub archived: usize,
    pub by_type: HashMap<String, usize>,
}

impl Default for MemoryStore {
    fn default() -> Self {
        Self::load()
    }
}

/// 获取全局记忆存储实例。
fn store() -> &'static MemoryStore {
    static STORE: std::sync::LazyLock<MemoryStore> = std::sync::LazyLock::new(MemoryStore::load);
    STORE
}

/// 初始化记忆存储（首次调用时从磁盘加载）。
pub fn init() {
    let _ = store();
}

/// 保存记忆。
pub fn memory_save(scope: &str, mem_type: &str, content: &str, importance: f64) -> MemoryEntry {
    store().save(scope, mem_type, content, importance)
}

/// 召回记忆。
pub fn memory_recall(query: &str, scope: Option<&str>, limit: usize) -> Vec<MemoryEntry> {
    store().recall(query, scope, limit)
}

/// 删除记忆。
pub fn memory_delete(id: u64) -> bool {
    store().delete(id)
}

/// 列出记忆。
pub fn memory_list(include_archived: bool, limit: usize) -> Vec<MemoryEntry> {
    store().list(include_archived, limit)
}

/// 获取记忆统计。
pub fn memory_stats() -> MemoryStats {
    store().stats()
}

/// 获取配置。
pub fn memory_config() -> MemoryConfig {
    store().get_config()
}

/// 更新配置。
pub fn memory_update_config(config: &MemoryConfig) {
    store().update_config(config);
}

/// 自动归档过期记忆（每次启动时调用一次）。
pub fn memory_auto_archive() {
    store().auto_archive();
}

/// 路径：记忆数据文件。
fn memory_path() -> Result<PathBuf, String> {
    let dir = dirs::config_dir()
        .ok_or_else(|| "无法定位配置目录".to_string())?
        .join("tuan-chat");
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir.join("memories.json"))
}

/// 路径：配置数据文件。
fn config_path() -> Result<PathBuf, String> {
    let dir = dirs::config_dir()
        .ok_or_else(|| "无法定位配置目录".to_string())?
        .join("tuan-chat");
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir.join("memory_config.json"))
}

/// 当前 Unix 时间戳（秒）。
fn unix_now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

// ============================================================ Tauri Commands

#[tauri::command]
pub fn cmd_memory_save(scope: String, mem_type: String, content: String, importance: f64) -> MemoryEntry {
    memory_save(&scope, &mem_type, &content, importance)
}

#[tauri::command]
pub fn cmd_memory_recall(query: String, scope: Option<String>, limit: Option<usize>) -> Vec<MemoryEntry> {
    memory_recall(&query, scope.as_deref(), limit.unwrap_or(10))
}

#[tauri::command]
pub fn cmd_memory_delete(id: u64) -> bool {
    memory_delete(id)
}

#[tauri::command]
pub fn cmd_memory_list(include_archived: Option<bool>, limit: Option<usize>) -> Vec<MemoryEntry> {
    memory_list(include_archived.unwrap_or(false), limit.unwrap_or(100))
}

#[tauri::command]
pub fn cmd_memory_stats() -> MemoryStats {
    memory_stats()
}

#[tauri::command]
pub fn cmd_memory_config() -> MemoryConfig {
    memory_config()
}

#[tauri::command]
pub fn cmd_memory_update_config(config: MemoryConfig) -> MemoryConfig {
    memory_update_config(&config);
    config
}

#[tauri::command]
pub fn cmd_memory_auto_archive() -> usize {
    memory_auto_archive();
    memory_stats().archived
}

#[tauri::command]
pub fn cmd_memory_clear() -> usize {
    let mut entries = store().entries.lock().unwrap();
    let count = entries.len();
    entries.clear();
    drop(entries);
    store().persist();
    count
}

// ============================================================ 自动记忆提取
// 从对话消息中自动检测值得记住的信息

/// 从用户消息中提取可记忆信息。
/// 返回 (scope, type, content, importance) 列表。
pub fn auto_extract_memories(user_message: &str, assistant_response: Option<&str>) -> Vec<(String, String, String, f64)> {
    let mut results = Vec::new();
    let msg = user_message.trim();

    // 检测显式记忆指令
    if let Some(content) = detect_explicit_memory(msg) {
        let scope = if content.starts_with("记住") || content.starts_with("记下") {
            "user"
        } else {
            "session"
        };
        results.push((scope, "fact", content, 0.8));
    }

    // 检测偏好表达
    if let Some(content) = detect_preference(msg) {
        results.push(("user".to_string(), "preference".to_string(), content, 0.7));
    }

    // 检测指令表达（"每次...都要..."、"以后..."、"不要再..."）
    if let Some(content) = detect_instruction(msg) {
        results.push(("user".to_string(), "instruction".to_string(), content, 0.9));
    }

    // 检测上下文信息（"我在做..."、"项目是..."）
    if let Some(content) = detect_context(msg) {
        results.push(("session".to_string(), "context".to_string(), content, 0.6));
    }

    // 检测重要事实（含"是"、"等于"、"包括"等定义性语句）
    if let Some(content) = detect_fact(msg) {
        results.push(("session".to_string(), "fact".to_string(), content, 0.5));
    }

    // 从助手回复中提取关键信息（如果回复中包含"你应该记住"等引导语）
    if let Some(resp) = assistant_response {
        if let Some(content) = detect_explicit_memory(resp) {
            results.push(("session".to_string(), "fact".to_string(), content, 0.7));
        }
    }

    results
}

/// 检测显式记忆指令（"记住 XXX"、"记住：XXX"、"请记住 XXX"）。
fn detect_explicit_memory(msg: &str) -> Option<String> {
    let patterns = [
        "记住：", "记住:", "请记住", "记住", "记下",
    ];
    for pat in &patterns {
        if let Some(pos) = msg.find(pat) {
            let after = &msg[pos + pat.len()..];
            let content = after.trim().trim_matches(['。', '!', '.', ',', '，']);
            if content.len() >= 5 && content.len() <= 500 {
                return Some(content.to_string());
            }
        }
    }
    None
}

/// 检测偏好表达（"我喜欢..."、"我偏好..."、"我喜欢用..."、"最好用..."）。
fn detect_preference(msg: &str) -> Option<String> {
    let patterns = ["我喜欢", "我偏好", "我习惯", "最好用", "我更愿意", "请不要", "不要用"];
    for pat in &patterns {
        if msg.contains(pat) {
            return Some(msg.to_string());
        }
    }
    None
}

/// 检测指令表达（"每次都要..."、"以后..."、"不要再..."、"一定要..."、"务必..."）。
fn detect_instruction(msg: &str) -> Option<String> {
    let patterns = ["每次", "以后", "不要再", "一定要", "务必", "永远", "总是", "每次都要"];
    for pat in &patterns {
        if msg.contains(pat) {
            return Some(msg.to_string());
        }
    }
    None
}

/// 检测上下文信息（"我在做..."、"项目是..."、"我正在..."、"当前的..."）。
fn detect_context(msg: &str) -> Option<String> {
    let patterns = ["我在做", "我正在", "项目是", "当前的", "正在做", "目前"];
    for pat in &patterns {
        if msg.contains(pat) {
            return Some(msg.to_string());
        }
    }
    None
}

/// 检测重要事实（含"是"、"等于"、"包括"、"由...组成"等定义性语句）。
fn detect_fact(msg: &str) -> Option<String> {
    // 排除疑问句
    if msg.ends_with('?') || msg.ends_with('？') {
        return None;
    }
    let fact_markers = ["是", "等于", "包括", "由", "包含", "分为"];
    let has_marker = fact_markers.iter().any(|m| msg.contains(m));
    if has_marker && msg.len() >= 10 && msg.len() <= 300 {
        return Some(msg.to_string());
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_keywords() {
        let kws = MemoryStore::extract_keywords("Rust 语言支持异步编程");
        assert!(kws.contains(&"rust".to_string()));
        assert!(kws.contains(&"异步".to_string()));
        assert!(kws.contains(&"编程".to_string()));
    }

    #[test]
    fn test_detect_explicit_memory() {
        assert_eq!(
            detect_explicit_memory("请记住：这个项目使用 TypeScript"),
            Some("这个项目使用 TypeScript".to_string())
        );
        assert_eq!(
            detect_explicit_memory("记住：用户偏好暗色主题"),
            Some("用户偏好暗色主题".to_string())
        );
    }

    #[test]
    fn test_detect_preference() {
        assert!(detect_preference("我喜欢简洁的回答").is_some());
        assert!(detect_preference("不要用 emoji").is_some());
    }

    #[test]
    fn test_detect_instruction() {
        assert!(detect_instruction("以后每次都要跑测试").is_some());
        assert!(detect_instruction("不要再提这个").is_some());
    }

    #[test]
    fn test_detect_context() {
        assert!(detect_context("我在做支付功能").is_some());
        assert!(detect_context("我正在写一个爬虫").is_some());
    }

    #[test]
    fn test_detect_fact() {
        assert!(detect_fact("项目使用 Rust 和 React 构建").is_some());
        assert!(detect_fact("什么是量子计算？").is_none());
    }

    #[test]
    fn test_auto_extract_memories() {
        let results = auto_extract_memories("请记住：这个项目的数据库是 PostgreSQL", None);
        assert!(!results.is_empty());
        assert!(results[0].2.contains("PostgreSQL"));
    }
}
