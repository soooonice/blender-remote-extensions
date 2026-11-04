
@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

set "ROOT=%CD%"
set "ADDONS=%ROOT%\addons"
set "OUTPUT=%ROOT%\docs"
set "PS_SCRIPT=%TEMP%\quick_extensions_build_%RANDOM%_%RANDOM%.ps1"

if not exist "%ADDONS%\" (
    echo [ERROR] addons folder not found.
    pause
    exit /b 1
)

REM Extract embedded PowerShell script
powershell -NoProfile -Command ^
  "$src=Get-Content -LiteralPath '%~f0';" ^
  "$marker=':POWERSHELL_SCRIPT';" ^
  "$i=[Array]::IndexOf($src,$marker);" ^
  "if($i -lt 0){exit 1};" ^
  "$src[($i+1)..($src.Length-1)] | Set-Content -LiteralPath $env:PS_SCRIPT -Encoding UTF8"

if errorlevel 1 (
    echo [ERROR] Cannot extract PowerShell script.
    pause
    exit /b 1
)

powershell -NoProfile -STA -ExecutionPolicy Bypass -File "%PS_SCRIPT%"
set "RESULT=%ERRORLEVEL%"

del /q "%PS_SCRIPT%" >nul 2>&1

echo.
if "%RESULT%"=="0" (
    echo [SUCCESS] Extension repository updated.
) else (
    echo [FAILED] Build or repository update failed.
)

pause
exit /b %RESULT%

:POWERSHELL_SCRIPT
$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$root = $env:ROOT
$addons = $env:ADDONS
$output = $env:OUTPUT

function Read-Manifest {
    param([string]$Path)

    $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8

    $idMatch = [regex]::Match(
        $text,
        '(?m)^\s*id\s*=\s*"([^"]+)"'
    )

    $versionMatch = [regex]::Match(
        $text,
        '(?m)^\s*version\s*=\s*"([^"]+)"'
    )

    if (!$idMatch.Success -or !$versionMatch.Success) {
        throw "Cannot read id/version: $Path"
    }

    return @{
        Id = $idMatch.Groups[1].Value
        Version = $versionMatch.Groups[1].Value
    }
}

function Read-ZipManifest {
    param([string]$ZipPath)

    $zip = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)

    try {
        $entry = $zip.Entries |
            Where-Object { $_.FullName -eq 'blender_manifest.toml' } |
            Select-Object -First 1

        if (!$entry) {
            return $null
        }

        $reader = [System.IO.StreamReader]::new($entry.Open())

        try {
            $text = $reader.ReadToEnd()
        }
        finally {
            $reader.Dispose()
        }

        $match = [regex]::Match(
            $text,
            '(?m)^\s*id\s*=\s*"([^"]+)"'
        )

        if ($match.Success) {
            return $match.Groups[1].Value
        }

        return $null
    }
    finally {
        $zip.Dispose()
    }
}

try {
    Write-Host "========================================"
    Write-Host "     Blender Extension Repository"
    Write-Host "========================================"
    Write-Host ""

    # 1. Select Blender
    $fileDialog = New-Object System.Windows.Forms.OpenFileDialog
    $fileDialog.Title = "Select Blender executable"
    $fileDialog.Filter = "Blender (blender.exe)|blender.exe"

    if ($fileDialog.ShowDialog() -ne 'OK') {
        throw "Blender selection cancelled."
    }

    $blender = $fileDialog.FileName

    # 2. Select extension folder
    $folderDialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $folderDialog.Description = "Select an extension folder inside addons"
    $folderDialog.SelectedPath = $addons

    if ($folderDialog.ShowDialog() -ne 'OK') {
        throw "Extension selection cancelled."
    }

    $source = (Resolve-Path -LiteralPath $folderDialog.SelectedPath).Path

    $parent = Split-Path -Parent $source

    if ($parent.TrimEnd('\') -ine $addons.TrimEnd('\')) {
        throw "The extension must be directly inside addons."
    }

    $manifestPath = Join-Path $source 'blender_manifest.toml'

    if (!(Test-Path -LiteralPath $manifestPath)) {
        throw "blender_manifest.toml not found."
    }

    $manifest = Read-Manifest $manifestPath
    $extensionId = $manifest.Id
    $version = $manifest.Version

    Write-Host ""
    Write-Host "Extension: $extensionId"
    Write-Host "Version:   $version"
    Write-Host ""

    New-Item -ItemType Directory -Force -Path $output | Out-Null

    # 3. Build into a temporary staging folder
    $staging = Join-Path $env:TEMP (
        "blender_ext_stage_" + [guid]::NewGuid().ToString('N')
    )

    New-Item -ItemType Directory -Path $staging | Out-Null

    try {
        Write-Host "[1/3] Building extension..."

        & $blender --command extension build `
            --source-dir $source `
            --output-dir $staging

        if ($LASTEXITCODE -ne 0) {
            throw "Extension build failed."
        }

        $packages = @(Get-ChildItem -LiteralPath $staging -Filter '*.zip' -File)

        if ($packages.Count -ne 1) {
            throw "Expected exactly one generated ZIP."
        }

        $newPackage = $packages[0]

        if ((Read-ZipManifest $newPackage.FullName) -ne $extensionId) {
            throw "Generated ZIP has an unexpected extension ID."
        }

        # 4. Identify old packages
        $oldPackages = @(
            Get-ChildItem -LiteralPath $output -Filter '*.zip' -File |
                Where-Object {
                    (Read-ZipManifest $_.FullName) -eq $extensionId
                }
        )

        # Backup existing index and packages
        $backup = Join-Path $staging 'backup'
        New-Item -ItemType Directory -Path $backup | Out-Null

        $indexFiles = @('index.json', 'index.html')
        $backedUpIndexes = @()

        foreach ($name in $indexFiles) {
            $path = Join-Path $output $name
            if (Test-Path -LiteralPath $path) {
                Copy-Item -LiteralPath $path -Destination $backup
                $backedUpIndexes += $name
            }
        }

        $movedPackages = @()
        $installedPackage = $null

        try {
            Write-Host "[2/3] Replacing old version..."

            foreach ($package in $oldPackages) {
                Move-Item -LiteralPath $package.FullName -Destination $backup
                $movedPackages += $package.Name
                Write-Host "Archived: $($package.Name)"
            }

            $installedPackage = Join-Path $output $newPackage.Name

            Copy-Item -LiteralPath $newPackage.FullName `
                -Destination $installedPackage

            Write-Host "[3/3] Generating repository index..."

            & $blender --command extension server-generate `
                --repo-dir $output --html

            if ($LASTEXITCODE -ne 0) {
                throw "Repository index generation failed."
            }

            Write-Host ""
            Write-Host "BUILD SUCCESSFUL" -ForegroundColor Green
            Write-Host "Extension: $extensionId"
            Write-Host "Version:   $version"
            Write-Host "Package:   $installedPackage"
            Write-Host "Index:     $(Join-Path $output 'index.json')"
        }
        catch {
            Write-Host "Restoring previous repository state..."

            if ($installedPackage -and
                (Test-Path -LiteralPath $installedPackage)) {
                Remove-Item -LiteralPath $installedPackage -Force
            }

            foreach ($name in $movedPackages) {
                Move-Item -LiteralPath (Join-Path $backup $name) `
                    -Destination $output -Force
            }

            foreach ($name in $indexFiles) {
                $target = Join-Path $output $name

                if ($name -in $backedUpIndexes) {
                    Copy-Item -LiteralPath (Join-Path $backup $name) `
                        -Destination $target -Force
                }
                elseif (Test-Path -LiteralPath $target) {
                    Remove-Item -LiteralPath $target -Force
                }
            }

            throw
        }
    }
    finally {
        if (Test-Path -LiteralPath $staging) {
            Remove-Item -LiteralPath $staging -Recurse -Force
        }
    }
}
catch {
    Write-Host ""
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

exit 0
