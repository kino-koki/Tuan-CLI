mod agent;
mod agent_tools;
mod engine;
mod engine_chat;
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
        ])
        .setup(|_app| Ok(()))
        .run(tauri::generate_context!())
        .expect("启动 Tauri 应用失败");
}