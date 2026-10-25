mod agent;
mod agent_tools;
mod engine;
mod engine_chat;
mod media;
mod memory;
mod net;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            net::chat_stream,
            net::probe_models,
            net::read_text_file,
            engine_chat::engine_chat_stream,
            engine_chat::engine_stop,
            engine_chat::engine_approve,
            engine_chat::check_engine,
            // Android 轻量 Agent：Rust 侧实现工具调用循环，不依赖本地 Python 引擎
            agent::agent_chat_stream,
            // Scope Recall 3.0：多层记忆系统
            memory::cmd_memory_save,
            memory::cmd_memory_recall,
            memory::cmd_memory_delete,
            memory::cmd_memory_list,
            memory::cmd_memory_stats,
            memory::cmd_memory_config,
            memory::cmd_memory_update_config,
            memory::cmd_memory_auto_archive,
            memory::cmd_memory_clear,
        ])
        .setup(|_app| {
            // 启动时归档过期记忆
            memory::cmd_memory_auto_archive();
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("启动 Tauri 应用失败");
}