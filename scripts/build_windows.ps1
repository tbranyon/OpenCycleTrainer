<#
.SYNOPSIS
    Build the OpenCycleTrainer Windows installer (MSI) with one command.

.DESCRIPTION
    Fetches what it needs (uv, Python, PyInstaller and WiX 3) into build\, brings the
    locked dependencies up to date, runs the tests, freezes the app with PyInstaller
    and packages it with WiX. Only PowerShell and an internet connection are required.

    Output: dist\OpenCycleTrainer-<version>-x64.msi

.PARAMETER Upgrade
    Upgrade every dependency to the newest version pyproject.toml allows (rewrites uv.lock).

.PARAMETER SkipTests
    Skip the test suite.

.EXAMPLE
    scripts\build_windows.cmd -Upgrade
#>
param(
    [switch]$Upgrade,
    [switch]$SkipTests
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
# The progress bar makes Invoke-WebRequest many times slower on Windows PowerShell 5.1.
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$PythonVersion = "3.13"
$UvVersion = "0.13.7"
$UvWheelUrl = "https://files.pythonhosted.org/packages/8e/4f/041b59d2a38807a3e31ef41064cf3e45d2752fe0409d89040d52778049ae/uv-0.13.7-py3-none-win_amd64.whl"
$UvWheelSha256 = "2835e2ab397d0db86323b9975dce75ecd76aa9cfa0d6a2aea84734aae7f8c9b3"
$WixVersion = "3.14.1"
$WixPackageUrl = "https://api.nuget.org/v3-flatcontainer/wix/3.14.1/wix.3.14.1.nupkg"
$WixPackageSha256 = "15d50463c73dce31fbea5440ac33af47e92d54d4188166d207e9e39577b8fe0f"
$AppName = "OpenCycleTrainer"
$VersionScript = "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PackagingDir = Join-Path $RepoRoot "packaging\windows"
$BuildRoot = Join-Path $RepoRoot "build\windows"
$ToolsRoot = Join-Path $RepoRoot "build\tools"
$DistRoot = Join-Path $RepoRoot "dist"
$FrozenRoot = Join-Path $BuildRoot "app"
$AppDir = Join-Path $FrozenRoot $AppName
$WixObjDir = Join-Path $BuildRoot "wixobj"

function Write-Step {
    <# Print a build stage heading. #>
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Tool {
    <# Run a native command, returning its output, and stop the build if it fails. #>
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$ArgumentList = @()
    )
    # Windows PowerShell turns a tool's stderr progress output into terminating errors
    # under "Stop", so the exit code is checked instead.
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $FilePath @ArgumentList
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($LASTEXITCODE -ne 0) {
        throw "'$FilePath $($ArgumentList -join ' ')' failed with exit code $LASTEXITCODE."
    }
}

function Reset-Directory {
    <# Create an empty directory, deleting anything already there. #>
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
}

function Install-ZipTool {
    <# Download a zip archive, check its SHA-256 and unpack it into a directory. #>
    param(
        [string]$Url,
        [string]$Sha256,
        [string]$Destination
    )
    New-Item -ItemType Directory -Path $ToolsRoot -Force | Out-Null
    # Expand-Archive in Windows PowerShell only accepts the .zip extension.
    $archive = Join-Path $ToolsRoot ((Split-Path $Destination -Leaf) + ".zip")
    Write-Host "Downloading $Url"
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $archive
    $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
    if ($actual -ne $Sha256) {
        Remove-Item -LiteralPath $archive -Force
        throw "Checksum mismatch for $Url (expected $Sha256, got $actual)."
    }
    Reset-Directory $Destination
    Expand-Archive -LiteralPath $archive -DestinationPath $Destination -Force
    Remove-Item -LiteralPath $archive -Force
}

function Get-Uv {
    <# Return uv from PATH, or a pinned copy downloaded into build\tools. #>
    $onPath = Get-Command uv -ErrorAction SilentlyContinue
    if ($onPath) {
        return $onPath.Source
    }
    $uvDir = Join-Path $ToolsRoot "uv-$UvVersion"
    $uvExe = Join-Path $uvDir "uv-$UvVersion.data\scripts\uv.exe"
    if (-not (Test-Path -LiteralPath $uvExe)) {
        Install-ZipTool -Url $UvWheelUrl -Sha256 $UvWheelSha256 -Destination $uvDir
    }
    return $uvExe
}

function Get-WixToolsDir {
    <# Return the folder holding heat, candle and light from a pinned WiX download. #>
    $wixDir = Join-Path $ToolsRoot "wix-$WixVersion"
    $toolsDir = Join-Path $wixDir "tools"
    if (-not (Test-Path -LiteralPath (Join-Path $toolsDir "light.exe"))) {
        Install-ZipTool -Url $WixPackageUrl -Sha256 $WixPackageSha256 -Destination $wixDir
    }
    return $toolsDir
}

Push-Location $RepoRoot
try {
    # Keep the build's environment apart from any development .venv.
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $BuildRoot "venv"
    $env:UV_PYTHON = $PythonVersion
    $uv = Get-Uv

    Write-Step "Updating dependencies"
    if ($Upgrade) {
        Invoke-Tool $uv @("lock", "--upgrade")
    }
    else {
        Invoke-Tool $uv @("lock")
    }
    Invoke-Tool $uv @("sync", "--locked", "--extra", "dev", "--group", "windows-build")

    if (-not $SkipTests) {
        Write-Step "Running tests"
        Invoke-Tool $uv @("run", "--no-sync", "python", "-m", "pytest")
    }

    $version = ((Invoke-Tool $uv @("run", "--no-sync", "python", "-c", $VersionScript)) | Select-Object -Last 1).Trim()

    Write-Step "Freezing OpenCycleTrainer $version with PyInstaller"
    Invoke-Tool $uv @(
        "run", "--no-sync", "python", "-m", "PyInstaller",
        "--clean", "--noconfirm",
        "--distpath", $FrozenRoot,
        "--workpath", (Join-Path $BuildRoot "pyinstaller"),
        (Join-Path $PackagingDir "opencycletrainer.spec")
    )
    if (-not (Test-Path -LiteralPath (Join-Path $AppDir "$AppName.exe"))) {
        throw "PyInstaller output is missing: $AppDir\$AppName.exe"
    }

    Write-Step "Packaging the MSI with WiX $WixVersion"
    $wixTools = Get-WixToolsDir
    Reset-Directory $WixObjDir
    $harvestWxs = Join-Path $WixObjDir "AppFiles.wxs"
    $productObj = Join-Path $WixObjDir "OpenCycleTrainer.wixobj"
    $harvestObj = Join-Path $WixObjDir "AppFiles.wixobj"
    $msiPath = Join-Path $DistRoot "$AppName-$version-x64.msi"

    Invoke-Tool (Join-Path $wixTools "heat.exe") @(
        "dir", $AppDir, "-nologo",
        "-cg", "AppFiles", "-dr", "INSTALLDIR", "-var", "var.AppDistRoot",
        "-gg", "-sfrag", "-srd", "-scom", "-sreg",
        "-out", $harvestWxs
    )
    $candleArgs = @("-nologo", "-arch", "x64", "-dAppVersion=$version", "-dAppDistRoot=$AppDir")
    Invoke-Tool (Join-Path $wixTools "candle.exe") ($candleArgs + @("-out", $productObj, (Join-Path $PackagingDir "OpenCycleTrainer.wxs")))
    Invoke-Tool (Join-Path $wixTools "candle.exe") ($candleArgs + @("-out", $harvestObj, $harvestWxs))
    New-Item -ItemType Directory -Path $DistRoot -Force | Out-Null
    Invoke-Tool (Join-Path $wixTools "light.exe") @("-nologo", "-out", $msiPath, $productObj, $harvestObj)

    Write-Step "MSI created at: $msiPath"
}
finally {
    Pop-Location
}
