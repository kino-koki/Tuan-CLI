/**
 * acpClient.ts — 通过 stdio 与 `qxt acp` 子进程通信的 ACP 客户端。
 *
 * 通信模型：
 *   - 用 child_process.spawn 拉起 `qxt acp`（命令/参数可在设置中覆盖）。
 *   - stdout 是 NDJSON 字节流，按 \n 切帧后 JSON.parse。
 *   - stdin 是 NDJSON 字节流，每条请求/通知 JSON.stringify 后追加 \n。
 *   - 请求-响应通过自增 id 配对（Promise 池）。
 *   - 服务端推送的 session/update、task/update 通知通过 EventEmitter 风格的回调分发。
 *
 * 这里不实现任何 Agent 业务逻辑，只做协议帧的编解码与进程生命周期管理。
 */

import { ChildProcess, spawn } from 'child_process';
import { EventEmitter } from 'events';
import * as vscode from 'vscode';
import {
  InitializeParams,
  InitializeResult,
  JsonRpcMessage,
  PromptParams,
  PendingPermission,
  SessionUpdateParams,
  TaskUpdateParams,
  UpdateParams,
} from './types';

/** 一条挂起请求的等待句柄。 */
interface PendingRequest {
  resolve: (result: unknown) => void;
  reject: (err: Error) => void;
  timer: NodeJS.Timeout;
}

export interface AcpClientEvents {
  /** initialize 成功完成。 */
  ready: [InitializeResult];
  /** 收到 session/update 通知。 */
  sessionUpdate: [SessionUpdateParams];
  /** 收到 task/update 通知。 */
  taskUpdate: [TaskUpdateParams];
  /** 进程退出或出错。 */
  exit: [code: number | null, signal: NodeJS.Signals | null];
  /** 日志输出（stderr 或内部调试）。 */
  log: [string];
}

/**
 * ACP 客户端。每个 QXT 会话对应一个实例；扩展激活时懒启动。
 */
export class AcpClient {
  private proc: ChildProcess | null = null;
  private nextId = 1;
  private pending = new Map<number, PendingRequest>();
  private emitter = new EventEmitter();
  /** stdout 残留字节（半行），用于跨 chunk 拼帧。 */
  private stdoutBuf = '';
  private disposed = false;
  private initResult: InitializeResult | null = null;

  constructor(
    private readonly command: string,
    private readonly args: string[],
    private readonly cwd: string,
  ) {}

  // ---------------------------------------------------------------------
  // 事件订阅
  // ---------------------------------------------------------------------
  on<K extends keyof AcpClientEvents>(event: K, listener: (...args: AcpClientEvents[K]) => void): this {
    this.emitter.on(event as string, listener);
    return this;
  }

  private emit<K extends keyof AcpClientEvents>(event: K, ...args: AcpClientEvents[K]): void {
    this.emitter.emit(event as string, ...args);
  }

  // ---------------------------------------------------------------------
  // 生命周期
  // ---------------------------------------------------------------------

  /** 拉起子进程并完成 initialize 握手。 */
  async start(): Promise<InitializeResult> {
    if (this.proc) {
      throw new Error('ACP 客户端已经启动');
    }
    this.emit('log', `启动子进程: ${this.command} ${this.args.join(' ')} (cwd=${this.cwd})`);

    this.proc = spawn(this.command, this.args, {
      cwd: this.cwd,
      env: process.env,
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    });
    const proc = this.proc;
    const stdout = proc.stdout!;
    const stderr = proc.stderr;

    stdout.setEncoding('utf8');
    stdout.on('data', (chunk: string) => this.onStdout(chunk));
    stderr?.setEncoding('utf8');
    stderr?.on('data', (chunk: string) => {
      // stderr 不参与协议，仅作为日志回显。
      this.emit('log', `[stderr] ${chunk.trim()}`);
    });
    proc.on('error', (err) => {
      this.emit('log', `子进程错误: ${err.message}`);
      this.failAllPending(new Error(`无法启动 ACP 子进程: ${err.message}`));
      this.emit('exit', null, null);
    });
    proc.on('exit', (code, signal) => {
      this.emit('log', `子进程退出 code=${code} signal=${signal}`);
      this.failAllPending(new Error(`ACP 子进程意外退出 (code=${code})`));
      this.emit('exit', code, signal);
    });

    // 等待 initialize 握手。
    const initParams: InitializeParams = {
      protocolVersion: 1,
      clientInfo: { name: 'qingxiaotuan-vscode', version: '0.2.017' },
      workspaceFolders: [{ uri: `file://${this.cwd}`, name: this.cwd }],
      rootUri: `file://${this.cwd}`,
    };
    const result = (await this.request('initialize', initParams, 30_000)) as InitializeResult;
    this.initResult = result;
    this.emit('ready', result);
    return result;
  }

  get initialized(): InitializeResult | null {
    return this.initResult;
  }

  // ---------------------------------------------------------------------
  // 对外方法
  // ---------------------------------------------------------------------

  /** 发送一条用户提示（异步：server 立即回 {}，后续通过通知流式回报）。 */
  async prompt(text: string): Promise<void> {
    await this.request('prompt', { prompt: text } satisfies PromptParams, 10_000);
  }

  /** 取消当前正在运行的 agent。 */
  async cancel(): Promise<void> {
    await this.request('cancel', {}, 5_000);
  }

  /** 回复权限请求。 */
  async respondPermission(toolCallId: string, decision: string): Promise<void> {
    const params: UpdateParams = {
      type: 'permission_response',
      toolCallId,
      decision: decision as UpdateParams['decision'],
    };
    await this.request('update', params, 5_000);
  }

  /** 优雅关闭。 */
  async shutdown(): Promise<void> {
    if (!this.proc || this.disposed) {
      return;
    }
    this.disposed = true;
    try {
      await this.request('shutdown', {}, 5_000);
    } catch {
      // 忽略关闭时的错误。
    }
    // 兜底：500ms 后强杀。
    setTimeout(() => {
      if (this.proc && !this.proc.killed) {
        this.proc.kill();
      }
    }, 500).unref();
  }

  // ---------------------------------------------------------------------
  // 内部：JSON-RPC 帧收发
  // ---------------------------------------------------------------------

  private request(method: string, params: unknown, timeoutMs: number): Promise<unknown> {
    const id = this.nextId++;
    const msg: JsonRpcMessage = { jsonrpc: '2.0', id, method, params: params ?? {} };
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`ACP 请求超时: ${method}`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.write(msg);
    });
  }

  private write(msg: JsonRpcMessage): void {
    if (!this.proc || this.proc.killed) {
      this.failAllPending(new Error('ACP 子进程未连接'));
      return;
    }
    const line = JSON.stringify(msg);
    this.proc.stdin?.write(line + '\n');
  }

  private onStdout(chunk: string): void {
    this.stdoutBuf += chunk;
    let idx: number;
    while ((idx = this.stdoutBuf.indexOf('\n')) >= 0) {
      const line = this.stdoutBuf.slice(0, idx).trim();
      this.stdoutBuf = this.stdoutBuf.slice(idx + 1);
      if (!line) {
        continue;
      }
      this.dispatch(line);
    }
  }

  private dispatch(line: string): void {
    let msg: JsonRpcMessage;
    try {
      msg = JSON.parse(line) as JsonRpcMessage;
    } catch {
      this.emit('log', `跳过非法帧: ${line.slice(0, 200)}`);
      return;
    }

    // 响应：按 id 路由到 pending。
    if (typeof msg.id === 'number' && this.pending.has(msg.id)) {
      const p = this.pending.get(msg.id)!;
      this.pending.delete(msg.id);
      clearTimeout(p.timer);
      if (msg.error) {
        p.reject(new Error(`${msg.error.code}: ${msg.error.message}`));
      } else {
        p.resolve(msg.result ?? {});
      }
      return;
    }

    // 通知：按 method 分发。
    if (msg.method === 'session/update') {
      this.emit('sessionUpdate', (msg.params ?? {}) as SessionUpdateParams);
    } else if (msg.method === 'task/update') {
      this.emit('taskUpdate', (msg.params ?? {}) as TaskUpdateParams);
    } else if (msg.method) {
      this.emit('log', `未知通知: ${msg.method}`);
    }
  }

  private failAllPending(err: Error): void {
    for (const [, p] of this.pending) {
      clearTimeout(p.timer);
      p.reject(err);
    }
    this.pending.clear();
  }
}
