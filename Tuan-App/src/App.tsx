import { useEffect, useMemo, useRef, useState } from 'react';
import Sidebar from './components/Sidebar';
import ChatView from './components/ChatView';
import ChatsPage from './components/ChatsPage';
import ProjectsPage, { type Project } from './components/ProjectsPage';
import ArtifactsPage from './components/ArtifactsPage';
import SettingsPage from './components/SettingsPage';
import SkillsPage from './components/SkillsPage';
import McpPage from './components/McpPage';
import PluginsPage from './components/PluginsPage';
import GuidePage from './components/GuidePage';
import DocsPage from './components/DocsPage';
import ErrorBoundary from './components/ErrorBoundary';
import type { PageKey } from './components/Sidebar';
import TitleBar from './components/TitleBar';
import CommandPalette, { type PaletteAction } from './components/CommandPalette';
import BootScreen, { type BootEngineStatus } from './components/BootScreen';
import EngineSetupPage from './components/EngineSetupPage';
import { engineChat, setEngineAvailable, isAndroid } from './platform/engine';
import { speakWithSettings, stopSpeech } from './platform/tts';
import {
  attachBackNav,
  attachKeyboardAvoidance,
  attachMenuKey,
  attachOrientation,
  installNav,
} from './platform/mobile';
import { getMode, MODES, needsConfirmSwitch, platformBlockReason, type ModeId } from './platform/modes';
import { ttsStatus } from './platform/tts';
import { store, applyTheme, uid } from './store/config';
import type { Conversation, PendingApproval, Provider, ToolEvent } from './types';
import { invoke, isTauri } from '@tauri-apps/api/core';
import {
  MessageSquarePlus,
  MessageCircle,
  FileText,
  Code2,
  Palette,
  Zap,
  Cpu,
  Server,
  FolderKanban,
  Package,
  Wrench,
  Blocks,
  Puzzle,
  BookOpen,
  BookText,
  Settings,
  SunMoon,
} from 'lucide-react';
import { DOC_ARTICLES } from './docs/articles';

/** 五模式在命令面板中的图标（modes.ts 只存语义，图标属表现层，在此映射） */
const MODE_ICONS: Record<ModeId, React.ReactNode> = {
  chat: <MessageCircle size={16} />,
  collaboration: <FileText size={16} />,
  lingma: <Code2 size={16} />,
  gantong: <Palette size={16} />,
  boundless: <Zap size={16} />,
};

export default function App() {
  type View = 'chat' | PageKey;
  const [page, setPage] = useState<View>('chat');
  const [collapsed, setCollapsed] = useState(false);
  // ⌘K 命令面板开关（Claude Code 桌面标志性交互）
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [narrow, setNarrow] = useState(
    () => typeof window !== 'undefined' && window.innerWidth < 820,
  );
  const isNarrow = () => narrow;
  const [theme, setTheme] = useState<'light' | 'dark'>(() => store.theme());
  const [agentMode, setAgentMode] = useState<boolean>(() => store.agentMode());
  const [mode, setMode] = useState<ModeId>(() => store.mode());
  const [providers, setProviders] = useState<Provider[]>(() => store.providers());
  const [convs, setConvs] = useState<Conversation[]>(() => store.conversations());
  const [projects, setProjects] = useState<Project[]>(() => store.projects<Project>());
  const [activeId, setActiveId] = useState<string | undefined>();
  const [providerId, setProviderId] = useState<string>(() => store.providerId());
  const [model, setModel] = useState<string>(() => store.model());
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState('');
  const [tools, setTools] = useState<ToolEvent[]>([]);
  const [approval, setApproval] = useState<PendingApproval | null>(null);
  const [online, setOnline] = useState(() => navigator.onLine);
  const abortRef = useRef<AbortController | null>(null);
  // 启动加载序列（豆包 × CodeX 风格）：引擎自检返回前不消失
  const [booting, setBooting] = useState(true);
  // 引擎安装向导：桌面端引擎缺失时自动弹出，也可从标题栏状态灯手动打开
  const [setupOpen, setSetupOpen] = useState(false);
  // 技术文档模块：当前文章 id（命令面板可深链到具体文章）
  const [docId, setDocId] = useState<string>(() => DOC_ARTICLES[0]?.id ?? '');
  // 引擎状态：启动时检查，用于显示状态指示器 + 引擎不可用时降级直连
  const [engineStatus, setEngineStatus] = useState<BootEngineStatus>({
    ok: false,
    reason: '',
    python: '',
  });
  /** 引擎自检是否已有过一次真实返回（决定 BootScreen 第三行何时落笔） */
  const [engineChecked, setEngineChecked] = useState(false);

  const applyEngineResult = (r: any) => {
    const next: BootEngineStatus = {
      ok: !!r.ok,
      reason: r.reason ?? '',
      python: r.python ?? '',
      app_version: r.app_version,
      engine_version: r.engine_version,
      engine_root: r.engine_root,
    };
    setEngineAvailable(next.ok);
    setEngineStatus(next);
    setEngineChecked(true);
    return next;
  };

  /** 重新检测引擎：安装向导第 4 步的真实回调 */
  const recheckEngine = async (): Promise<BootEngineStatus> => {
    if (!isTauri()) return { ok: false, reason: '非 Tauri 环境', python: '' };
    const r: any = await invoke('check_engine');
    return applyEngineResult(r);
  };

  // 启动时引擎自检
  useEffect(() => {
    if (!isTauri()) {
      setEngineChecked(true);
      return;
    }
    let cancelled = false;
    invoke('check_engine')
      .then((r: any) => {
        if (cancelled) return;
        applyEngineResult(r);
      })
      .catch((e) => {
        if (cancelled) return;
        setEngineAvailable(false);
        setEngineStatus({ ok: false, reason: String(e), python: '' });
        setEngineChecked(true);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const onResize = () => {
      const n = typeof window !== 'undefined' && window.innerWidth < 820;
      setNarrow(n);
      if (n) setCollapsed(true);
    };
    onResize();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  useEffect(() => applyTheme(theme), [theme]);
  useEffect(() => store.saveAgentMode(agentMode), [agentMode]);
  useEffect(() => store.saveMode(mode), [mode]);
  useEffect(() => store.saveProviders(providers), [providers]);
  useEffect(() => store.saveProviderId(providerId), [providerId]);
  useEffect(() => store.saveModel(model), [model]);
  useEffect(() => store.saveConversations(convs), [convs]);
  useEffect(() => store.saveProjects(projects), [projects]);

  // 五模式切换：被平台禁用的模式直接拒绝（无界在安卓端）；
  // 切到无界（L4 高权限）时先做风险披露 + 二次确认，不允许静默升级。
  const changeMode = (next: ModeId) => {
    if (next === mode) return;
    const blocked = platformBlockReason(next);
    if (blocked) {
      window.alert(blocked);
      return;
    }
    if (needsConfirmSwitch(mode, next)) {
      const spec = getMode(next);
      const ok = window.confirm(
        `切换到「${spec.name}」模式？\n\n` +
          `权限：${spec.level} · 风险：${spec.risk}\n\n` +
          `${spec.desc}\n\n` +
          `该模式放宽权限限制，但安全闸门仍然生效；不可逆操作（删除、覆盖、执行脚本）会先弹确认。`,
      );
      if (!ok) return;
    }
    setMode(next);
  };

  // 在线/离线检测
  useEffect(() => {
    const handleOnline = () => setOnline(true);
    const handleOffline = () => setOnline(false);
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  // 全局快捷键（桌面端 ⌘ / Windows Ctrl 双覆盖，对齐 Claude Code 桌面习惯）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey;
      if (!mod) return;
      const k = e.key.toLowerCase();
      // ⌘N: 新建对话
      if (k === 'n') {
        e.preventDefault();
        newChat();
      }
      // ⌘K: 命令面板
      else if (k === 'k') {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
      // ⌘O: 打开设置
      else if (k === 'o') {
        e.preventDefault();
        setPage('settings');
      }
      // ⌘,: 打开设置（桌面端惯例，与 ⌘O 等价）
      else if (e.key === ',') {
        e.preventDefault();
        setPage('settings');
      }
      // ⌘G: 打开指南
      else if (k === 'g') {
        e.preventDefault();
        setPage('guide');
      }
      // ⌘B: 切换侧栏
      else if (k === 'b') {
        e.preventDefault();
        setCollapsed((c) => !c);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // ===== 移动端 / 原生壳适配（W-2 / W-3 / W-7 / W-8）=====
  // 侧栏抽屉、伪路由返回栈、横竖屏复位、软键盘避让四件事的触发源各不相同
  // （硬件菜单键 / 浏览器 popstate / orientationchange / resize），统一在
  // platform/mobile.ts 里接线，这里只给出「该退哪一层」的业务语义。
  const navRef = useRef({ page, collapsed, approval: null as PendingApproval | null });
  useEffect(() => {
    navRef.current = { page, collapsed, approval };
  }, [page, collapsed, approval]);

  useEffect(() => {
    const canGoBack = () => {
      const s = navRef.current;
      // 审批弹窗算一层；非聊天页算一层；窄屏下侧栏仍展开也算一层
      // （三者任一在栈里都能让原生壳吞掉物理返回键，不把应用踢出）
      return !!s.approval || s.page !== 'chat' || (!s.collapsed && isNarrow());
    };
    const goBack = () => {
      const s = navRef.current;
      if (s.approval) {
        // 返回键视为「拒绝」：引擎阻塞在 _ask_approval 等答复，
        // 必须回传 deny 才能解除阻塞，否则审批卡悬着、生成也不动
        setApproval(null);
        invoke('engine_approve', { id: s.approval.id, decision: 'deny' }).catch(() => {});
        return;
      }
      if (s.page !== 'chat') {
        setPage('chat');
        return;
      }
      if (!s.collapsed && isNarrow()) setCollapsed(true);
    };
    const toggleSidebar = () => setCollapsed((c) => !c);
    const resetLayout = () => {
      // 横竖屏切换后收掉可能残留的侧栏抽屉，避免覆盖在错误位置上
      if (isNarrow()) setCollapsed(true);
    };

    const cleanupNav = installNav({
      toggleSidebar,
      back: goBack,
      canBack: canGoBack,
      onOrientation: resetLayout,
    });
    const offMenu = attachMenuKey(toggleSidebar);
    const offBack = attachBackNav({ canGoBack, goBack });
    const offOrient = attachOrientation({ onChange: resetLayout });
    const offKb = attachKeyboardAvoidance({ selector: '#inputbar' });
    return () => {
      cleanupNav();
      offMenu();
      offBack();
      offOrient();
      offKb();
    };
    // 只挂载时接一次线；内部通过 navRef 读最新状态
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // W-3 伪路由：切到非聊天页、或弹出审批卡时补一层浏览器历史，让原生返回键 /
  // popstate 能退回来；全部关掉时 replaceState 复位，保证历史栈里最多只有一层，
  // 不会出现连退三次。
  useEffect(() => {
    if (!window.history || typeof window.history.pushState !== 'function') return;
    try {
      if (page === 'chat' && !approval) window.history.replaceState(null, '', window.location.href);
      else window.history.pushState(null, '', window.location.href);
    } catch {
      /* file:// 等受限来源不允许写 history，忽略 */
    }
  }, [page, approval]);

  const activeConv = useMemo(
    () => convs.find((c) => c.id === activeId),
    [convs, activeId],
  );

  const newChat = () => {
    setActiveId(undefined);
    setError('');
    setPage('chat');
  };

  const openConv = (id: string) => {
    setActiveId(id);
    setError('');
    setPage('chat');
  };

  // ⌘K 命令面板动作表：随状态实时重建（约 20 项，构建成本可忽略）。
  // 模式项带风险提示，L4（无界）用危险色描边；模型/供应商反映当前可用集合。
  const paletteActiveProvider = providers.find((p) => p.id === providerId) ?? providers[0];
  const paletteModels = paletteActiveProvider?.models.filter((m) => m.enabled) ?? [];
  const paletteActions: PaletteAction[] = [
    {
      id: 'new-chat',
      label: '新建对话',
      group: '对话',
      icon: <MessageSquarePlus size={16} />,
      shortcut: '⌘N',
      run: newChat,
    },
    ...MODES.map((m): PaletteAction => ({
      id: `mode-${m.id}`,
      label: `切换到「${m.name}」模式`,
      group: '模式',
      icon: MODE_ICONS[m.id],
      hint: m.tagline,
      danger: m.level === 'L4',
      keywords: `${m.name} ${m.tagline} mode ${m.level}`,
      run: () => changeMode(m.id),
    })),
    ...paletteModels.slice(0, 15).map((m): PaletteAction => ({
      id: `model-${m.id}`,
      label: m.name,
      group: '模型',
      icon: <Cpu size={16} />,
      hint: paletteActiveProvider?.name,
      keywords: m.id,
      run: () => setModel(m.id),
    })),
    ...providers.map((p): PaletteAction => ({
      id: `provider-${p.id}`,
      label: p.name,
      group: '供应商',
      icon: <Server size={16} />,
      hint: p.id === providerId ? '当前' : undefined,
      run: () => setProviderId(p.id),
    })),
    ...[
      { key: 'chats' as PageKey, label: '聊天记录', icon: <MessageCircle size={16} /> },
      { key: 'projects' as PageKey, label: '项目', icon: <FolderKanban size={16} /> },
      { key: 'artifacts' as PageKey, label: '成品', icon: <Package size={16} /> },
      { key: 'skills' as PageKey, label: '技能', icon: <Wrench size={16} /> },
      { key: 'mcp' as PageKey, label: 'MCP 服务', icon: <Blocks size={16} /> },
      { key: 'plugins' as PageKey, label: '插件', icon: <Puzzle size={16} /> },
      { key: 'guide' as PageKey, label: '使用教程', icon: <BookOpen size={16} /> },
      { key: 'docs' as PageKey, label: '技术文档', icon: <BookText size={16} /> },
      { key: 'settings' as PageKey, label: '设置', icon: <Settings size={16} />, shortcut: '⌘,' },
    ].map((n): PaletteAction => ({
      id: `nav-${n.key}`,
      label: n.label,
      group: '导航',
      icon: n.icon,
      hint: page === n.key ? '当前' : undefined,
      shortcut: n.shortcut,
      run: () => setPage(n.key),
    })),
    // 技术文档：全部文章进命令面板，可搜索 + 深链到具体一篇
    ...DOC_ARTICLES.map((a): PaletteAction => ({
      id: `doc-${a.id}`,
      label: a.title,
      group: '技术文档',
      icon: <BookText size={16} />,
      hint: a.summary,
      keywords: `${a.keywords ?? ''} docs 文档`,
      run: () => {
        setPage('docs');
        setDocId(a.id);
      },
    })),
    {
      id: 'sys-theme',
      label: theme === 'dark' ? '切换到浅色主题' : '切换到深色主题',
      group: '系统',
      icon: <SunMoon size={16} />,
      keywords: 'theme dark light 主题',
      run: () => setTheme(theme === 'dark' ? 'light' : 'dark'),
    },
    {
      id: 'sys-engine-setup',
      label: '引擎安装向导',
      group: '系统',
      icon: <Wrench size={16} />,
      hint: engineStatus.ok ? '引擎已就绪' : '本地引擎未就绪',
      keywords: 'engine setup install 引擎 安装 向导',
      run: () => setSetupOpen(true),
    },
  ];

  const send = async (text: string) => {
    const provider = providers.find((p) => p.id === providerId) ?? providers[0];
    if (!provider) {
      setError('请先在「设置」添加供应商。');
      return;
    }
    const chosenModel = model || provider.models.find((m) => m.enabled)?.id;
    if (!chosenModel) {
      setError('当前供应商没有可用模型，请在设置中获取模型。');
      return;
    }
    setError('');
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    // 新消息发出时打断正在播放的语音（旧回复/新回复不同时出声）
    stopSpeech();

    let conv = activeConv;
    if (!conv) {
      conv = {
        id: uid(),
        title: text.slice(0, 24),
        createdAt: Date.now(),
        updatedAt: Date.now(),
        providerId: provider.id,
        model: chosenModel,
        messages: [],
      };
      // 关键：先把新对话写进状态，后续 patch 才能按 id 命中并渲染消息/输出
      setConvs((prev) => [conv!, ...prev]);
      setActiveId(conv.id);
    }
    const userMsg = { id: uid(), role: 'user' as const, content: text, ts: Date.now() };
    const assistantId = uid();
    const history = [...conv.messages, userMsg];

    const patch = (messages: typeof conv.messages, title?: string) => {
      setConvs((prev) =>
        prev.map((c) =>
          c.id === conv!.id
            ? { ...c, messages, updatedAt: Date.now(), ...(title ? { title } : {}) }
            : c,
        ),
      );
    };
    patch([...conv.messages, userMsg], conv.messages.length === 0 ? userMsg.content.slice(0, 24) : undefined);

    setStreaming(true);
    setTools([]);
    setApproval(null);
    let acc = '';
    let reasonAcc = '';
    let completed = false;
    try {
      // 引擎通道：桌面端由引擎承载完整提示词/工具/安全闸门，session 复用对话 id 续接上下文。
      // history 一并传入：安卓端无本地引擎，走 Rust agent 通道时需要它拼多轮上下文。
      const gen = engineChat(provider, chosenModel, text, conv.id, ctrl.signal, history, {
        agentMode,
      });
      for await (const chunk of gen) {
        if (chunk.type === 'text' && chunk.text) {
          acc += chunk.text;
          patch([
            ...history,
            {
              id: assistantId,
              role: 'assistant',
              content: acc,
              ts: Date.now(),
              model: chosenModel,
              ...(reasonAcc ? { reasoning: reasonAcc } : {}),
            },
          ]);
        } else if (chunk.type === 'reason' && chunk.text) {
          reasonAcc += chunk.text;
          patch([
            ...history,
            {
              id: assistantId,
              role: 'assistant',
              content: acc,
              ts: Date.now(),
              model: chosenModel,
              reasoning: reasonAcc,
            },
          ]);
        } else if (chunk.type === 'tool') {
          setTools((prev) => [
            ...prev,
            { name: chunk.name ?? '工具', args: chunk.args, status: 'running' },
          ]);
        } else if (chunk.type === 'tool_result') {
          const failed = /^err|fail|错误|失败/i.test(chunk.out ?? '');
          setTools((prev) =>
            prev.map((t) =>
              t.name === chunk.name
                ? { ...t, status: failed ? 'error' : 'done', out: chunk.out }
                : t,
            ),
          );
        } else if (chunk.type === 'approval') {
          // 引擎安全闸门：阻塞等待我们答复。不落进任何消息文本，单独弹审批卡。
          setApproval({
            id: chunk.name ?? '',
            prompt: chunk.text ?? '',
            verdict: chunk.args,
          });
        } else if (chunk.type === 'error') {
          setError(chunk.error ?? '请求失败');
          // 出错且没有任何正文时，去掉空的助手占位消息
          if (!acc) patch([...history]);
        } else if (chunk.type === 'done') {
          completed = true;
          break;
        }
      }
    } catch (e) {
      // 用户主动点「停止生成」触发的 AbortError 不报错
      const aborted =
        (e instanceof DOMException && e.name === 'AbortError') ||
        (e instanceof Error && /aborted|中止|取消/i.test(e.message));
      if (!aborted) setError(e instanceof Error ? e.message : '请求失败');
    } finally {
      setStreaming(false);
      abortRef.current = null;
      setTools([]);
      setApproval(null);
      // 完整回复到达后，按用户设置自动朗读（完全本地 MOSS-TTS-Nano）
      if (completed && acc.trim() && store.ttsEnabled()) {
        speakWithSettings(acc.trim()).catch(() => {});
      }
    }
  };

  const stop = () => {
    abortRef.current?.abort();
    setStreaming(false);
  };

  const deleteConv = (id: string) => {
    setConvs((prev) => prev.filter((c) => c.id !== id));
    if (activeId === id) setActiveId(undefined);
  };

  const renameConv = (id: string, title: string) => {
    setConvs((prev) =>
      prev.map((c) => (c.id === id ? { ...c, title, updatedAt: Date.now() } : c)),
    );
  };

  const deleteMessage = (msgId: string) => {
    if (!activeId) return;
    setConvs((prev) =>
      prev.map((c) =>
        c.id === activeId
          ? { ...c, messages: c.messages.filter((m) => m.id !== msgId), updatedAt: Date.now() }
          : c,
      ),
    );
  };

  const editMessage = (msgId: string, newText: string) => {
    if (!activeId) return;
    setConvs((prev) =>
      prev.map((c) =>
        c.id === activeId
          ? {
              ...c,
              messages: c.messages.map((m) =>
                m.id === msgId ? { ...m, content: newText, ts: Date.now() } : m,
              ),
              updatedAt: Date.now(),
            }
          : c,
      ),
    );
  };

  /** 重试：找到最后一条用户消息并重新发送 */
  const retry = () => {
    if (!activeConv || !activeConv.messages.length) return;
    const lastUserMsg = [...activeConv.messages].reverse().find((m) => m.role === 'user');
    if (lastUserMsg) {
      // 先删除最后一条助手消息（如果有的话）
      const lastMsg = activeConv.messages[activeConv.messages.length - 1];
      if (lastMsg.role === 'assistant') {
        setConvs((prev) =>
          prev.map((c) =>
            c.id === activeId
              ? { ...c, messages: c.messages.slice(0, -1), updatedAt: Date.now() }
              : c,
          ),
        );
      }
      send(lastUserMsg.content);
    }
  };

  /** 危险操作审批回传：引擎阻塞在 _ask_approval，答复后继续执行。 */
  const approve = async (id: string, decision: 'allow' | 'deny') => {
    setApproval(null);
    await invoke('engine_approve', { id, decision }).catch(() => {});
  };

  const createProject = (data: Omit<Project, 'id' | 'createdAt'>) => {
    setProjects((prev) => [{ id: uid(), createdAt: Date.now(), ...data }, ...prev]);
  };

  const updateProject = (id: string, data: Omit<Project, 'id' | 'createdAt'>) => {
    setProjects((prev) => prev.map((p) => (p.id === id ? { ...p, ...data } : p)));
  };

  const deleteProject = (id: string) => {
    setProjects((prev) => prev.filter((p) => p.id !== id));
  };

  // 桌面端（Windows/macOS）引擎缺失 → 走安装引导；Android 本就没有本地引擎，不弹
  const engineMissing = isTauri() && !isAndroid() && engineChecked && !engineStatus.ok;
  const setupAuto = engineMissing && !store.engineSetupDismissed();
  const showSetup = setupAuto || setupOpen;

  // 启动加载序列：引擎自检真实返回前不消失（BootScreen 内部等待）
  if (booting) {
    return (
      <BootScreen
        engineStatus={engineChecked ? engineStatus : null}
        onDone={() => setBooting(false)}
      />
    );
  }

  // 引擎安装引导（豆包 × CodeX 风格）：自动弹出或从标题栏/命令面板手动打开
  if (showSetup) {
    return (
      <EngineSetupPage
        engineStatus={engineStatus}
        manual={setupOpen && !setupAuto}
        onRecheck={recheckEngine}
        onEnterDegraded={() => {
          if (setupAuto) store.saveEngineSetupDismissed(true);
          setSetupOpen(false);
        }}
        onReady={() => {
          setSetupOpen(false);
          setPage('chat');
        }}
      />
    );
  }

  return (
    <div className="h-full flex flex-col bg-tuan-main app-shell">
      <TitleBar
        onToggleSidebar={() => setCollapsed((c) => !c)}
        onOpenPalette={() => setPaletteOpen(true)}
        engineMissing={engineMissing}
        onOpenSetup={() => setSetupOpen(true)}
      />
      {/* 离线提示 */}
      {!online && (
        <div className="flex items-center justify-center gap-2 bg-amber-50 dark:bg-amber-950/30 border-b border-amber-200 dark:border-amber-800 px-4 py-2 text-[12.5px] text-amber-800 dark:text-amber-300">
          <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
          当前处于离线状态，部分功能可能无法使用
        </div>
      )}
      <div className="flex-1 flex min-h-0">
      <ErrorBoundary>
        {!collapsed && (
          <>
            <div
              className="sidebar-scrim fixed inset-0 z-40 bg-black/30 md:hidden"
              onClick={() => setCollapsed(true)}
            />
            <div className="sidebar-drawer fixed inset-y-0 left-0 z-50 md:static md:z-auto md:block shadow-xl md:shadow-none">
              <Sidebar
                page={page === 'chat' ? 'chats' : page}
                onNavigate={(p) => {
                  setPage(p);
                  if (narrow) setCollapsed(true);
                }}
                onNewChat={() => {
                  newChat();
                  if (narrow) setCollapsed(true);
                }}
                recent={convs.map((c) => ({ id: c.id, title: c.title, ts: c.updatedAt }))}
                activeId={activeId}
              onOpenConv={(id) => {
                openConv(id);
                if (narrow) setCollapsed(true);
              }}
              onRename={renameConv}
              onDelete={deleteConv}
                collapsed={false}
                isNarrow={narrow}
            />
          </div>
        </>
      )}
      {/* 桌面端折叠：64px 图标轨（Claude Code 桌面风格），不渲染遮罩 */}
      {collapsed && !narrow && (
        <Sidebar
          page={page === 'chat' ? 'chats' : page}
          onNavigate={(p) => setPage(p)}
          onNewChat={() => newChat()}
          recent={convs.map((c) => ({ id: c.id, title: c.title, ts: c.updatedAt }))}
          activeId={activeId}
          onOpenConv={openConv}
          onRename={renameConv}
          onDelete={deleteConv}
          collapsed={true}
          isNarrow={false}
        />
      )}

      {page === 'chat' && (
        <ChatView
          convId={activeId}
          providers={providers}
          providerId={providerId || providers[0]?.id}
          model={model}
          onProviderChange={(id) => {
            setProviderId(id);
            setModel('');
          }}
          onModelChange={setModel}
          messages={activeConv?.messages ?? []}
          title={activeConv?.title}
          streaming={streaming}
          error={error}
          tools={tools}
          approval={approval}
          onApprove={approve}
          onSend={send}
          onStop={stop}
          onDeleteMessage={deleteMessage}
          onEditMessage={editMessage}
          onRetry={retry}
          onOpenGuide={() => setPage('guide')}
          onOpenSettings={() => setPage('settings')}
          mode={mode}
          onModeChange={changeMode}
          onNewChat={newChat}
          onOpenPalette={() => setPaletteOpen(true)}
        />
      )}
      {page === 'chats' && (
        <ChatsPage
          conversations={convs}
          activeId={activeId}
          onOpen={openConv}
          onDelete={deleteConv}
          onRename={renameConv}
        />
      )}
      {page === 'projects' && (
        <ProjectsPage projects={projects} onCreate={createProject} onUpdate={updateProject} onDelete={deleteProject} />
      )}
      {page === 'artifacts' && <ArtifactsPage />}
      {page === 'skills' && <SkillsPage />}
      {page === 'mcp' && <McpPage />}
      {page === 'plugins' && <PluginsPage />}
      {page === 'guide' && <GuidePage />}
      {page === 'docs' && <DocsPage activeId={docId} onActiveChange={setDocId} />}
      {page === 'settings' && (
        <SettingsPage
          providers={providers}
          onChange={setProviders}
          agentMode={agentMode}
          onAgentModeChange={setAgentMode}
          theme={theme}
          onThemeChange={setTheme}
          mode={mode}
          onModeChange={changeMode}
          onClearConversations={() => {
            setConvs([]);
            setActiveId(undefined);
          }}
            engineStatus={engineStatus}
          />
        )}
        </ErrorBoundary>
      </div>
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        actions={paletteActions}
      />
      {/* Claude Code 式底部状态栏：模式 · 模型 · 引擎 · TTS · 会话数 */}
      <StatusBar
        mode={mode}
        providerLabel={providerId ? `${providers.find((p) => p.id === providerId)?.name ?? ''}${model ? ' · ' + model : ''}` : ''}
        engineStatus={engineStatus}
        convCount={convs.length}
      />
    </div>
  );
}

/** Claude Code 终端式单行状态栏。TTS 状态每 15s 轮询一次引擎。 */
function StatusBar({
  mode,
  providerLabel,
  engineStatus,
  convCount,
}: {
  mode: ModeId;
  providerLabel: string;
  engineStatus?: { ok: boolean; reason: string; python: string };
  convCount: number;
}) {
  const [tts, setTts] = useState<{ reachable: boolean; loaded: boolean } | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = () => {
      if (isAndroid()) {
        setTts({ reachable: true, loaded: true }); // 安卓走系统原生 TTS
        return;
      }
      ttsStatus()
        .then((s) => {
          if (alive) setTts(s ? { reachable: true, loaded: s.model_loaded } : null);
        })
        .catch(() => {
          if (alive) setTts(null);
        });
    };
    tick();
    const t = setInterval(tick, 15000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);
  const m = getMode(mode);
  return (
    <div className="cc-statusbar">
      <span className="sb-group sb-label" style={{ color: 'var(--tuan-accent-soft)', fontWeight: 700 }}>
        ❯ {m.name}
      </span>
      <span className="sb-sep" />
      <span className="sb-group sb-hide-mobile" title={providerLabel || '未配置模型'}>
        <span className="sb-label truncate max-w-[220px]">{providerLabel || '未配置模型'}</span>
      </span>
      <span className="sb-sep sb-hide-mobile" />
      <span className="sb-group" title={engineStatus?.reason ?? ''}>
        <span
          className="sb-dot"
          style={{
            background:
              engineStatus?.ok === true
                ? 'var(--tuan-ok)'
                : engineStatus == null
                  ? 'var(--text-tuan-secondary)'
                  : 'var(--tuan-danger)',
          }}
        />
        <span className="sb-label">
          {engineStatus?.ok === true
            ? '引擎就绪'
            : engineStatus == null
              ? '引擎检测中'
              : '引擎未就绪'}
        </span>
      </span>
      <span className="sb-sep" />
      <span className="sb-group" title="本地 TTS（MOSS-TTS-Nano，安卓为系统原生）">
        <span
          className="sb-dot"
          style={{ background: tts ? (tts.loaded ? 'var(--tuan-ok)' : 'var(--tuan-accent-soft)') : 'var(--text-tuan-secondary)' }}
        />
        <span className="sb-label">
          {isAndroid() ? '系统 TTS' : tts ? (tts.loaded ? 'TTS 就绪' : 'TTS 待加载') : 'TTS 离线'}
        </span>
      </span>
      <span className="sb-sep sb-hide-mobile" />
      <span className="sb-group sb-label sb-hide-mobile">会话 {convCount}</span>
    </div>
  );
}
