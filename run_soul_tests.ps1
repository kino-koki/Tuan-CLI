$ErrorActionPreference = "Continue"
# 临时目录: 使用系统盘 (不写死 C:, 兼容以其他盘为主盘的机器)
$tmpRoot = Join-Path $env:SystemDrive "Temp"
$env:TEMP = $tmpRoot
$env:TMP = $tmpRoot
if (-not (Test-Path $tmpRoot)) {
    try { New-Item -ItemType Directory -Force -Path $tmpRoot | Out-Null } catch { }
}
# 用脚本自身所在目录作为仓库根，不写死盘符
cd $PSScriptRoot
python -m pytest tests/test_prompt_tier.py tests/test_soul_template.py tests/test_prompt_cache_segmentation.py tests/test_prompt_discipline.py tests/test_prompt_execution.py -q -p no:cacheprovider 2>&1 | Select-String -Pattern "passed|failed|error"
