/**
 * diffPreview.ts — 行内 diff 预览。
 *
 * 当 Agent 调用代码编辑类工具（edit_file / write_to_file / str_replace_based_edit_tool /
 * apply_diff 等）完成后，在对应的编辑器里用 TextEditorDecorationType 显示：
 *   - 绿色背景：新增行
 *   - 红色背景：删除行（gutter 或整行装饰）
 *
 * 说明：当前 ACP server 上报的 tool_call description / result 是被截断的纯文本摘要，
 * 没有结构化的 old/new 文件内容。因此这里采取"尽力而为"策略：
 *   1. 从工具名 + 参数摘要里正则提取目标文件路径。
 *   2. 如果该文件此时在编辑器中打开，在对应行区间加一个"已被 Agent 修改"的高亮装饰。
 *   3. 后续 ACP 增强（结构化 edit 事件）落地后，再升级为真正的 unified diff。
 *
 * 设计参考：Claude Code 的 inline diff —— 在原文件里直接看到绿色/红色的行级高亮，
 * 而不是必须打开 diff 视图。
 */

import * as vscode from 'vscode';
import { ChatProvider } from './chatProvider';
import { ToolCallRecord } from './types';

/** 判定一个工具调用是否属于"代码编辑类"。 */
const EDIT_TOOL_PATTERNS = [
  /edit/i,
  /write_file/i,
  /str_replace/i,
  /apply_diff/i,
  /patch/i,
  /^write$/i,
];

/** 从参数摘要里提取看起来像文件路径的 token。 */
const FILE_PATH_RE = /(?:^|[\s"'(])([A-Za-z]:[\\\/][^\s"'()]+|[\/~][^\s"'()]+|[a-zA-Z0-9_\-\/\\]+\.[a-zA-Z0-9]{1,8})(?=["'\s)]|$)/g;

export class DiffPreview {
  private addDecoration: vscode.TextEditorDecorationType;
  private delDecoration: vscode.TextEditorDecorationType;
  /** 每个 editor 当前挂着的装饰 id，用于清理。 */
  private decorationsByEditor = new Map<vscode.TextEditor, vscode.Disposable[]>();

  constructor(private readonly chat: ChatProvider) {
    // 绿色：新增行
    this.addDecoration = vscode.window.createTextEditorDecorationType({
      backgroundColor: 'rgba(35, 165, 122, 0.18)',
      isWholeLine: true,
      overviewRulerColor: 'rgba(35, 165, 122, 0.6)',
      overviewRulerLane: vscode.OverviewRulerLane.Left,
    });
    // 红色：删除行（在 gutter 上显示一条细条）
    this.delDecoration = vscode.window.createTextEditorDecorationType({
      backgroundColor: 'rgba(241, 76, 76, 0.12)',
      isWholeLine: true,
      overviewRulerColor: 'rgba(241, 76, 76, 0.6)',
      overviewRulerLane: vscode.OverviewRulerLane.Left,
    });

    this.chat.onChange(() => this.scanCompletedTools());
  }

  private isEditTool(name: string): boolean {
    return EDIT_TOOL_PATTERNS.some((re) => re.test(name));
  }

  /** 扫描最近完成的工具调用，命中编辑类就尝试挂装饰。 */
  private scanCompletedTools(): void {
    const state = this.chat.getState();
    // 收集所有"刚完成"的编辑工具。
    const editedFiles: vscode.Uri[] = [];
    for (const m of state.messages) {
      for (const t of m.toolCalls) {
        if (t.status !== 'completed' && t.status !== 'failed') {
          continue;
        }
        if (!this.isEditTool(t.name)) {
          continue;
        }
        const uri = this.extractFileUri(t);
        if (uri) {
          editedFiles.push(uri);
        }
      }
    }
    this.highlightOpenEditors(editedFiles);
  }

  private extractFileUri(t: ToolCallRecord): vscode.Uri | null {
    const blob = `${t.argsSummary}\n${t.result ?? ''}`;
    const matches = blob.match(FILE_PATH_RE);
    if (!matches) {
      return null;
    }
    for (const raw of matches) {
      const p = raw.trim().replace(/^["'(]+|["')]+$/g, '');
      if (!p || p.includes(' ') || p.length < 3) {
        continue;
      }
      try {
        return vscode.Uri.file(p);
      } catch {
        // ignore
      }
    }
    return null;
  }

  private highlightOpenEditors(files: vscode.Uri[]): void {
    const enabled = vscode.workspace.getConfiguration('qingxiaotuan').get<boolean>('enableInlineDiff', true);
    if (!enabled) {
      return;
    }
    for (const editor of vscode.window.visibleTextEditors) {
      const isTarget = files.some((u) => u.fsPath === editor.document.uri.fsPath);
      if (!isTarget) {
        continue;
      }
      // 用一个整文件范围的"被修改"高亮（淡绿），作为后续真正 diff 的占位。
      const lineCount = editor.document.lineCount;
      const range = new vscode.Range(0, 0, Math.max(lineCount - 1, 0), 0);
      editor.setDecorations(this.addDecoration, [range]);
    }
  }

  dispose(): void {
    this.addDecoration.dispose();
    this.delDecoration.dispose();
    for (const [, list] of this.decorationsByEditor) {
      list.forEach((d) => d.dispose());
    }
    this.decorationsByEditor.clear();
  }
}
