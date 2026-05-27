param(
  [string[]]$Tasks,
  [int]$BatchSize = 3,
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$MoreTasks
)

$ErrorActionPreference = "Stop"
$env:UV_CACHE_DIR = (Join-Path (Get-Location) ".uv-cache")
New-Item -ItemType Directory -Force -Path $env:UV_CACHE_DIR | Out-Null

if (-not $Tasks) { $Tasks = @() }
if ($MoreTasks) { $Tasks += $MoreTasks }

$normalizedTasks = @()
foreach ($item in $Tasks) {
  if (-not $item) { continue }
  $parts = $item -split "[,\s]+" | Where-Object { $_ -and $_.Trim() -ne "" }
  foreach ($part in $parts) {
    $normalizedTasks += $part.Trim()
  }
}
$Tasks = $normalizedTasks | Select-Object -Unique

if (-not $Tasks -or $Tasks.Count -eq 0) {
  throw "Pass tasks via -Tasks t07 t13 t14 or positional args: .\run_failed_batches.ps1 t07 t13 t14"
}

function Get-EnvValue {
  param(
    [string]$Path,
    [string]$Key
  )
  if (-not (Test-Path $Path)) { return $null }
  $line = Get-Content $Path | Where-Object {
    $_ -match "^\s*$Key\s*=" -and $_ -notmatch "^\s*#"
  } | Select-Object -First 1
  if (-not $line) { return $null }
  $value = ($line -split "=", 2)[1].Trim()
  if ($value.StartsWith('"') -and $value.EndsWith('"')) { $value = $value.Substring(1, $value.Length - 2) }
  if ($value.StartsWith("'") -and $value.EndsWith("'")) { $value = $value.Substring(1, $value.Length - 2) }
  return $value
}

$envPath = Join-Path (Get-Location) ".env"
$threadsRaw = Get-EnvValue -Path $envPath -Key "RUN_THREADS"
$modelAdapter = Get-EnvValue -Path $envPath -Key "MODEL_ADAPTER"
$openaiApiKey = Get-EnvValue -Path $envPath -Key "OPENAI_API_KEY"
$openaiBaseUrl = Get-EnvValue -Path $envPath -Key "OPENAI_BASE_URL"
$modelId = Get-EnvValue -Path $envPath -Key "MODEL_ID"
$codexModelId = Get-EnvValue -Path $envPath -Key "CODEX_MODEL_ID"
$benchId = Get-EnvValue -Path $envPath -Key "BENCH_ID"
$bitgnApiKey = Get-EnvValue -Path $envPath -Key "BITGN_API_KEY"
$threads = 1
if ($threadsRaw -and ($threadsRaw -as [int]) -ge 1) {
  $threads = [int]$threadsRaw
}

$stamp = Get-Date -Format "yyyy-MM-ddTHH-mm-ssZ"
$workspace = (Get-Location).Path
$batchRoot = Join-Path $workspace ("logs\\manual-batches-" + $stamp)
New-Item -ItemType Directory -Force -Path $batchRoot | Out-Null

$batches = @()
for ($i = 0; $i -lt $Tasks.Count; $i += $BatchSize) {
  $end = [Math]::Min($i + $BatchSize - 1, $Tasks.Count - 1)
  $batch = $Tasks[$i..$end]
  $batchNum = "{0:D2}" -f (($i / $BatchSize) + 1)
  $name = "batch_{0}_{1}.log" -f $batchNum, ($batch -join "_")
  $logFile = Join-Path $batchRoot $name
  $batches += [PSCustomObject]@{
    Number = $batchNum
    Tasks = $batch
    LogFile = $logFile
  }
}

Write-Host ("RUN_THREADS={0}, batch size={1}, total batches={2}" -f $threads, $BatchSize, $batches.Count) -ForegroundColor Yellow

$running = @()
foreach ($batch in $batches) {
  if ($threads -le 1) {
    Write-Host ("Run {0}: {1}" -f $batch.Number, ($batch.Tasks -join ", ")) -ForegroundColor Cyan
    Set-Location -Path $workspace
    $env:UV_CACHE_DIR = $env:UV_CACHE_DIR
    if ($modelAdapter) { $env:MODEL_ADAPTER = $modelAdapter }
    if ($openaiApiKey) { $env:OPENAI_API_KEY = $openaiApiKey }
    if ($openaiBaseUrl) { $env:OPENAI_BASE_URL = $openaiBaseUrl }
    if ($modelId) { $env:MODEL_ID = $modelId }
    if ($codexModelId) { $env:CODEX_MODEL_ID = $codexModelId }
    if ($benchId) { $env:BENCH_ID = $benchId }
    if ($bitgnApiKey) { $env:BITGN_API_KEY = $bitgnApiKey }

    "Running batch $($batch.Number): $($batch.Tasks -join ', ')" | Tee-Object -FilePath $batch.LogFile -Append | Out-Null
    $cmd = @("run", "python", "main.py") + $batch.Tasks
    & uv @cmd 2>&1 | Tee-Object -FilePath $batch.LogFile -Append | Out-Null
    "Batch $($batch.Number) done: $($batch.Tasks -join ', ')" | Tee-Object -FilePath $batch.LogFile -Append | Out-Null
    Write-Host ("Finished batch {0} -> {1}" -f $batch.Number, $batch.LogFile)
    continue
  }

  while ($running.Count -ge $threads) {
    $done = Wait-Job -Job $running -Any
    Receive-Job -Job $done | Write-Output
    Remove-Job -Job $done
    $running = $running | Where-Object { $_.Id -ne $done.Id }
  }

  Write-Host ("Queue {0}: {1}" -f $batch.Number, ($batch.Tasks -join ", ")) -ForegroundColor Cyan
  $job = Start-Job -ScriptBlock {
    param(
      $number,
      $tasksArg,
      $logPath,
      $cwd,
      $uvCacheDir,
      $modelAdapterArg,
      $openaiApiKeyArg,
      $openaiBaseUrlArg,
      $modelIdArg,
      $codexModelIdArg,
      $benchIdArg,
      $bitgnApiKeyArg
    )
    Set-Location -Path $cwd
    $env:UV_CACHE_DIR = $uvCacheDir
    if ($modelAdapterArg) { $env:MODEL_ADAPTER = $modelAdapterArg }
    if ($openaiApiKeyArg) { $env:OPENAI_API_KEY = $openaiApiKeyArg }
    if ($openaiBaseUrlArg) { $env:OPENAI_BASE_URL = $openaiBaseUrlArg }
    if ($modelIdArg) { $env:MODEL_ID = $modelIdArg }
    if ($codexModelIdArg) { $env:CODEX_MODEL_ID = $codexModelIdArg }
    if ($benchIdArg) { $env:BENCH_ID = $benchIdArg }
    if ($bitgnApiKeyArg) { $env:BITGN_API_KEY = $bitgnApiKeyArg }
    "Running batch ${number}: $($tasksArg -join ', ')" | Tee-Object -FilePath $logPath -Append | Out-Null
    $cmd = @("run", "python", "main.py") + $tasksArg
    & uv @cmd 2>&1 | Tee-Object -FilePath $logPath -Append | Out-Null
    "Batch ${number} done: $($tasksArg -join ', ')" | Tee-Object -FilePath $logPath -Append | Out-Null
    "Finished batch ${number} -> $logPath"
  } -ArgumentList `
    $batch.Number, `
    $batch.Tasks, `
    $batch.LogFile, `
    $workspace, `
    $env:UV_CACHE_DIR, `
    $modelAdapter, `
    $openaiApiKey, `
    $openaiBaseUrl, `
    $modelId, `
    $codexModelId, `
    $benchId, `
    $bitgnApiKey
  $running += $job
}

while ($running.Count -gt 0) {
  $done = Wait-Job -Job $running -Any
  Receive-Job -Job $done | Write-Output
  Remove-Job -Job $done
  $running = $running | Where-Object { $_.Id -ne $done.Id }
}

Write-Host ("Batch logs saved to: {0}" -f $batchRoot) -ForegroundColor Green
