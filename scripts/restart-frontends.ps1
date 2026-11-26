#Requires -Version 5.1
<#
.SYNOPSIS
  zeroAgent 一键重启前端：员工端 :3000 + 管理端 :3001。

.DESCRIPTION
  释放 3000/3001（含 web/admin-web 残留 Next 进程），写回两端 API_PROXY_TARGET=8000，
  再在新窗口分别启动 npm run dev。不触碰后端 :8000 / Docker 栈。

.PARAMETER SkipWeb
  仅重启管理端 :3001。

.PARAMETER SkipAdmin
  仅重启员工端 :3000。

@author 赵振明
@date 2026-08-03 09:32:59
#>
[CmdletBinding()]
param(
    [switch]$SkipWeb,
    [switch]$SkipAdmin
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ApiPort = 8000
$WebPort = 3000
$AdminPort = 3001
$ProxyTarget = "http://127.0.0.1:$ApiPort"
$WebDir = Join-Path $RepoRoot "web"
$AdminDir = Join-Path $RepoRoot "admin-web"

function Write-Step {
    param([string]$Message)
    Write-Host "[restart-frontends] $Message" -ForegroundColor Cyan
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

function Stop-ProcessSafe {
    <#
    .SYNOPSIS
      安全结束进程：跳过受保护进程，失败仅告警不中断。
    #>
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [string]$Reason = ""
    )

    if ($ProcessId -le 4) { return }
    try {
        $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        if ($null -eq $proc) { return }
        if (Test-ProtectedProcess -Process $proc) {
            Write-Warning "Skip protected PID=$ProcessId ($($proc.ProcessName))"
            return
        }
        $suffix = if ($Reason) { " ($Reason)" } else { "" }
        Write-Step "Kill PID=$ProcessId ($($proc.ProcessName))$suffix"
        Stop-Process -Id $ProcessId -Force -ErrorAction Stop
    } catch {
        Write-Warning "Failed to kill PID=$ProcessId : $($_.Exception.Message)"
    }
}

function Stop-ListenPort {
    <#
    .SYNOPSIS
      释放指定监听端口上的宿主进程（含幽灵 PID 的孤儿子进程）。
    #>
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
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($null -eq $proc) {
            # 设计思路：父进程已死但子进程仍占端口时，按 ParentProcessId 清孤儿
            $orphans = @(
                Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                    Where-Object { $_.ParentProcessId -eq $procId } |
                    Select-Object -ExpandProperty ProcessId
            )
            foreach ($childId in $orphans) {
                Stop-ProcessSafe -ProcessId $childId -Reason "orphan of dead PID=$procId port=$Port"
            }
            continue
        }
        Stop-ProcessSafe -ProcessId $procId -Reason "port $Port"
    }
}

function Stop-NextByPath {
    <#
    .SYNOPSIS
      按工作区路径结束 web/admin-web 的 Next.js 相关 node 进程。
    #>
    param([Parameter(Mandatory = $true)][string]$Marker)

    $escaped = [regex]::Escape($Marker)
    $nodes = @(
        Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -and ($_.CommandLine -match $escaped) }
    )
    foreach ($n in $nodes) {
        Stop-ProcessSafe -ProcessId ([int]$n.ProcessId) -Reason $Marker
    }
}

function Ensure-ApiProxyTarget {
    <#
    .SYNOPSIS
      确保指定 .env.local 中 API_PROXY_TARGET 指向固定后端 :8000。
    #>
    param([Parameter(Mandatory = $true)][string]$EnvLocalPath)

    $dir = Split-Path -Parent $EnvLocalPath
    if (-not (Test-Path $dir)) {
        throw "Frontend dir missing: $dir"
    }

    $lines = @()
    if (Test-Path $EnvLocalPath) {
        $lines = @(Get-Content -Path $EnvLocalPath -ErrorAction SilentlyContinue)
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
            [void]$newLines.Add("# API fixed :$ApiPort")
        }
        [void]$newLines.Add("API_PROXY_TARGET=$ProxyTarget")
    }

    $text = ($newLines -join "`r`n") + "`r`n"
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($EnvLocalPath, $text, $utf8)
    Write-Step "Proxy OK: $EnvLocalPath -> $ProxyTarget"
}

function Start-DevWindow {
    <#
    .SYNOPSIS
      在独立 PowerShell 窗口中启动开发命令，保持窗口以便查看日志。
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Title,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$Command
    )

    if (-not (Test-Path $WorkingDirectory)) {
        throw "WorkingDirectory missing: $WorkingDirectory"
    }

    $script = @"
Set-Location -LiteralPath '$WorkingDirectory'
`$Host.UI.RawUI.WindowTitle = '$Title'
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

function Wait-HttpReady {
    <#
    .SYNOPSIS
      轮询 HTTP 直到就绪或超时，用于确认前端已监听。
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Name,
        [int]$TimeoutSec = 60
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    Write-Step "Waiting $Name $Url ..."
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
                Write-Step "$Name ready (HTTP $($resp.StatusCode))"
                return
            }
        } catch {
            Start-Sleep -Milliseconds 800
        }
    }
    Write-Warning "$Name health timeout ${TimeoutSec}s. Check the $Name window logs."
}

Write-Step "Repo: $RepoRoot"

if ($SkipWeb -and $SkipAdmin) {
    throw "SkipWeb and SkipAdmin cannot both be set."
}

Write-Step "Stopping frontends..."
if (-not $SkipWeb) {
    Stop-NextByPath -Marker 'zeroAgent\web\'
    Stop-ListenPort -Port $WebPort
}
if (-not $SkipAdmin) {
    Stop-NextByPath -Marker 'zeroAgent\admin-web\'
    Stop-ListenPort -Port $AdminPort
}
Start-Sleep -Seconds 1

if (-not $SkipWeb) {
    Ensure-ApiProxyTarget -EnvLocalPath (Join-Path $WebDir ".env.local")
    Start-DevWindow -Title "zeroAgent-Web:$WebPort" -WorkingDirectory $WebDir -Command "npm run dev"
}
if (-not $SkipAdmin) {
    Ensure-ApiProxyTarget -EnvLocalPath (Join-Path $AdminDir ".env.local")
    Start-DevWindow -Title "zeroAgent-Admin:$AdminPort" -WorkingDirectory $AdminDir -Command "npm run dev"
}

if (-not $SkipWeb) {
    Wait-HttpReady -Url "http://127.0.0.1:$WebPort" -Name "Web"
}
if (-not $SkipAdmin) {
    Wait-HttpReady -Url "http://127.0.0.1:$AdminPort" -Name "Admin"
}

Write-Host ""
Write-Step "Done. Web http://127.0.0.1:$WebPort  Admin http://127.0.0.1:$AdminPort"
Write-Step "Examples: .\scripts\restart-frontends.ps1 | -SkipWeb | -SkipAdmin"
