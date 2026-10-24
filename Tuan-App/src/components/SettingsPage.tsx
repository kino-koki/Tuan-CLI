import { useEffect, useMemo, useState } from 'react';
import {
  Plus,
  Trash2,
  RefreshCw,
  Eye,
  EyeOff,
  Search,
  Check,
  X,
  Settings,
  SlidersHorizontal,
  Palette,
  Server,
  ShieldCheck,
  Info,
  Sun,
  Moon,
  HardDrive,
  KeyRound,
  TerminalSquare,
  Globe,
  Package,
  Sparkles,
  MessageSquare,
  Download,
  Upload,
  ExternalLink,
  Monitor,
  Apple,
  Smartphone,
  Zap,
  LayoutGrid,
  MessageCircle,
  Users,
  CodeXml,
} from 'lucide-react';
import type { ApiFormat, CatalogProvider, Provider } from '../types';
import { MODES, type ModeId } from '../platform/modes';
import { probeModels } from '../platform/engine';
import { sampleImage, DEFAULT_MASCOT } from '../platform/mascot';
import { uid } from '../store/config';

interface Props {
  providers: Provider[];
  onChange: (list: Provider[]) => void;
  avatarMode: 'anime' | 'default';
  onAvatarModeChange: (m: 'anime' | 'default') => void;
  agentMode: boolean;
  onAgentModeChange: (v: boolean) => void;
  theme: 'light' | 'dark';
  onThemeChange: (t: 'light' | 'dark') => void;
  onClearConversations: () => void;
  /** 五模式：闲聊 / 协同 / 灵码 / 感通 / 无界 */
  mode: ModeId;
  onModeChange: (m: ModeId) => void;
  /** 引擎状态（启动时 check_engine 结果） */
  engineStatus?: {
    ok: boolean;
    reason: string;
    python: string;
    app_version?: string;
    engine_version?: string;
    engine_root?: string;
  };
}

const EMPTY: Provider = {
  id: '',
  name: '',
  baseUrl: '',
  format: 'openai',
  apiKey: '',
  models: [],
};

const TIER_LABEL: Record<string, string> = { free: '免费', cheap: '低价', standard: '付费' };

type SettingTab = 'general' | 'mode' | 'appearance' | 'style' | 'providers' | 'about';

const TABS: { key: SettingTab; label: string; icon: typeof Settings }[] = [
  { key: 'general', label: '通用', icon: SlidersHorizontal },
  { key: 'mode', label: '模式', icon: LayoutGrid },
  { key: 'appearance', label: '外观', icon: Palette },
  { key: 'style', label: '样式', icon: Sparkles },
  { key: 'providers', label: '供应商', icon: Server },
  { key: 'about', label: '关于', icon: Info },
];

/** 五模式 → 图标映射：与 modes.ts 的 ModeId 一一对应 */
const MODE_ICONS: Record<ModeId, typeof Settings> = {
  chat: MessageCircle,
  collaboration: Users,
  lingma: CodeXml,
  gantong: Palette,
  boundless: Globe,
};

/** 信息行：图标 + 标题 + 说明（引擎/隐私模块共用） */
function InfoRow({
  icon: Icon,
  title,
  desc,
}: {
  icon: typeof Settings;
  title: string;
  desc: string;
}) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-tuan-border bg-tuan-input px-4 py-3">
      <span className="w-8 h-8 rounded-lg bg-tuan-hover flex-none flex items-center justify-center text-tuan-text">
        <Icon size={15} />
      </span>
      <div className="min-w-0">
        <div className="text-[13.5px] font-medium text-tuan-text">{title}</div>
        <div className="text-[12.5px] text-tuan-textSecondary mt-0.5 leading-relaxed">{desc}</div>
      </div>
    </div>
  );
}

export default function SettingsPage({
  providers,
  onChange,
  avatarMode,
  onAvatarModeChange,
  agentMode,
  onAgentModeChange,
  theme,
  onThemeChange,
  onClearConversations,
  mode,
  onModeChange,
  engineStatus,
}: Props) {
  const [tab, setTab] = useState<SettingTab>('general');
  // 立绘预览随主题切换（浅色用原图、深色用透明底变体）。
  // 本组件已持有 theme prop，直接派生即可，无需再订阅 DOM。
  const dark = theme === 'dark';
  const [catalog, setCatalog] = useState<CatalogProvider[]>([]);
  const [draft, setDraft] = useState<Provider>({ ...EMPTY, id: uid() });
  const [showKey, setShowKey] = useState(false);
  const [probing, setProbing] = useState(false);
  const [probeMsg, setProbeMsg] = useState('');
  const [query, setQuery] = useState('');
  const [openModels, setOpenModels] = useState<Record<string, boolean>>({});
  const [customModel, setCustomModel] = useState('');
  // 数据导入/导出
  const [exporting, setExporting] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);

  const addCustomModel = () => {
    const id = customModel.trim();
    if (!id) return;
    if (draft.models.some((m) => m.id === id)) {
      setProbeMsg('该模型已在列表中');
      return;
    }
    update({ models: [...draft.models, { id, name: id, enabled: true }] });
    setCustomModel('');
    setProbeMsg(`已添加模型「${id}」，记得点保存`);
  };

  const toggleModel = (id: string, enabled: boolean) => {
    update({ models: draft.models.map((m) => (m.id === id ? { ...m, enabled } : m)) });
  };

  const removeModel = (id: string) => {
    update({ models: draft.models.filter((m) => m.id !== id) });
  };

  useEffect(() => {
    fetch('/data/providers.json')
      .then((r) => r.json())
      .then((data: CatalogProvider[]) => setCatalog(data))
      .catch(() => setCatalog([]));
  }, []);

  // 检测系统平台
  const [platformInfo, setPlatformInfo] = useState<{ os: string; isTauri: boolean }>({ os: '', isTauri: false });
  useEffect(() => {
    const ua = navigator.userAgent;
    let os = '未知';
    if (/Windows/i.test(ua)) os = 'Windows';
    else if (/Macintosh|Mac OS X/i.test(ua)) os = 'macOS';
    else if (/Linux/i.test(ua)) os = 'Linux';
    else if (/Android/i.test(ua)) os = 'Android';
    else if (/iPhone|iPad/i.test(ua)) os = 'iOS';
    setPlatformInfo({ os, isTauri: typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window });
  }, []);

  const update = (patch: Partial<Provider>) => setDraft((d) => ({ ...d, ...patch }));

  const save = () => {
    if (!draft.name.trim() || !draft.baseUrl.trim()) {
      setProbeMsg('请选择供应商并填写接口地址');
      return;
    }
    const next = providers.some((p) => p.id === draft.id)
      ? providers.map((p) => (p.id === draft.id ? draft : p))
      : [...providers, draft];
    onChange(next);
    setDraft({ ...EMPTY, id: uid() });
    setProbeMsg('已保存');
  };

  const remove = (id: string) => onChange(providers.filter((p) => p.id !== id));

  const exportData = () => {
    try {
      const data = {
        version: 1,
        exportedAt: new Date().toISOString(),
        providers,
        conversations: JSON.parse(localStorage.getItem('tuan.conversations') || '[]'),
        settings: {
          theme,
          avatarMode,
          agentMode,
        },
      };
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `tuan-backup-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      setProbeMsg('已导出备份文件');
    } catch (e) {
      setProbeMsg('导出失败：' + (e instanceof Error ? e.message : String(e)));
    }
  };

  const importData = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      try {
        const text = await file.text();
        const data = JSON.parse(text);
        if (data.providers && Array.isArray(data.providers)) {
          onChange(data.providers);
        }
        if (data.conversations && Array.isArray(data.conversations)) {
          localStorage.setItem('tuan.conversations', JSON.stringify(data.conversations));
        }
        if (data.settings) {
          if (data.settings.theme) onThemeChange(data.settings.theme);
          if (data.settings.avatarMode) onAvatarModeChange(data.settings.avatarMode);
          if (typeof data.settings.agentMode === 'boolean') onAgentModeChange(data.settings.agentMode);
        }
        setProbeMsg('导入完成，部分设置需重启生效');
      } catch (e) {
        setProbeMsg('导入失败：' + (e instanceof Error ? e.message : String(e)));
      }
    };
    input.click();
  };

  const edit = (p: Provider) => {
    setDraft({ ...p, models: p.models.map((m) => ({ ...m })) });
    setProbeMsg(`正在编辑「${p.name}」，修改后点保存`);
  };

  const pick = (c: CatalogProvider) => {
    // 同名供应商已保存过则复用其 id 与密钥，避免重复建档、丢失已填 Key
    const existing = providers.find((p) => p.name === c.name);
    update({
      id: existing?.id ?? uid(),
      name: c.name,
      baseUrl: c.baseUrl,
      format: c.format,
      apiKey: existing?.apiKey ?? '',
      models: (existing?.models?.length ? existing.models : c.models.map((m) => ({ id: m.id, name: m.id, enabled: true }))),
    });
    setProbeMsg(`已载入「${c.name}」共 ${c.models.length} 个模型${existing?.apiKey ? '（已保留原密钥）' : '，请填写 API 密钥后保存'}`);
  };

  const probe = async () => {
    setProbing(true);
    setProbeMsg('正在获取模型列表…');
    const ids = await probeModels(draft);
    setProbing(false);
    if (ids.length === 0) {
      setProbeMsg('未获取到模型，请检查地址与密钥');
      return;
    }
    update({ models: ids.map((id) => ({ id, name: id, enabled: true })) });
    setProbeMsg(`已获取 ${ids.length} 个模型`);
  };

  /** 测试单个模型是否可用 */
  const [testingModel, setTestingModel] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, 'ok' | 'fail'>>({});
  const testModel = async (modelId: string) => {
    if (!draft.apiKey) {
      setProbeMsg('请先填写 API 密钥');
      return;
    }
    setTestingModel(modelId);
    setTestResult((r) => ({ ...r, [modelId]: 'ok' }));
    try {
      // 使用 probeModels 测试单个模型
      const testProvider = { ...draft, models: [{ id: modelId, name: modelId, enabled: true }] };
      const result = await probeModels(testProvider);
      if (result.length > 0) {
        setTestResult((r) => ({ ...r, [modelId]: 'ok' }));
        setProbeMsg(`模型「${modelId}」测试成功`);
      } else {
        setTestResult((r) => ({ ...r, [modelId]: 'fail' }));
        setProbeMsg(`模型「${modelId}」测试失败`);
      }
    } catch {
      setTestResult((r) => ({ ...r, [modelId]: 'fail' }));
      setProbeMsg(`模型「${modelId}」测试出错`);
    } finally {
      setTestingModel(null);
      // 3 秒后清除测试结果
      setTimeout(() => {
        setTestResult((r) => {
          const { [modelId]: _, ...rest } = r;
          return rest;
        });
      }, 3000);
    }
  };

  const grouped = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = catalog.filter(
      (c) =>
        !q ||
        c.name.toLowerCase().includes(q) ||
        c.desc.toLowerCase().includes(q) ||
        c.category.toLowerCase().includes(q),
    );
    const map = new Map<string, CatalogProvider[]>();
    for (const c of list) {
      const arr = map.get(c.category) ?? [];
      arr.push(c);
      map.set(c.category, arr);
    }
    return [...map.entries()];
  }, [catalog, query]);

  const clearConversations = () => {
    if (window.confirm('确定清空全部对话记录吗？该操作不可撤销。')) {
      onClearConversations();
    }
  };

  const clearProviders = () => {
    if (window.confirm('确定清除全部供应商配置（含已保存的 API 密钥）吗？该操作不可撤销。')) {
      onChange([]);
      setDraft({ ...EMPTY, id: uid() });
    }
  };

  return (
    <div className="page-shell flex-1 overflow-y-auto custom-scrollbar">
      <h1 className="text-[20px] font-semibold text-tuan-text mb-1">设置</h1>
      <p className="text-[13.5px] text-tuan-textSecondary mb-6">
        管理应用外观、模型供应商与本地运行信息；界面文案已全部本地化为简体中文。
      </p>

      <div className="flex flex-col lg:flex-row gap-5">
        {/* 左侧：模块导航（二级菜单，统一圆角） */}
        <nav className="flex lg:flex-col gap-1 lg:w-[190px] flex-shrink-0 overflow-x-auto lg:overflow-visible pb-1 lg:pb-0">
          {TABS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`flex items-center gap-2.5 px-3.5 py-2 text-[13.5px] transition-colors rounded-xl flex-shrink-0 ${
                tab === key
                  ? 'bg-tuan-input border border-tuan-border text-tuan-text shadow-sm'
                  : 'text-tuan-textSecondary hover:bg-tuan-hover hover:text-tuan-text border border-transparent'
              }`}
            >
              <Icon size={16} className="flex-shrink-0" />
              {label}
            </button>
          ))}
        </nav>

        {/* 右侧：当前模块内容 */}
        <div className="flex-1 min-w-0 max-w-[760px] space-y-5">
          {tab === 'general' && (
            <>
              <div className="border border-tuan-border rounded-xl p-5 bg-tuan-input">
                <h2 className="text-[15px] font-semibold text-tuan-text mb-1">界面语言</h2>
                <p className="text-[12.5px] text-tuan-textSecondary mb-4">应用界面、菜单与提示文案的语言。</p>
                <div className="flex items-center gap-3 rounded-xl border border-tuan-border p-3">
                  <span className="w-12 h-12 rounded-xl bg-tuan-hover flex-none flex items-center justify-center text-tuan-text">
                    <Globe size={20} />
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-[13.5px] font-medium text-tuan-text">简体中文</div>
                    <div className="text-[12px] text-tuan-textSecondary">默认语言，全界面已本地化</div>
                  </div>
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-tuan-hover text-tuan-textSecondary flex-none">已启用</span>
                </div>
              </div>
            </>
          )}

          {tab === 'mode' && (
            <div className="border border-tuan-border rounded-xl p-5 bg-tuan-input">
              <h2 className="text-[15px] font-semibold text-tuan-text mb-1">模式</h2>
              <p className="text-[12.5px] text-tuan-textSecondary mb-4">
                选择助手的运行模式；模式决定可用工具、权限边界与风险等级。切换即时生效并持久保存。
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {MODES.map((m) => {
                  const Icon = MODE_ICONS[m.id];
                  const active = mode === m.id;
                  return (
                    <button
                      key={m.id}
                      onClick={() => onModeChange(m.id)}
                      className={`flex items-start gap-3 rounded-xl border p-3 text-left transition-colors ${active ? 'border-[var(--tuan-selected-border)] bg-tuan-hover' : 'border-tuan-border hover:bg-tuan-hover'}`}
                    >
                      <span className="w-12 h-12 rounded-xl flex-none flex items-center justify-center bg-tuan-main border border-tuan-border">
                        <Icon size={20} className="text-tuan-text" />
                      </span>
                      <span className="flex-1 min-w-0">
                        <span className="block text-[13.5px] font-medium text-tuan-text">{m.name}</span>
                        <span className="block text-[12px] text-tuan-textSecondary mt-0.5 leading-relaxed">
                          {m.tagline} · 风险：{m.risk}
                        </span>
                        <span className="block text-[12px] text-tuan-textSecondary mt-1 leading-relaxed">{m.desc}</span>
                      </span>
                      {active && <Check size={16} className="flex-none text-tuan-text mt-1" />}
                    </button>
                  );
                })}
              </div>
              <p className="mt-3 text-[12px] leading-relaxed text-tuan-textSecondary">
                权限基调：{MODES.map((m) => `${m.name} ${m.level} ${m.badge}`).join('；')}。无界为桌面端功能，Android 端不可用。
              </p>
            </div>
          )}

          {tab === 'style' && (
            <div className="border border-tuan-border rounded-xl p-5 bg-tuan-input">
              <h2 className="text-[15px] font-semibold text-tuan-text mb-1">对话样式</h2>
              <p className="text-[12.5px] text-tuan-textSecondary mb-4">
                助手形象统一使用二次元立绘（按供应商匹配，明暗主题各一套背景）。
              </p>
              <div className="flex items-start gap-4">
                <div className="w-20 h-20 rounded-xl overflow-hidden flex-none bg-[var(--tuan-art-bg)] border border-tuan-border">
                  <img src={sampleImage(dark)} alt="助手形象预览" className="tuan-art-img w-full h-full object-cover" />
                </div>
                <p className="flex-1 min-w-0 text-[12px] leading-relaxed text-tuan-textSecondary">
                  已收录：DeepSeek、Claude、GPT、通义千问、Kimi、GLM、豆包 / Seed、Gemini、MiniMax、混元、文心、Mimo；未收录供应商与聚合 / 中转平台回落到代表立绘。
                </p>
              </div>
            </div>
          )}

          {tab === 'appearance' && (
            <div className="border border-tuan-border rounded-xl p-5 bg-tuan-input">
              <h2 className="text-[15px] font-semibold text-tuan-text mb-1">主题</h2>
              <p className="text-[12.5px] text-tuan-textSecondary mb-4">选择应用的明暗外观，切换即时生效并持久保存。</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <button
                  onClick={() => onThemeChange('light')}
                  className={`flex items-center gap-3 rounded-xl border p-3 text-left transition-colors ${theme === 'light' ? 'border-[var(--tuan-selected-border)] bg-tuan-hover' : 'border-tuan-border hover:bg-tuan-hover'}`}
                >
                  <span className="w-12 h-12 rounded-xl overflow-hidden flex-none flex items-center justify-center bg-tuan-main border border-tuan-border text-tuan-text">
                    <Sun size={20} />
                  </span>
                  <span className="flex-1 min-w-0">
                    <span className="block text-[13.5px] font-medium text-tuan-text">浅色</span>
                    <span className="block text-[12px] text-tuan-textSecondary">暖米色明亮外观</span>
                  </span>
                  {theme === 'light' && <Check size={16} className="flex-none text-tuan-text" />}
                </button>
                <button
                  onClick={() => onThemeChange('dark')}
                  className={`flex items-center gap-3 rounded-xl border p-3 text-left transition-colors ${theme === 'dark' ? 'border-[var(--tuan-selected-border)] bg-tuan-hover' : 'border-tuan-border hover:bg-tuan-hover'}`}
                >
                  <span className="w-12 h-12 rounded-xl overflow-hidden flex-none flex items-center justify-center bg-[#26251f] border border-tuan-border text-[#ece9e2]">
                    <Moon size={20} />
                  </span>
                  <span className="flex-1 min-w-0">
                    <span className="block text-[13.5px] font-medium text-tuan-text">深色</span>
                    <span className="block text-[12px] text-tuan-textSecondary">暖炭色夜间外观</span>
                  </span>
                  {theme === 'dark' && <Check size={16} className="flex-none text-tuan-text" />}
                </button>
              </div>
            </div>
          )}

          {tab === 'providers' && (
            <>
              {/* 已配置 */}
              <div className="space-y-3">
                <h2 className="text-[15px] font-semibold text-tuan-text">已配置供应商</h2>
                {providers.map((p) => (
                  <div key={p.id} className="border border-tuan-border rounded-xl p-4 bg-tuan-input">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-tuan-text">{p.name}</span>
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-tuan-hover text-tuan-textSecondary">
                        {p.format === 'openai' ? 'OpenAI 兼容' : 'Anthropic'}
                      </span>
                      <span className={`text-[10.5px] px-1.5 py-0.5 rounded-full font-medium ${
                        p.apiKey
                          ? 'bg-[var(--tuan-ok-bg)] text-[var(--tuan-ok)]'
                          : 'bg-tuan-hover text-tuan-textSecondary'
                      }`}>
                        {p.apiKey ? '已配置密钥' : '未配置密钥'}
                      </span>
                      <span className="text-[12px] text-tuan-textSecondary truncate ml-1">{p.baseUrl}</span>
                      <button onClick={() => edit(p)} className="ml-auto px-2.5 py-1 rounded-full border border-tuan-border text-[12.5px] text-tuan-textSecondary hover:bg-tuan-hover">
                        编辑
                      </button>
                      <button onClick={() => remove(p.id)} className="p-1.5 rounded-lg hover:bg-[var(--tuan-danger-bg)] text-[var(--tuan-danger)]">
                        <Trash2 size={15} />
                      </button>
                    </div>
                    <div className="mt-2 text-[12.5px] text-tuan-textSecondary">
                      已启用模型 {p.models.filter((m) => m.enabled).length} 个
                    </div>
                  </div>
                ))}
                {providers.length === 0 && (
                  <div className="border border-dashed border-tuan-border rounded-xl py-8 text-center text-[13.5px] text-tuan-textSecondary">
                    还没有配置供应商，从下方目录选择一个并填入密钥
                  </div>
                )}
              </div>

              {/* 编辑/新建表单 */}
              <div className="border border-tuan-border rounded-xl p-5 bg-tuan-input space-y-4">
                <div className="flex items-center gap-2 font-medium text-tuan-text">
                  <Plus size={16} /> {providers.some((p) => p.id === draft.id) ? '编辑供应商' : '配置供应商'}
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <label className="block">
                    <span className="text-[12px] text-tuan-textSecondary">名称</span>
                    <input
                      value={draft.name}
                      onChange={(e) => update({ name: e.target.value })}
                      placeholder="从下方目录选择"
                      style={{ borderRadius: 12 }}
                      className="mt-1 w-full bg-tuan-input border border-tuan-border px-3 py-2 text-[13.5px] text-tuan-text outline-none"
                    />
                  </label>
                  <label className="block">
                    <span className="text-[12px] text-tuan-textSecondary">接口地址（Base URL）</span>
                    <input
                      value={draft.baseUrl}
                      onChange={(e) => update({ baseUrl: e.target.value })}
                      placeholder="https://example.com/v1"
                      style={{ borderRadius: 12 }}
                      className="mt-1 w-full bg-tuan-input border border-tuan-border px-3 py-2 text-[13.5px] text-tuan-text outline-none"
                    />
                  </label>
                </div>

                <div>
                  <span className="text-[12px] text-tuan-textSecondary">API 格式</span>
                  <div className="flex gap-2 mt-1.5 flex-wrap">
                    {(['openai', 'anthropic'] as ApiFormat[]).map((f) => (
                      <button
                        key={f}
                        onClick={() => update({ format: f })}
                        className={`px-4 py-1.5 rounded-full text-[12.5px] font-medium transition-colors ${
                          draft.format === f ? 'cc-btn-primary' : 'cc-btn-ghost'
                        }`}
                      >
                        {f === 'openai' ? 'OpenAI 兼容' : 'Anthropic'}
                      </button>
                    ))}
                  </div>
                </div>

                <label className="block relative">
                  <span className="text-[12px] text-tuan-textSecondary">API 密钥</span>
                  <input
                    type={showKey ? 'text' : 'password'}
                    value={draft.apiKey}
                    onChange={(e) => update({ apiKey: e.target.value })}
                    placeholder="sk-..."
                    style={{ borderRadius: 12 }}
                    className="mt-1 w-full bg-tuan-input border border-tuan-border px-3 py-2 pr-10 text-[13.5px] text-tuan-text outline-none"
                  />
                  <button
                    onClick={() => setShowKey((s) => !s)}
                    className="absolute right-2 top-[26px] p-1 rounded-lg text-tuan-textSecondary hover:bg-tuan-hover hover:text-tuan-text"
                    type="button"
                  >
                    {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </label>

                <div className="flex items-center gap-3 flex-wrap">
                  <button
                    onClick={probe}
                    disabled={probing || !draft.baseUrl}
                    className="cc-btn-ghost px-4 py-2 text-[13px]"
                  >
                    <RefreshCw size={15} className={probing ? 'animate-spin' : ''} /> 获取模型
                  </button>
                  <button
                    onClick={save}
                    className="cc-btn-primary px-5 py-2 text-[13px] font-medium"
                  >
                    保存
                  </button>
                  {probeMsg && (
                    <span className="inline-flex items-center rounded-full bg-tuan-hover px-3 py-1 text-[12.5px] text-tuan-textSecondary">
                      {probeMsg}
                    </span>
                  )}
                </div>

                {/* 模型管理：可手动添加自定义模型、启停、删除 */}
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-[12px] text-tuan-textSecondary">
                      模型列表（{draft.models.filter((m) => m.enabled).length} 启用 / 共 {draft.models.length}）
                    </span>
                  </div>
                  <div className="flex gap-2 mt-1.5">
                    <input
                      value={customModel}
                      onChange={(e) => setCustomModel(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && addCustomModel()}
                      placeholder="手动输入模型 ID，如 gpt-4o-mini、claude-3-5-sonnet-latest"
                      style={{ borderRadius: 12 }}
                      className="flex-1 bg-tuan-input border border-tuan-border px-3 py-2 text-[13.5px] text-tuan-text outline-none"
                    />
                    <button onClick={addCustomModel} className="cc-btn-ghost px-3.5 py-2 text-[13px] flex-none">
                      <Plus size={15} /> 添加
                    </button>
                  </div>
                  {draft.models.length > 0 && (
                    <div className="mt-2 max-h-[220px] overflow-y-auto custom-scrollbar grid grid-cols-1 sm:grid-cols-2 gap-1.5 pr-1">
                      {draft.models.map((m) => (
                        <label
                          key={m.id}
                          className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-[12.5px] cursor-pointer transition-colors ${
                            m.enabled ? 'border-tuan-border bg-tuan-hover text-tuan-text' : 'border-tuan-border/60 text-tuan-textSecondary'
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={m.enabled}
                            onChange={(e) => toggleModel(m.id, e.target.checked)}
                            className="accent-[#1f1e1c] h-3.5 w-3.5"
                          />
                          <span className="flex-1 min-w-0 truncate" title={m.id}>{m.name || m.id}</span>
                          {testingModel === m.id ? (
                            <span className="flex-none text-[11px] text-tuan-textSecondary">测试中...</span>
                          ) : testResult[m.id] === 'ok' ? (
                            <Check size={13} className="flex-none text-green-500" />
                          ) : testResult[m.id] === 'fail' ? (
                            <X size={13} className="flex-none text-red-500" />
                          ) : null}
                          <button
                            type="button"
                            onClick={(e) => { e.preventDefault(); testModel(m.id); }}
                            className="p-0.5 rounded-lg text-tuan-textSecondary hover:text-tuan-accent flex-none"
                            title="测试模型"
                          >
                            <Zap size={13} />
                          </button>
                          <button
                            type="button"
                            onClick={() => removeModel(m.id)}
                            className="p-0.5 rounded-lg text-tuan-textSecondary hover:text-[var(--tuan-danger)] hover:bg-[var(--tuan-danger-bg)] flex-none"
                            title="移除"
                          >
                            <X size={13} />
                          </button>
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* 内置目录 */}
              <div>
                <h2 className="text-[15px] font-semibold text-tuan-text mb-3">tuan_cli 内置目录（{catalog.length}）</h2>
                <div className="flex items-center gap-2 bg-tuan-input border border-tuan-border rounded-xl px-3 py-2 mb-4">
                  <Search size={16} className="text-tuan-textSecondary" />
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="搜索供应商 / 分类"
                    style={{ borderRadius: 12 }}
                    className="flex-1 bg-transparent outline-none text-[13.5px] text-tuan-text placeholder:text-tuan-textSecondary"
                  />
                </div>
                {grouped.map(([cat, list]) => (
                  <div key={cat} className="mb-5">
                    <div className="text-[13px] font-medium text-tuan-textSecondary mb-2">{cat}</div>
                    <div className="space-y-2">
                      {list.map((c) => {
                        const active = draft.name === c.name;
                        const open = !!openModels[c.name];
                        return (
                          <div key={c.name} className="bg-tuan-input border border-tuan-border rounded-xl px-4 py-3">
                            <div className="flex items-center gap-3">
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 flex-wrap">
                                  <span className="text-[14.5px] font-medium text-tuan-text">{c.name}</span>
                                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-tuan-hover text-tuan-textSecondary">
                                    {TIER_LABEL[c.tier] ?? c.tier}
                                  </span>
                                  {c.freeTier && (
                                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-[var(--tuan-ok-bg)] text-[var(--tuan-ok)]">免费</span>
                                  )}
                                </div>
                                <div className="text-[12.5px] text-tuan-textSecondary mt-1 leading-relaxed">{c.desc}</div>
                                <div className="flex items-center gap-3 mt-1">
                                  <span className="text-[11.5px] text-tuan-textSecondary">
                                    默认：{c.defaultModel} · {c.models.length} 个模型
                                  </span>
                                  <button
                                    onClick={() => setOpenModels((p) => ({ ...p, [c.name]: !p[c.name] }))}
                                    className="text-[11.5px] text-[var(--tuan-link)] hover:underline"
                                  >
                                    {open ? '收起模型' : `展开 ${c.models.length} 个模型`}
                                  </button>
                                </div>
                              </div>
                              <button
                                onClick={() => pick(c)}
                                className={`${active ? 'cc-btn-primary' : 'cc-btn-ghost'} px-3.5 py-1.5 text-[13px] flex-shrink-0`}
                              >
                                {active && <Check size={14} />} 选用
                              </button>
                            </div>
                            {open && (
                              <div className="mt-3 max-h-[220px] overflow-y-auto custom-scrollbar grid grid-cols-2 gap-1.5 pr-2">
                                {c.models.map((m) => (
                                  <div key={m.id} className="flex items-center gap-1.5 text-[12px] text-tuan-textSecondary rounded-full border border-tuan-border/60 px-2.5 py-1 truncate">
                                    {m.free && <span className="text-[var(--tuan-ok)] flex-shrink-0">免费</span>}
                                    <span className="truncate">{m.id}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}

          {tab === 'about' && (
            <>
              {/* 应用信息 */}
              <div className="border border-tuan-border rounded-xl p-5 bg-tuan-input flex items-start gap-4">
                <img src={DEFAULT_MASCOT} alt="Tuan-Chat" className="w-14 h-14 object-contain rounded-xl bg-tuan-main border border-tuan-border p-1" />
                <div>
                  <div className="text-[16px] font-semibold text-tuan-text">Tuan-Chat</div>
                  <div className="text-[12.5px] text-tuan-textSecondary mt-0.5">tuan_cli 引擎的桌面客户端 · 版本 0.1.0</div>
                </div>
              </div>

              {/* 系统信息 */}
              <div className="border border-tuan-border rounded-xl p-5 bg-tuan-input">
                <h2 className="text-[15px] font-semibold text-tuan-text mb-3">系统信息</h2>
                <div className="space-y-2 text-[13px]">
                  <div className="flex items-center gap-2">
                    <span className="text-tuan-textSecondary">运行平台：</span>
                    <span className="text-tuan-text">{platformInfo.isTauri ? 'Tauri 桌面端' : 'Web 模式'}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-tuan-textSecondary">操作系统：</span>
                    <span className="text-tuan-text">{platformInfo.os}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-tuan-textSecondary">用户代理：</span>
                    <span className="text-tuan-text truncate max-w-[300px]">{navigator.userAgent.slice(0, 60)}...</span>
                  </div>
                </div>
              </div>

              <div className="space-y-2">
                <InfoRow
                  icon={Package}
                  title="技术栈"
                  desc="Tauri 2 + React 19 桌面壳，内嵌 tuan_cli 本地引擎；聊天能力与 TUI 完全对齐。"
                />
                <InfoRow
                  icon={Server}
                  title="模型中立"
                  desc="内置 tuan_cli 供应商目录（含 58 家预设），同时支持任意 OpenAI 兼容与 Anthropic 自建端点。"
                />
                <InfoRow
                  icon={Globe}
                  title="开源说明"
                  desc="本地自托管运行：对话、工具与记忆均由本机引擎完成，不依赖第三方云端服务。"
                />
              </div>

              {/* 相关链接 */}
              <div className="border border-tuan-border rounded-xl p-5 bg-tuan-input">
                <h2 className="text-[15px] font-semibold text-tuan-text mb-3">相关链接</h2>
                <div className="space-y-2">
                  <a
                    href="https://github.com/66666647/tuan_cli"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 text-[13px] text-tuan-text hover:text-tuan-accent transition-colors"
                  >
                    <ExternalLink size={14} className="text-tuan-textSecondary" />
                    GitHub 仓库（tuan_cli）
                  </a>
                  <a
                    href="https://tauri.app"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 text-[13px] text-tuan-text hover:text-tuan-accent transition-colors"
                  >
                    <ExternalLink size={14} className="text-tuan-textSecondary" />
                    Tauri 官方文档
                  </a>
                  <a
                    href="https://react.dev"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 text-[13px] text-tuan-text hover:text-tuan-accent transition-colors"
                  >
                    <ExternalLink size={14} className="text-tuan-textSecondary" />
                    React 文档
                  </a>
                </div>
              </div>

              {/* 引擎与运行 */}
              <h2 className="text-[15px] font-semibold text-tuan-text pt-1">引擎与运行</h2>

              {/* 引擎状态指示器 */}
              {engineStatus && (
                <div className={`rounded-xl border p-4 mb-3 ${engineStatus.ok ? 'border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/30' : 'border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30'}`}>
                  <div className="flex items-start gap-3">
                    <span className={`w-2 h-2 rounded-full mt-1.5 flex-none ${engineStatus.ok ? 'bg-emerald-500' : 'bg-amber-500'}`} />
                    <div className="flex-1 min-w-0">
                      <div className="text-[13.5px] font-medium text-tuan-text">
                        {engineStatus.ok ? '本地引擎就绪' : '本地引擎不可用（已降级到纯对话模式）'}
                      </div>
                      {engineStatus.ok && engineStatus.python && (
                        <div className="mt-0.5 text-[12px] text-tuan-textSecondary font-mono break-all">
                          Python: {engineStatus.python}
                        </div>
                      )}
                      {engineStatus.ok && (engineStatus.app_version || engineStatus.engine_version) && (
                        <div className="mt-0.5 text-[12px] text-tuan-textSecondary">
                          {engineStatus.app_version && <>外壳 v{engineStatus.app_version}</>}
                          {engineStatus.app_version && engineStatus.engine_version && ' · '}
                          {engineStatus.engine_version && <>引擎 v{engineStatus.engine_version}</>}
                        </div>
                      )}
                      {engineStatus.ok && engineStatus.engine_root && (
                        <div className="mt-0.5 text-[12px] text-tuan-textSecondary font-mono break-all">
                          引擎目录: {engineStatus.engine_root}
                        </div>
                      )}
                      {!engineStatus.ok && engineStatus.reason && (
                        <div className="mt-1 text-[12px] text-tuan-textSecondary leading-relaxed">
                          {engineStatus.reason}
                        </div>
                      )}
                      {!engineStatus.ok && (
                        <div className="mt-2 text-[12px] text-tuan-textSecondary">
                          纯对话模式仍可正常使用。如需完整 Agent 能力（工具调用、安全闸门、会话持久化），
                          请安装 Python 3.10+ 或在设置中配置 TUAN_PYTHON 环境变量。
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}

              <div className="border border-tuan-border rounded-xl p-5 bg-tuan-input">
                <h2 className="text-[15px] font-semibold text-tuan-text mb-1">轻量 Agent（Android）</h2>
                <p className="text-[12.5px] text-tuan-textSecondary mb-4">
                  移动端无本地引擎，开启后助手可联网搜索、抓取网页、计算与记录笔记；关闭则退化为纯对话。
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <button
                    onClick={() => onAgentModeChange(true)}
                    className={`flex items-center gap-3 rounded-xl border p-3 text-left transition-colors ${agentMode ? 'border-[var(--tuan-selected-border)] bg-tuan-hover' : 'border-tuan-border hover:bg-tuan-hover'}`}
                  >
                    <span className="w-12 h-12 rounded-xl flex-none flex items-center justify-center bg-tuan-main border border-tuan-border">
                      <Sparkles size={20} className="text-tuan-text" />
                    </span>
                    <span className="flex-1 min-w-0">
                      <span className="block text-[13.5px] font-medium text-tuan-text">开启（推荐）</span>
                      <span className="block text-[12px] text-tuan-textSecondary break-words">需要外部信息时主动查证</span>
                    </span>
                    {agentMode && <Check size={16} className="flex-none text-tuan-text" />}
                  </button>
                  <button
                    onClick={() => onAgentModeChange(false)}
                    className={`flex items-center gap-3 rounded-xl border p-3 text-left transition-colors ${!agentMode ? 'border-[var(--tuan-selected-border)] bg-tuan-hover' : 'border-tuan-border hover:bg-tuan-hover'}`}
                  >
                    <span className="w-12 h-12 rounded-xl flex-none flex items-center justify-center bg-tuan-hover border border-tuan-border">
                      <MessageSquare size={20} className="text-tuan-textSecondary" />
                    </span>
                    <span className="flex-1 min-w-0">
                      <span className="block text-[13.5px] font-medium text-tuan-text">关闭</span>
                      <span className="block text-[12px] text-tuan-textSecondary break-words">仅对话，不使用任何工具</span>
                    </span>
                    {!agentMode && <Check size={16} className="flex-none text-tuan-text" />}
                  </button>
                </div>
                <p className="mt-3 text-[12px] leading-relaxed text-tuan-textSecondary">
                  能力边界：移动端无法执行 shell 命令、无法改动代码工程，也无法访问设备上的任意文件；这类任务请在桌面端使用完整版。
                </p>
              </div>
              <div className="border border-tuan-border rounded-xl p-5 bg-tuan-input">
                <h2 className="text-[15px] font-semibold text-tuan-text mb-1">聊天通道</h2>
                <p className="text-[12.5px] text-tuan-textSecondary leading-relaxed">
                  对话由本机内嵌的 tuan_cli 引擎运行：完整注入与 TUI 一致的系统提示词，支持工具调用、安全闸门与会话持久化；
                  切换供应商或更新密钥后即时生效，无需重启应用。
                </p>
              </div>
              <div className="space-y-2">
                <InfoRow
                  icon={TerminalSquare}
                  title="引擎服务"
                  desc="随应用自动启动的本地引擎进程（127.0.0.1:8137），仅监听本机回环地址，不对外网开放。"
                />
                <InfoRow
                  icon={HardDrive}
                  title="本地存储"
                  desc="对话记录、供应商配置与界面偏好仅保存在本机应用数据目录，不向任何服务器上传。"
                />
                <InfoRow
                  icon={KeyRound}
                  title="密钥管理"
                  desc="API 密钥随供应商配置保存在本机；引擎在调用时按所选供应商自动注入对应密钥。"
                />
              </div>

              {/* 数据与隐私 */}
              <h2 className="text-[15px] font-semibold text-tuan-text pt-1">数据与隐私</h2>
              <div className="space-y-2">
                <InfoRow
                  icon={ShieldCheck}
                  title="数据本地化"
                  desc="所有对话、供应商与设置数据均存于本机，不上传、不分享；引擎进程仅在本机运行。"
                />
                <InfoRow
                  icon={KeyRound}
                  title="密钥安全"
                  desc="API 密钥仅用于向所选模型服务发起请求，以密码框输入、默认隐藏显示。"
                />
              </div>
              <div className="border border-tuan-border rounded-xl p-5 bg-tuan-input">
                <h2 className="text-[15px] font-semibold text-tuan-text mb-1">数据管理</h2>
                <p className="text-[12.5px] text-tuan-textSecondary mb-4">
                  备份、恢复或清空本机数据。导出包含供应商、对话与设置。
                </p>
                <div className="flex flex-wrap gap-3">
                  <button onClick={exportData} className="cc-btn-ghost px-4 py-2 text-[13px]">
                    <Download size={15} /> 导出备份
                  </button>
                  <button onClick={importData} className="cc-btn-ghost px-4 py-2 text-[13px]">
                    <Upload size={15} /> 导入备份
                  </button>
                  <button onClick={clearConversations} className="cc-btn-ghost px-4 py-2 text-[13px]">
                    <Trash2 size={15} /> 清空对话
                  </button>
                  <button onClick={clearProviders} className="cc-btn-ghost px-4 py-2 text-[13px]">
                    <KeyRound size={15} /> 清除供应商
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
