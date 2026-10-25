param(
    [ValidateSet('up', 'down', 'status', 'logs', 'test', 'user')]
    [string]$Action = 'up',
    [switch]$Web,
    [string]$Email,
    [ValidateSet('admin', 'analyst', 'manager')]
    [string]$Role = 'manager'
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$envPath = Join-Path $repositoryRoot '.env'
$composePath = Join-Path $repositoryRoot 'infra\docker\docker-compose.yml'

function Invoke-Compose {
    param([string[]]$ComposeArguments, [string[]]$CommandArguments)
    & docker @ComposeArguments @CommandArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose failed with exit code $LASTEXITCODE."
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker is required. Install and start Docker Desktop with its Linux engine.'
}
$engineReady = $false
try {
    & docker info --format '{{.ServerVersion}}' 2>&1 | Out-Null
    $engineReady = $LASTEXITCODE -eq 0
}
catch { $engineReady = $false }
if (-not $engineReady) {
    throw 'Docker engine is unavailable. Start Docker Desktop; on Windows, enable WSL 2 first.'
}

if ($Action -eq 'test') {
    $testArguments = @('compose', '-p', 'telecom-backend-test', '-f',
        (Join-Path $repositoryRoot 'infra\docker\docker-compose.test.yml'))
    try {
        Invoke-Compose $testArguments @('up', '--build', '--abort-on-container-exit',
            '--exit-code-from', 'tests', 'tests')
    }
    finally {
        Invoke-Compose $testArguments @('down')
    }
    return
}

if (-not (Test-Path -LiteralPath $envPath)) {
    if ($Action -ne 'up') { throw 'Run dev.ps1 up first to create the local configuration.' }
    $template = [System.IO.File]::ReadAllText((Join-Path $repositoryRoot '.env.example'))
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        foreach ($key in @('SECRET_KEY', 'TOTP_ENCRYPTION_KEY')) {
            $bytes = New-Object byte[] 48
            $generator.GetBytes($bytes)
            $value = [Convert]::ToBase64String($bytes)
            $template = [regex]::Replace($template, "(?m)^$key=.*$", "$key=$value")
        }
    }
    finally { $generator.Dispose() }
    [System.IO.File]::WriteAllText($envPath, $template, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host 'Created .env with random local keys. Keep this file private.'
}

$composeArguments = @('compose', '-f', $composePath, '--env-file', $envPath)
if ($Web) { $composeArguments += @('--profile', 'web') }

switch ($Action) {
    'up' {
        Invoke-Compose $composeArguments @('up', '--build', '--wait')
        Write-Host 'API: http://localhost:8000/docs'
        Write-Host 'Create a user: .\infra\scripts\dev.ps1 user -Email you@example.com'
    }
    'down' { Invoke-Compose $composeArguments @('down') }
    'status' { Invoke-Compose $composeArguments @('ps', '-a') }
    'logs' { Invoke-Compose $composeArguments @('logs', '-f', '--tail', '100') }
    'user' {
        if (-not $Email) { throw 'Pass -Email, for example: dev.ps1 user -Email you@example.com' }
        Invoke-Compose $composeArguments @('exec', 'backend', 'python', '-m', 'app.cli',
            'create-user', '--email', $Email, '--role', $Role)
        Invoke-Compose $composeArguments @('exec', 'backend', 'python', '-m', 'app.cli',
            'enable-2fa', '--email', $Email)
    }
}
