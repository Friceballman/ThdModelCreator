# Register the repository launcher alongside iwb in the existing user command bin.
# Run only when installation of this user-scoped launcher is authorized.
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$commandBin = Join-Path $env:LOCALAPPDATA 'Python\bin'
if (-not (Test-Path -LiteralPath $commandBin -PathType Container)) {
    throw 'The existing Python user command bin was not found.'
}
$commandBin = (Resolve-Path -LiteralPath $commandBin).Path
$pathEntries = @($env:Path -split ';' | ForEach-Object { $_.TrimEnd('\') })
if ($pathEntries -notcontains $commandBin.TrimEnd('\')) {
    throw 'The Python user command bin is not on PATH. No settings were changed.'
}
$sourceLauncher = Join-Path $repoRoot 'mwb.cmd'
$pythonLauncher = Join-Path $repoRoot 'mwb.py'
$launcherContent = [IO.File]::ReadAllText($sourceLauncher).Replace('%~dp0mwb.py', $pythonLauncher)
$targetLauncher = Join-Path $commandBin 'mwb.cmd'
if (Test-Path -LiteralPath $targetLauncher) {
    if ([IO.File]::ReadAllText($targetLauncher) -ne $launcherContent) {
        throw "Another launcher already exists; it was preserved: $targetLauncher"
    }
} else {
    $launcherBytes = [Text.UTF8Encoding]::new($false).GetBytes($launcherContent)
    $launcherStream = [IO.File]::Open($targetLauncher, [IO.FileMode]::CreateNew)
    try { $launcherStream.Write($launcherBytes, 0, $launcherBytes.Length) }
    finally { $launcherStream.Dispose() }
}
Write-Output "Registered: $targetLauncher"
Write-Output "Repository: $repoRoot"
Write-Output 'PATH, Python packages and PowerShell profiles were not changed.'
