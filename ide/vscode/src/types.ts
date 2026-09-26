/**
 * types.ts — ACP（Agent Client Protocol）消息类型定义。
 *
 * 与主项目 qingxiaotuan/acp/protocol.py 对齐：
 *   - 所有消息均为 NDJSON（一行一条）JSON-RPC 2.0 帧。
 *   - client -> server 方法：initialize / prompt / update / cancel / shutdown
 *   - server -> client 通知：session/update、task/update
 *
 * 这里只声明 IDE 侧需要用到的字段，未声明的字段以 any 兜底，避免协议扩展导致编译失败。
 */

// ---------------------------------------------------------------------------
// JSON-RPC 基础帧
// ---------------------------------------------------------------------------

/** 一条 JSON-RPC 消息的通用外壳。 */
export interface JsonRpcMessage {
  jsonrpc: '2.0';
  id?: number | string | null;
  method?: string;
  params?: unknown;
  result?: unknown;
  error?: RpcError;
}

/** JSON-RPC 错误对象。 */
export interface RpcError {
  code: number;
  message: string;
  data?: unknown;
}

// ---------------------------------------------------------------------------
// initialize
// ---------------------------------------------------------------------------

/** initialize 请求参数（client -> server）。 */
export interface InitializeParams {
  /** 客户端期望的协议版本（融合层增强时使用）。 */
  protocolVersion?: number;
  /** 客户端展示名，便于 server 侧日志区分。 */
  clientInfo?: { name: string; version: string };
  /** 工作区目录（file:// URI 或绝对路径）。 */
  workspaceFolders?: Array<{ uri: string; name: string }>;
  /** 根目录。 */
  rootUri?: string | null;
}

/** initialize 返回体（与 build_initialize_result 对齐）。 */
export interface InitializeResult {
  sessionId: string;
  session?: { sessionId: string };
  agentInfo: { name: string; version?: string; [k: string]: unknown };
  model: string;
  modelInfo: { id?: string; displayName?: string; [k: string]: unknown };
  tools: AcpTool[];
  slash_commands: SlashCommand[];
  workspaceFolder: { uri: string; name: string };
  authMethods: unknown[];
  protocolVersion?: number;
}

/** 一个可用工具的描述。 */
export interface AcpTool {
  name: string;
  description?: string;
  /** JSON Schema，描述参数。 */
  parameters?: unknown;
  /** 工具来源：比如 mcp server 名。 */
  source?: string;
  [k: string]: unknown;
}

/** 斜杠命令。 */
export interface SlashCommand {
  name: string;
  description?: string;
  [k: string]: unknown;
}

// ---------------------------------------------------------------------------
// prompt
// ---------------------------------------------------------------------------

/** prompt 请求参数。 */
export interface PromptParams {
  prompt: string;
  /** 可选：附加上下文（用户选中的代码片段等）。 */
  filePath?: string;
  selection?: { startLine: number; startCol: number; endLine: number; endCol: number };
}

// ---------------------------------------------------------------------------
// session/update 通知（server -> client）
// ---------------------------------------------------------------------------

/** session/update 通知的 params 体。 */
export interface SessionUpdateParams {
  sessionId: string;
  type: SessionUpdateType;
  /** agent_message_chunk / agent_thought_chunk 的文本增量。 */
  text?: string;
  /** tool_call 相关。 */
  toolCallId?: string;
  toolCall?: { name: string; [k: string]: unknown };
  description?: string;
  /** tool_call_update 相关。 */
  status?: 'running' | 'completed' | 'failed' | string;
  result?: string;
  error?: string;
  /** permission_request 相关。 */
  permission?: string;
  options?: string[];
  /** available_commands_update。 */
  commands?: SlashCommand[];
  [k: string]: unknown;
}

export type SessionUpdateType =
  | 'initialized'
  | 'available_commands_update'
  | 'agent_message_chunk'
  | 'agent_thought_chunk'
  | 'tool_call'
  | 'tool_call_update'
  | 'permission_request'
  | 'permission_update'
  | string;

// ---------------------------------------------------------------------------
// task/update 通知（server -> client）
// ---------------------------------------------------------------------------

export interface TaskUpdateParams {
  sessionId: string;
  status: 'running' | 'completed' | 'failed' | string;
  result?: string;
  error?: string;
}

// ---------------------------------------------------------------------------
// update（client -> server，主要用于权限回执）
// ---------------------------------------------------------------------------

/** permission_response 决策取值。 */
export type PermissionDecision =
  | 'approved'
  | 'approved_for_session'
  | 'approve_once'
  | 'approve_always'
  | 'reject'
  | 'denied'
  | 'plan_review';

export interface UpdateParams {
  type: 'permission_response' | string;
  toolCallId?: string;
  decision?: PermissionDecision;
  [k: string]: unknown;
}

// ---------------------------------------------------------------------------
// 聊天流内部数据模型（供 chatProvider 使用）
// ---------------------------------------------------------------------------

/** 一条消息在聊天流中的角色。 */
export type ChatRole = 'user' | 'agent' | 'system';

/** 工具调用在 UI 中的生命周期状态。 */
export type ToolStatus = 'running' | 'completed' | 'failed' | 'cancelled';

/** 一次工具调用的完整记录。 */
export interface ToolCallRecord {
  id: string;
  name: string;
  /** 参数摘要（server 端截断到 500 字符）。 */
  argsSummary: string;
  status: ToolStatus;
  result?: string;
  error?: string;
  /** 起止时间戳，用于在 UI 上展示耗时。 */
  startedAt: number;
  endedAt?: number;
}

/** 聊天流中的一条消息。 */
export interface ChatMessage {
  id: string;
  role: ChatRole;
  /** 已经累积完成的正文（流式 delta 会持续追加到这里）。 */
  content: string;
  /** 推理/思考块（agent_thought_chunk 累积）。 */
  thinking?: string;
  /** 是否正在流式输出。 */
  streaming?: boolean;
  /** 关联的工具调用列表。 */
  toolCalls: ToolCallRecord[];
  /** 时间戳。 */
  ts: number;
}

/** 权限请求的挂起状态。 */
export interface PendingPermission {
  toolCallId: string;
  description: string;
  permission: string;
  options: string[];
}

/** MCP 服务器条目（从 initialize.tools 聚合得到）。 */
export interface McpServerEntry {
  name: string;
  toolCount: number;
  status: 'connected' | 'unknown';
}
