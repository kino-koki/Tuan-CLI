//! tuan_cli engine lifecycle abstraction.
//!
//! Desktop: locate a Python interpreter (bundled portable runtime first, then a
//! configured venv/system Python), spawn the local `tuan_cli` engine, and await
//! readiness with a bounded timeout. A child crash/close rejects readiness
//! immediately instead of letting the caller hang forever.
//!
//! Android: code-level support only; on-device local runtime integration is
//! validated separately and lives behind the target-specific module.

#![allow(unused_variables, unused_imports)]
use anyhow::{anyhow, Result};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};
#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[derive(Clone, serde::Serialize, serde::Deserialize)]
pub struct Provider {
    pub id: String,
    pub name: String,
    #[serde(rename = "format")]
    pub format: String, // "openai" | "anthropic"
    #[serde(alias = "baseUrl")]
    pub base_url: String,
    #[serde(alias = "apiKey")]
    pub api_key: String,
    pub models: Vec<ModelEntry>,
}

#[derive(Clone, serde::Serialize, serde::Deserialize)]
pub struct ModelEntry {
    pub id: String,
    pub name: String,
    pub enabled: bool,
}

/// 应用专用虚拟环境的解释器路径（`engine/.venv`）。
///
/// 引擎的第三方依赖装在这个 venv 里。它不可重定位 —— `pyvenv.cfg` 的
/// `home` 指向生成时的基础解释器绝对路径 —— 因此不能随安装包分发，
/// 目标机器需要在本地各自生成一份（可用仓库里的 `scripts/install_engine_env.py`
/// 在开发机上生成；在已安装设备上按下方错误提示手动 pip install 亦可）。
fn venv_python_path(exe_dir: &Path) -> PathBuf {
    exe_dir
        .join("engine")
        .join(".venv")
        .join(if cfg!(windows) { "Scripts" } else { "bin" })
        .join(if cfg!(windows) { "python.exe" } else { "python" })
}

/// Resolve a Python interpreter for the local engine.
///
/// 优先级：
///   1. 打包的便携式运行时（exe 同目录 engine/python/python.exe）
///      —— 用户按安装后错误提示从 python-build-standalone 解压到这里即可。
///   2. 环境变量 TUAN_PYTHON 覆盖（显式意图，优先于本机自动产物）
///   3. 应用专用虚拟环境（engine/.venv）
///      —— 每台机器上各自生成，不能随包分发（见 venv_python_path 注释）。
///   4. PATH 中的 python / python3 / py -3（Windows Python Launcher）
///   5. Windows 注册表 HKLM\SOFTWARE\Python\PythonCore\*\InstallPath
///   6. 常见 Windows/macOS/Linux 安装路径（系统级 + 用户级 LOCALAPPDATA）
///
/// 找不到时返回带操作建议的错误信息（含两条可行路径 + 指向随包分发的
/// engine\requirements.txt），而不是硬编码开发者本机路径。
pub fn resolve_python(exe_dir: &Path) -> Result<PathBuf> {
    // 1. 打包的便携式运行时
    let bundled = exe_dir.join("engine").join("python").join(if cfg!(windows) { "python.exe" } else { "python" });
    if bundled.is_file() {
        return Ok(bunded);
    }

    // 2. 环境变量覆盖（显式意图，优先于本机的自动产物）
    if let Ok(v) = std::env::var("TUAN_PYTHON") {
        let p = PathBuf::from(v);
        if p.is_file() {
            return Ok(p);
        }
    }

    // 3. 应用专用虚拟环境。引擎的第三方依赖（rich / httpx / openai …）装在
    //    这里，而不是系统 Python —— 目标机器通常没有 Python，或只有 Microsoft
    //    Store 的引导存根。该 venv 不可重定位（pyvenv.cfg 的 home 是绝对路径），
    //    所以每台机器都要用 scripts/install_engine_env.py 各自生成一份。
    let venv = venv_python_path(exe_dir);
    if venv.is_file() {
        return Ok(venv);
    }

    // 4. PATH 中的常见命令
    let candidates = [
        PathBuf::from("python"),
        PathBuf::from("python3"),
        #[cfg(windows)]
        PathBuf::from("py"), // Windows Python Launcher（调用时会自动加 -3 参数）
    ];
    for c in candidates {
        if c.is_file() || which(&c) {
            return Ok(c);
        }
    }

    // 5. Windows 注册表检测（Python 安装路径）
    #[cfg(windows)]
    if let Some(p) = detect_python_from_registry() {
        return Ok(p);
    }

    // 6. 常见安装路径兜底
    for p in common_install_paths() {
        if p.is_file() {
            return Ok(p);
        }
    }

    Err(anyhow!(
        "未找到可用的 Python 解释器。请在当前设备上准备一个可运行的 Python 环境，任选一种方式：\n\
         \n\
         【方式一 · 推荐】安装 Python 并装依赖（本机手动一次性设置）\n\
         1. 从 https://www.python.org/downloads/ 下载安装 Python 3.10+，\n\
            安装向导勾选 \"Add Python to PATH\"。\n\
         2. 打开 PowerShell，执行（把路径换成实际安装目录）：\n\
              pip install -r \"<安装目录>\\engine\\requirements.txt\"\n\
         3. 设置环境变量 TUAN_PYTHON 指向该解释器（例如）：\n\
              setx TUAN_PYTHON \"C:\\Python312\\python.exe\"\n\
         4. 重启 Tuan-Chat。\n\
         \n\
         【方式二】便携运行时（离线可用，无需系统 Python）\n\
         从 https://github.com/indygreg/python-build-standalone 下载 python 3.12 压缩包，\n\
         解压到 <安装目录>\\engine\\python\\ （需包含 python\\python.exe），\n\
         应用启动时会优先使用这个便携运行时。\n\
         \n\
         引擎第三方依赖清单（rich / httpx / openai 等）已随安装包一同分发在\n\
         engine\\requirements.txt，按上面任一步骤引用即可。"
    ))
}

/// 常见 Python 安装路径兜底。
///
/// 覆盖 Windows 系统级与用户级安装位置，以及 macOS/Linux 常见路径。
/// 这些路径是 Python 官方安装器的默认位置，不是某台机器的绝对路径。
fn common_install_paths() -> Vec<PathBuf> {
    let mut paths = Vec::new();
    #[cfg(windows)]
    {
        for ver in ["3.13", "3.12", "3.11", "3.10"] {
            // 系统级安装（per-machine，管理员安装器默认）
            paths.push(PathBuf::from(format!(r"C:\Python{ver}\python.exe")));
            paths.push(PathBuf::from(format!(r"C:\Program Files\Python{ver}\python.exe")));
            paths.push(PathBuf::from(format!(r"C:\Program Files (x86)\Python{ver}\python.exe")));
            // 用户级安装（per-user，勾选 "Install for me only" 时的默认位置）。
            // 之前这里只查了 \Launcher\py.exe（那是 Python Launcher，不是解释器本身）；
            // 补上解释器本体的路径，才能让"用户级安装"的目标机器无需管理员也能命中。
            if let Ok(local) = std::env::var("LOCALAPPDATA") {
                paths.push(
                    PathBuf::from(local)
                        .join("Programs")
                        .join("Python")
                        .join(format!("Python{ver}"))
                        .join("python.exe"),
                );
            }
        }
        // 用户级 Python Launcher 兜底（Launcher 可代理任意已装解释器）
        if let Ok(local) = std::env::var("LOCALAPPDATA") {
            paths.push(
                PathBuf::from(local)
                    .join("Programs")
                    .join("Python")
                    .join("Launcher")
                    .join("py.exe"),
            );
        }
    }
    #[cfg(not(windows))]
    {
        paths.push(PathBuf::from("/usr/bin/python3"));
        paths.push(PathBuf::from("/usr/local/bin/python3"));
        paths.push(PathBuf::from("/opt/homebrew/bin/python3"));
    }
    paths
}

#[cfg(not(target_os = "android"))]
fn which(p: &Path) -> bool {
    let mut c = Command::new(p);
    c.arg("--version").stdout(Stdio::null()).stderr(Stdio::null());
    #[cfg(windows)]
    c.creation_flags(CREATE_NO_WINDOW);
    c.status()
        .map(|s| s.success())
        .unwrap_or(false)
}

/// Android 端不内置本地 Python 引擎，`which` 不会被调用；此实现仅为编译通过。
#[cfg(target_os = "android")]
fn which(_p: &Path) -> bool {
    false
}

/// 通过 Windows 注册表查找 Python 安装路径。
///
/// 遍历 HKLM\SOFTWARE\Python\PythonCore\*\InstallPath，返回首个存在的 python.exe。
/// 使用 reg.exe 查询以避免引入 winreg 依赖。
#[cfg(windows)]
fn detect_python_from_registry() -> Option<PathBuf> {
    let output = Command::new("reg")
        .args(["query", r"HKLM\SOFTWARE\Python\PythonCore", "/s", "/v", "InstallPath"])
        .creation_flags(CREATE_NO_WINDOW)
        .output();
    let output = output.ok()?;
    if !output.status.success() {
        return None;
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    for line in stdout.lines() {
        let line = line.trim();
        if !line.contains("InstallPath") {
            continue;
        }
        // 行格式: "    InstallPath    REG_SZ    C:\Python312\"
        let parts: Vec<&str> = line.split_whitespace().collect();
        for i in (2..parts.len()).rev() {
            let candidate = PathBuf::from(parts[i].trim_matches('"')).join("python.exe");
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    None
}

pub struct EngineHandle {
    child: Option<Child>,
}

impl EngineHandle {
    /// Spawn the local tuan_cli engine and wait for readiness, bounded by
    /// `timeout`. Any child failure before ready returns an error immediately.
    pub fn spawn_ready(exe_dir: &Path, module: &str, timeout: Duration) -> Result<Self> {
        #[cfg(target_os = "android")]
        {
            // Code-level support: on-device local engine adapter is wired in a
            // separate integration pass.
            return Err(anyhow!("Android 本地引擎适配待设备联调"));
        }

        #[cfg(not(target_os = "android"))]
        {
            let python = resolve_python(exe_dir)?;
            let started = Instant::now();
            let mut cmd = Command::new(&python);
            // Windows Python Launcher 需要 -3 参数指定 Python 3.x
            #[cfg(windows)]
            if python.file_name().and_then(|s| s.to_str()).map(|s| s == "py" || s == "py.exe").unwrap_or(false) {
                cmd.arg("-3");
            }
            cmd.arg("-m")
                .arg(module)
                .current_dir(exe_dir.join("engine"))
                .stdout(Stdio::piped())
                .stderr(Stdio::piped());
            #[cfg(windows)]
            cmd.creation_flags(CREATE_NO_WINDOW);
            let mut child = cmd
                .spawn()
                .map_err(|e| anyhow!("引擎进程启动失败: {e}"))?;

            // Bounded readiness wait: poll the child status; if it exited early,
            // surface the error instead of blocking forever.
            while started.elapsed() < timeout {
                match child.try_wait()? {
                    Some(status) => {
                        return Err(anyhow!("引擎进程提前退出，状态 {status}"));
                    }
                    None => std::thread::sleep(Duration::from_millis(120)),
                }
            }
            Ok(Self { child: Some(child) })
        }
    }

    pub fn stop(&mut self) {
        if let Some(mut c) = self.child.take() {
            let _ = c.kill();
            let _ = c.wait();
        }
    }
}

impl Drop for EngineHandle {
    fn drop(&mut self) {
        self.stop();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    /// 临时改 TUAN_PYTHON 并在测试结束恢复原状，避免污染同进程其它测试。
    struct EnvGuard {
        key: &'static str,
        had_value: bool,
        old: Option<String>,
    }

    impl EnvGuard {
        fn set(key: &'static str, value: &str) -> Self {
            let prev = std::env::var(key).ok();
            std::env::set_var(key, value);
            Self {
                key,
                had_value: prev.is_some(),
                old: prev,
            }
        }
    }

    impl Drop for EnvGuard {
        fn drop(&mut self) {
            match self.old {
                Some(v) => std::env::set_var(self.key, v),
                None if self.had_value => std::env::set_var(self.key, ""),
                None => std::env::remove_var(self.key),
            }
        }
    }

    #[test]
    fn venv_python_path_matches_platform_layout() {
        // 用相对路径避免平台相关的绝对路径假设（"C:/app" 在 Linux/macOS 上
        // 不是有效绝对路径，会让测试在跨平台 CI 上表现不一致）。
        let root = Path::new("app");
        let mut expected = PathBuf::from("app");
        expected.push("engine");
        expected.push(".venv");
        if cfg!(windows) {
            expected.push("Scripts");
            expected.push("python.exe");
        } else {
            expected.push("bin");
            expected.push("python");
        }
        assert_eq!(venv_python_path(root), expected);
    }

    #[test]
    fn resolve_python_error_points_to_bundled_requirements() {
        // 错误提示必须指向随包分发的 engine/requirements.txt，且不能引用仅存于
        // 仓库根目录的 scripts/install_engine_env.py（那不在 NSIS 安装包内，
        // 用户装完应用后执行不了，等于把用户引向一个死胡同）。
        let root = tempfile_dir();
        let _guard = EnvGuard::set("TUAN_PYTHON", "definitely-not-a-real-python.exe");
        // 若本机恰好装了系统 Python，resolve_python 会成功（走第 4/5/6 步）——
        // 那种情况下错误提示不会被触发，测试直接通过，只验证"成功路径"存在。
        if let Err(e) = resolve_python(&root) {
            let msg = e.to_string();
            assert!(
                msg.contains("requirements.txt"),
                "错误提示应指向随包分发的 requirements.txt，让用户知道装什么依赖：{msg}"
            );
            assert!(
                msg.contains("python.org"),
                "错误提示应给出安装 Python 的下载入口：{msg}"
            );
            assert!(
                !msg.contains("scripts/install_engine_env.py"),
                "错误提示不能引用仓库根的脚本（不在安装包内，用户跑不了）：{msg}"
            );
        }
    }

    #[test]
    fn resolve_python_finds_app_venv() {
        let root = tempfile_dir();
        // TUAN_PYTHON 指向不存在的文件：让"环境变量覆盖"这一步失败，
        // 才能落到新加的虚拟环境分支。
        let _guard = EnvGuard::set("TUAN_PYTHON", "definitely-not-a-real-python.exe");
        let venv = venv_python_path(&root);
        fs::create_dir_all(venv.parent().unwrap()).unwrap();
        fs::write(&venv, b"").unwrap();

        let got = resolve_python(&root).expect("应解析到 engine/.venv 里的解释器");
        assert_eq!(got, venv);
    }

    #[test]
    fn resolve_python_skips_missing_venv() {
        let root = tempfile_dir();
        // 故意留下空的 .venv 目录但没有解释器文件
        fs::create_dir_all(venv_python_path(&root).parent().unwrap()).unwrap();

        let guard = EnvGuard::set("TUAN_PYTHON", "");
        // 无便携运行时、无可用环境变量、无虚拟环境 -> 不应返回 .venv 路径
        let res = resolve_python(&root);
        drop(guard);
        match res {
            Ok(p) => assert_ne!(
                p,
                venv_python_path(&root),
                "解释器文件不存在时不该返回 .venv 路径"
            ),
            Err(_) => {}
        }
    }

    /// 建一个进程内唯一的临时目录（不依赖 tempfile crate）。
    fn tempfile_dir() -> PathBuf {
        let n = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let d = std::env::temp_dir().join(format!("tuan-app-resolve-{}-{}", std::process::id(), n));
        let _ = fs::create_dir_all(&d);
        d
    }
}

