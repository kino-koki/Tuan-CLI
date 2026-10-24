import { BookOpen, KeyRound, Database, MessageSquare, Palette, Wrench, Blocks, Puzzle, Settings, Keyboard, FolderKanban, Download, Search, Pencil, Trash2 } from 'lucide-react';

const STEPS = [
  {
    icon: KeyRound,
    title: '第一步：打开设置，添加一个供应商',
    body: '点击侧栏「菜单 → 设置」。在「tuan_cli 内置目录」里任选一家（例如 DeepSeek、OpenRouter、硅基流动等），点「选用」，它会自动填好接口地址与格式。',
  },
  {
    icon: Database,
    title: '第二步：填入 API 密钥',
    body: '在密钥框粘贴你在该平台申请的 Key（通常以 sk- 开头）。点「获取模型」可在线拉取该平台模型，也可以直接用目录里已带的全量模型清单。填完点「保存」。',
  },
  {
    icon: MessageSquare,
    title: '第三步：回到对话，选模型并发送',
    body: '在输入框上方选择刚配置的供应商与具体模型，输入消息后按 Enter 发送（Shift+Enter 换行）。不需要本地安装任何模型，填好一个能联网的账号即可开始聊天。',
  },
  {
    icon: Palette,
    title: '样式：助手形象',
    body: '助手形象统一使用二次元立绘，按供应商匹配（资源统一放在 Tuan-App/dist/assets/），明暗主题各一套背景——浅色界面用白底、深色界面用黑底，两张图主体完全一致，切换不会跳画。未收录供应商与聚合 / 中转平台回落到代表立绘。不再有可选开关。',
  },
  {
    icon: Wrench,
    title: '技能：查看与安装',
    body: '「菜单 → 技能」列出 tuan_cli 自带的全部技能，可一键启用；也可以点「安装本地技能」导入自己的 SKILL.md 目录。',
  },
  {
    icon: Blocks,
    title: 'MCP 服务：扩展工具',
    body: '「菜单 → MCP 服务」添加 stdio 本地命令或 SSE 远程地址，为助手接入外部工具。',
  },
  {
    icon: Puzzle,
    title: '插件：扩展能力',
    body: '「菜单 → 插件」添加并管理第三方插件。',
  },
  {
    icon: FolderKanban,
    title: '项目：组织对话',
    body: '「菜单 → 项目」创建项目来组织相关对话。项目是本地标签，不会同步到云端，适合按任务或主题分类管理。',
  },
  {
    icon: Download,
    title: '数据：导出与备份',
    body: '「菜单 → 设置 → 关于 → 数据管理」可导出全部数据（对话、供应商、设置）为 JSON 备份文件，也可从备份文件恢复。单个对话可在「聊天记录」页点导出按钮保存为 Markdown。',
  },
  {
    icon: Search,
    title: '搜索：快速查找对话',
    body: '侧栏顶部搜索框支持按标题快速查找对话（Ctrl+F 聚焦）。搜索结果会实时过滤，清空搜索框即可恢复显示所有对话。',
  },
  {
    icon: Pencil,
    title: '编辑：修改已发送的消息',
    body: '鼠标悬停在已发送的消息上，会出现「编辑」按钮。点击后可修改消息内容，Enter 保存，Escape 取消。编辑后消息时间会更新。',
  },
  {
    icon: Trash2,
    title: '删除：清理不需要的消息',
    body: '鼠标悬停在消息上，点击「删除」按钮可移除单条消息。对话可在侧栏或聊天记录页整段删除。删除操作不可撤销，请谨慎操作。',
  },
  {
    icon: Settings,
    title: '通用说明',
    body: '对话记录、供应商与偏好都保存在本机。Windows 由内嵌 tuan_cli 引擎承载完整 Agent 能力；Android 无本地引擎，走你填写的接口直连与轻量工具循环；两边都只需配置一个可用模型即可开始。',
  },
];

const SHORTCUTS = [
  { keys: 'Ctrl + N', desc: '新建对话' },
  { keys: 'Ctrl + O', desc: '打开设置' },
  { keys: 'Ctrl + G', desc: '打开使用教程' },
  { keys: 'Ctrl + B', desc: '切换侧栏显示/隐藏' },
  { keys: 'Ctrl + F', desc: '聚焦搜索框' },
  { keys: 'Escape', desc: '返回聊天页面' },
  { keys: 'Enter', desc: '发送消息' },
  { keys: 'Shift + Enter', desc: '输入框换行' },
];

export default function GuidePage() {
  return (
    <div className="page-shell flex-1 overflow-y-auto custom-scrollbar">
      <div className="flex items-center gap-2 mb-1">
        <BookOpen size={20} className="text-tuan-textSecondary" />
        <h1 className="text-[20px] font-semibold text-tuan-text">使用教程</h1>
      </div>
      <p className="text-[13.5px] text-tuan-textSecondary mb-6">
        跟着下面八步，从零配置到发出第一条消息。Android 10+ 与 Windows 10 流程一致。
      </p>

      <div className="max-w-[760px] space-y-3">
        {STEPS.map((s, i) => {
          const Icon = s.icon;
          return (
            <div key={i} className="flex gap-4 bg-tuan-input border border-tuan-border rounded-xl px-4 py-4">
              <div className="flex flex-col items-center flex-shrink-0">
                <div className="h-10 w-10 rounded-xl bg-tuan-hover flex items-center justify-center">
                  <Icon size={18} className="text-tuan-textSecondary" />
                </div>
                {i < STEPS.length - 1 && <div className="flex-1 w-px bg-tuan-border mt-2" />}
              </div>
              <div className="min-w-0">
                <div className="text-[15px] font-medium text-tuan-text">{s.title}</div>
                <div className="text-[13.5px] text-tuan-textSecondary mt-1 leading-relaxed">{s.body}</div>
              </div>
            </div>
          );
        })}

        {/* 快捷键 */}
        <div className="border border-tuan-border rounded-xl p-5 bg-tuan-input">
          <div className="flex items-center gap-2 mb-3">
            <Keyboard size={16} className="text-tuan-textSecondary" />
            <span className="text-[15px] font-medium text-tuan-text">快捷键</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {SHORTCUTS.map((s) => (
              <div key={s.keys} className="flex items-center gap-2 text-[13px]">
                <kbd className="px-2 py-0.5 rounded-md bg-tuan-hover text-tuan-text text-[11.5px] font-mono border border-tuan-border">
                  {s.keys}
                </kbd>
                <span className="text-tuan-textSecondary">{s.desc}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
