// Windows 下不弹出控制台/PowerShell 窗口；Android 忽略该属性。
#![windows_subsystem = "windows"]

fn main() {
    tuan_app_lib::run();
}
