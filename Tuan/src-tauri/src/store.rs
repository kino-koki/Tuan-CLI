//! JSON config persistence in the OS app-data directory.

use anyhow::Result;
use std::fs;
use std::path::PathBuf;

use crate::engine::Provider;

fn config_dir() -> Result<PathBuf> {
    let dir = dirs::config_dir()
        .ok_or_else(|| anyhow::anyhow!("无法定位配置目录"))?
        .join("tuan");
    fs::create_dir_all(&dir)?;
    Ok(dir)
}

fn providers_path() -> Result<PathBuf> {
    Ok(config_dir()?.join("providers.json"))
}

#[tauri::command]
pub fn load_providers() -> Vec<Provider> {
    providers_path()
        .ok()
        .and_then(|p| fs::read_to_string(p).ok())
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

#[tauri::command]
pub fn save_providers(list: Vec<Provider>) -> Result<(), String> {
    let p = providers_path().map_err(|e| e.to_string())?;
    fs::write(p, serde_json::to_string_pretty(&list).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())
}
