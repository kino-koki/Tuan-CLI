/**
 * mcpStatus.ts — MCP 服务器状态树视图。
 *
 * 从 initialize 返回的 tools[] 里聚合出每个 MCP server（按 tool.source 字段分组），
 * 在侧边栏第三个面板里列出：服务器名 + 已暴露工具数 + 连接状态。
 *
 * 如果当前 ACP server 还没在 tools 里带 source 字段，就全部归到内置 "qxt builtin" 组。
 */

import * as vscode from 'vscode';
import { ChatProvider } from './chatProvider';
import { AcpTool, McpServerEntry } from './types';

class McpNode extends vscode.TreeItem {
  constructor(public readonly entry: McpServerEntry) {
    super(entry.name, vscode.TreeItemCollapsibleState.Collapsed);
    this.id = `mcp:${entry.name}`;
    this.description = `${entry.toolCount} 个工具 · ${entry.status === 'connected' ? '已连接' : '未知'}`;
    this.iconPath = new vscode.ThemeIcon(
      entry.status === 'connected' ? 'cloud' : 'cloud-outline',
      entry.status === 'connected'
        ? new vscode.ThemeColor('testing.iconPassed')
        : new vscode.ThemeColor('statusBarItem.warningBackground'),
    );
  }
}

class ToolNode extends vscode.TreeItem {
  constructor(public readonly tool: AcpTool) {
    super(String(tool.name), vscode.TreeItemCollapsibleState.None);
    this.description = tool.description ? String(tool.description).slice(0, 60) : '';
    this.tooltip = tool.description ? String(tool.description) : tool.name;
  }
}

export class McpStatusView implements vscode.TreeDataProvider<vscode.TreeItem> {
  private _onDidChange = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  /** 缓存当前已知的工具列表，便于展开节点时取详情。 */
  private toolsByServer = new Map<string, AcpTool[]>();

  constructor(private readonly chat: ChatProvider) {
    this.chat.onChange(() => {
      this.refresh();
    });
  }

  private refresh(): void {
    const init = this.chat.getState().initialized;
    this.toolsByServer.clear();
    if (init) {
      for (const t of init.tools) {
        const src = typeof t.source === 'string' && t.source ? t.source : 'qxt builtin';
        const list = this.toolsByServer.get(src) ?? [];
        list.push(t);
        this.toolsByServer.set(src, list);
      }
    }
    this._onDidChange.fire();
  }

  getTreeItem(element: vscode.TreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: vscode.TreeItem): vscode.ProviderResult<vscode.TreeItem[]> {
    if (!element) {
      if (this.toolsByServer.size === 0) {
        return [new ToolNode({ name: '（等待 ACP initialize 完成…', description: '' })];
      }
      const entries: McpServerEntry[] = [...this.toolsByServer.entries()].map(([name, tools]) => ({
        name,
        toolCount: tools.length,
        status: 'connected',
      }));
      return entries.map((e) => new McpNode(e));
    }
    if (element instanceof McpNode) {
      const tools = this.toolsByServer.get(element.entry.name) ?? [];
      return tools.map((t) => new ToolNode(t));
    }
    return [];
  }
}
