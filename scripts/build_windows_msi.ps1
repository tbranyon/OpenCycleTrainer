param(
    [string]$PythonExe = "",
    [string]$AppVersion = "",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$packagingRoot = Join-Path $repoRoot "packaging\\windows"
$tmpRoot = Join-Path $repoRoot ".tmp_runtime\\windows_msi_build"
$pyiBuildRoot = Join-Path $tmpRoot "pyinstaller"
$wixObjRoot = Join-Path $tmpRoot "wixobj"
$distRoot = Join-Path $repoRoot "dist"
$installerRoot = Join-Path $distRoot "installer"
$appDistRoot = Join-Path $distRoot "OpenCycleTrainer"
$specPath = Join-Path $packagingRoot "opencycletrainer.spec"
$wxsPath = Join-Path $packagingRoot "OpenCycleTrainer.wxs"
$harvestPath = Join-Path $tmpRoot "AppFiles.wxs"

function Assert-Command {
    param([string]$Name)
    if (Test-Path $Name) {
        return
    }
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found in PATH."
    }
}

function Resolve-PythonExe {
    param([string]$ProvidedPythonExe)
    if ($ProvidedPythonExe) {
        return $ProvidedPythonExe
    }
    $venvPython = Join-Path $repoRoot ".venv\\Scripts\\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }
    return "python"
}

function Resolve-AppVersion {
    param(
        [string]$ProvidedVersion,
        [string]$ResolvedPythonExe
    )
    if ($ProvidedVersion) {
        return $ProvidedVersion
    }

    $script = @"
import pathlib, tomllib
data = tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'))
print(data['project']['version'])
"@

    $resolved = & $ResolvedPythonExe -c $script
    if ($LASTEXITCODE -ne 0 -or -not $resolved) {
        throw "Could not resolve project version from pyproject.toml"
    }
    return $resolved.Trim()
}

Push-Location $repoRoot
try {
    $resolvedPythonExe = Resolve-PythonExe -ProvidedPythonExe $PythonExe
    Assert-Command $resolvedPythonExe
    Assert-Command "heat"
    Assert-Command "candle"
    Assert-Command "light"

    $resolvedVersion = Resolve-AppVersion -ProvidedVersion $AppVersion -ResolvedPythonExe $resolvedPythonExe
    Write-Host "Building OpenCycleTrainer MSI version $resolvedVersion"

    New-Item -ItemType Directory -Path $tmpRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $pyiBuildRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $wixObjRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $installerRoot -Force | Out-Null

    & $resolvedPythonExe -m pip install --upgrade pip
    & $resolvedPythonExe -m pip install -e ".[dev]" pyinstaller

    if (-not $SkipTests) {
        & $resolvedPythonExe -m pytest
    }

    & $resolvedPythonExe -m PyInstaller `
        --clean `
        --noconfirm `
        --distpath $distRoot `
        --workpath $pyiBuildRoot `
        $specPath

    if (-not (Test-Path (Join-Path $appDistRoot "OpenCycleTrainer.exe"))) {
        throw "PyInstaller output is missing: $appDistRoot\\OpenCycleTrainer.exe"
    }

    & heat dir $appDistRoot `
        -cg AppFiles `
        -dr INSTALLDIR `
        -var var.AppDistRoot `
        -gg `
        -sfrag `
        -srd `
        -scom `
        -sreg `
        -out $harvestPath

    & candle `
        -nologo `
        -arch x64 `
        -dAppVersion=$resolvedVersion `
        -dAppDistRoot=$appDistRoot `
        -out "$wixObjRoot\\" `
        $wxsPath `
        $harvestPath

    $msiPath = Join-Path $installerRoot "OpenCycleTrainer-$resolvedVersion-x64.msi"
    & light `
        -nologo `
        -out $msiPath `
        (Join-Path $wixObjRoot "OpenCycleTrainer.wixobj") `
        (Join-Path $wixObjRoot "AppFiles.wixobj")

    Write-Host "MSI created at: $msiPath"
}
finally {
    Pop-Location
}
