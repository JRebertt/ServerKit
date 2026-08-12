#Requires -Version 5.1
<#
.SYNOPSIS
    Windows entry point for the ServerKit development environment.
.DESCRIPTION
    Delegates to dev/dev.sh through WSL so local development runs in a
    Linux-like environment and stays in sync with the Bash launcher.

    With several distros installed, the launcher picks the first one that has a
    real Linux node (not the Windows shim reached through PATH interop) rather
    than trusting the current WSL default. Set SERVERKIT_WSL_DISTRO to override.
.EXAMPLE
    .\dev.ps1
    Start backend + frontend through WSL on stable non-default ports.
.EXAMPLE
    .\dev.ps1 frontend -BackendPort 5600
    Start Vite through WSL, targeting an existing backend on port 5600.
.EXAMPLE
    $env:SERVERKIT_WSL_DISTRO = 'Ubuntu-22.04'; .\dev.ps1
    Force a specific distro instead of auto-detecting one.
#>

$ProjectRoot = $PSScriptRoot

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    Write-Host "Error: WSL is required for .\dev.ps1." -ForegroundColor Red
    Write-Host "Install WSL, then run this again, or run ./dev.sh directly from Linux/WSL." -ForegroundColor Yellow
    exit 1
}

# Which distro to run in. Pinning this matters on machines with more than one:
# a distro without a Linux node/npm silently falls through WSL's PATH interop to
# the Windows node shim under /mnt/c, which then fails with messages that read
# like a WSL problem ("WSL 1 is not supported", "Could not determine Node.js
# install directory") rather than "node isn't installed here". So prefer a
# distro that actually has node, instead of trusting whichever one happens to be
# the current default.
function Get-WslDistros {
    # `wsl -l -q` emits UTF-16LE; decode explicitly or every name arrives with
    # NUL bytes interleaved.
    $prevEncoding = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = [System.Text.Encoding]::Unicode
        return (& wsl.exe -l -q) |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -and $_ -ne 'docker-desktop' -and $_ -ne 'docker-desktop-data' }
    } finally {
        [Console]::OutputEncoding = $prevEncoding
    }
}

function Test-DistroHasNode {
    param([string]$Distro)
    # `command -v node` alone is not enough: PATH interop makes the Windows
    # shim answer. Require the resolved path to be a real Linux one.
    #
    # The probe can emit several lines (a failing Windows shim prints its own
    # errors), so scan every line for one absolute Linux path rather than
    # assuming a single-string result.
    $lines = @(& wsl.exe -d $Distro --exec bash -lc 'command -v node 2>/dev/null' 2>$null)
    foreach ($line in $lines) {
        $path = "$line".Trim()
        if ($path.StartsWith('/') -and -not $path.StartsWith('/mnt/')) { return $true }
    }
    return $false
}

function Resolve-DevDistro {
    if ($env:SERVERKIT_WSL_DISTRO) { return $env:SERVERKIT_WSL_DISTRO }

    $distros = @(Get-WslDistros)
    if ($distros.Count -le 1) { return $null }   # nothing to choose between

    foreach ($d in $distros) {
        if (Test-DistroHasNode -Distro $d) { return $d }
    }
    return $null
}

$distro = Resolve-DevDistro
$distroArgs = if ($distro) { @('-d', $distro) } else { @() }

$wslRoot = (& wsl.exe @distroArgs --exec wslpath -a -u "$ProjectRoot" 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $wslRoot) {
    Write-Host "Error: Could not map this Windows path into WSL: $ProjectRoot" -ForegroundColor Red
    Write-Host "Make sure a WSL distro is installed and can access this repository." -ForegroundColor Yellow
    exit 1
}

$wslRoot = $wslRoot.Trim()
$devArgs = @($args)
$forwardedEnv = @()

function Get-DevMode {
    foreach ($arg in $devArgs) {
        if ($arg -in @('start', 'backend', 'frontend', 'tunnel', 'validate')) {
            return $arg
        }
    }
    return 'start'
}

function Get-DevPort {
    param(
        [string[]]$Names,
        [string]$EnvName,
        [int]$Default
    )

    for ($i = 0; $i -lt $devArgs.Count; $i++) {
        $arg = [string]$devArgs[$i]
        foreach ($name in $Names) {
            if ($arg -eq $name -and ($i + 1) -lt $devArgs.Count) {
                return [int]$devArgs[$i + 1]
            }
            if ($arg.StartsWith("$name=")) {
                return [int]$arg.Substring($name.Length + 1)
            }
        }
    }

    $item = Get-Item -Path "Env:$EnvName" -ErrorAction SilentlyContinue
    if ($item -and $item.Value) {
        return [int]$item.Value
    }

    return $Default
}

function Stop-WindowsListenersOnPort {
    param(
        [int]$Port,
        [string]$Label
    )

    # Parity with dev.sh: SERVERKIT_KILL_PORTS=0 opts out of port cleanup.
    if ($env:SERVERKIT_KILL_PORTS -eq '0') { return }

    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        Where-Object { $_ -and $_ -ne 0 -and $_ -ne $PID })

    foreach ($processId in $listeners) {
        $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if (-not $proc) {
            continue
        }

        Write-Host "Stopping existing $Label listener on port $Port ($($proc.ProcessName) PID $processId)..." -ForegroundColor Yellow
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
}

$mode = Get-DevMode
$backendPort = Get-DevPort -Names @('--backend-port', '-BackendPort') -EnvName 'SERVERKIT_BACKEND_PORT' -Default 47927
$frontendPort = Get-DevPort -Names @('--frontend-port', '-FrontendPort') -EnvName 'SERVERKIT_FRONTEND_PORT' -Default 41921
$isHelp = $devArgs -contains '-h' -or $devArgs -contains '--help'

if (-not $isHelp -and $mode -in @('start', 'backend', 'tunnel')) {
    Stop-WindowsListenersOnPort -Port $backendPort -Label 'backend'
}
if (-not $isHelp -and $mode -in @('start', 'frontend', 'tunnel')) {
    Stop-WindowsListenersOnPort -Port $frontendPort -Label 'frontend'
}

foreach ($name in @('SERVERKIT_BACKEND_PORT', 'SERVERKIT_FRONTEND_PORT', 'SERVERKIT_BROWSER_BACKEND_HOST', 'SERVERKIT_BACKEND_VENV', 'SERVERKIT_KILL_PORTS', 'NGROK_DOMAIN', 'NGROK_AUTHTOKEN', 'CORS_ORIGINS')) {
    $item = Get-Item -Path "Env:$name" -ErrorAction SilentlyContinue
    if ($item -and $item.Value) {
        $forwardedEnv += "$name=$($item.Value)"
    }
}

if ($distro) {
    Write-Host "Launching ServerKit dev environment in WSL ($distro)..." -ForegroundColor Cyan
} else {
    Write-Host "Launching ServerKit dev environment in WSL..." -ForegroundColor Cyan
}
& wsl.exe @distroArgs --cd "$wslRoot" --exec env @forwardedEnv bash ./dev/dev.sh @devArgs
exit $LASTEXITCODE
