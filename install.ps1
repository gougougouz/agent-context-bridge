<#
.SYNOPSIS
    Install agentlink (the agent-context-bridge skill) on Windows with one command.

.DESCRIPTION
    irm https://raw.githubusercontent.com/gougougouz/agent-context-bridge/main/install.ps1 | iex

    No git, no clone, no manual pip step. Downloads the repository as a zip,
    puts it under %LOCALAPPDATA%\agentlink, installs the SKILL.md into
    ~/.dsh/skills, ~/.codex/skills and ~/.claude/skills, and adds a launcher
    to your PATH. Re-running it upgrades in place.

    Already know what you are doing?
      & ([scriptblock]::Create((irm <url>))) -Dir F:\app\agentlink -NoPath

.PARAMETER Dir
    Where the tool lives. Default: %LOCALAPPDATA%\agentlink

.PARAMETER Agents
    Comma separated: dsh,codex,claude. Default: all three.

.PARAMETER NoPath
    Do not touch the user PATH.

.PARAMETER NoDeps
    Do not try to install the zstandard dependency.

.PARAMETER Ref
    Branch or tag to install. Default: main
#>
[CmdletBinding()]
param(
    [string]$Dir,
    [string]$Agents = "dsh,codex,claude",
    [switch]$NoPath,
    [switch]$NoDeps,
    [string]$Ref = "main"
)

$ErrorActionPreference = "Stop"
$Repo = "gougougouz/agent-context-bridge"

function Say($msg) { Write-Host "  $msg" }
function Head($msg) { Write-Host ""; Write-Host $msg -ForegroundColor Cyan }
function Fail($msg) {
    Write-Host ""
    Write-Host "  x $msg" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "  agent-context-bridge" -ForegroundColor White -NoNewline
Write-Host "  ·  sync project context across DSH / Codex / Claude" -ForegroundColor DarkGray

# ---------------------------------------------------------------- python
Head "1/4  python"
$pyPrefix = $null
foreach ($candidate in @(@("py", "-3"), @("python"), @("python3"))) {
    $exe = Get-Command $candidate[0] -ErrorAction SilentlyContinue
    if (-not $exe) { continue }
    $prefix = @($exe.Source)
    if ($candidate.Length -gt 1) { $prefix += $candidate[1..($candidate.Length - 1)] }
    $extra = @()
    if ($prefix.Length -gt 1) { $extra = $prefix[1..($prefix.Length - 1)] }
    try {
        $major = & $prefix[0] @extra -c "import sys; print(sys.version_info[0])" 2>$null
        if ($LASTEXITCODE -eq 0 -and "$major".Trim() -eq "3") { $pyPrefix = $prefix; break }
    } catch { }
}
if (-not $pyPrefix) {
    Fail "Python 3.9+ not found. Install it first:  winget install Python.Python.3.12"
}

function PyRun {
    param([Parameter(ValueFromRemainingArguments = $true)] $Rest)
    if ($pyPrefix.Length -gt 1) {
        & $pyPrefix[0] @($pyPrefix[1..($pyPrefix.Length - 1)]) @Rest
    } else {
        & $pyPrefix[0] @Rest
    }
}

$pyVersion = (PyRun -c "import sys; print('.'.join(map(str, sys.version_info[:3])))" | Out-String).Trim()
Say "$($pyPrefix -join ' ')  ($pyVersion)"

# ---------------------------------------------------------------- location
Head "2/4  files"
if (-not $Dir) {
    $base = if ($env:AGENTLINK_HOME) { $env:AGENTLINK_HOME } else { Join-Path $env:LOCALAPPDATA "agentlink" }
    $Dir = $base
}
$Dir = [System.IO.Path]::GetFullPath($Dir)
New-Item -ItemType Directory -Force -Path $Dir | Out-Null

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("agentlink-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$zip = Join-Path $tmp "repo.zip"

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$url = "https://codeload.github.com/$Repo/zip/refs/heads/$Ref"
Say "downloading $Ref"
try {
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
} catch {
    Fail "download failed: $($_.Exception.Message)"
}

Expand-Archive -Path $zip -DestinationPath $tmp -Force
$inner = Get-ChildItem -Path $tmp -Directory | Where-Object { $_.Name -like "agent-context-bridge-*" } | Select-Object -First 1
if (-not $inner) { Fail "unexpected archive layout" }

# replace the code, keep nothing stale (state lives in projects, not here)
Get-ChildItem -Path $Dir -Force | Where-Object { $_.Name -notin @(".venv") } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item -Path (Join-Path $inner.FullName "*") -Destination $Dir -Recurse -Force
Remove-Item -Path $tmp -Recurse -Force -ErrorAction SilentlyContinue
Say "$Dir"

# ---------------------------------------------------------------- dependency
Head "3/4  dependency"
if (-not $NoDeps) {
    $hasZstd = $false
    try {
        PyRun -c "import zstandard" 2>$null
        $hasZstd = ($LASTEXITCODE -eq 0)
    } catch { }
    if ($hasZstd) {
        Say "zstandard already available"
    } else {
        Say "installing zstandard (reads compressed DSH sessions)"
        PyRun -m pip install --quiet --disable-pip-version-check zstandard
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ! pip install failed - Codex/Claude still work, DSH needs it later:" -ForegroundColor Yellow
            Write-Host "    $py -m pip install zstandard" -ForegroundColor Yellow
        }
    }
}

# ---------------------------------------------------------------- skill + launcher
Head "4/4  skill"
$env:PYTHONPATH = Join-Path $Dir "src"
PyRun -m agentlink install --agents $Agents
if ($LASTEXITCODE -ne 0) { Fail "skill installation failed" }

if (-not $NoPath) {
    $bin = Join-Path $Dir "bin"
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $userPath) { $userPath = "" }
    $entries = $userPath.Split(";") | Where-Object { $_ -and $_.Trim() }
    if ($entries -notcontains $bin) {
        $newPath = (@($entries) + $bin) -join ";"
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Say "added to PATH: $bin  (open a new terminal)"
    } else {
        Say "PATH already contains $bin"
    }
    $env:Path = "$bin;$env:Path"
}

Head "done"
Say "try it in any project:"
Write-Host ""
Write-Host "    cd F:\path\to\your-project" -ForegroundColor White
Write-Host "    agentlink brief" -ForegroundColor White
Write-Host ""
Say "restart DSH / Codex / Claude (or open a new session) so the skill shows up."
Write-Host ""
