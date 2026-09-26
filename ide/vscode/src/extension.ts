/**
 * extension.ts — VS Code 扩展入口。
 *
 * 职责：
 *   - 激活时读取设置项（命令、参数、cwd），spawn `qxt acp` 子进程。
 *   - 建立 ChatProvider（聊天流数据模型）。
 *   - 注册侧边栏 Webview（SidebarPanel）、工具调用树（ToolCallView）、MCP 状态树（McpStatusView）。
 *   - 注册命令：新建对话 / 发送 / 取消 / 重启。
 *   - 失活时优雅关闭 ACP 子进程。
 */

import * as vscode from 'vscode';
import { AcpClient } from './acpClient';
import { ChatProvider } from './chatProvider';
import { SidebarPanel } from './sidebarPanel';
import { ToolCallView } from './toolCallView';
import { McpStatusView } from './mcpStatus';
import { DiffPreview } from './diffPreview';
import { PermissionDialog } from './permissionDialog';

/** 扩展激活期内共享的单例。 */
let client: AcpClient | null = null;
let chat: ChatProvider | null = null;
let sidebar: SidebarPanel | null = null;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  const config = vscode.workspace.getConfiguration('qingxiaotuan');
  const command = String(config.get<string>('command') ?? 'qxt');
  const args = Array.isArray(config.get<string[]>('args')) ? (config.get<string[]>('args') as string[]) : ['acp'];
  const configuredCwd = String(config.get<string>('cwd') ?? '');
  const workspaceRoot =
    configuredCwd ||
    (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0
      ? vscode.workspace.workspaceFolders[0].uri.fsPath
      : process.cwd());

  // 1. 启动 ACP 客户端。
  client = new AcpClient(command, args, workspaceRoot);
  client.on('log', (line) => {
    // 调试日志：输出到 OutputChannel，便于排查。
    outputChannel.appendLine(`[acp] ${line}`);
  });

  chat = new ChatProvider(client);

  // 2. 注册视图。
  sidebar = new SidebarPanel(context.extensionUri, chat);
  const toolView = new ToolCallView(chat);
  const mcpView = new McpStatusView(chat);
  const diffPreview = new DiffPreview(chat);
  const permDialog = new PermissionDialog(chat);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(SidebarPanel.viewType, sidebar, {
      webviewOptions: { retainContextWhenHidden: true },
    }),
    vscode.window.registerTreeDataProvider('qingxiaotuan.tools', toolView),
    vscode.window.registerTreeDataProvider('qingxiaotuan.mcpStatus', mcpView),
    diffPreview,
    permDialog,
  );

  // 3. 注册命令。
  context.subscriptions.push(
    vscode.commands.registerCommand('qingxiaotuan.newChat', () => {
      chat?.clear();
    }),
    vscode.commands.registerCommand('qingxiaotuan.cancel', async () => {
      await chat?.cancel();
    }),
    vscode.commands.registerCommand('qingxiaotuan.restart', async () => {
      await restartSession(context);
    }),
    vscode.commands.registerCommand('qingxiaotuan.focusInput', () => {
      // 让侧边栏 webview 自动获得焦点（用户在 webview 内部监听 focus 事件）。
      void vscode.commands.executeCommand('workbench.view.extension.qingxiaotuan-view');
    }),
    vscode.commands.registerCommand('qingxiaotuan.sendPrompt', async () => {
      const text = await vscode.window.showInputBox({
        prompt: '向青小团发送一条提示',
        placeHolder: '例如：帮我把 src/foo.ts 里的 TODO 清理掉',
      });
      if (text) {
        await chat?.sendUserMessage(text);
      }
    }),
  );

  // 4. 异步启动子进程（不阻塞激活）。
  outputChannel.appendLine(`正在启动 ACP: ${command} ${args.join(' ')} (cwd=${workspaceRoot})`);
  try {
    await client.start();
    vscode.commands.executeCommand('setContext', 'qingxiaotuan.busy', false);
  } catch (err) {
    outputChannel.appendLine(`启动失败: ${(err as Error).message}`);
    vscode.window.showErrorMessage(
      `青小团 ACP 启动失败：${(err as Error).message}\n请确认 qxt 已安装并在 PATH 中，或在设置 qingxiaotuan.command 中指定。`,
    );
  }

  // 监听 busy 状态切换，控制取消按钮显示。
  chat.onChange(() => {
    const st = chat?.getState();
    void vscode.commands.executeCommand('setContext', 'qingxiaotuan.busy', !!st?.busy);
  });
}

export async function deactivate(): Promise<void> {
  if (client) {
    try {
      await client.shutdown();
    } catch {
      // ignore
    }
  }
  sidebar?.dispose();
}

// ---------------------------------------------------------------------------
// 内部工具
// ---------------------------------------------------------------------------

const outputChannel = vscode.window.createOutputChannel('青小团 QXT');

async function restartSession(context: vscode.ExtensionContext): Promise<void> {
  if (client) {
    try {
      await client.shutdown();
    } catch {
      // ignore
    }
  }
  // 这里简单地重新加载窗口是最稳妥的重启方式；后续可改为原地重新 spawn。
  void vscode.window.showInformationMessage('青小团会话已重启', '重新加载窗口').then((pick) => {
    if (pick === '重新加载窗口') {
      void vscode.commands.executeCommand('workbench.action.reloadWindow');
    }
  });
  context; // 保留参数引用，避免未使用告警。
}
