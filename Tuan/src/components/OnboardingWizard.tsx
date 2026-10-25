import { useEffect, useState } from 'react';
import { ArrowLeft, ArrowRight, Check, KeyRound, Server, X } from 'lucide-react';
import BrandMark from './BrandMark';
import { MODES, type ModeId } from '../platform/modes';
import { store, uid } from '../store/config';
import type { CatalogProvider, Provider } from '../types';

/**
 * 首次运行三步引导向导（T-1.2 / T-1.4）。
 *
 * 三步真实配置，不是静态教程：
 *  1. 选供应商：从 tuan_cli 内置目录（/data/providers.json）点选一家平台；
 *  2. 填 API 密钥：写入本地供应商档案（同名已有则复用 id 与旧密钥）；
 *  3. 选权限模式：从三档模式里选一个作为起步权限。
 *
 * 可在任意一步右上角关闭 / 底部「跳过引导」退出——退出即视为完成，
 * 不再下次启动弹出（完成存储防御调用 store.completeOnboarding()，
 * 「设置与外观」分片 API 缺席时回落 localStorage 标记）。
 * 已配置过供应商的老用户在设置 / 空态可随时从「开始引导」重开本向导。
 */
interface Props {
  onClose: () => void;
  /** 已保存的供应商档案（用于同名复用 id 与已填密钥） */
  providers: Provider[];
  /** 保存 / 更新供应商档案并切换为当前供应商 */
  onProviderSave: (p: Provider) => void;
  /** 当前权限模式（第 3 步预选） */
  currentMode: ModeId;
  /** 用户选定模式（直接走 App 的变更逻辑，含高权限二次确认） */
  onModeSelect: (m: ModeId) => void;
}

const STEPS = [
  { id: 'provider', title: '第 1 步 · 选择供应商' },
  { id: 'apikey', title: '第 2 步 · 填写 API 密钥' },
  { id: 'mode', title: '第 3 步 · 选择权限模式' },
] as const;

/** 内置目录加载失败时的兜底推荐（与 SettingsPage 同源 fetch，失败不阻塞） */
const TIER_LABEL: Record<string, string> = { free: '免费额度', cheap: '低价', standard: '按量付费' };

export default function OnboardingWizard({
  onClose,
  providers,
  onProviderSave,
  currentMode,
  onModeSelect,
}: Props) {
  const [step, setStep] = useState(0);
  const [catalog, setCatalog] = useState<CatalogProvider[]>([]);
  const [picked, setPicked] = useState<CatalogProvider | null>(null);
  const [apiKey, setApiKey] = useState('');
  const [pickedMode, setPickedMode] = useState<ModeId>(currentMode);

  // 拉取内置供应商目录（与 SettingsPage 同一数据源）；失败留空，可手跳到设置
  useEffect(() => {
    fetch('/data/providers.json')
      .then((r) => r.json())
      .then((data: CatalogProvider[]) => setCatalog(Array.isArray(data) ? data : []))
      .catch(() => setCatalog([]));
  }, []);

  /** 同名供应商已有档案：复用 id 与旧密钥，避免重复建档 */
  const existing = picked ? providers.find((p) => p.name === picked.name) : undefined;

  /** 退出引导 = 引导完成：防御调用 store 契约 API，缺席时 localStorage 兜底 */
  const finish = () => {
    try {
      const s = store as unknown as Record<string, unknown>;
      const fn = s.completeOnboarding;
      if (typeof fn === 'function') fn.call(store);
    } catch {
      /* 契约 API 缺席/报错都走兜底 */
    }
    try {
      localStorage.setItem('tuan.onboardingDone', '1');
    } catch {
      /* 隐私模式等场景忽略 */
    }
    onClose();
  };

  /** 第 2 步「下一步」：把选中的供应商落成真实档案并切为当前供应商 */
  const saveProvider = () => {
    if (!picked) return;
    const p: Provider = {
      id: existing?.id ?? uid(),
      name: picked.name,
      baseUrl: picked.baseUrl,
      format: picked.format,
      apiKey: apiKey.trim() || existing?.apiKey || '',
      models: existing?.models?.length
        ? existing.models
        : picked.models.map((m) => ({
            id: m.id,
            name: m.id,
            enabled: m.id === picked.defaultModel,
          })),
    };
    onProviderSave(p);
    setStep(2);
  };

  const last = step === STEPS.length - 1;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-[70] flex items-center justify-center p-4 bg-black/25 backdrop-blur-[2px]"
      onClick={finish}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[90vh] w-full max-w-[520px] flex-col rounded-2xl border border-tuan-border bg-tuan-bg p-6 shadow-[var(--shadow-pop)]"
      >
        {/* 头部：logo + 进度圆点 + 关闭 */}
        <div className="mb-5 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <BrandMark size="md" />
            <span className="text-[14px] font-semibold text-tuan-text">快速上手 · 三步完成配置</span>
          </div>
          <div className="flex items-center gap-1.5">
            {STEPS.map((s, i) => (
              <span
                key={s.id}
                className={`h-1.5 rounded-full transition-all ${
                  i === step ? 'w-4 bg-tuan-accent' : i < step ? 'w-1.5 bg-tuan-accent/60' : 'w-1.5 bg-tuan-border'
                }`}
              />
            ))}
            <button
              onClick={finish}
              className="ml-2 rounded-md p-1 text-tuan-textSecondary hover:bg-tuan-hover hover:text-tuan-text"
              title="跳过引导"
            >
              <X size={15} />
            </button>
          </div>
        </div>

        {/* 步骤内容（可滚动） */}
        <div className="min-h-[220px] flex-1 overflow-y-auto custom-scrollbar">
          <h2 className="mb-1 text-[17px] font-semibold text-tuan-text">{STEPS[step].title}</h2>

          {/* ===== 第 1 步：选供应商 ===== */}
          {step === 0 && (
            <>
              <p className="mb-3 text-[13.5px] leading-relaxed text-tuan-textSecondary">
                对话需要接入一个模型平台。从下面选一家常用平台（密钥只存在本地，不会上传）；
                也可以之后在「设置」里随时增删。
              </p>
              <div className="space-y-2">
                {catalog.slice(0, 8).map((c) => {
                  const active = picked?.name === c.name;
                  return (
                    <button
                      key={c.name}
                      onClick={() => setPicked(c)}
                      className={`flex w-full items-center gap-3 rounded-xl border px-3.5 py-2.5 text-left transition-colors ${
                        active
                          ? 'border-tuan-accent bg-tuan-accent/10'
                          : 'border-tuan-border hover:bg-tuan-hover'
                      }`}
                    >
                      <span className="flex h-8 w-8 flex-none items-center justify-center rounded-lg bg-tuan-hover text-tuan-textSecondary">
                        <Server size={15} />
                      </span>
                      <span className="flex-1 min-w-0">
                        <span className="block truncate text-[13.5px] font-medium text-tuan-text">{c.name}</span>
                        <span className="block truncate text-[12px] text-tuan-textSecondary">{c.desc}</span>
                      </span>
                      <span className="flex-none rounded-full bg-tuan-hover px-2 py-0.5 text-[11px] text-tuan-textSecondary">
                        {TIER_LABEL[c.tier] ?? c.tier}
                      </span>
                      {active && <Check size={15} className="flex-none text-tuan-accent" />}
                    </button>
                  );
                })}
                {catalog.length === 0 && (
                  <p className="rounded-xl border border-tuan-border px-3.5 py-4 text-[13px] text-tuan-textSecondary">
                    目录加载失败？没关系——点下方「下一步」后随时在设置里手动添加供应商。
                  </p>
                )}
              </div>
            </>
          )}

          {/* ===== 第 2 步：填 API 密钥 ===== */}
          {step === 1 && (
            <>
              {picked ? (
                <>
                  <p className="mb-3 text-[13.5px] leading-relaxed text-tuan-textSecondary">
                    已选「{picked.name}」。在该平台控制台创建 API 密钥后粘贴到下方——
                    它只保存在本机浏览器 / 应用存储里。
                  </p>
                  <div className="rounded-xl border border-tuan-border bg-tuan-input p-3.5">
                    <div className="mb-1.5 text-[12px] text-tuan-textSecondary">{picked.baseUrl}</div>
                    <label className="mb-1 block text-[12.5px] text-tuan-textSecondary">API 密钥</label>
                    <div className="flex items-center gap-2 rounded-lg border border-tuan-border bg-tuan-bg px-3">
                      <KeyRound size={14} className="flex-none text-tuan-textSecondary" />
                      <input
                        type="password"
                        value={apiKey}
                        onChange={(e) => setApiKey(e.target.value)}
                        placeholder={existing?.apiKey ? '已保存过密钥，留空沿用旧值' : 'sk-…'}
                        className="h-9 flex-1 bg-transparent text-[13.5px] text-tuan-text outline-none placeholder:text-tuan-textSecondary"
                        autoFocus
                      />
                    </div>
                  </div>
                </>
              ) : (
                <p className="rounded-xl border border-tuan-border px-3.5 py-4 text-[13px] text-tuan-textSecondary">
                  还没有选择供应商。点「上一步」选一家平台，或直接跳过在设置里配置。
                </p>
              )}
            </>
          )}

          {/* ===== 第 3 步：选权限模式 ===== */}
          {step === 2 && (
            <>
              <p className="mb-3 text-[13.5px] leading-relaxed text-tuan-textSecondary">
                权限模式决定 Agent 的放手程度。可以随时切换——起步用「标准」最稳妥。
              </p>
              <div className="space-y-2">
                {MODES.map((m) => {
                  const active = pickedMode === m.id;
                  return (
                    <button
                      key={m.id}
                      onClick={() => setPickedMode(m.id)}
                      className={`flex w-full items-start gap-3 rounded-xl border px-3.5 py-2.5 text-left transition-colors ${
                        active
                          ? 'border-tuan-accent bg-tuan-accent/10'
                          : 'border-tuan-border hover:bg-tuan-hover'
                      }`}
                    >
                      <span className="flex-1 min-w-0">
                        <span className="block text-[13.5px] font-medium text-tuan-text">
                          {m.name}
                          <span className="ml-2 rounded-full bg-tuan-hover px-2 py-0.5 text-[11px] font-normal text-tuan-textSecondary">
                            {m.level} · 风险{m.risk}
                          </span>
                        </span>
                        <span className="mt-0.5 block text-[12.5px] leading-relaxed text-tuan-textSecondary">{m.desc}</span>
                      </span>
                      {active && <Check size={15} className="mt-1 flex-none text-tuan-accent" />}
                    </button>
                  );
                })}
              </div>
            </>
          )}
        </div>

        {/* 底部操作 */}
        <div className="mt-5 flex items-center justify-between gap-3 border-t border-tuan-border pt-4">
          <button
            onClick={() => setStep((x) => Math.max(0, x - 1))}
            disabled={step === 0}
            className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] text-tuan-textSecondary hover:bg-tuan-hover hover:text-tuan-text disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <ArrowLeft size={14} />
            上一步
          </button>
          <button
            onClick={finish}
            className="text-[12.5px] text-tuan-textSecondary underline-offset-2 hover:text-tuan-text hover:underline"
          >
            跳过引导
          </button>
          <div className="flex items-center gap-2.5">
            {!last ? (
              <button
                onClick={() => (step === 1 ? saveProvider() : setStep((x) => x + 1))}
                disabled={step === 1 && !picked}
                className="inline-flex items-center gap-1.5 rounded-full bg-tuan-accent px-4 py-1.5 text-[13px] font-medium text-white hover:bg-tuan-accentStrong disabled:opacity-40"
              >
                下一步
                <ArrowRight size={14} />
              </button>
            ) : (
              <button
                onClick={() => {
                  onModeSelect(pickedMode);
                  finish();
                }}
                className="inline-flex items-center gap-1.5 rounded-full bg-tuan-accent px-4 py-1.5 text-[13px] font-medium text-white hover:bg-tuan-accentStrong"
              >
                <Check size={14} />
                开始使用
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
