#Requires -Version 5.1
<#
.SYNOPSIS
  zeroAgent local restart (API :8000 + Web :3000).

.DESCRIPTION
  Free ports 8000/3000 (and stale 8001/8002), ensure API_PROXY_TARGET=8000,
  then start uvicorn and Next.js in new windows.
  Port rule: always 8000/3000; never switch to other ports.

.PARAMETER WithCelery
  Also start Celery worker.

.PARAMETER WithDeps
  Also docker compose up mysql/redis/rabbitmq/litellm.

.PARAMETER SkipFrontend
  Restart API only.

.PARAMETER SkipBackend
  Restart Web only.

@author 赵振明
@date 2026-11-19 15:41:53
#>
[CmdletBinding()]
param(
    [switch]$WithCelery,
    [switch]$WithDeps,
    [switch]$SkipFrontend,
    [switch]$SkipBackend
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
$ApiPort = 8000
$WebPort = 3000
$StalePorts = @(8001, 8002)
$EnvLocal = Join-Path $RepoRoot "web\.env.local"
$ProxyTarget = "http://127.0.0.1:$ApiPort"

function Write-Step {
    param([string]$Message)
    Write-Host "[restart-dev] $Message" -ForegroundColor Cyan
}

function Test-ProtectedProcess {
    <#
    .SYNOPSIS
      判断是否为 Docker/WSL 转发进程，禁止误杀以免拖垮 Docker Desktop。
    #>
    param([Parameter(Mandatory = $true)]$Process)

    $name = [string]$Process.ProcessName
    $protected = @(
        "com.docker.backend",
        "com.docker.service",
        "Docker Desktop",
        "docker",
        "dockerd",
        "wslrelay",
        "wslservice",
        "vmmem",
        "vmmemWSL"
    )
    return ($protected -contains $name)
}

function Stop-UvicornOrphanWorkers {
    <#
    .SYNOPSIS
      清理 uvicorn --reload 留下的 multiprocessing 孤儿 worker。

    .NOTES
      父进程被杀后，spawn 子进程仍占 :8000 并继续以旧环境（如 MOCK_EXTERNAL=true）应答，
      导致重启脚本「看起来成功」但实际仍打到旧 Mock 进程。
      @author 赵振明
      @date 2026-11-19 15:55:02
    #>
    $workers = @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -eq "python.exe" -and
                (
                    $_.CommandLine -match "multiprocessing\.spawn" -or
                    $_.CommandLine -match "uvicorn app\.main:app"
                )
            }
    )
    foreach ($w in $workers) {
        $parentAlive = $null -ne (Get-Process -Id $w.ParentProcessId -ErrorAction SilentlyContinue)
        $isMain = $w.CommandLine -match "uvicorn app\.main:app"
        if ($isMain -or -not $parentAlive) {
            Write-Step "Kill uvicorn/orphan pid=$($w.ProcessId) parent=$($w.ParentProcessId)"
            Stop-Process -Id $w.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
}

function Stop-ListenPort {
    param([Parameter(Mandatory = $true)][int]$Port)

    $procIds = @()
    try {
        $procIds = @(
            Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty OwningProcess -Unique
        )
    } catch {
        $lines = netstat -ano | Select-String ":$Port\s+.*LISTENING"
        foreach ($line in $lines) {
            $parts = @(($line.ToString() -split "\s+") | Where-Object { $_ })
            if ($parts.Count -ge 5) {
                $procIds += [int]$parts[-1]
            }
        }
        $procIds = @($procIds | Select-Object -Unique)
    }

    foreach ($procId in $procIds) {
        if (-not $procId -or $procId -le 4) { continue }
        try {
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if ($null -eq $proc) {
                # 设计思路：uvicorn --reload 父进程死后，netstat 仍显示幽灵 PID，
                # 但其 multiprocessing 子进程继续占 127.0.0.1:8000，会挡住 Docker 映射。
                $orphans = @(
                    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                        Where-Object { $_.ParentProcessId -eq $procId } |
                        Select-Object -ExpandProperty ProcessId
                )
                foreach ($childId in $orphans) {
                    Write-Step "Kill orphan worker of dead PID=$procId -> child=$childId (port $Port)"
                    Stop-Process -Id $childId -Force -ErrorAction SilentlyContinue
                }
                continue
            }
            # 设计思路：Docker 把 8000/3306 等映射到 com.docker.backend/wslrelay；
            # 误杀会直接打挂 Docker Desktop，导致 MySQL/API 全部不可用。
            if (Test-ProtectedProcess -Process $proc) {
                Write-Warning "Skip protected PID=$procId ($($proc.ProcessName)) on port $Port"
                continue
            }
            Write-Step "Kill port $Port PID=$procId ($($proc.ProcessName))"
            Stop-Process -Id $procId -Force -ErrorAction Stop
        } catch {
            Write-Warning "Failed to kill PID=$procId : $($_.Exception.Message)"
        }
    }

    if ($Port -eq $ApiPort) {
        Stop-UvicornOrphanWorkers
    }
}

function Ensure-ApiProxyTarget {
    $dir = Split-Path -Parent $EnvLocal
    if (-not (Test-Path $dir)) {
        throw "Web dir missing: $dir"
    }

    $lines = @()
    if (Test-Path $EnvLocal) {
        $lines = @(Get-Content -Path $EnvLocal -ErrorAction SilentlyContinue)
    }

    $found = $false
    $newLines = New-Object System.Collections.Generic.List[string]
    foreach ($line in $lines) {
        if ($line -match "^\s*API_PROXY_TARGET\s*=") {
            $found = $true
            [void]$newLines.Add("API_PROXY_TARGET=$ProxyTarget")
        } else {
            [void]$newLines.Add($line)
        }
    }

    if (-not $found) {
        if ($newLines.Count -eq 0) {
            [void]$newLines.Add("# API fixed :$ApiPort (do not change ports; kill zombie then back to $ApiPort)")
            [void]$newLines.Add("API_PROXY_TARGET=$ProxyTarget")
        } else {
            [void]$newLines.Add("API_PROXY_TARGET=$ProxyTarget")
        }
    }

    $text = ($newLines -join "`r`n") + "`r`n"
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($EnvLocal, $text, $utf8)
    Write-Step "Proxy OK: $EnvLocal -> $ProxyTarget"
}

function Get-DeployEnvValue {
    <#
    .SYNOPSIS
      从 deploy/.env 读取单个键；无文件或无键时返回 $null。
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Key
    )

    $deployEnv = Join-Path $RepoRoot "deploy\.env"
    if (-not (Test-Path $deployEnv)) {
        return $null
    }
    $pattern = "^\s*" + [regex]::Escape($Key) + "\s*=\s*(.+?)\s*$"
    foreach ($line in Get-Content -LiteralPath $deployEnv) {
        if ($line -match "^\s*#" -or [string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        if ($line -match $pattern) {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return $null
}

function Sync-MockExternalFromDeploy {
    <#
    .SYNOPSIS
      用 deploy/.env 的 MOCK_EXTERNAL 覆盖当前进程环境，避免 Cursor/Agent 壳污染。

    .NOTES
      pydantic 优先读进程环境；Agent 会话常残留 MOCK_EXTERNAL=true，
      会盖过 deploy/.env=false，导致 API 回显「收到：…」。
      @author 赵振明
      @date 2026-11-19 15:41:53
    #>
    $fromFile = Get-DeployEnvValue -Key "MOCK_EXTERNAL"
    if ($null -eq $fromFile -or [string]::IsNullOrWhiteSpace($fromFile)) {
        Write-Warning "deploy/.env missing MOCK_EXTERNAL; leave process env as-is ($($env:MOCK_EXTERNAL))"
        return
    }
    $prev = $env:MOCK_EXTERNAL
    $env:MOCK_EXTERNAL = $fromFile
    Write-Step "MOCK_EXTERNAL: process='$prev' -> deploy/.env='$fromFile'"
}

function Start-DevWindow {
    param(
        [Parameter(Mandatory = $true)][string]$Title,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$Command
    )

    if (-not (Test-Path $WorkingDirectory)) {
        throw "WorkingDirectory missing: $WorkingDirectory"
    }

    # 设计思路：子窗口继承父进程环境；显式写入 MOCK_EXTERNAL，防止 Agent 壳 true 污染。
    $mockVal = if ($env:MOCK_EXTERNAL) { $env:MOCK_EXTERNAL } else { "false" }
    $script = @"
Set-Location -LiteralPath '$WorkingDirectory'
`$Host.UI.RawUI.WindowTitle = '$Title'
`$env:MOCK_EXTERNAL = '$mockVal'
$Command
"@
    $bytes = [System.Text.Encoding]::Unicode.GetBytes($script)
    $encoded = [Convert]::ToBase64String($bytes)
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoExit",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-EncodedCommand", $encoded
    ) | Out-Null
    Write-Step "Started window: $Title"
}

function Wait-ApiHealthy {
    param([int]$TimeoutSec = 45)

    $url = "http://127.0.0.1:$ApiPort/health"
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    Write-Step "Waiting health $url ..."
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300) {
                Write-Step "API ready (HTTP $($resp.StatusCode))"
                return
            }
        } catch {
            Start-Sleep -Milliseconds 800
        }
    }
    Write-Warning "Health check timeout ${TimeoutSec}s. Check API window logs."
}

Write-Step "Repo: $RepoRoot"

if (-not (Test-Path $Python)) {
    throw "Python3.12 not found: $Python"
}

Write-Step "Freeing ports..."
$portsToFree = @()
if (-not $SkipBackend) {
    $portsToFree += @($ApiPort) + $StalePorts
}
if (-not $SkipFrontend) {
    $portsToFree += $WebPort
}
foreach ($p in ($portsToFree | Select-Object -Unique)) {
    Stop-ListenPort -Port $p
}
Start-Sleep -Seconds 1

Ensure-ApiProxyTarget
Sync-MockExternalFromDeploy

if ($WithDeps) {
    $deployDir = Join-Path $RepoRoot "deploy"
    Write-Step "docker compose up mysql redis rabbitmq litellm ..."
    Push-Location $deployDir
    try {
        docker compose --env-file .env up -d mysql redis rabbitmq litellm
        if ($LASTEXITCODE -ne 0) {
            throw "docker compose failed with exit $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}

if (-not $SkipBackend) {
    $backendCmd = "& `"$Python`" -m uvicorn app.main:app --app-dir src --reload --host 127.0.0.1 --port $ApiPort"
    Start-DevWindow -Title "zeroAgent-API:$ApiPort" -WorkingDirectory $RepoRoot -Command $backendCmd
}

if (-not $SkipFrontend) {
    $webDir = Join-Path $RepoRoot "web"
    Start-DevWindow -Title "zeroAgent-Web:$WebPort" -WorkingDirectory $webDir -Command "npm run dev"
}

if ($WithCelery) {
    # Windows 必须 solo：prefork 会报 not enough values to unpack (expected 3, got 0)
    $celeryCmd = "`$env:PYTHONPATH = 'src'; & `"$Python`" -m celery -A app.workers.celery_app worker --loglevel=info --pool=solo"
    Start-DevWindow -Title "zeroAgent-Celery" -WorkingDirectory $RepoRoot -Command $celeryCmd
}

if (-not $SkipBackend) {
    Wait-ApiHealthy
}

Write-Host ""
Write-Step "Done. API http://127.0.0.1:$ApiPort  Web http://127.0.0.1:$WebPort"
Write-Step "Examples: .\scripts\restart-dev.ps1 | -WithDeps | -WithCelery"
