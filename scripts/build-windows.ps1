$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$newVersion = ""

try {
    $newVersion = python .\scripts\version-tool.py bump
    Write-Host "Versao atualizada para $newVersion" -ForegroundColor Green

    python -m pip install -e .[build]
    python -m PyInstaller --noconfirm --clean EqualizadorProMax.spec
}
catch {
    Write-Warning "Falha no build. Revertendo versao..."
    python .\scripts\version-tool.py rollback | Out-Null
    throw
}

Write-Host ""
Write-Host "Build concluido em:" -ForegroundColor Green
Write-Host "  $root\dist\EqualizadorProMax.exe"
Write-Host "Versao gerada: $newVersion"
