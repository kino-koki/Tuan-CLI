# Agent 工具面能力接线对照表

> 由 `python scripts/dump_tool_wiring.py` 生成 (审计 #20: 核对「有命令、
> 无接线」)。方法: 在最小内核 (config + tool_registry) 上逐个真实激活
> `builtin_tool_plugins()` 的全部插件, 记录其注册进注册表的工具。
> 生成时工具面共 **107** 个工具; 激活失败插件 **0** 个。

| 工具 | 注册插件 | 只读 | 分组 | 默认暴露层级 |
|---|---|---|---|---|
| `delete_dir` | tools.filesystem | no | filesystem | extended |
| `delete_file` | tools.filesystem | no | filesystem | extended |
| `diff_preview` | tools.filesystem | yes | filesystem | core |
| `edit_file` | tools.filesystem | no | filesystem | core |
| `edit_files` | tools.filesystem | no | filesystem | core |
| `glob` | tools.filesystem | yes | filesystem | core |
| `list_dir` | tools.filesystem | yes | filesystem | core |
| `move_file` | tools.filesystem | no | filesystem | extended |
| `read_file` | tools.filesystem | yes | filesystem | core |
| `read_files` | tools.filesystem | yes | filesystem | core |
| `search_files` | tools.filesystem | yes | filesystem | core |
| `write_file` | tools.filesystem | no | filesystem | core |
| `bg_shell` | tools.shell | no | shell | extended |
| `run_shell` | tools.shell | no | shell | core |
| `web_fetch` | tools.web | yes | web | extended |
| `web_search` | tools.web | yes | web | extended |
| `memory_delete` | tools.memory | no | memory | extended |
| `memory_note_append` | tools.memory | no | memory | extended |
| `memory_recall` | tools.memory | yes | memory | extended |
| `memory_recent` | tools.memory | yes | memory | extended |
| `memory_search` | tools.memory | yes | memory | extended |
| `memory_stats` | tools.memory | yes | memory | extended |
| `memory_update_user` | tools.memory | yes | memory | extended |
| `memory_write` | tools.memory | no | memory | extended |
| `skill_install` | tools.skills | no | skills | extended |
| `skill_list` | tools.skills | yes | skills | extended |
| `skill_read` | tools.skills | yes | skills | extended |
| `skill_remove` | tools.skills | no | skills | extended |
| `skill_save` | tools.skills | no | skills | extended |
| `skill_update` | tools.skills | no | skills | extended |
| `codebase_map` | tools.code | yes | code | deferred (tool_search 按需检索) |
| `doctor` | tools.code | yes | agent | deferred (tool_search 按需检索) |
| `find_references` | tools.code | yes | code | extended |
| `find_symbol` | tools.code | yes | code | extended |
| `git_diff` | tools.code | yes | code | extended |
| `git_log` | tools.code | yes | code | extended |
| `git_status` | tools.code | yes | code | extended |
| `open_file` | tools.code | yes | code | extended |
| `run_tests` | tools.code | no | code | core |
| `dispatch_tasks` | tools.dispatch | no | agent | deferred (tool_search 按需检索) |
| `pipeline_list_tools` | tools.pipeline | no | orchestration | deferred (tool_search 按需检索) |
| `pipeline_run` | tools.pipeline | no | orchestration | deferred (tool_search 按需检索) |
| `code_review` | tools.code_review | yes | code | extended |
| `code_review_quick` | tools.code_review | yes | code | extended |
| `ext_ansi_strip` | tools.external | no | general | deferred (tool_search 按需检索) |
| `ext_crypto_seal` | tools.external | no | general | deferred (tool_search 按需检索) |
| `ext_crypto_unseal` | tools.external | no | general | deferred (tool_search 按需检索) |
| `ext_diff` | tools.external | no | general | deferred (tool_search 按需检索) |
| `ext_index_build` | tools.external | no | general | deferred (tool_search 按需检索) |
| `ext_index_query` | tools.external | no | general | deferred (tool_search 按需检索) |
| `ext_json_diff` | tools.external | no | general | deferred (tool_search 按需检索) |
| `ext_json_merge` | tools.external | no | general | deferred (tool_search 按需检索) |
| `ext_json_pointer` | tools.external | no | general | deferred (tool_search 按需检索) |
| `ext_merge3` | tools.external | no | general | deferred (tool_search 按需检索) |
| `ext_notify` | tools.external | no | general | deferred (tool_search 按需检索) |
| `ext_patch` | tools.external | no | general | deferred (tool_search 按需检索) |
| `ext_rules_check` | tools.external | no | general | deferred (tool_search 按需检索) |
| `ext_rules_load` | tools.external | no | general | deferred (tool_search 按需检索) |
| `ext_safety_score` | tools.external | no | general | deferred (tool_search 按需检索) |
| `ext_search` | tools.external | no | general | deferred (tool_search 按需检索) |
| `language_checks` | tools.languages | yes | code | deferred (tool_search 按需检索) |
| `project_languages` | tools.languages | yes | code | extended |
| `checkpoint` | tools.checkpoint | no | session | extended |
| `background_status` | tools.task | yes | agent | extended |
| `task` | tools.task | no | agent | extended |
| `ask_user` | tools.session | yes | session | core |
| `enter_plan_mode` | tools.session | yes | session | core |
| `exit_plan_mode` | tools.session | yes | session | core |
| `todo_read` | tools.session | yes | session | extended |
| `todo_write` | tools.session | yes | session | extended |
| `todo_list` | tools.todo | yes | session | extended |
| `code_dependency_graph` | tools.code_graph | yes | code | deferred (tool_search 按需检索) |
| `generate_from_template` | tools.backend_dev | no | backend | deferred (tool_search 按需检索) |
| `list_templates` | tools.backend_dev | yes | backend | deferred (tool_search 按需检索) |
| `sandbox_cleanup` | tools.sandbox | yes | sandbox | deferred (tool_search 按需检索) |
| `sandbox_diff` | tools.sandbox | yes | sandbox | deferred (tool_search 按需检索) |
| `sandbox_run` | tools.sandbox | no | sandbox | deferred (tool_search 按需检索) |
| `sandbox_snapshot` | tools.sandbox | yes | sandbox | deferred (tool_search 按需检索) |
| `dynamic_workflow` | tools.dynamic_workflow | no | agent | extended |
| `workflow_status` | tools.dynamic_workflow | no | agent | extended |
| `team_list_members` | tools.team | yes | team | extended |
| `team_post_update` | tools.team | no | team | extended |
| `team_read_updates` | tools.team | yes | team | extended |
| `team_share_note` | tools.team | no | team | extended |
| `image_generate` | tools.image_gen | no | image | deferred (tool_search 按需检索) |
| `image_list_generated` | tools.image_gen | yes | image | deferred (tool_search 按需检索) |
| `pick_files` | tools.picker | yes | navigation | extended |
| `tool_search` | tools.tool_search | yes | meta | core |
| `browser_close` | tools.browser | no | browser | extended |
| `browser_status` | tools.browser | yes | browser | extended |
| `browser_task` | tools.browser | no | browser | extended |
| `background_monitor` | tools.monitor | yes | agent | extended |
| `notebook_edit` | tools.notebook | no | filesystem | extended |
| `notebook_read` | tools.notebook | yes | filesystem | extended |
| `create_artifact` | tools.artifact | no | tools | deferred (tool_search 按需检索) |
| `list_agents` | tools.messaging | yes | messaging | extended |
| `receive_messages` | tools.messaging | yes | messaging | deferred (tool_search 按需检索) |
| `send_message` | tools.messaging | yes | messaging | deferred (tool_search 按需检索) |
| `agents_list` | tools.subagent | yes | agent | extended |
| `subagent` | tools.subagent | yes | agent | extended |
| `subagent_resume` | tools.subagent | yes | agent | extended |
| `workflow` | tools.workflow | no | agent | deferred (tool_search 按需检索) |
| `cron` | tools.cron | no | tools | extended |
| `gh` | tools.gh | yes | tools | extended |
| `ecosystem` | tools.ecosystem | no | tools | extended |
| `audit_query` | tools.audit | no | tools | extended |
| `external_dispatch` | tools.external_dispatch | no | tools | extended |

## 激活失败 / 需要额外服务的插件 (接线缺口)

(无 —— 全部内置工具插件在最小内核上激活成功。)

## 口径说明

- 本表只回答「Agent 工具面接了什么」; CLI 子命令面 (`tuan ...`) 是另一套
  入口, 二者不一一对应。历史上 `create_artifact` / `send_message` /
  `subagent` / `workflow` / `cron` / `gh` / `ecosystem` / `audit` /
  `dispatch` 等只有 CLI 命令、未接 Agent 工具面, 0.4.5 起已补齐接线
  (见 `tuan_cli/tools/__init__.py` 内注释)。
- 「激活失败」多数表示该插件需要额外服务 (如 memory/skill 的引擎服务),
  在完整内核里是否可用以运行时为准; 本表给出的是**最小内核**下的接线事实。
