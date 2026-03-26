# =============================================================
# install.ps1 — MeetRec Windows Installer
# =============================================================
# Requirements: Windows 10/11, Docker Desktop, PowerShell 5.1+
#
# Usage:
#   .\install.ps1
#   .\install.ps1 -NonInteractive
#   .\install.ps1 -Domain meetrec.local
# =============================================================

param(
    [switch]$NonInteractive,
    [string]$Domain = "",
    [string]$WhisperModel = "",
    [string]$AdminUser = "",
    [string]$AdminEmail = "",
    [string]$AdminPassword = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Colors ────────────────────────────────────────────────────
function Write-Ok    { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Info  { param($msg) Write-Host "  [..] $msg" -ForegroundColor Cyan }
function Write-Warn  { param($msg) Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Write-Step  { param($msg) Write-Host "`n━━━ $msg ━━━" -ForegroundColor White }
function Write-Fail  { param($msg) Write-Host "`n  [ERR] $msg" -ForegroundColor Red; exit 1 }

function Prompt-Input {
    param([string]$Question, [string]$Default = "")
    if ($NonInteractive) { return $Default }
    if ($Default) {
        $ans = Read-Host "  $Question [$Default]"
        return if ($ans -eq "") { $Default } else { $ans }
    } else {
        return Read-Host "  $Question"
    }
}

function Prompt-Password {
    param([string]$Question)
    if ($NonInteractive) { return -join ((65..90 + 97..122 + 48..57) | Get-Random -Count 16 | % {[char]$_}) }
    $s = Read-Host "  $Question" -AsSecureString
    return [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
    )
}

# ── Banner ────────────────────────────────────────────────────
Clear-Host
Write-Host @"

  ███╗   ███╗███████╗███████╗████████╗██████╗ ███████╗ ██████╗
  ████╗ ████║██╔════╝██╔════╝╚══██╔══╝██╔══██╗██╔════╝██╔════╝
  ██╔████╔██║█████╗  █████╗     ██║   ██████╔╝█████╗  ██║
  ██║╚██╔╝██║██╔══╝  ██╔══╝     ██║   ██╔══██╗██╔══╝  ██║
  ██║ ╚═╝ ██║███████╗███████╗   ██║   ██║  ██║███████╗╚██████╗
  ╚═╝     ╚═╝╚══════╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚══════╝ ╚═════╝

  Self-hosted meeting transcription platform — Windows Installer
"@ -ForegroundColor Cyan

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# ── Step 1: Prerequisites ─────────────────────────────────────
Write-Step "1/7  Prerequisites"

# Docker Desktop
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Fail "Docker not found. Install Docker Desktop from https://www.docker.com/products/docker-desktop/ and re-run this script."
}

# Docker running?
$dockerInfo = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Docker is installed but not running. Start Docker Desktop and try again."
}

# docker compose (plugin v2)
$composeVer = docker compose version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Docker Compose plugin not found. Update Docker Desktop to version 4.x or later."
}

Write-Ok "Docker: $(docker --version)"
Write-Ok "Compose: $($composeVer -replace 'Docker Compose version ','')"

# openssl (bundled with Git for Windows / Docker Desktop)
$opensslCmd = Get-Command openssl -ErrorAction SilentlyContinue
if (-not $opensslCmd) {
    # Try common paths
    $candidates = @(
        "C:\Program Files\Git\usr\bin\openssl.exe",
        "C:\Program Files\OpenSSL-Win64\bin\openssl.exe",
        "C:\Program Files\OpenSSL\bin\openssl.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $opensslCmd = $c; break }
    }
    if (-not $opensslCmd) {
        Write-Fail "openssl not found. Install Git for Windows (https://git-scm.com) — it includes openssl."
    }
    $env:Path += ";$(Split-Path $opensslCmd)"
}
Write-Ok "openssl found"

# ── Step 2: Configuration ─────────────────────────────────────
Write-Step "2/7  Configuration"

# Domain
if (-not $Domain) {
    $Domain = Prompt-Input "Server hostname or IP (for SSL certificate)" "localhost"
}
Write-Info "Domain: $Domain"

# Whisper model
if (-not $WhisperModel) {
    $WhisperModel = Prompt-Input "Whisper model [tiny/base/small/medium/large]" "medium"
}
$validModels = @("tiny","base","small","medium","large")
if ($WhisperModel -notin $validModels) {
    Write-Warn "Unknown model '$WhisperModel', defaulting to 'medium'."
    $WhisperModel = "medium"
}
Write-Info "Whisper model: $WhisperModel"

# Admin credentials
if (-not $AdminUser)  { $AdminUser  = Prompt-Input  "Admin username" "admin" }
if (-not $AdminEmail) { $AdminEmail = Prompt-Input  "Admin email"    "admin@meetrec.local" }
if (-not $AdminPassword) {
    $AdminPassword = Prompt-Password "Admin password (min 8 chars)"
    if ($AdminPassword.Length -lt 8) { Write-Fail "Password must be at least 8 characters." }
}

# ── Step 3: .env file ─────────────────────────────────────────
Write-Step "3/7  Environment file"

$envFile = Join-Path $ScriptDir ".env"
$envExample = Join-Path $ScriptDir ".env.example"

if (-not (Test-Path $envExample)) {
    Write-Fail ".env.example not found. Make sure you're running this script from the MeetRec root directory."
}

if (Test-Path $envFile) {
    $overwrite = Prompt-Input ".env already exists. Overwrite? [y/N]" "N"
    if ($overwrite -notmatch "^[yY]$") {
        Write-Info "Keeping existing .env"
        $skipEnv = $true
    }
}

if (-not $skipEnv) {
    Copy-Item $envExample $envFile -Force

    # Generate secrets
    $jwtSecret = -join ((0..63) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })
    $dbPassword = -join ((65..90 + 97..122 + 48..57) | Get-Random -Count 20 | ForEach-Object {[char]$_})

    # Patch .env
    $env = Get-Content $envFile -Raw

    $env = $env -replace 'JWT_SECRET_KEY=.*',          "JWT_SECRET_KEY=$jwtSecret"
    $env = $env -replace 'POSTGRES_PASSWORD=.*',        "POSTGRES_PASSWORD=$dbPassword"
    $env = $env -replace 'DATABASE_URL=.*',             "DATABASE_URL=postgresql+asyncpg://mt_user:${dbPassword}@postgres:5432/meeting_transcriber"
    $env = $env -replace 'SERVER_NAME=.*',              "SERVER_NAME=$Domain"
    $env = $env -replace 'WHISPER_MODEL=.*',            "WHISPER_MODEL=$WhisperModel"
    $env = $env -replace 'APP_ENV=.*',                  "APP_ENV=production"

    Set-Content $envFile $env -Encoding UTF8
    Write-Ok ".env configured"
    Write-Info "JWT secret and DB password auto-generated"
}

# ── Step 4: Data directories ──────────────────────────────────
Write-Step "4/7  Data directories"

$dirs = @("data\inbox", "data\processed", "data\exports", "nginx\ssl")
foreach ($d in $dirs) {
    $path = Join-Path $ScriptDir $d
    if (-not (Test-Path $path)) {
        New-Item -ItemType Directory -Path $path -Force | Out-Null
        Write-Ok "Created: $d"
    } else {
        Write-Info "Exists:  $d"
    }
}

# ── Step 5: SSL certificates ──────────────────────────────────
Write-Step "5/7  SSL certificates"

$sslDir  = Join-Path $ScriptDir "nginx\ssl"
$certPem = Join-Path $sslDir "fullchain.pem"
$keyPem  = Join-Path $sslDir "privkey.pem"

if ((Test-Path $certPem) -and (Test-Path $keyPem)) {
    $regen = Prompt-Input "SSL certificates already exist. Regenerate? [y/N]" "N"
    $skipSsl = ($regen -notmatch "^[yY]$")
} else {
    $skipSsl = $false
}

if (-not $skipSsl) {
    # Determine SAN
    if ($Domain -match '^\d+\.\d+\.\d+\.\d+$') {
        $san = "IP:${Domain},IP:127.0.0.1"
    } else {
        $san = "DNS:${Domain},DNS:localhost,IP:127.0.0.1"
    }

    Write-Info "Generating self-signed certificate for: $Domain"

    # Write openssl config to temp file (needed for SAN on Windows)
    $tmpCfg = [System.IO.Path]::GetTempFileName() + ".cfg"
    @"
[req]
distinguished_name = req_distinguished_name
x509_extensions    = v3_req
prompt             = no

[req_distinguished_name]
C  = RO
ST = Romania
L  = Bucharest
O  = MeetRec
CN = $Domain

[v3_req]
subjectAltName = $san
"@ | Set-Content $tmpCfg -Encoding ASCII

    openssl req -x509 -nodes -days 3650 `
        -newkey rsa:2048 `
        -keyout $keyPem `
        -out    $certPem `
        -config $tmpCfg 2>$null

    Remove-Item $tmpCfg -Force

    if ($LASTEXITCODE -ne 0) { Write-Fail "SSL certificate generation failed." }
    Write-Ok "SSL certificates generated (valid 10 years)"
    Write-Warn "Browser will show a security warning (self-signed). Click Advanced → Proceed."
}

# ── Step 6: Build Docker images ───────────────────────────────
Write-Step "6/7  Docker build"

$modelSizes = @{ tiny="75 MB"; base="140 MB"; small="460 MB"; medium="1.5 GB"; large="3 GB" }
Write-Info "Building Docker images. First build downloads PyTorch + Whisper '$WhisperModel' ($($modelSizes[$WhisperModel]))."
Write-Info "This can take 20-40 minutes. Grab a coffee."
Write-Host ""

Set-Location $ScriptDir
docker compose build
if ($LASTEXITCODE -ne 0) { Write-Fail "Docker build failed. Check the output above." }
Write-Ok "Docker images built"

# ── Step 7: Start services ────────────────────────────────────
Write-Step "7/7  Start services"

docker compose up -d
if ($LASTEXITCODE -ne 0) { Write-Fail "Failed to start services." }

# Wait for API to be healthy
Write-Info "Waiting for API to become healthy..."
$retries = 0
do {
    Start-Sleep -Seconds 3
    $retries++
    $apiState = docker inspect --format='{{.State.Health.Status}}' mt-api 2>$null
    if ($retries % 5 -eq 0) { Write-Info "Still waiting... ($($retries * 3)s)" }
} while ($apiState -ne "healthy" -and $retries -lt 40)

if ($apiState -ne "healthy") {
    Write-Warn "API health check timed out. Services may still be starting."
    Write-Info "Check with: docker compose logs api"
} else {
    Write-Ok "All services healthy"
}

# ── Create admin user ─────────────────────────────────────────
Write-Info "Creating administrator account '$AdminUser'..."

$createAdminScript = @"
import asyncio, uuid, sys
sys.path.insert(0, '/app')
from src.database import AsyncSessionLocal
from src.models.audit_log import User
from passlib.context import CryptContext
from sqlalchemy import select

async def run():
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(select(User).where(User.username == '$AdminUser'))).scalar_one_or_none()
        if existing:
            print('EXISTS')
            return
        pwd = CryptContext(schemes=['bcrypt']).hash('$AdminPassword')
        db.add(User(
            id=uuid.uuid4(),
            username='$AdminUser',
            email='$AdminEmail',
            hashed_password=pwd,
            role='admin',
            is_active=True,
            force_password_change=True,
        ))
        await db.commit()
        print('CREATED')

asyncio.run(run())
"@

$result = docker compose exec -T api python3 -c $createAdminScript 2>&1
if ($result -match "CREATED") {
    Write-Ok "Administrator '$AdminUser' created (password change required on first login)"
} elseif ($result -match "EXISTS") {
    Write-Warn "User '$AdminUser' already exists — skipped"
} else {
    Write-Warn "Could not create admin automatically. Run: make create-admin"
    Write-Info "Output: $result"
}

# ── Done ──────────────────────────────────────────────────────
$url = if ($Domain -eq "localhost") { "https://localhost" } else { "https://$Domain" }

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host "  MeetRec is ready!" -ForegroundColor Green
Write-Host ""
Write-Host "  URL:      $url" -ForegroundColor White
Write-Host "  Username: $AdminUser" -ForegroundColor White
Write-Host "  Password: (the one you entered)" -ForegroundColor White
Write-Host ""
Write-Host "  You will be prompted to change your password on first login." -ForegroundColor Gray
Write-Host ""
Write-Host "  Useful commands:" -ForegroundColor Gray
Write-Host "    docker compose ps              - service status" -ForegroundColor Gray
Write-Host "    docker compose logs -f api     - API logs" -ForegroundColor Gray
Write-Host "    docker compose logs -f stt-worker - transcription logs" -ForegroundColor Gray
Write-Host "    docker compose stop            - stop everything" -ForegroundColor Gray
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host ""

$open = Prompt-Input "Open $url in browser now? [Y/n]" "Y"
if ($open -notmatch "^[nN]$") {
    Start-Process $url
}
