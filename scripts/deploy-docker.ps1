#Requires -Version 5.1
<#
.SYNOPSIS
  zeroAgent one-click Docker deploy (Compose stack, API fixed :8000).

.DESCRIPTION
  Starts mysql/redis/rabbitmq/litellm + api/worker/beat in Docker.
  Ensures deploy/.env exists, frees host :8000, builds images, runs compose,
  then alembic upgrade inside api container.
  Frontend (Next.js :3000) stays on host; point web/.env.local to :8000.

.PARAMETER Full
  Also start profile full (neo4j/etcd/milvus).

.PARAMETER Embed
  Also start profile embed (embed-rerank :8088).

.PARAMETER Minio
  Also start profile minio (biz minio).

.PARAMETER SkipMigrate
  Skip alembic upgrade head.

.PARAMETER NoBuild
  docker compose up without --build.

.PARAMETER Down
  Stop and remove the compose stack instead of deploying.

@author 赵振明
@date 2026-07-28 15:29:36
#>
[CmdletBinding()]
param(
    [switch]$Full,
    [switch]$Embed,
    [switch]$Minio,
    [switch]$SkipMigrate,
    [switch]$NoBuild,
    [switch]$Down
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DeployDir = Join-Path $RepoRoot "deploy"
$EnvFile = Join-Path $DeployDir ".env"
$EnvExample = Join-Path $DeployDir ".env.example"
$ApiPort = 8000
$ComposeProject = "zeroagent"

function Write-Step {
    param([string]$Message)
    Write-Host "[deploy-docker] $Message" -ForegroundColor Cyan
}

function Assert-DockerReady {
    $cmd = Get-Command docker -ErrorAction SilentlyContinue
    if ($null -eq $cmd) {
        throw "Docker CLI not found. Install Docker Desktop first."
    }
    docker info 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker engine not running. Start Docker Desktop and retry."
    }
}

function Ensure-DeployEnv {
    if (-not (Test-Path $EnvFile)) {
        if (-not (Test-Path $EnvExample)) {
            throw "Missing $EnvExample"
        }
        Copy-Item -Path $EnvExample -Destination $EnvFile
        Write-Step "Created deploy/.env from .env.example (edit secrets if needed)"
    } else {
        Write-Step "Using existing deploy/.env"
    }

    $dataDir = "D:/dockers/zeroagent"
    $line = Select-String -Path $EnvFile -Pattern "^\s*DOCKER_DATA_DIR\s*=\s*(.+)$" | Select-Object -First 1
    if ($line) {
        $dataDir = ($line.Matches[0].Groups[1].Value).Trim().Trim('"').Trim("'")
    }
    if (-not (Test-Path $dataDir)) {
        New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
        Write-Step "Created data dir: $dataDir"
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
                # 幽灵监听 PID：父进程已死，子 worker 仍占 127.0.0.1，挡住 Docker 映射。
                # @author 赵振明
                # @date 2026-07-29 14:10:45
                $orphans = @(
                    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                        Where-Object { $_.ParentProcessId -eq $procId } |
                        Select-Object -ExpandProperty ProcessId
                )
                foreach ($childId in $orphans) {
                    Write-Step "Free port ${Port}: kill orphan child=$childId of dead PID=$procId"
                    Stop-Process -Id $childId -Force -ErrorAction SilentlyContinue
                }
                continue
            }
            # Do not kill Docker / com.docker; only free host uvicorn etc.
            if ($proc.ProcessName -match "docker|com\.docker|vpnkit") {
                Write-Step "Port ${Port} held by $($proc.ProcessName) (PID=$procId), skip kill"
                continue
            }
            Write-Step "Free host port ${Port}: kill PID=$procId ($($proc.ProcessName))"
            Stop-Process -Id $procId -Force -ErrorAction Stop
        } catch {
            Write-Warning "Cannot kill PID=$procId : $($_.Exception.Message)"
        }
    }
}

function Get-ComposeArgs {
    $composeArgs = @("compose", "--env-file", ".env", "-p", $ComposeProject)
    if ($Full) { $composeArgs += @("--profile", "full") }
    if ($Embed) { $composeArgs += @("--profile", "embed") }
    if ($Minio) { $composeArgs += @("--profile", "minio") }
    return ,$composeArgs
}

function Wait-ApiHealthy {
    param([int]$TimeoutSec = 120)

    $url = "http://127.0.0.1:$ApiPort/health"
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    Write-Step "Waiting API health $url ..."
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300) {
                Write-Step "API ready (HTTP $($resp.StatusCode))"
                return
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    throw "API health timeout after ${TimeoutSec}s. Check: docker compose -p $ComposeProject logs api"
}

function Invoke-Migrate {
    Write-Step "Running alembic upgrade head in api container..."
    $cargs = Get-ComposeArgs
    & docker @cargs exec -T api alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "alembic upgrade failed (exit $LASTEXITCODE)"
    }
    Write-Step "Migration OK"
}

# ---- main ----
Write-Step "Repo: $RepoRoot"
Assert-DockerReady

if (-not (Test-Path $DeployDir)) {
    throw "deploy/ missing: $DeployDir"
}

Push-Location $DeployDir
try {
    Ensure-DeployEnv
    $cargs = Get-ComposeArgs

    if ($Down) {
        Write-Step "Stopping compose stack..."
        & docker @cargs down
        if ($LASTEXITCODE -ne 0) {
            throw "docker compose down failed (exit $LASTEXITCODE)"
        }
        Write-Step "Stack stopped."
        return
    }

    Write-Step "Free host :$ApiPort before publishing container port..."
    Stop-ListenPort -Port $ApiPort
    Start-Sleep -Seconds 1

    $upArgs = @("up", "-d")
    if (-not $NoBuild) {
        $upArgs += "--build"
    }

    Write-Step ("docker " + (($cargs + $upArgs) -join " "))
    & docker @($cargs + $upArgs)
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose up failed (exit $LASTEXITCODE)"
    }

    Wait-ApiHealthy

    if (-not $SkipMigrate) {
        Invoke-Migrate
    } else {
        Write-Step "Skip migrate (-SkipMigrate)"
    }

    Write-Host ""
    Write-Step "Deploy done."
    Write-Step "API     http://127.0.0.1:$ApiPort/health"
    Write-Step "LiteLLM http://127.0.0.1:4000"
    Write-Step "MQ UI   http://127.0.0.1:15672"
    Write-Step "Web is NOT in Docker; use .\scripts\restart-dev.ps1 -SkipBackend  (proxy :8000)"
    Write-Step "Stop:   .\scripts\deploy-docker.ps1 -Down"
}
finally {
    Pop-Location
}
