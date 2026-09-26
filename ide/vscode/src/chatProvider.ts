/**
 * chatProvider.ts — 聊天流数据模型。
 *
 * 负责：
 *   - 维护消息列表（用户消息 / Agent 流式消息 / 工具调用记录）。
 *   - 把 acpClient 推过来的 session/update、task/update 事件翻译成 UI 状态。
 *   - 暴露给 sidebarPanel 做渲染（通过 onDidChange 事件）。
 *
 * 这个类不直接操作 Webview DOM，只维护纯数据 + 发事件；Webview 拿到最新状态后自己渲染。
 */

import { EventEmitter } from 'events';
import * as vscode from 'vscode';
import { AcpClient } from './acpClient';
import {
  ChatMessage,
  InitializeResult,
  PendingPermission,
  SessionUpdateParams,
  TaskUpdateParams,
  ToolCallRecord,
  ToolStatus,
} from './types';

let msgCounter = 0;
function nextMsgId(): string {
  msgCounter += 1;
  return `msg_${Date.now()}_${msgCounter}`;
}

export interface ChatState {
  messages: ChatMessage[];
  busy: boolean;
  initialized: InitializeResult | null;
  pendingPermission: PendingPermission | null;
  lastError?: string;
}

export class ChatProvider {
  private messages: ChatMessage[] = [];
  private busy = false;
  private initResult: InitializeResult | null = null;
  private pendingPerm: PendingPermission | null = null;
  private lastError?: string;
  /** 当前正在接收流式文本的 agent 消息 id。 */
  private currentAgentId: string | null = null;
  private emitter = new EventEmitter();

  constructor(private readonly client: AcpClient) {
    this.client.on('ready', (res) => this.onReady(res));
    this.client.on('sessionUpdate', (p) => this.onSessionUpdate(p));
    this.client.on('taskUpdate', (p) => this.onTaskUpdate(p));
  }

  // ---------------------------------------------------------------------
  // 事件订阅（给 sidebarPanel）
  // ---------------------------------------------------------------------
  onChange(listener: () => void): vscode.Disposable {
    this.emitter.on('change', listener);
    return new vscode.Disposable(() => this.emitter.off('change', listener));
  }

  private notify(): void {
    this.emitter.emit('change');
  }

  getState(): ChatState {
    return {
      messages: [...this.messages],
      busy: this.busy,
      initialized: this.initResult,
      pendingPermission: this.pendingPerm,
      lastError: this.lastError,
    };
  }

  // ---------------------------------------------------------------------
  // 用户操作
  // ---------------------------------------------------------------------

  /** 追加一条用户消息并发送给 agent。 */
  async sendUserMessage(text: string): Promise<void> {
    const trimmed = text.trim();
    if (!trimmed) {
      return;
    }
    if (this.busy) {
      vscode.window.showWarningMessage('青小团：当前任务尚未完成，请先取消或等待。');
      return;
    }
    this.messages.push({
      id: nextMsgId(),
      role: 'user',
      content: trimmed,
      toolCalls: [],
      ts: Date.now(),
    });
    this.lastError = undefined;
    this.notify();
    try {
      await this.client.prompt(trimmed);
    } catch (err) {
      this.lastError = (err as Error).message;
      this.notify();
    }
  }

  async cancel(): Promise<void> {
    try {
      await this.client.cancel();
    } catch (err) {
      vscode.window.showErrorMessage(`取消失败: ${(err as Error).message}`);
    }
  }

  /** 清空聊天记录（不重启子进程）。 */
  clear(): void {
    this.messages = [];
    this.currentAgentId = null;
    this.pendingPerm = null;
    this.busy = false;
    this.notify();
  }

  // ---------------------------------------------------------------------
  // 事件处理：把 ACP 通知翻译成聊天流状态
  // ---------------------------------------------------------------------

  private onReady(res: InitializeResult): void {
    this.initResult = res;
    this.messages.push({
      id: nextMsgId(),
      role: 'system',
      content: `已连接 ${res.agentInfo.name}${res.model ? ' · 模型 ' + res.model : ''}`,
      toolCalls: [],
      ts: Date.now(),
    });
    this.notify();
  }

  private onSessionUpdate(p: SessionUpdateParams): void {
    switch (p.type) {
      case 'initialized':
        // 已经在 onReady 里推过系统消息。
        break;

      case 'available_commands_update':
        // 斜杠命令快照，暂存在 initResult 里。
        if (this.initResult && Array.isArray(p.commands)) {
          this.initResult.slash_commands = p.commands;
        }
        break;

      case 'agent_message_chunk':
        this.appendAgentText(p.text ?? '');
        break;

      case 'agent_thought_chunk':
        this.appendAgentThought(p.text ?? '');
        break;

      case 'tool_call':
        this.onToolCall(p);
        break;

      case 'tool_call_update':
        this.onToolCallUpdate(p);
        break;

      case 'permission_request':
        this.onPermissionRequest(p);
        break;

      case 'permission_update':
        // 服务端回执，仅用于调试。
        break;

      default:
        // 未知类型，忽略。
        break;
    }
    this.notify();
  }

  private onTaskUpdate(p: TaskUpdateParams): void {
    if (p.status === 'running') {
      this.busy = true;
    } else if (p.status === 'completed') {
      this.busy = false;
      this.finalizeCurrentAgent();
    } else if (p.status === 'failed') {
      this.busy = false;
      this.lastError = p.error;
      this.finalizeCurrentAgent();
    }
    this.notify();
  }

  // ---------------------------------------------------------------------
  // 内部：流式文本累积
  // ---------------------------------------------------------------------

  private ensureAgentMessage(): ChatMessage {
    if (this.currentAgentId) {
      const found = this.messages.find((m) => m.id === this.currentAgentId);
      if (found) {
        return found;
      }
    }
    const m: ChatMessage = {
      id: nextMsgId(),
      role: 'agent',
      content: '',
      thinking: '',
      streaming: true,
      toolCalls: [],
      ts: Date.now(),
    };
    this.messages.push(m);
    this.currentAgentId = m.id;
    return m;
  }

  private appendAgentText(delta: string): void {
    const m = this.ensureAgentMessage();
    m.content += delta;
  }

  private appendAgentThought(delta: string): void {
    const m = this.ensureAgentMessage();
    m.thinking = (m.thinking ?? '') + delta;
  }

  private finalizeCurrentAgent(): void {
    if (this.currentAgentId) {
      const m = this.messages.find((x) => x.id === this.currentAgentId);
      if (m) {
        m.streaming = false;
      }
      this.currentAgentId = null;
    }
  }

  // ---------------------------------------------------------------------
  // 内部：工具调用
  // ---------------------------------------------------------------------

  private onToolCall(p: SessionUpdateParams): void {
    const m = this.ensureAgentMessage();
    const rec: ToolCallRecord = {
      id: p.toolCallId ?? nextMsgId(),
      name: p.toolCall?.name ?? 'unknown',
      argsSummary: p.description ?? '',
      status: 'running',
      startedAt: Date.now(),
    };
    m.toolCalls.push(rec);
  }

  private onToolCallUpdate(p: SessionUpdateParams): void {
    const id = p.toolCallId;
    if (!id) {
      return;
    }
    for (const m of this.messages) {
      const rec = m.toolCalls.find((t) => t.id === id);
      if (rec) {
        rec.status = (p.status as ToolStatus) ?? 'completed';
        rec.result = p.result;
        rec.error = p.error;
        rec.endedAt = Date.now();
      }
    }
  }

  // ---------------------------------------------------------------------
  // 内部：权限请求
  // ---------------------------------------------------------------------

  private onPermissionRequest(p: SessionUpdateParams): void {
    this.pendingPerm = {
      toolCallId: p.toolCallId ?? '',
      description: p.description ?? '',
      permission: p.permission ?? 'ask_user',
      options: p.options ?? ['approve_once', 'reject'],
    };
    this.notify();
  }

  /** 用户在权限对话框里做出选择。 */
  async resolvePermission(decision: string): Promise<void> {
    if (!this.pendingPerm) {
      return;
    }
    const tid = this.pendingPerm.toolCallId;
    this.pendingPerm = null;
    this.notify();
    try {
      await this.client.respondPermission(tid, decision);
    } catch (err) {
      vscode.window.showErrorMessage(`权限回执失败: ${(err as Error).message}`);
    }
  }
}
