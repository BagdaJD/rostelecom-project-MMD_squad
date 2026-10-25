param(
    [ValidateSet('check', 'init', 'api', 'worker', 'user', 'test')]
    [string]$Action = 'check',
    [string]$PythonPath,
    [string]$Email,
    [ValidateSet('admin', 'analyst', 'manager')]
    [string]$Role = 'manager'
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$backendRoot = Join-Path $repositoryRoot 'backend'
if (-not $PythonPath) { $PythonPath = Join-Path $backendRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw 'Python environment not found. Pass -PythonPath with your configured interpreter.'
}
$envPath = Join-Path $repositoryRoot '.env'
if (-not (Test-Path -LiteralPath $envPath)) {
    if ($Action -ne 'init') { throw 'Run native.ps1 init first, or create and configure .env.' }
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
    Write-Host 'Created .env with private random keys. Configure DATABASE_URL and REDIS_URL.'
}

function Invoke-BackendPython {
    param([string[]]$PythonArguments)
    & $PythonPath @PythonArguments
    if ($LASTEXITCODE -ne 0) { throw "Backend command failed with exit code $LASTEXITCODE." }
}

Push-Location $backendRoot
try {
    switch ($Action) {
        'check' {
            Invoke-BackendPython @('-m', 'app.cli', 'check-config')
            Invoke-BackendPython @('-m', 'app.cli', 'check-services')
        }
        'init' {
            Invoke-BackendPython @('-m', 'app.cli', 'check-config')
            Invoke-BackendPython @('-m', 'app.cli', 'check-services')
            Invoke-BackendPython @('-m', 'alembic', 'upgrade', 'head')
            Invoke-BackendPython @('-m', 'app.cli', 'bootstrap-data')
            Invoke-BackendPython @('-m', 'modules.deal_calculator.seed')
            Invoke-BackendPython @('-m', 'app.cli', 'refresh-views')
            Write-Host 'Initialized. Run native.ps1 api and native.ps1 worker in separate terminals.'
        }
        'api' { Invoke-BackendPython @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000') }
        'worker' { Invoke-BackendPython @('-m', 'app.workers.main') }
        'user' {
            if (-not $Email) { throw 'Pass -Email.' }
            Invoke-BackendPython @('-m', 'app.cli', 'create-user', '--email', $Email, '--role', $Role)
            Invoke-BackendPython @('-m', 'app.cli', 'enable-2fa', '--email', $Email)
        }
        'test' { Invoke-BackendPython @('-m', 'pytest', '-m', 'not integration') }
    }
}
finally { Pop-Location }
