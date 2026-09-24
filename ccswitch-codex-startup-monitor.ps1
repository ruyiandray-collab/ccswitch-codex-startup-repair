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

function Get-DesktopStarts {
    # Match the installed desktop package, not its CLI workers or check process.
    $desktop = @(Get-CimInstance Win32_Process -Filter "Name = 'ChatGPT.exe'" | Where-Object {
        $_.ExecutablePath -match '\\WindowsApps\\OpenAI\.Codex_[^\\]+\\app\\ChatGPT\.exe$'
    })
    $ids = @($desktop | ForEach-Object { $_.ProcessId })
    @($desktop | Where-Object { $_.ParentProcessId -notin $ids } | ForEach-Object {
        try {
            '{0}:{1}' -f $_.ProcessId, $_.CreationDate.ToUniversalTime().Ticks
        } catch { }
    })
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
            return
        }
        $status = ($stdout.Result | ConvertFrom-Json).status
        if ($status -notin @('alias_present','repaired','blocked_provider','blocked_route','blocked_table_shape','blocked_file_busy','blocked_config_changed','blocked_check_error')) {
            $status = 'blocked_invalid_result'
        }
        Write-CheckLog ('status={0}; exit={1}' -f $status, $proc.ExitCode)
    } catch {
        Write-CheckLog 'status=blocked_worker_error'
    } finally { $proc.Dispose() }
}

# Also protects manual launches, beyond Task Scheduler's IgnoreNew setting.
$mutex = New-Object System.Threading.Mutex($false, 'Local\CodexCCSwitchStartupRepair')
$owned = $false
try {
    try { $owned = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $owned = $true }
    if (-not $owned) { return }
    if ($Once) { Invoke-StartupCheck; return }
    Write-CheckLog 'monitor=started; mode=offline'
    $seen = @{}
    while ($true) {
        $current = @(Get-DesktopStarts)
        foreach ($key in @($seen.Keys)) {
            if ($key -notin $current) { $seen.Remove($key) }
        }
        foreach ($key in $current) {
            if (-not $seen.ContainsKey($key)) { $seen[$key] = @{ Due = (Get-Date).AddSeconds(15); Done = $false } }
        }
        $due = @($current | Where-Object { -not $seen[$_].Done -and (Get-Date) -ge $seen[$_].Due })
        if ($due.Count -gt 0) {
            Invoke-StartupCheck
            foreach ($key in $due) { $seen[$key].Done = $true }
        }
        Start-Sleep -Seconds 3
    }
} finally {
    if ($owned) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
