<#
.SYNOPSIS
    Build the BatchSimLab Blender extension zip and publish it to the
    docs/ GitHub Pages feed (index.json + the zip).

.DESCRIPTION
    Mirrors the manual release steps in RELEASING.md:
      1. blender --command extension validate scripts/BatchSimLab
      2. blender --command extension build --source-dir scripts/BatchSimLab --output-dir dist
      3. copy the built zip into docs/, remove stale batchsimlab-*.zip files
      4. blender --command extension server-generate --repo-dir docs

    Does NOT touch git  -  review `git status` / `git diff` and commit + push
    yourself once this finishes (the script prints the exact commands).

.NOTES
    Each Blender invocation loads your full local addon set (not just
    BatchSimLab) before running the command, so it can take 10-30+ seconds
    and print unrelated addon warnings  -  that's normal, not a hang. If a
    step truly hangs, this script kills it after $TimeoutSec and reports
    failure rather than waiting forever.
#>

param(
    [string]$BlenderExe,
    [int]$TimeoutSec = 120
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

# ---------------------------------------------------------------------------
# Locate Blender
# ---------------------------------------------------------------------------
if (-not $BlenderExe) {
    $BlenderExe = Get-ChildItem "C:\Program Files\Blender Foundation\Blender *\blender.exe" -ErrorAction SilentlyContinue |
        Sort-Object { [version]($_.Directory.Name -replace 'Blender ', '') } -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $BlenderExe -or -not (Test-Path $BlenderExe)) {
    throw "Could not find blender.exe. Pass it explicitly: -BlenderExe 'C:\path\to\blender.exe'"
}
Write-Host "Blender: $BlenderExe"

# ---------------------------------------------------------------------------
# Read the version we're about to publish (manifest is the source of truth)
# ---------------------------------------------------------------------------
$ManifestPath = Join-Path $RepoRoot "scripts\BatchSimLab\blender_manifest.toml"
$ManifestText = Get-Content $ManifestPath -Raw
$VersionMatch = [regex]::Match($ManifestText, '(?m)^version\s*=\s*"([^"]+)"')
if (-not $VersionMatch.Success) {
    throw "Could not read version from $ManifestPath"
}
$Version = $VersionMatch.Groups[1].Value
Write-Host "Publishing BatchSimLab $Version"

$LogDir = Join-Path $env:TEMP "batchsimlab_publish_logs"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

# ---------------------------------------------------------------------------
# Helper: run a Blender --command invocation with a hard timeout
# ---------------------------------------------------------------------------
function Invoke-BlenderCommand {
    param(
        [string]$Name,
        [string[]]$Arguments
    )

    $outFile = Join-Path $LogDir "$Name.out.txt"
    $errFile = Join-Path $LogDir "$Name.err.txt"
    Remove-Item $outFile, $errFile -ErrorAction SilentlyContinue

    Write-Host "`n--- $Name ---"
    Write-Host "blender $($Arguments -join ' ')"

    # Started via the raw .NET Process API (not Start-Process -PassThru):
    # Start-Process's ExitCode is unreliable in Windows PowerShell 5.1 when
    # both streams are redirected to files (observed empty/$null here even
    # though the process exited 0) - this avoids that cmdlet-specific bug.
    # .Arguments (single string), not the newer .ArgumentList collection -
    # the latter came back $null under this machine's Windows PowerShell 5.1
    # / .NET Framework combination. Safe here: every argument we pass is a
    # plain flag/path token with no embedded spaces or quotes.
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $BlenderExe
    $psi.Arguments = ($Arguments -join ' ')
    $psi.WorkingDirectory = $RepoRoot
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi

    $stdout = New-Object System.Text.StringBuilder
    $stderr = New-Object System.Text.StringBuilder
    $outSub = Register-ObjectEvent -InputObject $proc -EventName OutputDataReceived -Action {
        if ($null -ne $EventArgs.Data) { [void]$Event.MessageData.AppendLine($EventArgs.Data) }
    } -MessageData $stdout
    $errSub = Register-ObjectEvent -InputObject $proc -EventName ErrorDataReceived -Action {
        if ($null -ne $EventArgs.Data) { [void]$Event.MessageData.AppendLine($EventArgs.Data) }
    } -MessageData $stderr

    try {
        [void]$proc.Start()
        $proc.BeginOutputReadLine()
        $proc.BeginErrorReadLine()

        $finished = $proc.WaitForExit($TimeoutSec * 1000)
        if (-not $finished) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            Write-Host "TIMED OUT after ${TimeoutSec}s"
            throw "$Name timed out"
        }
        $proc.WaitForExit()   # let the async output handlers finish draining
        $exitCode = $proc.ExitCode
    } finally {
        Unregister-Event -SourceIdentifier $outSub.Name -ErrorAction SilentlyContinue
        Unregister-Event -SourceIdentifier $errSub.Name -ErrorAction SilentlyContinue
    }

    Set-Content -Path $outFile -Value $stdout.ToString()
    Set-Content -Path $errFile -Value $stderr.ToString()

    if ($exitCode -ne 0) {
        Write-Host "FAILED (exit $exitCode)  -  see $outFile / $errFile"
        Get-Content $errFile -ErrorAction SilentlyContinue | Select-Object -Last 20
        throw "$Name failed"
    }

    Write-Host "OK (exit 0)"
    return $stdout.ToString() -split "`r?`n"
}

# ---------------------------------------------------------------------------
# 1. Validate
# ---------------------------------------------------------------------------
$validateOut = Invoke-BlenderCommand -Name "validate" -Arguments @(
    '--command', 'extension', 'validate', 'scripts/BatchSimLab'
)
if (-not ($validateOut -match "Success parsing TOML")) {
    Write-Host ($validateOut | Select-Object -Last 20)
    throw "Manifest validation did not report success  -  see log above"
}

# ---------------------------------------------------------------------------
# 2. Build
# ---------------------------------------------------------------------------
$distDir = Join-Path $RepoRoot "dist"
New-Item -ItemType Directory -Path $distDir -Force | Out-Null
Invoke-BlenderCommand -Name "build" -Arguments @(
    '--command', 'extension', 'build',
    '--source-dir', 'scripts/BatchSimLab',
    '--output-dir', 'dist'
) | Out-Null

$builtZip = Join-Path $distDir "batchsimlab-$Version.zip"
if (-not (Test-Path $builtZip)) {
    throw "Expected build output not found: $builtZip"
}
Write-Host "Built: $builtZip ($((Get-Item $builtZip).Length) bytes)"

# ---------------------------------------------------------------------------
# 3. Publish into docs/  -  drop any stale batchsimlab-*.zip, add the new one
# ---------------------------------------------------------------------------
$docsDir = Join-Path $RepoRoot "docs"
Get-ChildItem (Join-Path $docsDir "batchsimlab-*.zip") -ErrorAction SilentlyContinue |
    ForEach-Object {
        Write-Host "Removing stale $($_.Name)"
        Remove-Item $_.FullName -Force
    }
Copy-Item $builtZip (Join-Path $docsDir "batchsimlab-$Version.zip") -Force
Write-Host "Copied to docs\batchsimlab-$Version.zip"

# ---------------------------------------------------------------------------
# 4. Regenerate docs/index.json
# ---------------------------------------------------------------------------
$serverGenOut = Invoke-BlenderCommand -Name "server-generate" -Arguments @(
    '--command', 'extension', 'server-generate', '--repo-dir', 'docs'
)
if (-not ($serverGenOut -match "found \d+ packages?")) {
    Write-Host ($serverGenOut | Select-Object -Last 20)
    throw "server-generate did not report finding any packages  -  see log above"
}

# ---------------------------------------------------------------------------
# Sanity check + summary
# ---------------------------------------------------------------------------
$indexPath = Join-Path $docsDir "index.json"
$index = Get-Content $indexPath -Raw | ConvertFrom-Json
$published = $index.data | Where-Object { $_.id -eq "batchsimlab" }
if (-not $published -or $published.version -ne $Version) {
    throw "docs/index.json does not show batchsimlab $Version after server-generate"
}

Write-Host "`n=== Done ==="
Write-Host "docs/index.json now serves batchsimlab $($published.version) ($($published.archive_size) bytes)"
Write-Host "Logs: $LogDir"
Write-Host "`nNext (not run automatically):"
Write-Host "  git add docs/"
Write-Host "  git commit -m `"Publish batchsimlab $Version to the extension feed`""
Write-Host "  git push origin main"
