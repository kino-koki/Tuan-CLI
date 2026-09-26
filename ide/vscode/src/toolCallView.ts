/**
 * toolCallView.ts — 工具调用历史树视图。
 *
 * 把 ChatProvider 中累积的工具调用记录以 TreeDataProvider 形式展示在侧边栏第二个面板里：
 *   - 每个工具调用是一个节点，显示：状态图标 + 工具名 + 耗时。
 *   - 展开节点可以看到参数摘要、结果（作为子节点或 description）。
 *
 * 这个视图是对 Webview 内联工具卡片的补充：用户可以在不打开对话流的情况下，
 * 快速浏览"Agent 刚才做了什么"。
 */

import * as vscode from 'vscode';
import { ChatProvider } from './chatProvider';
import { ToolCallRecord } from './types';

/** Tree 节点：要么是一条工具调用，要么是工具调用下的"参数/结果"详情。 */
type TreeItem = ToolCallNode | DetailNode;

class ToolCallNode extends vscode.TreeItem {
  constructor(public readonly record: ToolCallRecord) {
    super(ToolCallView.buildLabel(record), vscode.TreeItemCollapsibleState.Collapsed);
    this.id = record.id;
    this.iconPath = ToolCallView.iconFor(record.status);
    this.description = ToolCallView.durationOf(record);
    this.tooltip = new vscode.MarkdownString(
      `**${record.name}**\n\n\`\`\`\n${record.argsSummary}\n\`\`\``,
    );
  }
}

class DetailNode extends vscode.TreeItem {
  constructor(label: string, body: string | undefined) {
    super(label, vscode.TreeItemCollapsibleState.None);
    this.description = body ? body.slice(0, 120) : '(空)';
    this.tooltip = body;
  }
}

export class ToolCallView implements vscode.TreeDataProvider<TreeItem> {
  private _onDidChange = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  constructor(private readonly chat: ChatProvider) {
    this.chat.onChange(() => this._onDidChange.fire());
  }

  static buildLabel(t: ToolCallRecord): string {
    return t.name;
  }

  static durationOf(t: ToolCallRecord): string {
    if (!t.endedAt) {
      return '运行中…';
    }
    return `${((t.endedAt - t.startedAt) / 1000).toFixed(1)}s`;
  }

  static iconFor(status: ToolCallRecord['status']): vscode.ThemeIcon {
    switch (status) {
      case 'running':
        return new vscode.ThemeIcon('sync~spin', new vscode.ThemeColor('icon.debugging-breakpoint-hoverForeground'));
      case 'completed':
        return new vscode.ThemeIcon('check', new vscode.ThemeColor('testing.iconPassed'));
      case 'failed':
        return new vscode.ThemeIcon('error', new vscode.ThemeColor('testing.iconFailed'));
      default:
        return new vscode.ThemeIcon('circle');
    }
  }

  getTreeItem(element: TreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: TreeItem): vscode.ProviderResult<TreeItem[]> {
    if (!element) {
      // 顶层：最近 N 条工具调用。
      const state = this.chat.getState();
      const all: ToolCallRecord[] = [];
      for (const m of state.messages) {
        all.push(...m.toolCalls);
      }
      const recent = all.slice(-50).reverse();
      if (recent.length === 0) {
        return [new DetailNode('（暂无工具调用）', 'Agent 执行任务后，这里会列出每一次工具调用。')];
      }
      return recent.map((r) => new ToolCallNode(r));
    }
    if (element instanceof ToolCallNode) {
      return [
        new DetailNode('参数', element.record.argsSummary),
        new DetailNode('结果', element.record.result),
        new DetailNode('错误', element.record.error),
      ];
    }
    return [];
  }
}
