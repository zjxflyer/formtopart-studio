[CmdletBinding()]
param(
    [string]$Python = 'python',
    [string]$Pnpm = 'pnpm'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-BuildTool([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Program exited with code $LASTEXITCODE."
    }
}

Push-Location -LiteralPath $PSScriptRoot
try {
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) {
        throw 'The x64 .NET Framework C# compiler is required to build the Windows host.'
    }

    $pythonCheck = 'import struct, sys; assert sys.version_info[:2] == (3, 13) and struct.calcsize("P") == 8, "Use Python 3.13 x64"'
    Invoke-BuildTool $Python @('-c', $pythonCheck)
    $venvPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        Invoke-BuildTool $Python @('-m', 'venv', '.venv')
    }
    Invoke-BuildTool $venvPython @('-c', $pythonCheck)
    Invoke-BuildTool $venvPython @('-m', 'pip', 'install', '-r', 'requirements.txt')

    Invoke-BuildTool $Pnpm @('--dir', 'frontend', 'install', '--frozen-lockfile', '--registry=https://registry.npmjs.org')
    Invoke-BuildTool $Pnpm @('--dir', 'frontend', 'run', 'typecheck')
    Invoke-BuildTool $Pnpm @('--dir', 'frontend', 'run', 'build')
    Invoke-BuildTool $Pnpm @('--dir', 'frontend', 'run', 'build:portable')

    $sdkVersion = '1.0.4314.35'
    $sdkHash = '90778deb1b77e36292828b4b5833c9255c27533f40e0ddd55891ae718944edc4'
    $sdkPackage = Join-Path $PSScriptRoot "desktop-app/desktop-host/Microsoft.Web.WebView2.$sdkVersion.nupkg"
    if (-not (Test-Path -LiteralPath $sdkPackage -PathType Leaf)) {
        $download = "$sdkPackage.download"
        $sdkUrl = "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/$sdkVersion/microsoft.web.webview2.$sdkVersion.nupkg"
        Invoke-WebRequest -Uri $sdkUrl -OutFile $download -UseBasicParsing
        if ((Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash -ne $sdkHash) {
            throw 'The downloaded WebView2 SDK did not match the pinned SHA-256.'
        }
        Move-Item -LiteralPath $download -Destination $sdkPackage
    }
    if ((Get-FileHash -LiteralPath $sdkPackage -Algorithm SHA256).Hash -ne $sdkHash) {
        throw 'The cached WebView2 SDK did not match the pinned SHA-256.'
    }
    Invoke-BuildTool $venvPython @('desktop-app/tools/build_desktop_host.py')

    $versionFile = Join-Path $PSScriptRoot 'desktop-app/studio/server.py'
    $versionMatch = [regex]::Match((Get-Content -LiteralPath $versionFile -Raw), '(?m)^VERSION\s*=\s*"(\d+\.\d+\.\d+)"')
    if (-not $versionMatch.Success) { throw 'The Studio version could not be read from source.' }
    $name = 'FormToPart-Studio-v' + $versionMatch.Groups[1].Value + '-GitHub'
    Invoke-BuildTool $venvPython @('desktop-app/build_studio.py', '--github', '--github-sample-dir', 'desktop-app/public-sample', '--name', $name)
    Write-Output "Built desktop-app/dist/$name.exe"
}
finally {
    Pop-Location
}
