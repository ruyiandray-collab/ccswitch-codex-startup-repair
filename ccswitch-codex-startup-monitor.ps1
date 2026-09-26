param([switch]$Once)
$ErrorActionPreference = 'Stop'
$configPath = Join-Path $env:USERPROFILE '.codex\config.toml'
$python = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$checker = Join-Path $PSScriptRoot 'repair_config.py'
$logPath = Join-Path $PSScriptRoot 'ccswitch-codex-startup-check.log'

function Write-CheckLog([string]$Message) {
    if ((Test-Path -LiteralPath $logPath) -and (Get-Item -LiteralPath $logPath).Length -gt 1MB) {
        Move-Item -LiteralPath $logPath -Destination ($logPath + '.1') -Force
    }
    Add-Content -LiteralPath $logPath -Value ('{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message) -Encoding UTF8
}

function Get-ConfigFingerprint {
    $stream = $null
    $hasher = $null
    try {
        $share = [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
        $stream = [IO.File]::Open($configPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, $share)
        $hasher = [Security.Cryptography.SHA256]::Create()
        [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '')
    } catch { $null } finally {
        if ($stream) { $stream.Dispose() }
        if ($hasher) { $hasher.Dispose() }
    }
}

function Test-RetryableStatus([string]$Status) {
    $Status -in @('blocked_provider','blocked_route','blocked_table_shape','blocked_file_busy',
        'blocked_config_changed','blocked_check_error','blocked_worker_error','blocked_timeout',
        'blocked_invalid_result')
}

function Invoke-StartupCheck {
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo.FileName = $python
    $proc.StartInfo.Arguments = '-I "' + $checker + '" "' + $configPath + '"'
    $proc.StartInfo.UseShellExecute = $false
    $proc.StartInfo.CreateNoWindow = $true
    $proc.StartInfo.RedirectStandardOutput = $true
    $proc.StartInfo.RedirectStandardError = $true
    try {
        [void]$proc.Start()
        $stdout = $proc.StandardOutput.ReadToEndAsync()
        $stderr = $proc.StandardError.ReadToEndAsync()
        if (-not $proc.WaitForExit(30000)) {
            $proc.Kill()
            $proc.WaitForExit()
            Write-CheckLog 'status=blocked_timeout'
            return 'blocked_timeout'
        }
        $status = ($stdout.Result | ConvertFrom-Json).status
        if ($status -notin @('alias_present','repaired','alias_synchronized','blocked_provider','blocked_route','blocked_table_shape','blocked_alias_conflict','blocked_file_busy','blocked_config_changed','blocked_check_error')) {
            $status = 'blocked_invalid_result'
        }
        Write-CheckLog ('status={0}; exit={1}' -f $status, $proc.ExitCode)
        return $status
    } catch {
        Write-CheckLog 'status=blocked_worker_error'
        return 'blocked_worker_error'
    } finally { $proc.Dispose() }
}

# Also protects manual launches, beyond Task Scheduler's IgnoreNew setting.
$mutex = New-Object System.Threading.Mutex($false, 'Local\CodexCCSwitchStartupRepair')
$owned = $false
try {
    try { $owned = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $owned = $true }
    if (-not $owned) { return }
    if ($Once) { Invoke-StartupCheck; return }
    Write-CheckLog 'monitor=started; mode=offline; watch=config.toml; compatibility=bidirectional-v3'
    $stableHash = Get-ConfigFingerprint
    $retryHash = $null
    $retryDue = $null
    $retryDelay = 5
    if ($stableHash) {
        $status = Invoke-StartupCheck
        if (Test-RetryableStatus $status) {
            $retryHash = $stableHash
            $retryDue = (Get-Date).AddSeconds($retryDelay)
        }
    }
    $candidateHash = $null
    $stableSamples = 0
    while ($true) {
        Start-Sleep -Seconds 2
        $currentHash = Get-ConfigFingerprint
        if (-not $currentHash) { $candidateHash = $null; $stableSamples = 0; continue }
        if ($currentHash -eq $stableHash) {
            $candidateHash = $null
            $stableSamples = 0
            if ($retryHash -eq $stableHash -and $retryDue -and (Get-Date) -ge $retryDue) {
                $status = Invoke-StartupCheck
                if (Test-RetryableStatus $status) {
                    $retryDelay = [Math]::Min($retryDelay * 2, 30)
                    $retryDue = (Get-Date).AddSeconds($retryDelay)
                    Write-CheckLog ('retry_scheduled={0}s' -f $retryDelay)
                } else {
                    $retryHash = $null
                    $retryDue = $null
                    $retryDelay = 5
                }
            }
            continue
        }
        if ($currentHash -eq $candidateHash) { $stableSamples++ }
        else { $candidateHash = $currentHash; $stableSamples = 1 }
        if ($stableSamples -ge 3) {
            # Mark only the stable version observed before repair. If CC Switch
            # writes again while the checker runs, the new hash stays detectable.
            $stableHash = $candidateHash
            $status = Invoke-StartupCheck
            $candidateHash = $null
            $stableSamples = 0
            $retryDelay = 5
            if (Test-RetryableStatus $status) {
                $retryHash = $stableHash
                $retryDue = (Get-Date).AddSeconds($retryDelay)
                Write-CheckLog ('retry_scheduled={0}s' -f $retryDelay)
            } else {
                $retryHash = $null
                $retryDue = $null
            }
        }
    }
} finally {
    if ($owned) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
