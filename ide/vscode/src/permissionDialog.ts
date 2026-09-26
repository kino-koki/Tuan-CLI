/**
 * permissionDialog.ts — 权限确认对话框。
 *
 * 当 ACP 服务端推送 permission_request 时，弹出 VS Code 模态框
 * （window.showInformationMessage）让用户选择：
 *   - Approve Once      仅本次放行
 *   - Approve Always    在本会话内对该工具名不再询问
 *   - Deny              拒绝
 *
 * 选择通过 ChatProvider.resolvePermission 回写给 `qxt acp`。
 *
 * 设计参考 Claude Code：危险操作不会静默执行，必须由用户显式确认；
 * 同时提供 "Approve Always" 减少重复确认的疲劳。
 */

import * as vscode from 'vscode';
import { ChatProvider } from './chatProvider';

export class PermissionDialog {
  private disposables: vscode.Disposable[] = [];
  /** 会话级"总是允许"的工具名集合。 */
  private alwaysAllow = new Set<string>();

  constructor(private readonly chat: ChatProvider) {
    this.chat.onChange(() => this.maybeShow());
  }

  private maybeShow(): void {
    const state = this.chat.getState();
    const p = state.pendingPermission;
    if (!p) {
      return;
    }

    // 从 description 里粗略提取工具名（permission_request 本身不带 toolCall.name，
    // 但 description 通常包含）。命中"总是允许"就直接放行。
    const guessedTool = this.guessToolName(p.description);
    if (guessedTool && this.alwaysAllow.has(guessedTool)) {
      void this.chat.resolvePermission('approve_always');
      return;
    }

    const message = `青小团请求执行：${p.description}`;
    const approveOnce = 'Approve Once';
    const approveAlways = 'Approve Always';
    const deny = 'Deny';

    void vscode.window
      .showInformationMessage(message, { modal: true, detail: 'Agent 想执行一个需要确认的操作。' }, approveOnce, approveAlways, deny)
      .then((choice) => {
        if (choice === approveOnce) {
          void this.chat.resolvePermission('approve_once');
        } else if (choice === approveAlways) {
          if (guessedTool) {
            this.alwaysAllow.add(guessedTool);
          }
          void this.chat.resolvePermission('approve_always');
        } else {
          // 用户关闭对话框或选 Deny。
          void this.chat.resolvePermission('reject');
        }
      });
  }

  /** 从描述文本里猜工具名（形如 "execute_command: ls -la" / "edit_file(src/foo.py)"）。 */
  private guessToolName(desc: string): string | null {
    const m = desc.match(/^\s*([a-zA-Z_][a-zA-Z0-9_\-]*)/);
    return m ? m[1] : null;
  }

  dispose(): void {
    for (const d of this.disposables) {
      d.dispose();
    }
  }
}
