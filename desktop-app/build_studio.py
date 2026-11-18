"""Reproducible Windows build with the explicitly supplied demonstration sources."""
from pathlib import Path
import argparse
import os
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def github_bundle_assets(sample_root):
    from studio.reference_demo import load_github_sample, load_manifest
    _, archive = load_github_sample(sample_root)
    _, reference_root, reference_assets = load_manifest(sample_root)
    return [(archive.parent / "showcase.json", "showcase"), (archive, "showcase"),
            *[(reference_root / name, "reference-demo")
              for name in ("reference-demo.json", *sorted(reference_assets))]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--onedir", action="store_true", help="Development packaging only")
    parser.add_argument("--name", default="VWC-Cabinet-Studio", help="Executable name, for example VWC-Cabinet-Studio-v0.3.0")
    parser.add_argument("--ui-dir", type=Path, default=ROOT / "ui-dist", help="Compiled Studio interface to bundle")
    parser.add_argument("--github", action="store_true", help="Build the isolated public sample edition")
    parser.add_argument("--github-sample-dir", type=Path, default=ROOT / "public-sample",
                        help="Sanitized public sample inputs for --github")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", args.name):
        parser.error("--name must contain 1-100 letters, digits, dots, underscores or hyphens")
    ui_dir = args.ui_dir.resolve()
    if not (ui_dir / "studio.html").is_file():
        raise RuntimeError("Compile the studio frontend before packaging")
    if not (ROOT / "desktop-host-dist" / "StudioWindow.exe").is_file():
        raise RuntimeError("Compile the desktop host before packaging")
    destination = (ROOT / "dist" / args.name).resolve()
    if not destination.is_relative_to(ROOT.resolve()) or destination == ROOT.resolve():
        raise RuntimeError("Build output must remain inside desktop-app")
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir" if args.onedir else "--onefile", "--windowed",
               "--icon", str(ROOT / "desktop-host" / "Studio.ico"),
               "--name", args.name, "--distpath", str(ROOT / "dist"),
               "--workpath", str(ROOT / "build" / args.name), "--specpath", str(ROOT / "build"),
               "--paths", str(ROOT.parent / "backend" / ".deps"),
               "--collect-data", "pypdfium2", "--collect-all", "pypdfium2_raw",
               "--collect-data", "pdfminer", "--collect-data", "reportlab",
               "--collect-submodules", "reportlab.pdfbase",
               "--hidden-import", "pdfplumber", "--hidden-import", "pdfminer.cmapdb",
               "--hidden-import", "reportlab.pdfgen.canvas", "--hidden-import", "reportlab.pdfbase._fontdata",
               "--exclude-module", "numpy", "--exclude-module", "pandas",
               "--exclude-module", "matplotlib", "--exclude-module", "scipy",
               "--exclude-module", "torch", "--exclude-module", "pytest",
               "--collect-data", "certifi", "--hidden-import", "uvicorn.logging",
               "--copy-metadata", "openpyxl", "--copy-metadata", "et_xmlfile",
               "--hidden-import", "uvicorn.loops.asyncio", "--hidden-import", "uvicorn.protocols.http.h11_impl",
               "--hidden-import", "uvicorn.lifespan.on", "--hidden-import", "python_multipart",
               "--add-data", str(ui_dir) + ";ui-dist",
               "--add-data", str(ROOT / "desktop-host-dist") + ";desktop-host-dist",
               "--add-data", str(ROOT / "portable-dist" / "portable.js") + ";assets",
               str(ROOT / "run_studio.py")]
    if args.github:
        assets = github_bundle_assets(args.github_sample_dir.resolve())
        marker = ROOT / "build" / args.name / "github-distribution.tag"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("FormToPart Studio GitHub edition\n", encoding="utf-8")
        assets.append((marker, "."))
    else:
        assets = [(ROOT / "demo" / "sources", "demo/sources"),
                  (ROOT / "examples" / "A202-Vanity-Pilot.vwc", "demo")]
        reviewed_demo = ROOT / "examples" / "A200-A202-Reviewed.vwc"
        if reviewed_demo.is_file():
            assets.append((reviewed_demo, "demo"))
        for folder in ("showcase", "reference-demo"):
            root = ROOT / folder
            if (root / f"{folder}.json").is_file():
                assets.append((root, folder))
    for path, target in assets:
        command[-1:-1] = ["--add-data", f"{path};{target}"]
    prompts = ROOT / "studio" / "prompts"
    if prompts.is_dir():
        command[-1:-1] = ["--add-data", str(prompts) + ";studio/prompts"]
    environment = os.environ.copy()
    dependencies = str(ROOT.parent / "backend" / ".deps")
    environment["PYTHONPATH"] = dependencies + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
    subprocess.run(command, cwd=ROOT, env=environment, check=True)


if __name__ == "__main__":
    main()
