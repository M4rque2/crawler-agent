param(
    [string]$OutputDir = ".",
    [string]$Prefix = "window_dump",
    [string]$DeviceId,
    [switch]$KeepRemote,
    [int]$RetryCount = 3,
    [int]$RetryDelaySeconds = 1
)

$ErrorActionPreference = "Stop"

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$fileName = "${Prefix}_${timestamp}.xml"
$remotePath = "/sdcard/$fileName"

if (-not (Test-Path -LiteralPath $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

$adbBase = @()
if ($DeviceId) {
    $adbBase += @("-s", $DeviceId)
}

function Test-RemoteFileExists {
    param([string]$RemotePath)

    $result = & adb @adbBase shell ls $RemotePath 2>&1
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    $text = ($result | Out-String)
    return -not ($text -match "No such file or directory")
}

Write-Host "[1/3] Dumping UI hierarchy on device: $remotePath"
$dumpSucceeded = $false
for ($attempt = 1; $attempt -le $RetryCount; $attempt++) {
    # Wake device before dump to reduce idle-state failures.
    & adb @adbBase shell input keyevent KEYCODE_WAKEUP | Out-Null
    Start-Sleep -Milliseconds 300

    $dumpOut = & adb @adbBase shell uiautomator dump $remotePath 2>&1
    $dumpExitCode = $LASTEXITCODE
    $dumpText = ($dumpOut | Out-String).Trim()

    if ($dumpText) {
        Write-Host "  dump attempt ${attempt}/${RetryCount}: $dumpText"
    }

    if ($dumpExitCode -eq 0 -and (Test-RemoteFileExists -RemotePath $remotePath)) {
        $dumpSucceeded = $true
        break
    }

    if ($attempt -lt $RetryCount) {
        Start-Sleep -Seconds $RetryDelaySeconds
    }
}

if (-not $dumpSucceeded) {
    throw "uiautomator dump failed after $RetryCount attempts. No remote XML found at $remotePath."
}

Write-Host "[2/3] Pulling XML to local directory: $OutputDir"
$pullOut = & adb @adbBase pull $remotePath $OutputDir 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "adb pull failed: $($pullOut | Out-String)"
}

if (-not $KeepRemote) {
    Write-Host "[3/3] Removing remote dump file"
    & adb @adbBase shell rm $remotePath | Out-Null
} else {
    Write-Host "[3/3] Keeping remote file: $remotePath"
}

$localPath = Join-Path $OutputDir $fileName
if (-not (Test-Path -LiteralPath $localPath)) {
    throw "Pull reported success but local file was not found: $localPath"
}

Write-Host "Done. Local file: $localPath"
