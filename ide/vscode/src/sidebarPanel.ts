/**
 * sidebarPanel.ts — 侧边栏 Webview 面板（vscode.WebviewViewProvider）。
 *
 * 视觉/交互参考 Claude Code 与 Qoder：
 *   - 深色背景 (#1e1e1e / #252526)，品牌色青绿 (#00d4aa / #4ec9b0)。
 *   - 顶部模型/会话信息条；中间消息流；底部输入框 + 发送/附件按钮。
 *   - 用户消息右对齐浅色气泡；Agent 消息左对齐深色卡片。
 *   - Agent 消息内联工具调用折叠卡片（⏳/✅/❌ 状态图标，展开看完整参数与结果）。
 *   - 流式输出打字机效果；thinking 块可折叠。
 *
 * Webview 与扩展宿主之间通过 postMessage 通信：
 *   - host -> webview: { type: 'state', state: ChatState }
 *   - webview -> host: { type: 'send', text } / { type: 'cancel' } / { type: 'resolvePermission', decision }
 */

import * as vscode from 'vscode';
import { ChatProvider } from './chatProvider';

export class SidebarPanel implements vscode.WebviewViewProvider {
  public static readonly viewType = 'qingxiaotuan.sidebar';

  private view: vscode.WebviewView | null = null;
  private disposables: vscode.Disposable[] = [];

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly chat: ChatProvider,
  ) {}

  public resolveWebviewView(
    webviewView: vscode.WebviewView,
    _ctx: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken,
  ): void {
    this.view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, 'media')],
    };

    webviewView.webview.html = this.buildHtml(webviewView.webview);

    // 接收来自 webview 的消息。
    webviewView.webview.onDidReceiveMessage(
      (msg) => this.onWebviewMessage(msg),
      undefined,
      this.disposables,
    );

    // 聊天状态变化 -> 推送给 webview。
    this.chat.onChange(() => this.pushState());

    // 首次推一次。
    this.pushState();

    webviewView.onDidDispose(() => {
      this.view = null;
    }, null, this.disposables);
  }

  // ---------------------------------------------------------------------
  // 消息桥
  // ---------------------------------------------------------------------

  private pushState(): void {
    if (!this.view) {
      return;
    }
    void this.view.webview.postMessage({ type: 'state', state: this.chat.getState() });
  }

  private async onWebviewMessage(msg: { type: string; [k: string]: unknown }): Promise<void> {
    switch (msg.type) {
      case 'send':
        await this.chat.sendUserMessage(String(msg.text ?? ''));
        break;
      case 'cancel':
        await this.chat.cancel();
        break;
      case 'resolvePermission':
        await this.chat.resolvePermission(String(msg.decision ?? 'denied'));
        break;
      case 'ready':
        // webview 首次加载完成，补推一次状态。
        this.pushState();
        break;
      default:
        break;
    }
  }

  // ---------------------------------------------------------------------
  // HTML/CSS/JS（内联，避免额外资源请求）
  // ---------------------------------------------------------------------

  private buildHtml(webview: vscode.Webview): string {
    // 品牌色：青绿，避免 heavy indigo/purple。
    const nonce = getNonce();
    const cspSource = webview.cspSource;
    return /* html */ `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src ${cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';">
<title>青小团</title>
<style>
  :root {
    --bg: #1e1e1e;
    --bg-elevated: #252526;
    --bg-hover: #2d2d2d;
    --border: #3c3c3c;
    --fg: #d4d4d4;
    --fg-dim: #9d9d9d;
    --accent: #00d4aa;
    --accent-soft: rgba(0, 212, 170, 0.12);
    --user-bubble: #2d2d30;
    --agent-card: #252526;
    --danger: #f14c4c;
    --warn: #ccae5c;
    --ok: #23a57a;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    background: var(--bg);
    color: var(--fg);
    font-family: var(--vscode-font-family, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif);
    font-size: 13px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  /* 顶部会话条 */
  .header {
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
    background: var(--bg-elevated);
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    color: var(--fg-dim);
    flex-shrink: 0;
  }
  .header .dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--accent);
  }
  .header .model { color: var(--fg); font-weight: 600; }

  /* 消息流 */
  .stream {
    flex: 1;
    overflow-y: auto;
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .msg { display: flex; }
  .msg.user { justify-content: flex-end; }
  .msg.system { justify-content: center; }
  .bubble {
    max-width: 90%;
    padding: 8px 12px;
    border-radius: 8px;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .msg.user .bubble {
    background: var(--user-bubble);
    color: var(--fg);
    border: 1px solid var(--border);
  }
  .msg.agent .bubble {
    background: var(--agent-card);
    border: 1px solid var(--border);
    border-left: 3px solid var(--accent);
    color: var(--fg);
    width: 100%;
  }
  .msg.system .bubble {
    background: transparent;
    color: var(--fg-dim);
    font-size: 11px;
    border: none;
    text-align: center;
  }
  .thinking {
    margin: 4px 0;
    padding: 6px 8px;
    background: rgba(255,255,255,0.03);
    border-left: 2px solid var(--warn);
    color: var(--fg-dim);
    font-size: 12px;
    cursor: pointer;
  }
  .thinking.collapsed .thinking-body { display: none; }

  /* 工具调用卡片 */
  .tool {
    margin: 6px 0;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--bg);
    overflow: hidden;
  }
  .tool-head {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 8px;
    cursor: pointer;
    font-size: 12px;
  }
  .tool-head:hover { background: var(--bg-hover); }
  .tool-name { color: var(--accent); font-family: var(--vscode-editor-font-family, monospace); }
  .tool-args { color: var(--fg-dim); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tool-status.running::before { content: '⏳'; }
  .tool-status.completed::before { content: '✅'; color: var(--ok); }
  .tool-status.failed::before, .tool-status.cancelled::before { content: '❌'; color: var(--danger); }
  .tool-body {
    display: none;
    padding: 6px 8px;
    border-top: 1px solid var(--border);
    font-family: var(--vscode-editor-font-family, monospace);
    font-size: 11px;
    color: var(--fg-dim);
    max-height: 240px;
    overflow: auto;
    white-space: pre-wrap;
  }
  .tool.open .tool-body { display: block; }
  .tool .dur { color: var(--fg-dim); font-size: 11px; }

  /* 权限请求条 */
  .perm {
    margin: 6px 0;
    padding: 8px;
    border: 1px solid var(--warn);
    border-radius: 6px;
    background: rgba(204, 174, 92, 0.08);
  }
  .perm .title { color: var(--warn); font-weight: 600; margin-bottom: 4px; }
  .perm .desc { color: var(--fg); margin-bottom: 8px; white-space: pre-wrap; }
  .perm .btns { display: flex; gap: 6px; flex-wrap: wrap; }
  .perm button, .composer button {
    background: var(--bg-elevated);
    color: var(--fg);
    border: 1px solid var(--border);
    padding: 4px 10px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 12px;
  }
  .perm button.primary { background: var(--accent); color: #0b0b0b; border-color: var(--accent); font-weight: 600; }
  .perm button:hover, .composer button:hover { background: var(--bg-hover); }
  .perm button.primary:hover { background: #00c09d; }

  /* 底部输入 */
  .composer {
    flex-shrink: 0;
    border-top: 1px solid var(--border);
    background: var(--bg-elevated);
    padding: 8px;
    display: flex;
    gap: 6px;
    align-items: flex-end;
  }
  .composer textarea {
    flex: 1;
    background: var(--bg);
    color: var(--fg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px;
    font-family: inherit;
    font-size: 13px;
    resize: none;
    max-height: 160px;
    min-height: 36px;
    outline: none;
  }
  .composer textarea:focus { border-color: var(--accent); }
  .composer .send { background: var(--accent); color: #0b0b0b; border-color: var(--accent); font-weight: 600; }
  .composer .send:disabled { opacity: 0.5; cursor: not-allowed; }

  .empty { color: var(--fg-dim); text-align: center; margin-top: 40px; }
  .error { color: var(--danger); font-size: 12px; padding: 4px 8px; }
</style>
</head>
<body>
  <div class="header">
    <span class="dot"></span>
    <span class="model" id="model">青小团 QXT</span>
    <span id="sub" style="margin-left:auto;"></span>
  </div>
  <div class="stream" id="stream"></div>
  <div class="composer">
    <textarea id="input" rows="1" placeholder="向青小团发送消息…  (Enter 发送, Shift+Enter 换行)"></textarea>
    <button class="send" id="send" title="发送">发送</button>
  </div>

<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  const stream = document.getElementById('stream');
  const input = document.getElementById('input');
  const sendBtn = document.getElementById('send');
  const modelEl = document.getElementById('model');
  const subEl = document.getElementById('sub');
  let state = { messages: [], busy: false, initialized: null, pendingPermission: null };

  function esc(s) {
    return String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  }

  function renderTool(t) {
    const dur = t.endedAt ? ((t.endedAt - t.startedAt)/1000).toFixed(1)+'s' : '';
    let body = '';
    if (t.argsSummary) body += '<div><b>参数:</b>\n' + esc(t.argsSummary) + '</div>';
    if (t.result) body += '<div style="margin-top:4px;"><b>结果:</b>\n' + esc(t.result) + '</div>';
    if (t.error) body += '<div style="margin-top:4px;color:var(--danger);"><b>错误:</b>\n' + esc(t.error) + '</div>';
    return '<div class="tool" data-id="' + esc(t.id) + '">'
      + '<div class="tool-head">'
      + '<span class="tool-status ' + esc(t.status) + '"></span>'
      + '<span class="tool-name">' + esc(t.name) + '</span>'
      + '<span class="tool-args">' + esc(t.argsSummary) + '</span>'
      + (dur ? '<span class="dur">' + dur + '</span>' : '')
      + '</div>'
      + '<div class="tool-body">' + body + '</div>'
      + '</div>';
  }

  function renderMessage(m) {
    if (m.role === 'system') {
      return '<div class="msg system"><div class="bubble">' + esc(m.content) + '</div></div>';
    }
    const side = m.role === 'user' ? 'user' : 'agent';
    let html = '<div class="msg ' + side + '"><div class="bubble">';
    if (m.thinking) {
      html += '<div class="thinking collapsed"><span>💭 思考过程 (点击展开)</span><div class="thinking-body">' + esc(m.thinking) + '</div></div>';
    }
    if (m.content) html += esc(m.content);
    if (m.streaming) html += ' ▍';
    if (m.toolCalls && m.toolCalls.length) {
      html += m.toolCalls.map(renderTool).join('');
    }
    html += '</div></div>';
    return html;
  }

  function renderPerm(p) {
    if (!p) return '';
    const opts = p.options && p.options.length ? p.options : ['approve_once', 'reject'];
    const labelMap = {
      approve_once: 'Approve Once',
      approve_always: 'Approve Always',
      approved: 'Approve',
      approved_for_session: 'Approve Always',
      reject: 'Deny',
      denied: 'Deny',
      plan_review: 'Approve Plan'
    };
    let btns = '';
    for (const o of opts) {
      const primary = (o === 'approve_once' || o === 'approved' || o === 'plan_review') ? 'primary' : '';
      btns += '<button class="' + primary + '" data-decision="' + esc(o) + '">' + esc(labelMap[o] || o) + '</button>';
    }
    return '<div class="perm"><div class="title">⚠ 需要权限确认</div>'
      + '<div class="desc">' + esc(p.description) + '</div>'
      + '<div class="btns">' + btns + '</div></div>';
  }

  function render() {
    if (state.initialized) {
      modelEl.textContent = state.initialized.agentInfo?.name || '青小团 QXT';
      subEl.textContent = state.initialized.model ? '· ' + state.initialized.model : '';
    }
    let html = '';
    if (!state.messages || state.messages.length === 0) {
      html = '<div class="empty">向青小团描述你的任务，它会读写文件、执行命令并帮你完成。</div>';
    } else {
      html = state.messages.map(renderMessage).join('');
    }
    if (state.pendingPermission) {
      html += renderPerm(state.pendingPermission);
    }
    if (state.lastError) {
      html += '<div class="error">✖ ' + esc(state.lastError) + '</div>';
    }
    stream.innerHTML = html;
    stream.scrollTop = stream.scrollHeight;
    sendBtn.disabled = !!state.busy;

    // 绑定工具折叠
    stream.querySelectorAll('.tool-head').forEach(h => {
      h.addEventListener('click', () => h.parentElement.classList.toggle('open'));
    });
    // 绑定 thinking 折叠
    stream.querySelectorAll('.thinking').forEach(t => {
      t.addEventListener('click', () => t.classList.toggle('collapsed'));
    });
    // 绑定权限按钮
    stream.querySelectorAll('.perm button').forEach(b => {
      b.addEventListener('click', () => {
        vscode.postMessage({ type: 'resolvePermission', decision: b.dataset.decision });
      });
    });
  }

  function send() {
    const text = input.value;
    if (!text.trim() || state.busy) return;
    input.value = '';
    vscode.postMessage({ type: 'send', text });
    autoResize();
  }

  sendBtn.addEventListener('click', send);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  function autoResize() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 160) + 'px';
  }
  input.addEventListener('input', autoResize);

  window.addEventListener('message', (e) => {
    const msg = e.data;
    if (!msg) return;
    if (msg.type === 'state') {
      state = msg.state;
      render();
    }
  });

  vscode.postMessage({ type: 'ready' });
</script>
</body>
</html>`;
  }

  dispose(): void {
    for (const d of this.disposables) {
      d.dispose();
    }
    this.disposables = [];
  }
}

function getNonce(): string {
  let text = '';
  const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  for (let i = 0; i < 32; i++) {
    text += possible.charAt(Math.floor(Math.random() * possible.length));
  }
  return text;
}
