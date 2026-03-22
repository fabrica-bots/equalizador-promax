$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$exePath = Join-Path $root "dist\EqualizadorProMax.exe"
if (-not (Test-Path $exePath)) {
    throw "Executavel nao encontrado em $exePath. Rode primeiro .\scripts\build-windows.ps1"
}

$iscc = Get-Command ISCC -ErrorAction SilentlyContinue
if (-not $iscc) {
    throw "Inno Setup (ISCC) nao encontrado no PATH. Instale o Inno Setup ou adicione o ISCC ao PATH."
}

& $iscc.Source (Join-Path $root "installer\EqualizadorProMax.iss")

Write-Host ""
Write-Host "Instalador concluido em:" -ForegroundColor Green
Write-Host "  $root\dist-installer"
