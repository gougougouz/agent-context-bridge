# agentlink 一键安装（Windows）
#
#   pwsh -ExecutionPolicy Bypass -File install.ps1
#
# 做三件事：检查 Python、安装 zstandard、把技能装进 DSH / Codex / Claude 的技能目录。
# 不修改系统 PATH，除非你传 -AddToPath。

param(
    [string]$Python = "D:\PythonEnv\python.exe",
    [switch]$AddToPath
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "== agentlink 安装 ==" -ForegroundColor Cyan
if (-not (Test-Path $Python)) {
    $found = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $found) { throw "找不到 Python：请用 -Python <路径> 指定" }
    $Python = $found
}
Write-Host "Python : $Python"
& $Python --version

Write-Host "`n[1/2] 安装依赖 zstandard" -ForegroundColor Cyan
& $Python -m pip install --disable-pip-version-check zstandard

Write-Host "`n[2/2] 安装技能到 DSH / Codex / Claude" -ForegroundColor Cyan
$env:PYTHONPATH = (Join-Path $repo "src")
$installArgs = @("-m", "agentlink", "install")
if ($AddToPath) { $installArgs += "--path" }
& $Python @installArgs

Write-Host "`n自检：" -ForegroundColor Cyan
& $Python -m agentlink doctor

Write-Host "`n完成。在项目里运行：`n  agentlink init`n  agentlink brief" -ForegroundColor Green