# QuantDinger interactive installer for Windows PowerShell.
#
# Usage:
#   irm https://raw.githubusercontent.com/OpenByteInc/QuantDinger/main/install.ps1 | iex
#
# Optional environment overrides:
#   $env:QUANTDINGER_INSTALL_REF = "main"
#   $env:QUANTDINGER_INSTALL_DIR = "C:\QuantDinger"

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$InstallDir = if ($env:QUANTDINGER_INSTALL_DIR) { $env:QUANTDINGER_INSTALL_DIR } else { Join-Path $HOME "quantdinger" }
$InstallRef = if ($env:QUANTDINGER_INSTALL_REF) { $env:QUANTDINGER_INSTALL_REF } else { "main" }
$GithubRaw = "https://raw.githubusercontent.com/OpenByteInc/QuantDinger/$InstallRef"
$ComposeFile = "docker-compose.yml"
$BackendEnv = "backend.env"
$RootEnv = ".env"

function Fail($Message) {
    Write-Host "Error: $Message" -ForegroundColor Red
    exit 1
}

function Get-EnvValue($Path, $Key) {
    if (-not (Test-Path $Path)) { return "" }
    $line = Get-Content $Path | Where-Object { $_ -match "^$([regex]::Escape($Key))=" } | Select-Object -Last 1
    if (-not $line) { return "" }
    return $line.Substring($Key.Length + 1)
}

function Set-EnvValue($Path, $Key, $Value) {
    if (-not (Test-Path $Path)) { New-Item -ItemType File -Path $Path | Out-Null }
    [string[]]$lines = @(Get-Content -LiteralPath $Path)
    $found = $false
    [string[]]$next = @(
        foreach ($line in $lines) {
            if ($line -match "^$([regex]::Escape($Key))=") {
                "$Key=$Value"
                $found = $true
            } else {
                $line
            }
        }
    )
    if (-not $found) { $next += "$Key=$Value" }
    Set-Content -LiteralPath $Path -Value $next -Encoding UTF8
}

function Repair-EnvLayout($Path, [string[]]$KnownKeys) {
    if (-not (Test-Path $Path)) { return }
    $content = Get-Content -LiteralPath $Path -Raw
    if (-not $content -or -not $KnownKeys) { return }
    $keyPattern = (($KnownKeys | ForEach-Object { [regex]::Escape($_) }) -join "|")
    $pattern = "(?<=[^`r`n])(?=(?:$keyPattern)=)"
    $repaired = [regex]::Replace($content, $pattern, [Environment]::NewLine)
    if ($repaired -ne $content) {
        Set-Content -LiteralPath $Path -Value $repaired.TrimEnd("`r", "`n") -Encoding UTF8
    }
}

function New-HexSecret([int]$Bytes) {
    $buffer = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($buffer)
    } finally {
        $rng.Dispose()
    }
    return (($buffer | ForEach-Object { $_.ToString("x2") }) -join "")
}

function Read-Value($Prompt, $Default = "") {
    if ($Default) {
        $value = Read-Host "$Prompt [$Default]"
        if (-not $value) { return $Default }
        return $value
    }
    return (Read-Host $Prompt)
}

function Read-SecretPlain($Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

function Check-Prerequisites {
    Write-Host "QuantDinger installer" -ForegroundColor Blue
    Write-Host "Install directory: $InstallDir"
    Write-Host "Source ref: $InstallRef"
    Write-Host ""

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Fail "Docker is required. Install Docker Desktop first."
    }

    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Fail "Docker is installed but the Docker daemon is not running."
    }

    docker compose version *> $null
    if ($LASTEXITCODE -ne 0) {
        Fail "Docker Compose v2 is required."
    }
}

function Prepare-Directory {
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    Set-Location $InstallDir
}

function Download-Files {
    Write-Host "Downloading compose and backend environment template..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri "$GithubRaw/docker-compose.ghcr.yml" -OutFile $ComposeFile
    if (-not (Test-Path $BackendEnv)) {
        Invoke-WebRequest -Uri "$GithubRaw/backend_api_python/env.example" -OutFile $BackendEnv
    }
    if (-not (Test-Path $RootEnv)) {
        New-Item -ItemType File -Path $RootEnv | Out-Null
    }
    Repair-EnvLayout $RootEnv @(
        "FRONTEND_PORT",
        "MOBILE_PORT",
        "BACKEND_PORT",
        "POSTGRES_PASSWORD",
        "IMAGE_PREFIX"
    )
}

function Collect-Settings {
    $existingUser = Get-EnvValue $BackendEnv "ADMIN_USER"
    $existingPassword = Get-EnvValue $BackendEnv "ADMIN_PASSWORD"
    $script:AdminCredentialsReused = $false
    if (
        $existingPassword -and
        $existingPassword -ne "123456" -and
        $existingUser.Length -ge 3 -and
        $existingUser.Length -le 50 -and
        $existingPassword.Length -ge 6
    ) {
        $script:AdminUser = $existingUser
        $script:AdminPassword = $existingPassword
        $script:AdminCredentialsReused = $true
        Write-Host "Existing administrator credentials detected; keeping the configured username and password." -ForegroundColor Yellow
        Write-Host "Change administrator credentials from Profile after signing in."
    } else {
        while ($true) {
            $script:AdminUser = Read-Value "Admin username" ($existingUser -replace '^$', 'quantdinger')
            if ($AdminUser.Length -lt 3 -or $AdminUser.Length -gt 50) {
                Write-Host "Admin username must be 3-50 characters." -ForegroundColor Red
                continue
            }
            break
        }

        while ($true) {
            $pass1 = Read-SecretPlain "Admin password"
            $pass2 = Read-SecretPlain "Confirm admin password"
            if ($pass1.Length -lt 6) {
                Write-Host "Admin password must be at least 6 characters." -ForegroundColor Red
                continue
            }
            if ($pass1 -eq "123456") {
                Write-Host "Do not use the built-in default password 123456." -ForegroundColor Red
                continue
            }
            if ($pass1 -ne $pass2) {
                Write-Host "Passwords do not match." -ForegroundColor Red
                continue
            }
            $script:AdminPassword = $pass1
            break
        }
    }
    $script:AdminEmail = Read-Value "Admin email (optional)" (Get-EnvValue $BackendEnv "ADMIN_EMAIL")

    $script:FrontendPort = Read-Value "Frontend port" ((Get-EnvValue $RootEnv "FRONTEND_PORT") -replace '^$', '8888')
    $script:MobilePort = Read-Value "Mobile H5 port" ((Get-EnvValue $RootEnv "MOBILE_PORT") -replace '^$', '8889')
    $script:BackendPort = Read-Value "Backend bind address" ((Get-EnvValue $RootEnv "BACKEND_PORT") -replace '^$', '127.0.0.1:5000')

    $existingPgPassword = Get-EnvValue $RootEnv "POSTGRES_PASSWORD"
    if ($existingPgPassword) { $script:PostgresPassword = $existingPgPassword } else { $script:PostgresPassword = New-HexSecret 18 }

    Write-Host ""
    Write-Host "Image source:"
    Write-Host "  1) global/default"
    Write-Host "  2) mainland China mirror (docker.m.daocloud.io/library/)"
    $choice = Read-Value "Select image source" "1"
    $existingImagePrefix = Get-EnvValue $RootEnv "IMAGE_PREFIX"
    if ($existingImagePrefix) {
        $script:ImagePrefix = $existingImagePrefix
    } elseif ($choice -eq "2") {
        $script:ImagePrefix = "docker.m.daocloud.io/library/"
    } else {
        $script:ImagePrefix = ""
    }

    $existingSecret = Get-EnvValue $BackendEnv "SECRET_KEY"
    if ($existingSecret -and $existingSecret -ne "quantdinger-secret-key-change-me") {
        $script:SecretKey = $existingSecret
    } else {
        $script:SecretKey = New-HexSecret 32
    }
}

function Write-Settings {
    Set-EnvValue $BackendEnv "SECRET_KEY" $SecretKey
    Set-EnvValue $BackendEnv "ADMIN_USER" $AdminUser
    Set-EnvValue $BackendEnv "ADMIN_PASSWORD" $AdminPassword
    Set-EnvValue $BackendEnv "ADMIN_EMAIL" $AdminEmail
    Set-EnvValue $BackendEnv "FRONTEND_URL" "http://localhost:$FrontendPort,http://localhost:$MobilePort"

    Set-EnvValue $RootEnv "FRONTEND_PORT" $FrontendPort
    Set-EnvValue $RootEnv "MOBILE_PORT" $MobilePort
    Set-EnvValue $RootEnv "BACKEND_PORT" $BackendPort
    Set-EnvValue $RootEnv "POSTGRES_PASSWORD" $PostgresPassword
    Set-EnvValue $RootEnv "IMAGE_PREFIX" $ImagePrefix
}

function Start-Stack {
    Write-Host "Pulling images..." -ForegroundColor Yellow
    docker compose -f $ComposeFile pull
    if ($LASTEXITCODE -ne 0) {
        Fail "Docker Compose could not pull the required images."
    }
    Write-Host "Starting services..." -ForegroundColor Yellow
    docker compose -f $ComposeFile up -d
    if ($LASTEXITCODE -ne 0) {
        Fail "Docker Compose could not start the services."
    }
}

function Wait-ForBackend {
    Write-Host "Waiting for backend health check..." -ForegroundColor Yellow
    $apiPort = ($BackendPort -split ':')[-1]
    $url = "http://127.0.0.1:$apiPort/api/health"
    for ($i = 1; $i -le 45; $i++) {
        try {
            Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2 | Out-Null
            Write-Host "Backend is ready." -ForegroundColor Green
            return
        } catch {
            Write-Host "  waiting... ($i/45)"
            Start-Sleep -Seconds 2
        }
    }
    Write-Host "Backend did not become healthy within the expected startup window. Check logs with:" -ForegroundColor Red
    Write-Host "  cd $InstallDir"
    Write-Host "  docker compose -f $ComposeFile logs -f backend"
    Fail "Installation did not complete successfully."
}

function Print-Summary {
    $apiPort = ($BackendPort -split ':')[-1]
    Write-Host ""
    Write-Host "QuantDinger is ready." -ForegroundColor Green
    Write-Host ""
    Write-Host "Web UI:      http://localhost:$FrontendPort"
    Write-Host "Mobile H5:   http://localhost:$MobilePort"
    Write-Host "API:         http://127.0.0.1:$apiPort"
    Write-Host "Directory:   $InstallDir"
    Write-Host "Username:    $AdminUser"
    if ($AdminCredentialsReused) {
        Write-Host "Password:    existing administrator password"
    } else {
        Write-Host "Password:    the password you entered during installation"
    }
    Write-Host ""
    Write-Host "Useful commands:"
    Write-Host "  cd $InstallDir"
    Write-Host "  docker compose -f $ComposeFile ps"
    Write-Host "  docker compose -f $ComposeFile logs -f backend"
    Write-Host "  docker compose -f $ComposeFile pull; docker compose -f $ComposeFile up -d"
    Write-Host ""
    Write-Host "Trading involves substantial risk. Start with paper trading and small test accounts." -ForegroundColor Yellow
}

Check-Prerequisites
Prepare-Directory
Download-Files
Collect-Settings
Write-Settings
Start-Stack
Wait-ForBackend
Print-Summary
