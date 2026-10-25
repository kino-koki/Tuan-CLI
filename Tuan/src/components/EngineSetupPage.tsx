import { useState } from 'react';
import { Check, RefreshCw, ArrowRight } from 'lucide-react';
import BrandMark from './BrandMark';

/** 引擎自检结果（BootScreen 移除后由本页定义并导出，App 与设置页共用） */
export interface BootEngineStatus {
  ok: boolean;
  reason: string;
  python: string;
  app_version?: string;
  engine_version?: string;
  engine_root?: string;
}
import {
  BrailleSpinner,
  OnboardCheck,
  OnboardProgress,
  OnboardShell,
  TermCommand,
  TermWindow,
} from './OnboardKit';

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

/** 品牌标识位：呼吸柔光 + 轻浮动 + 交错落入（与启动序列同一枚 BrandMark）。 */
function BrandHero({ size }: { size: 'lg' | 'xl' }) {
  const box = size === 'xl' ? 'h-[128px] w-[128px]' : 'h-[112px] w-[112px]';
  return (
    <div className={`boot-item-in relative mx-auto mb-10 flex ${box} items-center justify-center`}>
      <div className="boot-halo" />
      <BrandMark size={size} className="boot-float relative" />
    </div>
  );
}

/**
 * 引擎安装向导（CodeX 式 TUI 安装终端）。
 *
 * 结构照抄 OpenAI Codex 的首次运行安装引导：一扇终端窗口（三点窗饰 +
 * 等宽标题栏 + 底部状态栏），窗内 `>_` 标识行 + meta 行（engine / python
 * 实时自检值）、`!` 诊断行、进度条，然后是编号步骤（01–04）：每步给出
 * `$` 前缀的真实可复制命令（终端 chip，与聊天代码块同款底色）和审批式
 * `[ ]/[x]` 完成标记（Codex approval prompt 的口径）；第 4 步「重新检测」
 * 是真实回调 Rust `check_engine`，通过后窗口内打勾 + 柔光扩散收尾。
 *
 * 诚实原则：不做假下载表演。随时可走「降级模式」先用起来——装好引擎后
 * 从标题栏状态灯随时回来。动效与启动序列同 vocab（halo / float /
 * item-in / check-pop / card-in / success-glow）。
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
      title: '定位引擎目录',
      body: engineStatus.engine_root
        ? '应用已在以下位置找到引擎代码目录：'
        : '应用未找到引擎目录。请确认安装目录下存在 engine\\ 文件夹（内含 tuan_cli\\ 与 requirements.txt）。',
      cmd: engineStatus.engine_root || '<安装目录>\\engine',
      cmdNote: '目录路径',
    },
    {
      key: 'python',
      title: '准备 Python 3.10 或更高版本',
      body: engineStatus.python
        ? '已探测到可用的 Python 解释器：'
        : '未探测到 Python。请到 python.org 下载安装 3.10+（安装时勾选 "Add to PATH"），或把便携版 python.exe 放到 <安装目录>\\engine\\python\\ 下。',
      cmd: engineStatus.python || 'python --version',
      cmdNote: engineStatus.python ? '解释器路径' : '验证命令',
    },
    {
      key: 'deps',
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
  const appVersion = engineStatus.app_version;
  const engineVersion = engineStatus.engine_version;

  // ===== 成功态：终端窗口内的打勾收尾（柔光扩散后自动进入）=====
  if (success) {
    return (
      <OnboardShell>
        <div className="flex-1 flex flex-col items-center justify-center px-6">
          <TermWindow
            className="boot-item-in w-[400px] max-w-full"
            title="tuan — engine setup"
            right={appVersion ? `v${appVersion}` : undefined}
          >
            <div className="flex flex-col items-center py-7 text-center">
              <span className="onboard-success-glow inline-flex rounded-full">
                <OnboardCheck size="lg" />
              </span>
              <div className="tuan-mono boot-item-in mt-6 text-[13px] text-tuan-text" style={{ animationDelay: '0.2s' }}>
                engine: ready
              </div>
              <p className="boot-item-in mt-1.5 text-[13px] text-tuan-textSecondary" style={{ animationDelay: '0.28s' }}>
                正在进入青小团…
              </p>
            </div>
          </TermWindow>
        </div>
      </OnboardShell>
    );
  }

  // ===== 手动打开且引擎已就绪：只展示状态窗口（CodeX /status 的口径）=====
  if (manual && engineStatus.ok) {
    return (
      <OnboardShell scroll>
        <div className="mx-auto w-full max-w-[520px] py-14">
          <BrandHero size="lg" />
          <TermWindow
            className="onboard-card-in w-full"
            title="tuan — status"
            right={appVersion ? `v${appVersion}` : undefined}
            footer={<span>{engineStatus.ok ? 'engine: ready' : 'engine: not ready'}</span>}
          >
            <div className="flex items-center gap-2">
              <span className="term-prompt">&gt;_</span>
              <span className="tuan-mono text-[13px] font-medium text-tuan-text">青小团 Tuan</span>
            </div>
            <div className="mt-4 space-y-1.5">
              {engineStatus.app_version && (
                <div className="flex gap-4 text-[13px]">
                  <span className="tuan-mono w-[64px] flex-none text-tuan-textSecondary">shell</span>
                  <span className="tuan-mono text-tuan-text">v{engineStatus.app_version}</span>
                </div>
              )}
              {engineStatus.engine_version && (
                <div className="flex gap-4 text-[13px]">
                  <span className="tuan-mono w-[64px] flex-none text-tuan-textSecondary">engine</span>
                  <span className="tuan-mono text-tuan-text">v{engineStatus.engine_version}</span>
                </div>
              )}
              {engineStatus.python && (
                <div className="flex gap-4 text-[13px]">
                  <span className="tuan-mono w-[64px] flex-none text-tuan-textSecondary">python</span>
                  <span className="tuan-mono min-w-0 truncate text-tuan-text" title={engineStatus.python}>{engineStatus.python}</span>
                </div>
              )}
              {engineStatus.engine_root && (
                <div className="flex gap-4 text-[13px]">
                  <span className="tuan-mono w-[64px] flex-none text-tuan-textSecondary">root</span>
                  <span className="tuan-mono min-w-0 truncate text-tuan-text" title={engineStatus.engine_root}>{engineStatus.engine_root}</span>
                </div>
              )}
            </div>
            <p className="mt-4 text-[13px] leading-relaxed text-tuan-textSecondary">
              青小团的「身体」在线，完整 Agent 能力（工具调用 / 安全闸门 / 可撤销操作）全部可用。
            </p>
          </TermWindow>
          <div className="onboard-card-in mt-10 flex justify-center" style={{ animationDelay: '0.14s' }}>
            <button onClick={onEnterDegraded} className="cc-btn-ghost h-10 px-5 text-[14px]">
              <span>返回</span>
              <ArrowRight size={15} />
            </button>
          </div>
        </div>
      </OnboardShell>
    );
  }

  // ===== 四步安装向导 =====
  return (
    <OnboardShell scroll>
      <div className="mx-auto w-full max-w-[560px] py-14">
        <BrandHero size="lg" />

        <TermWindow
          className="onboard-card-in w-full"
          title="tuan — engine setup"
          right={appVersion ? `v${appVersion}` : undefined}
          footer={
            <>
              <span>4 steps · degraded mode available anytime</span>
              <span>{pct}%</span>
            </>
          }
        >
          {/* `>_` 标识行 + meta 行（实时自检值） */}
          <div className="flex items-center gap-2">
            <span className="term-prompt">&gt;_</span>
            <span className="tuan-mono text-[13px] font-medium text-tuan-text">青小团 Tuan</span>
          </div>
          <div className="tuan-mono term-meta">
            <span className="term-meta-key">engine:</span>{' '}
            {engineStatus.ok ? `ready${engineVersion ? ` · v${engineVersion}` : ''}` : 'not ready'}
          </div>
          <div className="tuan-mono term-meta">
            <span className="term-meta-key">python:</span> {engineStatus.python || 'not found'}
          </div>

          {/* 诊断行（CodeX 的错误信息位：`!` + 等宽正文） */}
          <div className="term-note">
            <span className="text-tuan-danger">!</span> {engineStatus.reason || '本地引擎不可用'}
          </div>

          {/* 进度 */}
          <div className="mt-4">
            <OnboardProgress pct={pct} label={false} />
          </div>

          {/* 编号步骤 01–03：命令 chip + 审批式完成标记 */}
          <div className="mt-5 space-y-5">
            {steps.map((s, i) => {
              const isDone = !!done[s.key];
              return (
                <div key={s.key} className="boot-item-in" style={{ animationDelay: `${0.1 + i * 0.08}s` }}>
                  <div className="flex items-center gap-2.5">
                    <span className="flex h-4 w-4 flex-none items-center justify-center">
                      {isDone ? (
                        <OnboardCheck />
                      ) : (
                        <span className="tuan-mono text-[12px] text-tuan-textSecondary">
                          {String(i + 1).padStart(2, '0')}
                        </span>
                      )}
                    </span>
                    <h3 className="text-[14px] font-medium text-tuan-text">{s.title}</h3>
                  </div>
                  <p className="mt-1.5 text-[13px] leading-relaxed text-tuan-textSecondary">{s.body}</p>

                  <TermCommand
                    text={s.cmd}
                    note={s.cmdNote}
                    copied={copied === s.key}
                    onCopy={() => copy(s.key, s.cmd)}
                  />
                  {s.alt && (
                    <TermCommand
                      text={s.alt}
                      note={s.altNote}
                      copied={copied === s.key + '-alt'}
                      onCopy={() => copy(s.key + '-alt', s.alt!)}
                    />
                  )}

                  {/* 审批式完成标记（CodeX approval prompt 的 `[ ]/[x]` 口径） */}
                  <button
                    onClick={() => setDone((d) => ({ ...d, [s.key]: !d[s.key] }))}
                    className={`mt-2.5 inline-flex items-center gap-1.5 text-[12.5px] transition-colors ${
                      isDone ? 'text-tuan-accentSoft' : 'text-tuan-textSecondary hover:text-tuan-text'
                    }`}
                  >
                    <span className="tuan-mono">{isDone ? '[x]' : '[ ]'}</span>
                    <span>{isDone ? '已完成' : '标记为已完成'}</span>
                  </button>
                </div>
              );
            })}

            {/* 第 4 步：重新检测（真实回调 Rust check_engine） */}
            <div className="boot-item-in" style={{ animationDelay: '0.34s' }}>
              <div className="flex items-center gap-2.5">
                <span className="flex h-4 w-4 flex-none items-center justify-center">
                  {rechecking ? (
                    <BrailleSpinner className="text-tuan-accentSoft" />
                  ) : (
                    <span className="tuan-mono text-[12px] text-tuan-textSecondary">04</span>
                  )}
                </span>
                <h3 className="text-[14px] font-medium text-tuan-text">重新检测</h3>
              </div>
              <p className="mt-1.5 text-[13px] leading-relaxed text-tuan-textSecondary">
                装好后点这里，应用会真实地重新检查一遍。通过后直接进入主界面。
              </p>
              {recheckErr && <p className="mt-2 text-[12.5px] text-tuan-danger">{recheckErr}</p>}
              <button
                onClick={recheck}
                disabled={rechecking}
                className="cc-btn-accent mt-3 h-9 px-4 text-[13.5px] font-medium"
              >
                <RefreshCw size={14} className={rechecking ? 'animate-spin' : ''} />
                <span>{rechecking ? '检测中…' : '重新检测'}</span>
              </button>
            </div>
          </div>
        </TermWindow>

        {/* 底部：降级通道 / 返回 */}
        <div className="onboard-card-in mt-10 flex flex-col items-center space-y-3" style={{ animationDelay: '0.42s' }}>
          <button onClick={onEnterDegraded} className="cc-btn-ghost h-10 px-5 text-[14px]">
            <span>{manual ? '返回' : '先以降级模式进入'}</span>
            <ArrowRight size={15} />
          </button>
          <p className="max-w-[420px] text-center text-[12px] leading-relaxed text-tuan-textSecondary">
            {manual
              ? '安装完成后点上方「重新检测」，通过即自动回到主界面。'
              : '降级模式 = 纯对话：不需要引擎也能立刻聊天（无工具调用与安全闸门）。之后随时点标题栏里的状态灯，可以回来接着装。'}
          </p>
        </div>
      </div>
    </OnboardShell>
  );
}
