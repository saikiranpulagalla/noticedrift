[CmdletBinding()]
param(
    [string]$Python = '',
    [switch]$SkipReleaseVerifier
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$server = $null

function Assert-Equal([object]$Actual, [object]$Expected, [string]$Label) {
    if ($Actual -ne $Expected) { throw "${Label}: expected '$Expected', got '$Actual'" }
}

function Get-FreeLoopbackPort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    }
    finally {
        $listener.Stop()
    }
}

function Invoke-LocalJson([string]$Uri, [string]$Method = 'GET', [string]$Body = $null) {
    $params = @{ Uri = $Uri; Method = $Method; TimeoutSec = 5; UseBasicParsing = $true }
    # PowerShell coerces an omitted [string] $null to ''. Do not attach an
    # empty content-body to GET; Windows PowerShell rejects it before dispatch.
    if ($PSBoundParameters.ContainsKey('Body')) { $params['Body'] = $Body; $params['ContentType'] = 'application/json' }
    $response = Invoke-WebRequest @params
    return @{ StatusCode = [int]$response.StatusCode; Body = ($response.Content | ConvertFrom-Json) }
}

Push-Location $repoRoot
try {
    # Never resolve a global Python/pip from PATH. All gates and the child
    # server use this same absolute virtual-environment interpreter.
    if ([string]::IsNullOrWhiteSpace($Python)) {
        $Python = Join-Path $repoRoot '.venv\Scripts\python.exe'
    }
    elseif (-not [System.IO.Path]::IsPathRooted($Python)) {
        $Python = Join-Path $repoRoot $Python
    }
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw 'PROJECT_VENV_PYTHON_MISSING: create the project .venv or supply its explicit Python executable'
    }
    $Python = (Resolve-Path -LiteralPath $Python).Path
    & $Python -c "import sys; sys.exit(0 if sys.prefix != sys.base_prefix and sys.version_info[:2] == (3, 11) else 1)"
    if ($LASTEXITCODE -ne 0) { throw 'PROJECT_VENV_PYTHON_INVALID: Windows release gate requires a Python 3.11 virtual environment' }
    Write-Host "Release interpreter: $Python"
    & $Python -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'PIP_CHECK_FAILED' }

    if (-not $SkipReleaseVerifier) {
        & $Python scripts\verify_v085.py
        if ($LASTEXITCODE -ne 0) { throw 'RELEASE_VERIFIER_FAILED' }
    }

    # Always choose an ephemeral loopback port. This never reuses or terminates
    # a process that happens to own port 8000, and keeps the smoke server local.
    $port = Get-FreeLoopbackPort
    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $Python
    $psi.Arguments = "-m uvicorn app.api.main:app --app-dir backend --host 127.0.0.1 --port $port"
    $psi.WorkingDirectory = $repoRoot
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardOutput = $true
    $psi.EnvironmentVariables.Remove('SERPAPI_API_KEY')
    $psi.EnvironmentVariables.Remove('NOTICEDRIFT_ISSUER_ATTESTATIONS')
    $psi.EnvironmentVariables.Remove('NOTICEDRIFT_EVIDENCE_DIR')
    $server = [System.Diagnostics.Process]::Start($psi)
    if ($null -eq $server) { throw 'SMOKE_SERVER_START_FAILED' }

    $base = "http://127.0.0.1:$port"
    $health = $null
    $readinessFailure = 'No readiness response'
    $until = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $until) {
        try {
            $health = Invoke-LocalJson "$base/health"
            break
        }
        catch {
            # Requests contain only the ephemeral localhost health URL.
            $readinessFailure = $_.Exception.Message
            if ($server.HasExited) { throw "SMOKE_SERVER_EXITED:$($server.ExitCode)" }
            Start-Sleep -Milliseconds 250
        }
    }
    if ($null -eq $health) {
        if (-not $server.HasExited) {
            $server.Kill()
            $server.WaitForExit()
        }
        $stderr = $server.StandardError.ReadToEnd().Trim()
        if ([string]::IsNullOrWhiteSpace($stderr)) { $stderr = 'no server stderr was emitted' }
        throw "SMOKE_SERVER_NOT_READY:${readinessFailure}; ${stderr}"
    }
    Assert-Equal $health.StatusCode 200 'health status'
    Assert-Equal $health.Body.version 'v0.8.5' 'health version'
    Assert-Equal $health.Body.configured $false 'live configuration'

    $landing = Invoke-WebRequest -Uri "$base/" -TimeoutSec 5 -UseBasicParsing
    Assert-Equal ([int]$landing.StatusCode) 200 'landing status'
    foreach ($requiredText in @(
        "SYNTHETIC $([char]0x00B7) offline fixture",
        'mocked SerpApi responses',
        'never a live SerpApi response',
        'Recorded live-search diagnostic',
        "UNRESOLVED $([char]0x00B7) coverage INSUFFICIENT",
        'No official page or PDF was fetched, captured, hashed, or authenticated.'
    )) {
        if (-not $landing.Content.Contains($requiredText)) { throw "LANDING_DISCLOSURE_MISSING:$requiredText" }
    }

    $diagnostic = Invoke-LocalJson "$base/api/live-search-diagnostic"
    Assert-Equal $diagnostic.StatusCode 200 'diagnostic status'
    Assert-Equal $diagnostic.Body.provider_attempts 6 'diagnostic attempts'
    Assert-Equal $diagnostic.Body.completed_attempts 2 'diagnostic completed attempts'
    Assert-Equal $diagnostic.Body.timed_out_attempts 4 'diagnostic timeouts'
    Assert-Equal $diagnostic.Body.coverage 'INSUFFICIENT' 'diagnostic coverage'
    Assert-Equal $diagnostic.Body.verdict 'UNRESOLVED' 'diagnostic verdict'
    Assert-Equal $diagnostic.Body.official_source_captures 0 'official source captures'
    Assert-Equal $diagnostic.Body.source_evidence_authenticated $false 'source authentication'
    foreach ($entry in $diagnostic.Body.attempts) {
        if ($entry.PSObject.Properties.Name -contains 'query' -or $entry.PSObject.Properties.Name -contains 'url') {
            throw 'DIAGNOSTIC_EXPOSES_SENSITIVE_SEARCH_DETAIL'
        }
    }

    $demo = Invoke-LocalJson "$base/api/demo/check" 'POST' '{"supplied_deadline":"2026-10-01"}'
    Assert-Equal $demo.StatusCode 200 'synthetic demo status'
    Assert-Equal $demo.Body.execution_mode 'SYNTHETIC_OFFLINE_FRESH_REQUESTED' 'synthetic execution mode'
    Assert-Equal $demo.Body.analysis.verdict 'SUPERSEDED' 'synthetic verdict'
    if (@($demo.Body.search_entries | Where-Object { $_.mode -ne 'SYNTHETIC' }).Count -ne 0) {
        throw 'SYNTHETIC_DEMO_CONTAINS_NON_SYNTHETIC_SEARCH_EVIDENCE'
    }

    try {
        Invoke-WebRequest -Uri "$base/api/check" -Method POST -ContentType 'application/json' -Body '{}' -UseBasicParsing -ErrorAction Stop | Out-Null
        throw 'LIVE_ERROR_STATE_UNEXPECTEDLY_SUCCEEDED'
    }
    catch {
        $response = $_.Exception.Response
        if ($null -eq $response -or [int]$response.StatusCode -ne 422) { throw }
    }

    Write-Host "PASS: local HTTP smoke test on $base"
}
finally {
    if ($null -ne $server -and -not $server.HasExited) {
        # This is the child process created above; no unrelated process is touched.
        $server.Kill()
        $server.WaitForExit()
    }
    Pop-Location
}
