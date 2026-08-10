#Requires -Version 5.1
<#
.SYNOPSIS
  zeroAgent local one-click Docker deploy: API :8000 + web :3000 + admin :3001.

.DESCRIPTION
  Starts compose stack (api/web/admin_web + mysql/redis/rabbitmq/litellm/worker/beat).
  Frees host ports 8000/3000/3001 before publish. Runs alembic upgrade in api container.

.PARAMETER Full
  Also start profile full (neo4j/etcd/milvus).

.PARAMETER Embed
  Also start profile embed (embed-rerank :8088).

.PARAMETER Minio
  Also start profile minio.

.PARAMETER SkipMigrate
  Skip alembic upgrade head.

.PARAMETER NoBuild
  docker compose up without --build.

.PARAMETER Down
  Stop and remove the compose stack.

.EXAMPLE
  .\scripts\deploy-docker.ps1
  .\scripts\deploy-docker.ps1 -Down
  .\scripts\deploy-docker.cmd

@author Zhao Zhenming
@date 2026-08-10 11:19:00
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
$WebPort = 3000
$AdminPort = 3001
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
        throw "Docker engine is not running. Start Docker Desktop and retry."
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

function Wait-HttpOk {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$TimeoutSec = 180
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    Write-Step "Waiting $Name ready: $Url ..."
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
                Write-Step "$Name ready (HTTP $($resp.StatusCode))"
                return
            }
        } catch {
            Start-Sleep -Seconds 3
        }
    }
    throw "$Name health timeout after ${TimeoutSec}s. Check: docker compose -p $ComposeProject logs"
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

    Write-Step "Free host ports $ApiPort / $WebPort / $AdminPort ..."
    Stop-ListenPort -Port $ApiPort
    Stop-ListenPort -Port $WebPort
    Stop-ListenPort -Port $AdminPort
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

    Wait-HttpOk -Name "API" -Url "http://127.0.0.1:$ApiPort/health" -TimeoutSec 180
    if (-not $SkipMigrate) {
        Invoke-Migrate
    } else {
        Write-Step "Skip migrate (-SkipMigrate)"
    }

    Wait-HttpOk -Name "Web" -Url "http://127.0.0.1:$WebPort" -TimeoutSec 300
    Wait-HttpOk -Name "Admin" -Url "http://127.0.0.1:$AdminPort" -TimeoutSec 300

    Write-Host ""
    Write-Step "Deploy done."
    Write-Host "  API     http://127.0.0.1:$ApiPort/health" -ForegroundColor Green
    Write-Host "  Web     http://127.0.0.1:$WebPort" -ForegroundColor Green
    Write-Host "  Admin   http://127.0.0.1:$AdminPort" -ForegroundColor Green
    Write-Host "  LiteLLM http://127.0.0.1:4000"
    Write-Host "  RabbitMQ http://127.0.0.1:15672"
    Write-Step "Stop: .\scripts\deploy-docker.ps1 -Down"
}
finally {
    Pop-Location
}