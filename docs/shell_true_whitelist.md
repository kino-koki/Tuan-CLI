# `shell=True` 白名单公开说明

> 本文档由 `python scripts/check_shell_true.py --doc` 生成, 与 CI 门禁
> (`scripts/check_shell_true.py`) 的 WHITELIST 表同源, 请勿手改;
> 修改白名单后重新生成即可。

门禁规则: `tuan_cli/**.py` 中任何 `shell=True` 调用点必须出现在下表
(按 文件 + 内容锚点 匹配, 行号仅作文档提示)。白名单外的新调用点直接
使 CI 失败。

当前白名单条目: 35 条。

| 文件 (相对 tuan_cli/) | 写入行号 | 锚点 | 必要性分类 |
|---|---|---|---|
| `core/proc.py` | 3 | ``subprocess.run(cmd, shell=True` | COMMENT — 注释中的文字描述, 非真实调用点 |
| `core/proc.py` | 28 | `直接用 `shell=True`` | COMMENT — 注释中的文字描述, 非真实调用点 |
| `cli/cmd_tutorial.py` | 71 | `回退到 shell=True` | COMMENT — 注释中的文字描述, 非真实调用点 |
| `cli/cmd_tutorial.py` | 79 | `回退到 shell=True` | COMMENT — 注释中的文字描述, 非真实调用点 |
| `ext/ast_scan.py` | 72 | `shell=True 参数` | COMMENT — 注释中的文字描述, 非真实调用点 |
| `ext/ast_scan.py` | 76 | `shell=True 或位置参数` | COMMENT — 注释中的文字描述, 非真实调用点 |
| `ext/ast_scan.py` | 184 | `shell=True` | COMMENT — 注释中的文字描述, 非真实调用点 |
| `ext/ast_scan.py` | 193 | `shell=True` | REGEX_CONST — 正则/错误消息字符串常量里的字样, 非真实调用点 |
| `ext/ast_scan.py` | 194 | `"shell=True"` | REGEX_CONST — 正则/错误消息字符串常量里的字样, 非真实调用点 |
| `tools/code_review.py` | 94 | `shell\s*=\s*True` | REGEX_CONST — 正则/错误消息字符串常量里的字样, 非真实调用点 |
| `tui/codexkit/stream_exec.py` | 13 | `命令用 `shell=True` 拼接` | COMMENT — 注释中的文字描述, 非真实调用点 |
| `tui/codexkit/stream_exec.py` | 288 | `**永不** ``shell=True``` | COMMENT — 注释中的文字描述, 非真实调用点 |
| `tui/codexkit/__init__.py` | 31 | `命令 ``shell=True`` 拼接` | COMMENT — 注释中的文字描述, 非真实调用点 |
| `web/code_anim_render.py` | 7 | `永不 ``shell=True``` | COMMENT — 注释中的文字描述, 非真实调用点 |
| `web/mh_runner.py` | 5 | `永不使用 ``shell=True``` | COMMENT — 注释中的文字描述, 非真实调用点 |
| `parity_claude/catalog.py` | 143 | `MCP `run_shell` 是另一处 shell=True 入口` | COMMENT — 注释中的文字描述, 非真实调用点 |
| `cli/user_commands.py` | 142 | `shell=True, capture_output=True` | USER_INPUT — 命令由用户/LLM 直接提供, 无法安全转 list |
| `cli/cmd_tutorial.py` | 90 | `r = subprocess.run(cmd, shell=True, timeout=120)` | SAFE_FALLBACK — 已 shlex 优先, 仅检测到 shell 元字符才回退 shell=True |
| `code_edit/verify_loop.py` | 53 | `shell=True, cwd=cwd` | USER_INPUT — 命令由用户/LLM 直接提供, 无法安全转 list |
| `core/verify_loop.py` | 319 | `shell=True, cwd=workspace` | USER_INPUT — 命令由用户/LLM 直接提供, 无法安全转 list |
| `core/reflector.py` | 155 | `shell=True, cwd=str(self.workspace)` | SHELL_META — 命令含 | & ; > < 等 shell 元字符, 需 shell 解释 |
| `core/background_shell.py` | 269 | `normalized, shell=True` | USER_INPUT — 命令由用户/LLM 直接提供, 无法安全转 list |
| `tools/code.py` | 317 | `command, shell=True` | USER_INPUT — 命令由用户/LLM 直接提供, 无法安全转 list |
| `tools/mcp/sandbox.py` | 229 | `shell=True,` | USER_INPUT — 命令由用户/LLM 直接提供, 无法安全转 list |
| `skills/plugin_sdk.py` | 338 | `shell=True,` | PLUGIN_HOOK — 命令来自插件 manifest (插件作者 = 外部输入) |
| `skills/plugin_sdk.py` | 364 | `shell=True,` | PLUGIN_HOOK — 命令来自插件 manifest (插件作者 = 外部输入) |
| `skills/plugin_sdk.py` | 402 | `shell=True,` | PLUGIN_HOOK — 命令来自插件 manifest (插件作者 = 外部输入) |
| `skills/plugin_sdk.py` | 532 | `直接 shell=True 执行` | COMMENT — 注释中的文字描述, 非真实调用点 |
| `tui/render.py` | 117 | `cmd, shell=True, capture_output=True` | USER_INPUT — 命令由用户/LLM 直接提供, 无法安全转 list |
| `web/handler.py` | 453 | `command, shell=True, cwd=self._owner.workspace` | USER_INPUT — 命令由用户/LLM 直接提供, 无法安全转 list |
| `web/server.py` | 1092 | `command, shell=True, cwd=self._owner.workspace,` | USER_INPUT — 命令由用户/LLM 直接提供, 无法安全转 list |
| `tools/shell.py` | 738 | `shell=True,` | USER_INPUT — 命令由用户/LLM 直接提供, 无法安全转 list |
| `sandbox/manager.py` | 449 | `command, shell=True, cwd=cwd,` | USER_INPUT — 命令由用户/LLM 直接提供, 无法安全转 list |
| `ecosystem/mcp_server.py` | 376 | `command, shell=True, capture_output=True,` | USER_INPUT — 命令由用户/LLM 直接提供, 无法安全转 list |
| `ecosystem/mcp_server.py` | 676 | `用 ``shell=True`` 执行` | COMMENT — 注释中的文字描述, 非真实调用点 |
