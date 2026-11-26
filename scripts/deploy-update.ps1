#Requires -Version 5.1
<#
.SYNOPSIS
  zeroAgent Windows 热更新：重建并滚动重启 API(:8000) / admin-web(:3001) / web(:3000)。

.DESCRIPTION
  对齐 scripts/deploy-update.sh。保留 mysql/redis/rabbitmq/litellm 等基础服务，不碰数据库、不跑 alembic。
  默认先备份当前业务镜像为 backup-时间戳，再 build，再按 beat → worker → api → admin_web → web 滚动重启。

.PARAMETER SkipApi
  跳过 API / worker / beat，仅更新前端。

.PARAMETER SkipFrontends
  跳过 web / admin_web，仅更新后端侧。

.PARAMETER NoBuild
  不重建镜像，用现有镜像重启（偏回滚或快速重启）。

.PARAMETER NoBackup
  跳过镜像备份。

.EXAMPLE
  .\scripts\deploy-update.ps1
  .\scripts\deploy-update.ps1 -SkipApi
  .\scripts\deploy-update.ps1 -SkipFrontends
  .\scripts\deploy-update.ps1 -NoBuild
  .\scripts\deploy-update.cmd

@author 赵振明
@date 2026-09-07 13:09:26
#>
[CmdletBinding()]
param(
    [switch]$SkipApi,
    [switch]$SkipFrontends,
    [switch]$NoBuild,
    [switch]$NoBackup
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DeployDir = Join-Path $RepoRoot "deploy"
$EnvFile = Join-Path $DeployDir ".env"
$ComposeProject = "zeroagent"
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
# docker 原生命令的退出码；勿用「$x = Invoke-Compose」接收，stdout 会污染返回值
$script:ComposeExitCode = 0

$ApiPort = 8000
$WebPort = 3000
$AdminPort = 3001

$SvcApi = "api"
$SvcWorker = "worker"
$SvcBeat = "beat"
$SvcWeb = "web"
$SvcAdmin = "admin_web"

$RestartSequence = @($SvcBeat, $SvcWorker, $SvcApi, $SvcAdmin, $SvcWeb)

function Write-Step {
    param([string]$Message)
    Write-Host "[deploy-update] $Message" -ForegroundColor Cyan
}

function Write-WarnStep {
    param([string]$Message)
    Write-Host "[deploy-update][WARN] $Message" -ForegroundColor Yellow
}

function Assert-DockerReady {
    $cmd = Get-Command docker -ErrorAction SilentlyContinue
    if ($null -eq $cmd) {
        throw "docker not found. Install Docker Desktop first."
    }
    docker info 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker engine is not running. Start Docker Desktop and retry."
    }
    docker compose version 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose not available."
    }
}

function Get-ComposeArgs {
    $composeArgs = @("compose", "--env-file", ".env", "-p", $ComposeProject)
    return ,$composeArgs
}

function Invoke-Compose {
    <#
    .SYNOPSIS
      执行 docker compose 子命令；退出码写入 $script:ComposeExitCode。
    .NOTES
      1) 禁止 `$x = Invoke-Compose`：stdout 会污染返回值。
      2) 全局 `$ErrorActionPreference=Stop` 下，docker 写到 stderr 的进度行
         （如 "Container xxx Stopping"）会被当成 NativeCommandError 终止脚本；
         此处临时改为 Continue，只认进程退出码。
    #>
    param(
        [Parameter(Mandatory = $true)][string[]]$ComposeArgs,
        [switch]$Quiet
    )
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        if ($Quiet) {
            & docker @ComposeArgs 1>$null 2>$null
        } else {
            & docker @ComposeArgs
        }
        $script:ComposeExitCode = [int]$LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prevEap
    }
}

function Test-BaseServices {
    Write-Step "Pre-check: base services (mysql / redis / rabbitmq)"
    $psOut = & docker compose -p $ComposeProject ps 2>$null | Out-String
    if ([string]::IsNullOrWhiteSpace($psOut)) {
        $psOut = & docker compose --env-file .env -p $ComposeProject ps 2>$null | Out-String
    }
    $needed = @("zeroagent-mysql", "zeroagent-redis", "zeroagent-rabbitmq")
    $running = @()
    foreach ($name in $needed) {
        if ($psOut -match [regex]::Escape($name)) {
            $running += $name
        }
    }
    if ($running.Count -eq 0) {
        throw "Base services not running. Start: cd deploy; docker compose -p zeroagent up -d mysql redis rabbitmq"
    }
    Write-Step ("Base services OK: " + ($running -join " "))
}

function Backup-ServiceImage {
    param([Parameter(Mandatory = $true)][string]$Service)

    $img = "zeroagent-$Service"
    $bak = "${img}:backup-$Timestamp"
    docker image inspect $img 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-WarnStep "Backup skipped: $img (image may not exist)"
        return
    }
    docker tag $img $bak
    if ($LASTEXITCODE -ne 0) {
        Write-WarnStep "Backup failed: $img -> $bak"
        return
    }
    Write-Step "Backup: $img -> $bak"
}

function Wait-TcpPort {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$Name,
        [int]$TimeoutSec = 90
    )

    Write-Step "Waiting $Name :$Port ..."
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $client = New-Object System.Net.Sockets.TcpClient
            $iar = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
            $ok = $iar.AsyncWaitHandle.WaitOne(1000, $false)
            if ($ok -and $client.Connected) {
                $client.EndConnect($iar)
                $client.Close()
                Write-Step "$Name :$Port ready"
                return
            }
            $client.Close()
        } catch {
            # retry
        }
        Start-Sleep -Seconds 1
    }
    throw "$Name :$Port not listening after ${TimeoutSec}s"
}

function Wait-ApiHealth {
    param([int]$TimeoutSec = 120)

    Write-Step "Waiting API /health ..."
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$ApiPort/health" -UseBasicParsing -TimeoutSec 3
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
                Write-Step "API /health OK (HTTP $($resp.StatusCode))"
                return
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    throw "API /health did not pass within ${TimeoutSec}s"
}

function Restart-ComposeService {
    param(
        [Parameter(Mandatory = $true)][string]$Service,
        [Parameter(Mandatory = $true)][string[]]$BaseComposeArgs
    )

    Write-Step "Stopping: $Service"
    Invoke-Compose -ComposeArgs ($BaseComposeArgs + @("stop", $Service)) -Quiet
    if ($script:ComposeExitCode -ne 0) {
        Write-WarnStep "stop failed: $Service"
    }

    Write-Step "Starting: $Service"
    Invoke-Compose -ComposeArgs ($BaseComposeArgs + @("up", "-d", "--no-deps", $Service))
    if ($script:ComposeExitCode -ne 0) {
        throw "start failed: $Service (exit $($script:ComposeExitCode))"
    }
}

# ---- main ----
if ($SkipApi -and $SkipFrontends) {
    throw "-SkipApi and -SkipFrontends cannot both be set"
}

Write-Step "Repo: $RepoRoot"
Write-Step "Timestamp: $Timestamp"
Assert-DockerReady

if (-not (Test-Path (Join-Path $DeployDir "docker-compose.yml"))) {
    throw "docker-compose.yml not found: $DeployDir"
}
if (-not (Test-Path $EnvFile)) {
    throw "Missing deploy/.env. Run deploy-docker first or copy from .env.example"
}

Push-Location $DeployDir
try {
    $cargs = Get-ComposeArgs
    Test-BaseServices

    if (-not $NoBackup) {
        Write-Step "Backing up current images ..."
        if (-not $SkipApi) {
            Backup-ServiceImage -Service $SvcApi
        }
        if (-not $SkipFrontends) {
            Backup-ServiceImage -Service $SvcWeb
            Backup-ServiceImage -Service $SvcAdmin
        }
    } else {
        Write-Step "NoBackup specified, skipping backup"
    }

    if (-not $NoBuild) {
        Write-Step "Building images ..."
        if (-not $SkipApi) {
            # worker/beat 与 api 同 Dockerfile；一并 build，避免滚动重启仍用旧镜像
            foreach ($svc in @($SvcApi, $SvcWorker, $SvcBeat)) {
                Write-Step "Building image: $svc"
                Invoke-Compose -ComposeArgs ($cargs + @("build", $svc))
                if ($script:ComposeExitCode -ne 0) {
                    throw "build failed: $svc (exit $($script:ComposeExitCode))"
                }
            }
        }
        if (-not $SkipFrontends) {
            foreach ($svc in @($SvcWeb, $SvcAdmin)) {
                Write-Step "Building image: $svc"
                Invoke-Compose -ComposeArgs ($cargs + @("build", $svc))
                if ($script:ComposeExitCode -ne 0) {
                    throw "build failed: $svc (exit $($script:ComposeExitCode))"
                }
            }
        }
    } else {
        Write-Step "NoBuild specified, skipping build"
    }

    Write-Step "Rolling restart ..."
    foreach ($svc in $RestartSequence) {
        $isBackend = ($svc -eq $SvcBeat -or $svc -eq $SvcWorker -or $svc -eq $SvcApi)
        $isFrontend = ($svc -eq $SvcAdmin -or $svc -eq $SvcWeb)
        if ($isBackend -and $SkipApi) { continue }
        if ($isFrontend -and $SkipFrontends) { continue }
        Restart-ComposeService -Service $svc -BaseComposeArgs $cargs
    }

    if (-not $SkipApi) {
        Wait-ApiHealth
    }
    if (-not $SkipFrontends) {
        Wait-TcpPort -Port $WebPort -Name "Web"
        Wait-TcpPort -Port $AdminPort -Name "Admin"
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Deploy update complete @ $Timestamp" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Test endpoints:"
    Write-Host "    API      : http://127.0.0.1:$ApiPort/health"
    Write-Host "    Admin    : http://127.0.0.1:$AdminPort"
    Write-Host "    Web      : http://127.0.0.1:$WebPort"
    Write-Host ""
    Write-Host "  Rollback hint (if needed):"
    if (-not $SkipApi) {
        Write-Host "    docker compose -f `"$DeployDir\docker-compose.yml`" -p $ComposeProject stop $SvcApi $SvcWorker $SvcBeat"
        Write-Host "    docker tag zeroagent-$SvcApi`:backup-$Timestamp zeroagent-$SvcApi`:latest"
        Write-Host "    docker compose -f `"$DeployDir\docker-compose.yml`" -p $ComposeProject up -d --no-deps $SvcApi $SvcWorker $SvcBeat"
    }
    if (-not $SkipFrontends) {
        Write-Host "    docker compose -f `"$DeployDir\docker-compose.yml`" -p $ComposeProject stop $SvcWeb $SvcAdmin"
        Write-Host "    docker tag zeroagent-$SvcWeb`:backup-$Timestamp zeroagent-$SvcWeb`:latest"
        Write-Host "    docker tag zeroagent-$SvcAdmin`:backup-$Timestamp zeroagent-$SvcAdmin`:latest"
        Write-Host "    docker compose -f `"$DeployDir\docker-compose.yml`" -p $ComposeProject up -d --no-deps $SvcWeb $SvcAdmin"
    }
    Write-Host "  Logs: cd deploy; docker compose -p $ComposeProject logs -f --tail=200 <service>"
}
finally {
    Pop-Location
}
