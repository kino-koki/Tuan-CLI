export type ApiFormat = 'openai' | 'anthropic';

export interface ModelEntry {
  id: string;
  name: string;
  enabled: boolean;
}

export interface Provider {
  id: string;
  name: string;
  baseUrl: string;
  format: ApiFormat;
  apiKey: string;
  models: ModelEntry[];
}

/** tuan_cli 内置供应商目录（只读，模型中立）。 */
export interface CatalogProvider {
  name: string;
  baseUrl: string;
  defaultModel: string;
  apiKeyEnv: string;
  desc: string;
  tier: 'free' | 'cheap' | 'standard';
  freeTier: boolean;
  region: 'cn' | 'global';
  category: string;
  models: { id: string; free: boolean }[];
  docsUrl: string;
  keyHint: string;
  format: ApiFormat;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  ts: number;
  model?: string;
  /** 引擎思考链（Claude Code 风格可折叠思考块） */
  reasoning?: string;
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  providerId?: string;
  model?: string;
  messages: ChatMessage[];
}

/** 工具调用卡片（引擎 tool / tool_result 事件） */
export interface ToolEvent {
  name: string;
  args?: string;
  status: 'running' | 'done' | 'error';
  out?: string;
}

export interface ChatChunk {
  type: 'text' | 'reason' | 'tool' | 'tool_result' | 'approval' | 'done' | 'error';
  text?: string;
  name?: string;
  args?: string;
  out?: string;
  error?: string;
}

/** 引擎安全闸门发起的危险操作审批请求（引擎阻塞等待答复）。 */
export interface PendingApproval {
  id: string;
  /** 要执行的命令/操作，展示给用户做决定 */
  prompt: string;
  /** analyze_command 的分析结果（risk / reasons / blast_radius / suggestions），JSON 字符串 */
  verdict?: string;
}
