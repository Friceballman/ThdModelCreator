# Dot-source once per PowerShell session: . .\mwb.ps1
# Direct invocation (.\mwb) also forwards arguments to the CLI.
# No install, profile edit, permanent PATH change or TripoSR dependency update.
$mwbLauncher = Join-Path $PSScriptRoot 'mwb.py'
$mwbInterpreter = if ($env:MWB_PYTHON) { $env:MWB_PYTHON } else { 'C:\AI_test\TripoSR\.venv\Scripts\python.exe' }
if ($MyInvocation.InvocationName -ne '.') {
    & $mwbInterpreter -B $mwbLauncher @args
    exit $LASTEXITCODE
}
$function:mwb = {
    & $mwbInterpreter -B $mwbLauncher @args
}.GetNewClosure()
