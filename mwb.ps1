# Dot-source once per PowerShell session: . .\mwb.ps1
# Direct invocation (.\mwb) also forwards arguments to the CLI.
# No install, profile edit or permanent PATH change.
$mwbLauncher = Join-Path $PSScriptRoot 'mwb.py'
$mwbInterpreter = if ($env:MWB_PYTHON) { $env:MWB_PYTHON } else { 'python' }
if ($MyInvocation.InvocationName -ne '.') {
    & $mwbInterpreter -B $mwbLauncher @args
    exit $LASTEXITCODE
}
$function:mwb = {
    & $mwbInterpreter -B $mwbLauncher @args
}.GetNewClosure()
