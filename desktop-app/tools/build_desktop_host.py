"""Build a small .NET Framework Windows host from Microsoft's pinned WebView2 SDK."""
from pathlib import Path
import hashlib
import io
import json
import os
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SDK_VERSION = "1.0.4314.35"
URL = f"https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/{SDK_VERSION}/microsoft.web.webview2.{SDK_VERSION}.nupkg"


def main():
    source = ROOT / "desktop-host"
    output = ROOT / "desktop-host-dist"
    output.mkdir(exist_ok=True)
    package = source / f"Microsoft.Web.WebView2.{SDK_VERSION}.nupkg"
    if not package.exists():
        with urllib.request.urlopen(URL, timeout=90) as response:
            data = response.read(60 * 1024 * 1024 + 1)
        if len(data) > 60 * 1024 * 1024:
            raise ValueError("Unexpected SDK size")
        package.write_bytes(data)
    data = package.read_bytes()
    selected = {
        "lib/net462/Microsoft.Web.WebView2.Core.dll": "Microsoft.Web.WebView2.Core.dll",
        "lib/net462/Microsoft.Web.WebView2.WinForms.dll": "Microsoft.Web.WebView2.WinForms.dll",
        "runtimes/win-x64/native/WebView2Loader.dll": "WebView2Loader.dll",
        "LICENSE.txt": "WebView2-SDK-LICENSE.txt",
    }
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name, destination in selected.items():
            (output / destination).write_bytes(archive.read(name))
    compiler = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    command = [str(compiler), "/nologo", "/target:winexe", "/platform:x64", "/optimize+",
               "/out:" + str(output / "StudioWindow.exe"),
               "/win32manifest:" + str(source / "StudioWindow.exe.manifest"),
               "/win32icon:" + str(source / "Studio.ico"),
               "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll", "/r:System.Net.Http.dll",
               "/r:" + str(output / "Microsoft.Web.WebView2.Core.dll"),
               "/r:" + str(output / "Microsoft.Web.WebView2.WinForms.dll"),
               str(source / "StudioWindow.cs")]
    subprocess.run(command, check=True)
    (output / "StudioWindow.exe.config").write_text('<?xml version="1.0"?><configuration><startup><supportedRuntime version="v4.0" sku=".NETFramework,Version=v4.8"/></startup><runtime><AppContextSwitchOverrides value="Switch.System.Windows.Forms.DoNotSupportDpiChanges=false"/></runtime></configuration>', encoding="utf-8")
    receipt = {"sdk_version": SDK_VERSION, "sdk_url": URL, "sdk_sha256": hashlib.sha256(data).hexdigest(),
               "host": "Windows Forms / WebView2; embedded web interface, no external browser",
               "files": {path.name: {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in output.iterdir() if path.is_file() and path.suffix != ".json"}}
    (output / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"built": True, "sdk_version": SDK_VERSION, "host_bytes": (output / "StudioWindow.exe").stat().st_size}))


if __name__ == "__main__":
    main()
