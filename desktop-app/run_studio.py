"""Windows desktop entry. Bundled backend + compiled UI, no development server."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from uuid import uuid4
import webbrowser

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(ROOT.parent / "backend" / ".deps"))

from studio.paths import filesystem_path


def desktop_window(pid, close=False):
    """Focus or close only the window belonging to this known owned host PID."""
    if os.name != "nt" or not isinstance(pid, int) or pid <= 0:
        return False
    import ctypes
    from ctypes import wintypes
    user = ctypes.windll.user32
    handles = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(handle, unused):
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(handle, ctypes.byref(owner))
        if owner.value == pid and user.IsWindowVisible(handle):
            handles.append(handle)
        return True
    user.EnumWindows(callback_type(collect), 0)
    for handle in handles:
        if close:
            user.PostMessageW(handle, 0x0010, 0, 0)  # WM_CLOSE, normal save/close path
        else:
            user.ShowWindow(handle, 9)
            user.SetForegroundWindow(handle)
    return bool(handles)


def desktop_host_running(pid):
    """Recognize a Studio host even while its window is still opening."""
    if os.name != "nt" or not isinstance(pid, int) or pid <= 0:
        return False
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.restype = wintypes.HANDLE
    handle = kernel.OpenProcess(0x101000, False, pid)  # synchronize + query limited information
    if not handle:
        return False
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        return bool(kernel.WaitForSingleObject(wintypes.HANDLE(handle), 0) == 258
                    and kernel.QueryFullProcessImageNameW(wintypes.HANDLE(handle), 0, buffer, ctypes.byref(length))
                    and Path(buffer.value).name.casefold() == "studiowindow.exe")
    finally:
        kernel.CloseHandle(wintypes.HANDLE(handle))


@contextmanager
def desktop_runtime_lock(runtime):
    """Serialize window claims and idle shutdown across native launchers."""
    if os.name != "nt":
        yield
        return
    import msvcrt
    with runtime.with_suffix(".desktop.lock").open("a+b") as lock:
        if lock.seek(0, os.SEEK_END) == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def owned_runtime(runtime, instance_id):
    try:
        state = json.loads(runtime.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) and state.get("instance_id") == instance_id else None


def write_runtime(runtime, state):
    temporary = runtime.with_suffix(f".{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(state), encoding="utf-8")
        os.replace(temporary, runtime)
    finally:
        temporary.unlink(missing_ok=True)


def release_desktop_claim(runtime, instance_id, pid):
    with desktop_runtime_lock(runtime):
        state = owned_runtime(runtime, instance_id)
        if state is not None and state.get("desktop_pid") == pid:
            state.pop("desktop_pid")
            write_runtime(runtime, state)


def active_group_draft(repository):
    from studio.repository import NotFound
    for item in repository.list():
        try:
            job = repository.get(item["id"]).get("active_job")
        except NotFound:
            continue
        if job and job.get("kind") == "generate3d" and job.get("draft_3d_group_id"):
            return True
    return False


def finish_native_runtime(runtime, instance_id, repository, shutdown, exiting):
    while not exiting():
        with desktop_runtime_lock(runtime):
            state = owned_runtime(runtime, instance_id)
            if state is not None and state.get("closing"):
                return
            if not (state and desktop_host_running(state.get("desktop_pid"))) and not active_group_draft(repository):
                if state is not None:
                    state["closing"] = True
                    write_runtime(runtime, state)
                shutdown()
                return
        time.sleep(0.5)


def start_desktop(url, profile, diagnostic=None, debug_port=0):
    host = ROOT / "desktop-host-dist" / "StudioWindow.exe"
    if not host.is_file():
        raise RuntimeError("Desktop host is missing; rebuild the desktop application")
    def native_path(value):
        path = str(Path(value).absolute()) if value else ""
        if path.startswith("\\\\?\\UNC\\"):
            return "\\\\" + path[8:]
        return path[4:] if path.startswith("\\\\?\\") else path
    return subprocess.Popen([str(host), url, native_path(profile), native_path(diagnostic), str(debug_port)],
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def fingerprint():
    if getattr(sys, "frozen", False):
        interface = ROOT / "ui-dist" / "studio.html"
        return hashlib.sha256(Path(sys.executable).read_bytes() + interface.read_bytes()).hexdigest()[:24]
    paths = [ROOT / "run_studio.py", *sorted((ROOT / "ui-dist").rglob("*")),
             *sorted((ROOT / "studio").glob("*.py")), *sorted((ROOT / "studio" / "prompts").rglob("*")),
             ROOT / "desktop-host-dist" / "StudioWindow.exe"]
    return hashlib.sha256(b"".join(p.read_bytes() for p in paths if p.is_file())).hexdigest()[:24]


def open_key_setup(github_data_root=None):
    command = [sys.executable, "--key-setup"] if getattr(sys, "frozen", False) else [sys.executable, str(ROOT / "run_studio.py"), "--key-setup"]
    if github_data_root is not None:
        command.extend(["--github-distribution", "--data-dir", str(github_data_root)])
    subprocess.Popen(command, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-setup", action="store_true")
    parser.add_argument("--no-browser", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--browser", action="store_true", help=argparse.SUPPRESS)
    assistant_mode = parser.add_mutually_exclusive_group()
    assistant_mode.add_argument("--enable-ai", dest="enable_ai", action="store_true", default=True,
                                help=argparse.SUPPRESS)
    assistant_mode.add_argument("--offline", dest="enable_ai", action="store_false",
                                help="Disable external assistant requests for local verification")
    parser.add_argument("--native-drafting", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--legacy-analysis", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--legacy-workspace", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--github-distribution", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--github-sample-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--desktop-diagnostic-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--desktop-debug-port", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--data-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--ready-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--native-self-test-output", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--import-diagnostic-file", type=Path,
                        default=os.environ.get("VWC_IMPORT_DIAGNOSTIC_FILE"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 0 <= args.desktop_debug_port <= 65535:
        parser.error("Invalid desktop diagnostic port")
    if args.native_self_test_output:
        from studio.native_check import run_native_check
        return run_native_check(filesystem_path(args.native_self_test_output))
    if args.ready_file:
        args.ready_file = filesystem_path(args.ready_file)
    if args.import_diagnostic_file:
        args.import_diagnostic_file = filesystem_path(args.import_diagnostic_file)
    from credentials import CredentialStore
    github_distribution = args.github_distribution or (ROOT / "github-distribution.tag").is_file()
    reference_demo_mode = github_distribution or not args.legacy_workspace
    github_sample_root = args.github_sample_dir
    if github_distribution and github_sample_root is None:
        github_sample_root = ROOT if getattr(sys, "frozen", False) else ROOT / "public-sample"
    profile = "CabinetStudioGitHub" if github_distribution else "CabinetStudio"
    data_root = filesystem_path(args.data_dir or CredentialStore().directory.parent / profile / "projects")
    credential_directory = data_root.parent / "credentials" if github_distribution else None
    if args.key_setup:
        from key_setup import main as setup_main
        sys.argv = [sys.argv[0]]
        if credential_directory is not None:
            sys.argv.extend(["--credential-dir", str(credential_directory)])
        return setup_main()
    from studio.repository import Repository
    from studio.server import APPLICATION, VERSION, create_app
    import uvicorn
    data_root.mkdir(parents=True, exist_ok=True)
    runtime = data_root.parent / "runtime.json"
    build_id = fingerprint()
    store_id = hashlib.sha256(str(data_root).encode()).hexdigest()
    try:
        previous = json.loads(runtime.read_text(encoding="utf-8"))
        url = f"http://127.0.0.1:{int(previous['port'])}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + "/api/studio/health", timeout=1.5) as response:
            identity = json.load(response)
        if (identity.get("application") == APPLICATION and identity.get("build_id") == build_id
                and identity.get("project_store") == store_id and identity.get("instance_id") == previous.get("instance_id")
                and identity.get("reference_demo_mode", False) == reference_demo_mode
                and identity.get("github_distribution", False) == github_distribution
                and identity.get("ai_enabled", True) == args.enable_ai
                and identity.get("ai_design_mode", "native") == ("autonomous_2d" if not args.legacy_analysis else "native" if args.native_drafting else "model")):
            window = None
            with desktop_runtime_lock(runtime):
                state = owned_runtime(runtime, previous["instance_id"])
                if state is None or state.get("closing"):
                    raise ValueError("Runtime is closing")
                if not args.no_browser and not args.browser:
                    pid = state.get("desktop_pid")
                    if desktop_host_running(pid):
                        desktop_window(pid)
                    else:
                        window = start_desktop(url, data_root.parent / "desktop-profile", args.desktop_diagnostic_file, args.desktop_debug_port)
                        state["desktop_pid"] = window.pid
                        write_runtime(runtime, state)
                if args.ready_file:
                    args.ready_file.parent.mkdir(parents=True, exist_ok=True)
                    args.ready_file.write_text(json.dumps(state), encoding="utf-8")
            if args.browser and not args.no_browser:
                webbrowser.open(url, new=0)
            if window is not None:
                window.wait()
                release_desktop_claim(runtime, state["instance_id"], window.pid)
                if not state.get("native_owner"):
                    def shutdown_attached():
                        request = urllib.request.Request(url + "/api/studio/shutdown", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
                        try:
                            with opener.open(request, timeout=5):
                                pass
                        except OSError:
                            pass
                    finish_native_runtime(runtime, state["instance_id"], Repository(data_root), shutdown_attached,
                                          lambda: owned_runtime(runtime, state["instance_id"]) is None)
            return 0
    except (OSError, ValueError, KeyError, TypeError):
        pass
    # A foreign/stale listener is never killed or adopted. Use a fresh loopback port.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", args.port))
    sock.listen(128)
    port = sock.getsockname()[1]
    instance_id = uuid4().hex
    server = None
    desktop = None
    desktop_error = False
    def shutdown():
        if server is not None:
            server.should_exit = True
    def import_diagnostic(report):
        args.import_diagnostic_file.parent.mkdir(parents=True, exist_ok=True)
        args.import_diagnostic_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    app = create_app(data_root, on_shutdown=shutdown,
                     on_key_setup=lambda: open_key_setup(data_root if github_distribution else None),
                     instance_id=instance_id, build_id=build_id,
                     allow_ai=args.enable_ai,
                     native_drafting=args.native_drafting,
                     autonomous_2d=not args.legacy_analysis,
                     reference_demo_mode=reference_demo_mode,
                     github_distribution=github_distribution, github_sample_root=github_sample_root,
                     credential_directory=credential_directory,
                     on_import_diagnostic=import_diagnostic if args.import_diagnostic_file else None)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None,
                            access_log=False, loop="asyncio", http="h11", lifespan="on",
                            timeout_graceful_shutdown=5)
    server = uvicorn.Server(config)
    state = {"application": APPLICATION, "version": VERSION, "port": port,
             "instance_id": instance_id, "build_id": build_id, "pid": os.getpid(), "ai_enabled": args.enable_ai,
             "reference_demo_mode": reference_demo_mode, "github_distribution": github_distribution,
             "native_owner": not args.no_browser and not args.browser}
    state["ai_design_mode"] = "autonomous_2d" if not args.legacy_analysis else "native" if args.native_drafting else "model"
    def ready():
        nonlocal desktop, desktop_error
        for _ in range(100):
            if server.started:
                try:
                    with desktop_runtime_lock(runtime):
                        if state["native_owner"]:
                            desktop = start_desktop(f"http://127.0.0.1:{port}", data_root.parent / "desktop-profile", args.desktop_diagnostic_file, args.desktop_debug_port)
                            state["desktop_pid"] = desktop.pid
                        write_runtime(runtime, state)
                        if args.ready_file:
                            args.ready_file.parent.mkdir(parents=True, exist_ok=True)
                            args.ready_file.write_text(json.dumps(state), encoding="utf-8")
                    if args.browser and not args.no_browser:
                        webbrowser.open(f"http://127.0.0.1:{port}", new=0)
                    if desktop is not None:
                        desktop_error = desktop.wait() != 0
                        release_desktop_claim(runtime, instance_id, desktop.pid)
                        finish_native_runtime(runtime, instance_id, app.state.repository, shutdown,
                                              lambda: server.should_exit)
                except Exception:
                    desktop_error = True
                    shutdown()
                return
            time.sleep(0.1)
    threading.Thread(target=ready, daemon=True).start()
    try:
        server.run(sockets=[sock])
    finally:
        sock.close()
        try:
            with desktop_runtime_lock(runtime):
                current = owned_runtime(runtime, instance_id)
                if current is not None:
                    pid = current.get("desktop_pid")
                    if desktop_host_running(pid):
                        desktop_window(pid, close=True)
                    runtime.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
        if desktop is not None and desktop.poll() is None:
            desktop_window(desktop.pid, close=True)
            try:
                desktop.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
    return 1 if desktop_error else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        if "--no-browser" in sys.argv:
            if "--ready-file" in sys.argv:
                position = sys.argv.index("--ready-file")
                if position + 1 < len(sys.argv):
                    report = filesystem_path(sys.argv[position + 1]).with_suffix(".error.json")
                    report.parent.mkdir(parents=True, exist_ok=True)
                    report.write_text(json.dumps({"success": False, "error_type": type(error).__name__}), encoding="utf-8")
            raise SystemExit(1) from None
        elif getattr(sys, "frozen", False):
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("FormToPart Studio",
                f"The application could not start ({type(error).__name__}).\n应用无法启动（{type(error).__name__}）。\nPlease check available disk space and try reopening the application.\n请检查可用磁盘空间，然后重新打开应用。")
            root.destroy()
        else:
            raise
