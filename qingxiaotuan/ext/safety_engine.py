"""纯 Python 实现 safety 引擎
最小影响半径护栏: 命令/SQL/写操作执行前静态风险评分 (none→critical)

本模块只依赖标准库, 既作为 IPC 引擎进程运行, 也作为包内模块被 tools/shell.py、
tools/code.py 直接 import —— 危险命令判定的「单一来源」在这里维护。

安全修复说明 (对照 CODE_REVIEW.md §4.2):
- is_redline 此前只调用 4 个 token 化函数, 完全不 consult 丰富的 CRITICAL_PATTERNS
  (dd / mkfs / format / chmod -R 000 / chown -R root / DROP / DELETE / 关机等),
  导致这些致命命令在 YOLO 红线判定中被放行, 与 score() 的 critical 口径严重不一致。
  现 is_redline 复用 _CRITICAL_PATTERNS, 与 score() 保持一致。
- _normalize 新增 _unwrap_indirection: 递归剥开 sh -c / bash -c / eval / sudo -u /
  xargs / env / find -exec 等执行间接层, 让真实命令浮到段首, 避免被 token 判定绕过。

拆分说明 (2026-10-06): 实现按职责拆为 `safety_normalize`(归一化/混淆还原) /
`safety_redline`(红线模式库与判定) / `safety_score`(SafetyEngine 门面) 三个模块。
本文件保留原模块路径, 仅做转发导出与 IPC 入口, 对外符号与行为不变。
"""


from .safety_normalize import (
    _ANSI_C_ESC,
    _CMD_C_RE,
    _CMD_SUB_ANY_RE,
    _COMBINING_MARKS_RE,
    _CONTROL_CHARS_RE,
    _CYRILLIC_MAP,
    _DANGEROUS_CMDS_IN_ARGS,
    _DASH_MAP,
    _EVAL_DETECT,
    _EVAL_RE,
    _FIND_EXEC_RE,
    _GLOB_MAX_DEPTH,
    _GLOB_MAX_ITERATIONS,
    _GLOB_MAX_MATCHES,
    _INNER,
    _INTERP_RE,
    _PASS_RE,
    _PS_COMMAND_RE,
    _PS_ENCODED_RE,
    _SUDO_RE,
    _VARIATION_SELECTORS_RE,
    _VAR_DEF_RE,
    _bounded_glob,
    _cmd_name,
    _decode_ansi_c_escapes,
    _detect_passthrough_danger,
    _eval_is_unverifiable,
    _expand_globs,
    _inline_command_subs,
    _normalize,
    _resolve_symlinks,
    _scan_variants,
    _segments,
    _strip_sudo,
    _tokenize_shell,
    _try_decode_ps_encoded,
    _unicode_clean,
    _unwrap_indirection,
)
from .safety_redline import (
    _AWK_PROGRAM_RE,
    _BASE64_DECODE_RE,
    _BENIGN_EXACT,
    _BENIGN_PREFIXES,
    _CHMOD_CHOWN_RE,
    _CLI_READONLY_RE,
    _CLI_READONLY_VERB_RE,
    _CONTAINER_READONLY_RE,
    _CRITICAL_PATTERNS,
    _ECHO_B64_PIPE_RE,
    _ECHO_HEX_RE,
    _EMBEDDED_EXEC_RE,
    _ENC_LIT_RE,
    _EXEC_SINK_RE,
    _EXTREME_PATTERNS,
    _HERESTRING_RE,
    _HIGH_PATTERNS,
    _IFS_BENIGN_RE,
    _INTERP_EXEC_ARG_RE,
    _INTERP_PAYLOAD_API_RE,
    _INTERP_PAYLOAD_PROG_RE,
    _INTERP_PAYLOAD_SHELL_RE,
    _MEDIUM_PATTERNS,
    _MENTION_VERB_RE,
    _NC_EXEC_RE,
    _NC_RE,
    _NC_SCAN_RE,
    _PIPE_TO_SHELL_RE,
    _RAW_DISK,
    _REDLINE_PATTERNS,
    _RSYNC_DESTRUCTIVE_RE,
    _RSYNC_RE,
    _SAFE_GIT_SUBCMDS,
    _SCP_RE,
    _SERVICE_READONLY_RE,
    _SYSTEMCTL_READONLY_RE,
    _SYSTEM_PATH_RE,
    _TAR_HAS_FILE_OP_RE,
    _TAR_RE,
    _TAR_SYS_TARGET_RE,
    _TEXT_MENTION_VERBS,
    _TEXT_UTIL_RE,
    _XXD_RE,
    _check_rm_flags,
    _conditional_benign,
    _decoded_shell_fragment_dangerous,
    _git_is_benign,
    _hex_to_text,
    _interpreter_payload_dangerous,
    _is_base64_pipeline_dangerous,
    _is_encoded_literal_dangerous,
    _iter_interpreter_payloads,
    _label_suppressed,
    _match_any,
    _mention_spans,
    _segment_is_benign,
    _sql_redline,
    _try_decode_base64_segments,
    has_auth_overwrite,
    has_force_push,
    has_dangerous_recursive_rm,
    has_recursive_rm,
    has_system_shutdown,
    has_win_recursive_delete,
    is_benign_dev_command,
    is_extreme,
    is_hard_redline,
    is_redline,
)
from .safety_score import (
    SafetyEngine,
)


if __name__ == "__main__":
    SafetyEngine().run()
