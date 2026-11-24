param(
    [switch]$NoBrowser,
    [switch]$Check,
    [switch]$SetupOnly
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $root 'scripts\launch.py'
$launcherArgs = @($launcher)
if ($NoBrowser) { $launcherArgs += '--no-browser' }
if ($Check) { $launcherArgs += '--check' }
if ($SetupOnly) { $launcherArgs += '--setup-only' }

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 @launcherArgs
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python @launcherArgs
} else {
    Write-Error 'Python não foi encontrado. Instale Python 3.11 ou superior e marque "Add python.exe to PATH".'
    exit 1
}
exit $LASTEXITCODE
