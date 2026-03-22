$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

python .\scripts\version-tool.py rollback

$pathsToClean = @(
    (Join-Path $root "dist"),
    (Join-Path $root "dist-installer"),
    (Join-Path $root "build")
)

foreach ($path in $pathsToClean) {
    if (Test-Path $path) {
        Remove-Item -Recurse -Force $path
    }
}

Write-Host "Versao revertida e artefatos locais removidos." -ForegroundColor Green
