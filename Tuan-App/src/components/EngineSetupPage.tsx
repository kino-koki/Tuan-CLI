import { useState } from 'react';
import { Check, Copy, RefreshCw, ArrowRight, CircleDashed, HardDrive, Terminal, Package, SearchCheck } from 'lucide-react';
import type { BootEngineStatus } from './BootScreen';
import BrandMark from './BrandMark';

interface Props {
  /** 当前（失败）的引擎自检结果 */
  engineStatus: BootEngineStatus;
  /** 真实重新检测：调用 Rust check_engine */
  onRecheck: () => Promise<BootEngineStatus>;
  /** 以纯对话降级模式进入主界面 */
  onEnterDegraded: () => void;
  /** 重新检测通过 */
  onReady: () => void;
  /** 手动打开（标题栏/命令面板）：底部按钮变为「返回」，且引擎已就绪时只展示信息卡 */
  manual?: boolean;
}

/** 复制到剪贴板；老 WebView 回退 execCommand。返回是否成功。 */
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* 落到兜底 */
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

/** 安装目录下的引擎 requirements 路径（与 Rust 侧错误提示口径一致）。 */
function requirementsCmd(root?: string): string {
  const dir = root ? root.replace(/[\\/]+$/, '') : '<安装目录>\\engine';
  return `pip install -r "${dir}\\requirements.txt"`;
}

/**
 * 引擎安装向导（豆包 × CodeX 风格）。
 *
 * 诚实原则：不做假下载表演。三步引导全部给**真实可复制**的命令，
 * 第四步的「重新检测」是真实回调 Rust `check_engine`；通过即放行。
 * 随时可走「降级模式」先用起来——装好引擎后从标题栏状态灯随时回来。
 */
export default function EngineSetupPage({ engineStatus, onRecheck, onEnterDegraded, onReady, manual }: Props) {
  const [done, setDone] = useState<Record<string, boolean>>({});
  const [copied, setCopied] = useState<string>('');
  const [rechecking, setRechecking] = useState(false);
  const [recheckErr, setRecheckErr] = useState('');
  const [success, setSuccess] = useState(false);

  const copy = async (key: string, text: string) => {
    const ok = await copyText(text);
    setCopied(ok ? key : '');
    window.setTimeout(() => setCopied(''), 1600);
  };

  const recheck = async () => {
    setRechecking(true);
    setRecheckErr('');
    try {
      const r = await onRecheck();
      if (r.ok) {
        setSuccess(true);
        window.setTimeout(onReady, 900);
      } else {
        setRecheckErr(r.reason || '检测未通过，请按上方步骤完成安装后重试');
      }
    } catch (e) {
      setRecheckErr(e instanceof Error ? e.message : '检测失败');
    } finally {
      setRechecking(false);
    }
  };

  const steps = [
    {
      key: 'root',
      icon: HardDrive,
      title: '定位引擎目录',
      body: engineStatus.engine_root
        ? '应用已在以下位置找到引擎代码目录：'
        : '应用未找到引擎目录。请确认安装目录下存在 engine\\ 文件夹（内含 tuan_cli\\ 与 requirements.txt）。',
      cmd: engineStatus.engine_root || '<安装目录>\\engine',
      cmdNote: '目录路径',
    },
    {
      key: 'python',
      icon: Terminal,
      title: '准备 Python 3.10 或更高版本',
      body: engineStatus.python
        ? '已探测到可用的 Python 解释器：'
        : '未探测到 Python。请到 python.org 下载安装 3.10+（安装时勾选 "Add to PATH"），或把便携版 python.exe 放到 <安装目录>\\engine\\python\\ 下。',
      cmd: engineStatus.python || 'python --version',
      cmdNote: engineStatus.python ? '解释器路径' : '验证命令',
    },
    {
      key: 'deps',
      icon: Package,
      title: '安装引擎依赖',
      body: '在系统终端（PowerShell）中执行下面命令，为引擎安装 rich / httpx / pyyaml 等依赖：',
      cmd: requirementsCmd(engineStatus.engine_root),
      cmdNote: 'pip 命令',
      alt: 'python scripts/install_engine_env.py',
      altNote: '或（开发机）一键脚本',
    },
  ];

  const doneCount = steps.filter((s) => done[s.key]).length;
  const pct = success ? 100 : Math.round((doneCount / 4) * 100);

  // 手动打开且引擎已就绪：只展示信息卡（无需安装步骤）
  if (manual && engineStatus.ok) {
    return (
      <div className="fixed inset-0 z-[90] overflow-y-auto custom-scrollbar bg-tuan-main">
        <div className="max-w-[560px] mx-auto px-6 py-16">
          <div className="onboard-card-in flex flex-col items-center text-center mb-8">
            <BrandMark size="lg" className="mb-5" />
            <h1 className="text-[22px] font-semibold text-tuan-heading mb-2" style={{ fontFamily: '"Spectral","Source Serif 4",Georgia,serif' }}>
              本地引擎已就绪
            </h1>
            <p className="text-[14px] text-tuan-textSecondary">青小团的「身体」在线，完整 Agent 能力（工具调用 / 安全闸门 / 可撤销操作）全部可用。</p>
          </div>
          <div className="onboard-card-in bg-tuan-input border border-tuan-border rounded-xl px-4 py-3 space-y-1.5" style={{ animationDelay: '0.08s' }}>
            {engineStatus.app_version && (
              <div className="flex justify-between text-[13px]"><span className="text-tuan-textSecondary">外壳版本</span><span className="text-tuan-text font-mono">v{engineStatus.app_version}</span></div>
            )}
            {engineStatus.engine_version && (
              <div className="flex justify-between text-[13px]"><span className="text-tuan-textSecondary">引擎版本</span><span className="text-tuan-text font-mono">v{engineStatus.engine_version}</span></div>
            )}
            {engineStatus.python && (
              <div className="flex justify-between gap-4 text-[13px]"><span className="text-tuan-textSecondary flex-none">Python</span><span className="text-tuan-text font-mono truncate" title={engineStatus.python}>{engineStatus.python}</span></div>
            )}
            {engineStatus.engine_root && (
              <div className="flex justify-between gap-4 text-[13px]"><span className="text-tuan-textSecondary flex-none">引擎目录</span><span className="text-tuan-text font-mono truncate" title={engineStatus.engine_root}>{engineStatus.engine_root}</span></div>
            )}
          </div>
          <div className="onboard-card-in mt-10 flex justify-center" style={{ animationDelay: '0.14s' }}>
            <button
              onClick={onEnterDegraded}
              className="inline-flex items-center gap-2 h-10 px-5 rounded-full border border-tuan-border text-[14px] text-tuan-text hover:bg-tuan-hover transition-colors"
            >
              返回
              <ArrowRight size={15} />
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (success) {
    return (
      <div className="fixed inset-0 z-[90] flex flex-col items-center justify-center bg-tuan-main px-6">
        <div className="onboard-success-glow w-20 h-20 rounded-full bg-tuan-ok-bg flex items-center justify-center mb-6">
          <Check size={36} className="text-tuan-ok" strokeWidth={2.5} />
        </div>
        <h1 className="text-[22px] font-semibold text-tuan-text mb-2">本地引擎已就绪</h1>
        <p className="text-[14px] text-tuan-textSecondary">正在进入青小团…</p>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-[90] overflow-y-auto custom-scrollbar bg-tuan-main">
      <div className="max-w-[640px] mx-auto px-6 py-14">
        {/* 头部：品牌标识 + 欢迎语 */}
        <div className="onboard-card-in flex flex-col items-center text-center mb-10">
          <BrandMark size="lg" className="mb-5" />
          <h1 className="text-[24px] font-semibold text-tuan-heading mb-2" style={{ fontFamily: '"Spectral","Source Serif 4",Georgia,serif' }}>
            欢迎使用青小团
          </h1>
          <p className="text-[14px] leading-relaxed text-tuan-textSecondary max-w-[460px]">
            本地引擎还没就绪。它是青小团的「身体」——负责把想法变成真实、可撤销的操作。
            按下面四步装好它，大约需要两分钟；想先用起来，也可以随时以纯对话模式进入。
          </p>
        </div>

        {/* 诊断信息（真实数据） */}
        <div className="onboard-card-in bg-tuan-input border border-tuan-border rounded-xl px-4 py-3 mb-8" style={{ animationDelay: '0.06s' }}>
          <div className="text-[12px] text-tuan-textSecondary mb-1">自检结果</div>
          <div className="text-[13px] text-tuan-text font-mono break-all">
            {engineStatus.reason || '本地引擎不可用'}
          </div>
        </div>

        {/* 进度 */}
        <div className="onboard-card-in flex items-center gap-3 mb-6" style={{ animationDelay: '0.1s' }}>
          <div className="flex-1 h-[4px] rounded-full bg-tuan-border overflow-hidden">
            <div className="h-full rounded-full bg-tuan-accent transition-all duration-500 ease-out" style={{ width: `${pct}%` }} />
          </div>
          <span className="text-[12px] text-tuan-textSecondary tabular-nums">{pct}%</span>
        </div>

        {/* 四步引导 */}
        <div className="space-y-4">
          {steps.map((s, i) => {
            const Icon = s.icon;
            const isDone = !!done[s.key];
            return (
              <div
                key={s.key}
                className={`onboard-card-in bg-tuan-input border rounded-xl px-4 py-4 transition-colors ${isDone ? 'border-tuan-ok/60' : 'border-tuan-border'}`}
                style={{ animationDelay: `${0.14 + i * 0.08}s` }}
              >
                <div className="flex items-start gap-3">
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-none ${isDone ? 'bg-tuan-ok-bg' : 'bg-tuan-hover'}`}>
                    {isDone ? <Check size={16} className="text-tuan-ok" strokeWidth={2.5} /> : <Icon size={16} className="text-tuan-textSecondary" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[12px] text-tuan-textSecondary tabular-nums">第 {i + 1} 步</span>
                      <h3 className="text-[14.5px] font-medium text-tuan-text">{s.title}</h3>
                    </div>
                    <p className="text-[13px] leading-relaxed text-tuan-textSecondary mt-1">{s.body}</p>

                    {/* 可复制内容 */}
                    <div className="mt-2.5 space-y-2">
                      <div className="flex items-stretch gap-2">
                        <code className="flex-1 min-w-0 text-[12px] font-mono bg-tuan-bg border border-tuan-border rounded-lg px-2.5 py-1.5 text-tuan-text truncate" title={s.cmd}>
                          {s.cmd}
                        </code>
                        <button
                          onClick={() => copy(s.key, s.cmd)}
                          className="flex-none px-2.5 rounded-lg border border-tuan-border text-tuan-textSecondary hover:text-tuan-text hover:bg-tuan-hover transition-colors"
                          title={`复制${s.cmdNote}`}
                        >
                          {copied === s.key ? <Check size={14} className="text-tuan-ok" /> : <Copy size={14} />}
                        </button>
                      </div>
                      {s.alt && (
                        <div className="flex items-stretch gap-2">
                          <code className="flex-1 min-w-0 text-[12px] font-mono bg-tuan-bg border border-tuan-border rounded-lg px-2.5 py-1.5 text-tuan-text truncate" title={s.alt}>
                            {s.alt}
                          </code>
                          <button
                            onClick={() => copy(s.key + '-alt', s.alt!)}
                            className="flex-none px-2.5 rounded-lg border border-tuan-border text-tuan-textSecondary hover:text-tuan-text hover:bg-tuan-hover transition-colors"
                            title={`复制${s.altNote}`}
                          >
                            {copied === s.key + '-alt' ? <Check size={14} className="text-tuan-ok" /> : <Copy size={14} />}
                          </button>
                        </div>
                      )}
                    </div>

                    {/* 标记完成 */}
                    <button
                      onClick={() => setDone((d) => ({ ...d, [s.key]: !d[s.key] }))}
                      className={`mt-3 inline-flex items-center gap-1.5 text-[12.5px] transition-colors ${isDone ? 'text-tuan-ok' : 'text-tuan-textSecondary hover:text-tuan-text'}`}
                    >
                      {isDone ? <Check size={13} /> : <CircleDashed size={13} />}
                      {isDone ? '已完成' : '标记为已完成'}
                    </button>
                  </div>
                </div>
              </div>
            );
          })}

          {/* 第 4 步：重新检测 */}
          <div className="onboard-card-in bg-tuan-input border border-tuan-border rounded-xl px-4 py-4" style={{ animationDelay: '0.38s' }}>
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-lg bg-tuan-hover flex items-center justify-center flex-none">
                <SearchCheck size={16} className="text-tuan-textSecondary" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-[12px] text-tuan-textSecondary tabular-nums">第 4 步</span>
                  <h3 className="text-[14.5px] font-medium text-tuan-text">重新检测</h3>
                </div>
                <p className="text-[13px] leading-relaxed text-tuan-textSecondary mt-1">
                  装好后点这里，应用会真实地重新检查一遍。通过后直接进入主界面。
                </p>
                {recheckErr && <p className="text-[12.5px] text-tuan-danger mt-2">{recheckErr}</p>}
                <button
                  onClick={recheck}
                  disabled={rechecking}
                  className="mt-3 inline-flex items-center gap-2 h-9 px-4 rounded-lg bg-tuan-accent text-tuan-bg text-[13.5px] font-medium hover:opacity-90 disabled:opacity-60 transition-opacity"
                >
                  {rechecking ? <RefreshCw size={14} className="animate-spin" /> : <SearchCheck size={14} />}
                  {rechecking ? '检测中…' : '重新检测'}
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* 底部：降级通道 / 返回 */}
        <div className="onboard-card-in mt-10 flex flex-col items-center gap-3" style={{ animationDelay: '0.46s' }}>
          <button
            onClick={onEnterDegraded}
            className="inline-flex items-center gap-2 h-10 px-5 rounded-full border border-tuan-border text-[14px] text-tuan-text hover:bg-tuan-hover transition-colors"
          >
            {manual ? '返回' : '先以降级模式进入'}
            <ArrowRight size={15} />
          </button>
          <p className="text-[12px] text-tuan-textSecondary text-center leading-relaxed max-w-[420px]">
            {manual
              ? '安装完成后点上方「重新检测」，通过即自动回到主界面。'
              : '降级模式 = 纯对话：不需要引擎也能立刻聊天（无工具调用与安全闸门）。之后随时点标题栏里的状态灯，可以回来接着装。'}
          </p>
        </div>
      </div>
    </div>
  );
}
