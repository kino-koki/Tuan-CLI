#!/usr/bin/env python3
"""code-architect 终检脚本：对交付项目做可机械判定的工程健康检查。

用法：
    python preflight.py [项目根目录]      # 默认当前目录
    python preflight.py --simple 项目根    # 只输出 PASS/FAIL 与退出码

结果分级：
    PASS  检查项确认通过
    WARN  建议补齐（不阻断交付，但请在交付说明中提及）
    FAIL  必须修复（直接影响工程健康度）
    SKIP  该项目不适用（如无依赖声明）

退出码：0 = 无 FAIL，可交付；1 = 存在 FAIL，需修复后重跑。

注意：本脚本是可机械判定的"终检子集"，用于兜底明显缺口；
不可机械判定的终检项（选型是否绑定痛点、验收标准是否量化、接口契约
是否稳定等）仍需按 SKILL.md 终检清单人工自检。错误路径/日志钩子等
检查为启发式，只能发现明显信号，不能替代代码审查。
"""
import json
import os
import re
import sys

ROOT = "."
RESULTS = []
SIMPLE = False

CODE_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".rb",
    ".php", ".c", ".cpp", ".h", ".hpp", ".cs", ".kt", ".swift", ".scala",
    ".sh", ".lua", ".ex", ".exs", ".erl", ".hs",
}
NOISE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "vendor",
    "dist", "build", "target", ".next", ".nuxt", ".idea", ".vscode", "coverage",
}


def report(name, level, detail):
    RESULTS.append({"name": name, "level": level, "detail": detail})
    if SIMPLE:
        print(f"[{level:4s}] {name}")
    else:
        print(f"[{level:4s}] {name}: {detail}")


def exists(*rel):
    return os.path.exists(os.path.join(ROOT, *rel))


def scan_files():
    found = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in NOISE_DIRS]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            found.append(os.path.relpath(full, ROOT))
    return found


def main():
    global ROOT, SIMPLE
    args = sys.argv[1:]
    if "--simple" in args:
        SIMPLE = True
        args.remove("--simple")
    ROOT = args[0] if args else "."
    ROOT = os.path.abspath(ROOT)
    if not os.path.isdir(ROOT):
        print(f"错误：{ROOT} 不是目录", file=sys.stderr)
        return 2

    # 1. 版本控制
    if exists(".git"):
        report("版本控制", "PASS", "存在 .git 目录")
    else:
        report("版本控制", "WARN", "未发现 .git（交付包可裁剪，但开发期应有版本控制与提交历史）")

    # 2. 文档（README）
    if any(exists(x) for x in ("README.md", "README.rst", "README.txt", "readme.md")):
        report("README", "PASS", "发现 README")
    else:
        report("README", "WARN", "未发现 README（应回答：这是什么、怎么装、怎么用、怎么扩展）")

    # 3. CI 配置
    ci_candidates = [
        ".github/workflows", ".gitlab-ci.yml", "Jenkinsfile", ".travis.yml",
        "azure-pipelines.yml", "circle.yml", ".circleci", "buildspec.yml",
        "appveyor.yml", ".buildkite", "bitbucket-pipelines.yml",
    ]
    found_ci = [c for c in ci_candidates if exists(c)]
    if found_ci:
        report("CI", "PASS", f"发现 CI 配置（{found_ci[0]}）")
    else:
        report("CI", "WARN", "未发现 CI 配置（项目型交付建议至少配置 lint + test 流水线）")

    # 4. 依赖声明/锁文件
    lock_candidates = [
        "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "Cargo.lock",
        "go.sum", "poetry.lock", "Pipfile.lock", "Gemfile.lock", "composer.lock",
        "requirements.txt", "Pipfile", "pyproject.toml", "Gemfile", "pom.xml",
        "build.gradle", "mix.lock", "pubspec.lock", "cargo.toml", "go.mod",
    ]
    found_lock = [c for c in lock_candidates if exists(c)]
    if found_lock:
        lock_name = found_lock[0]
        if lock_name.endswith(("lock", "sum")):
            report("依赖锁定", "PASS", f"发现锁文件（{lock_name}）")
        else:
            report("依赖锁定", "PASS", f"发现依赖声明（{lock_name}；若有锁定文件建议一并提交）")
    else:
        report("依赖锁定", "SKIP", "未发现依赖声明（无外部依赖或无需锁定则可忽略）")

    # 5. 测试
    all_files = scan_files()
    test_like = [f for f in all_files if "test" in os.path.basename(f).lower()]
    if test_like:
        report("测试", "PASS", f"发现 {len(test_like)} 个测试相关文件")
    else:
        report("测试", "WARN", "未发现测试（核心逻辑应至少覆盖正常路径与边界）")

    # 6. 错误路径与日志钩子（启发式）
    # 排除脚本自身与常见构建产物，避免把校验消息文本当作代码信号
    code_files = [
        f for f in all_files
        if os.path.splitext(f)[1] in CODE_EXTS
        and os.path.basename(f) != "preflight.py"
    ]
    if code_files:
        merged = ""
        for f in code_files:
            try:
                with open(os.path.join(ROOT, f), encoding="utf-8", errors="ignore") as fh:
                    merged += fh.read() + "\n"
            except OSError:
                pass
        has_log = any(k in merged for k in ("logging", "logger", "log(", "log.", "console.error", "tracing::", "slog", "zap.", "logger.info"))
        swallow_marks = []
        if re.search(r"except\s*:\s*pass", merged):
            swallow_marks.append("裸 except: pass")
        if re.search(r"except\s+Exception\s*:\s*pass", merged):
            swallow_marks.append("except Exception: pass")
        if re.search(r"catch\s*\([^)]*\)\s*\{\s*\}", merged):
            swallow_marks.append("空 catch 块")
        if has_log and not swallow_marks:
            report("错误路径可观测", "PASS", "源码含日志/错误输出信号，未发现明显吞异常模式")
        elif has_log:
            report("错误路径可观测", "WARN", f"已观测到日志信号，但存在疑似吞异常：{'; '.join(swallow_marks)}（请人工确认）")
        else:
            report("错误路径可观测", "WARN", "源码中未发现日志/错误输出信号（关键失败路径应有可见的日志或错误返回）")
    else:
        report("错误路径可观测", "SKIP", "未发现代码文件（可能为纯文档/配置交付）")

    # 7. 占位符残留
    todo_count = 0
    if code_files:
        for f in code_files:
            try:
                with open(os.path.join(ROOT, f), encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        if re.search(r"\b(TODO|FIXME|XXX|HACK)\b", line):
                            todo_count += 1
            except OSError:
                pass
    if todo_count == 0:
        report("占位符", "PASS", "未发现 TODO/FIXME")
    else:
        report("占位符", "WARN", f"发现 {todo_count} 处 TODO/FIXME（上线前应清理或明确归属）")

    # 汇总
    fails = [r for r in RESULTS if r["level"] == "FAIL"]
    warns = [r for r in RESULTS if r["level"] == "WARN"]
    print("")
    print(f"共 {len(RESULTS)} 项检查：{len(fails)} FAIL / {len(warns)} WARN / 其余 PASS/SKIP")
    if fails:
        print("存在 FAIL 项，请修复后重新交付。")
        return 1
    print("无 FAIL 项：可交付。若有 WARN 项，请在交付说明中提及。")
    return 0


if __name__ == "__main__":
    sys.exit(main())