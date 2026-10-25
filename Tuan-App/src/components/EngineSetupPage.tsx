import { useState } from 'react';
import { Check, RefreshCw, ArrowRight, CircleDashed } from 'lucide-react';
import type { BootEngineStatus } from './BootScreen';
import BrandMark from './BrandMark';
import {
  OnboardCheck,
  OnboardCommand,
  OnboardProgress,
  OnboardShell,
  OnboardStepDot,
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

/**
 * 引擎安装向导（豆包 × CodeX 风格，2026-10-25 恢复完整动效层）。
 *
 * 与 BootScreen 共用 OnboardKit 设计语言：同底、同卡、同打勾、同菊花、
 * 同进度条——是主界面"第一次开机"的延伸，不像一个外来网页。
 * 版式上采用清单式步骤卡：行间发丝分隔，步骤指示位是 26px 细边圆
 * （序号 → 爬动菊花 → 陶土橘打勾），整组以 onboard-card-in 交错落入。
 *
 * 诚实原则：不做假下载表演。三步引导全部给**真实可复制**的命令（终端深色
 * chip，与聊天代码块同款），第四步的「重新检测」是真实回调 Rust
 * `check_engine`；通过即放行（onboard-success-glow 柔光扩散）。
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

  // ===== 成功态：与启动序列同一套"品牌 + 打勾"收尾 =====
  if (success) {
    return (
      <OnboardShell>
        <div className="flex-1 flex flex-col items-center justify-center px-6 text-center">
          <div className="boot-item-in relative mb-6">
            <BrandMark size="lg" className="boot-float" />
            <span className="onboard-success-glow absolute -bottom-1 -right-1 inline-flex rounded-full">
              <OnboardCheck size="lg" />
            </span>
          </div>
          <h1 className="boot-item-in onboard-hero text-[24px] font-semibold text-tuan-heading mb-2" style={{ animationDelay: '0.14s' }}>
            本地引擎已就绪
          </h1>
          <p className="boot-item-in text-[14px] text-tuan-textSecondary" style={{ animationDelay: '0.22s' }}>
            正在进入青小团…
          </p>
        </div>
      </OnboardShell>
    );
  }

  // ===== 手动打开且引擎已就绪：只展示信息卡（无需安装步骤）=====
  if (manual && engineStatus.ok) {
    return (
      <OnboardShell scroll>
        <div className="mx-auto w-full max-w-[520px] py-14">
          <div className="onboard-card-in flex flex-col items-center text-center mb-8">
            <BrandMark size="lg" className="mb-5" />
            <h1 className="onboard-hero text-[22px] font-semibold text-tuan-heading mb-2">
              本地引擎已就绪
            </h1>
            <p className="text-[14px] leading-relaxed text-tuan-textSecondary max-w-[440px]">
              青小团的「身体」在线，完整 Agent 能力（工具调用 / 安全闸门 / 可撤销操作）全部可用。
            </p>
          </div>
          <div className="onboard-card-in tuan-card px-5 py-4 space-y-1.5" style={{ animationDelay: '0.08s' }}>
            {engineStatus.app_version && (
              <div className="flex justify-between text-[13px]"><span className="text-tuan-textSecondary">外壳版本</span><span className="text-tuan-text font-mono">v{engineStatus.app_version}</span></div>
            )}
            {engineStatus.engine_version && (
              <div className="flex justify-between text-[13px]"><span className="text-tuan-textSecondary">引擎版本</span><span className="text-tuan-text font-mono">v{engineStatus.engine_version}</span></div>
            )}
            {engineStatus.python && (
              <div className="flex gap-4 text-[13px]"><span className="flex-none text-tuan-textSecondary">Python</span><span className="truncate text-tuan-text font-mono" title={engineStatus.python}>{engineStatus.python}</span></div>
            )}
            {engineStatus.engine_root && (
              <div className="flex gap-4 text-[13px]"><span className="flex-none text-tuan-textSecondary">引擎目录</span><span className="truncate text-tuan-text font-mono" title={engineStatus.engine_root}>{engineStatus.engine_root}</span></div>
            )}
          </div>
          <div className="onboard-card-in mt-10 flex justify-center" style={{ animationDelay: '0.14s' }}>
            <button
              onClick={onEnterDegraded}
              className="cc-btn-ghost h-10 px-5 text-[14px]"
            >
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
      <div className="mx-auto w-full max-w-[520px] py-14">
        {/* 头部：品牌标识 + 欢迎语（衬线仅此一处，同 ChatView 空态问候语） */}
        <div className="onboard-card-in flex flex-col items-center text-center mb-10">
          <BrandMark size="lg" className="mb-5" />
          <h1 className="onboard-hero text-[24px] font-semibold text-tuan-heading mb-2">
            欢迎使用青小团
          </h1>
          <p className="max-w-[440px] text-[14px] leading-relaxed text-tuan-textSecondary">
            本地引擎还没就绪。它是青小团的「身体」——负责把想法变成真实、可撤销的操作。
            按下面四步装好它，大约需要两分钟；想先用起来，也可以随时以纯对话模式进入。
          </p>
        </div>

        {/* 诊断信息（真实数据） */}
        <div className="onboard-card-in tuan-card mb-6 px-5 py-4" style={{ animationDelay: '0.06s' }}>
          <div className="mb-1 text-[12px] text-tuan-textSecondary">自检结果</div>
          <div className="break-all font-mono text-[13px] text-tuan-text">
            {engineStatus.reason || '本地引擎不可用'}
          </div>
        </div>

        {/* 进度（与启动序列同一条进度条） */}
        <div className="onboard-card-in mb-6" style={{ animationDelay: '0.1s' }}>
          <OnboardProgress pct={pct} />
        </div>

        {/* 四步引导：一张清单卡，行间发丝分隔（Claude 设置面板式） */}
        <div className="onboard-card-in tuan-card overflow-hidden" style={{ animationDelay: '0.14s' }}>
          {steps.map((s, i) => {
            const isDone = !!done[s.key];
            return (
              <div
                key={s.key}
                className={`boot-item-in px-5 py-4 ${i > 0 ? 'border-t border-tuan-border' : ''}`}
                style={{ animationDelay: `${0.18 + i * 0.08}s` }}
              >
                <div className="flex items-start space-x-3.5">
                  <div className="pt-0.5">
                    <OnboardStepDot n={i + 1} done={isDone} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center space-x-2">
                      <span className="text-[11.5px] text-tuan-textSecondary tabular-nums">第 {i + 1} 步</span>
                      <h3 className="text-[14.5px] font-medium text-tuan-text">{s.title}</h3>
                    </div>
                    <p className="mt-1 text-[13px] leading-relaxed text-tuan-textSecondary">{s.body}</p>

                    {/* 可复制命令（终端 chip，与聊天代码块同款底色） */}
                    <OnboardCommand
                      text={s.cmd}
                      note={s.cmdNote}
                      copied={copied === s.key}
                      onCopy={() => copy(s.key, s.cmd)}
                    />
                    {s.alt && (
                      <OnboardCommand
                        text={s.alt}
                        note={s.altNote}
                        copied={copied === s.key + '-alt'}
                        onCopy={() => copy(s.key + '-alt', s.alt!)}
                      />
                    )}

                    {/* 标记完成 */}
                    <button
                      onClick={() => setDone((d) => ({ ...d, [s.key]: !d[s.key] }))}
                      className={`mt-3 inline-flex items-center space-x-1.5 text-[12.5px] transition-colors ${
                        isDone ? 'text-tuan-accentSoft' : 'text-tuan-textSecondary hover:text-tuan-text'
                      }`}
                    >
                      {isDone ? <Check size={13} /> : <CircleDashed size={13} />}
                      <span>{isDone ? '已完成' : '标记为已完成'}</span>
                    </button>
                  </div>
                </div>
              </div>
            );
          })}

          {/* 第 4 步：重新检测 */}
          <div className="boot-item-in border-t border-tuan-border px-5 py-4" style={{ animationDelay: '0.42s' }}>
            <div className="flex items-start space-x-3.5">
              <div className="pt-0.5">
                <OnboardStepDot n={4} done={false} busy={rechecking} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center space-x-2">
                  <span className="text-[11.5px] text-tuan-textSecondary tabular-nums">第 4 步</span>
                  <h3 className="text-[14.5px] font-medium text-tuan-text">重新检测</h3>
                </div>
                <p className="mt-1 text-[13px] leading-relaxed text-tuan-textSecondary">
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
          </div>
        </div>

        {/* 底部：降级通道 / 返回 */}
        <div className="onboard-card-in mt-10 flex flex-col items-center space-y-3" style={{ animationDelay: '0.5s' }}>
          <button
            onClick={onEnterDegraded}
            className="cc-btn-ghost h-10 px-5 text-[14px]"
          >
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
