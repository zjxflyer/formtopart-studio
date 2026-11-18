"""Private desktop entry point for API credentials; no key is returned to a browser."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import urllib.error
import urllib.request

from credentials import CredentialStore, CredentialError, MODELS, DEFAULT_MODEL, safe_status

APP_VERSION = "0.1.1"


def check_connection(key: str, model: str) -> tuple[bool, str]:
    """Read model access only. Never include response bodies or request headers in errors."""
    try:
        request = urllib.request.Request("https://api.openai.com/v1/models",
            headers={"Authorization": "Bearer " + key, "Accept": "application/json",
                     "User-Agent": "VWC-Key-Setup/1.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
        available = {item.get("id") for item in result.get("data", []) if isinstance(item, dict)}
        if model in available:
            return True, "Connection verified; selected model is listed.\n连接成功，账户可见所选模型。"
        return False, "Key accepted, but this account does not list the selected model.\n密钥有效，但此账户未列出所选模型。"
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            return False, "Key or account access was rejected. Check your API project.\n密钥或账户权限被拒绝，请检查 API 项目。"
        if error.code == 429:
            return False, "OpenAI returned a usage or rate limit. Please try later.\nOpenAI 返回用量或速率限制，请稍后重试。"
        return False, f"OpenAI connection failed (HTTP {error.code}).\nOpenAI 连接失败（HTTP {error.code}）。"
    except (urllib.error.URLError, TimeoutError, OSError):
        return False, "Could not reach OpenAI. Check your network and try again.\n无法连接 OpenAI，请检查网络后重试。"
    except (ValueError, AttributeError, TypeError):
        return False, "OpenAI returned an unexpected response. Please try again.\nOpenAI 返回了非预期响应，请重试。"


class KeySetup:
    def __init__(self, root: tk.Tk, store: CredentialStore):
        self.root, self.store = root, store
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        root.title(f"Vancouver Wood Carving · Key Setup {APP_VERSION} / 密钥设置")
        root.configure(bg="#f3f5f7")
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#f3f5f7")
        style.configure("TLabel", background="#f3f5f7", foreground="#22313f", font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"), foreground="#133e36")
        style.configure("Sub.TLabel", foreground="#536774")
        style.configure("TButton", font=("Segoe UI", 10), padding=(12, 10))
        style.configure("Accent.TButton", foreground="white", background="#216654")
        style.map("Accent.TButton", background=[("active", "#194e41"), ("disabled", "#8da79f")])
        style.configure("TCheckbutton", background="#f3f5f7", font=("Segoe UI", 10))
        style.configure("TCombobox", padding=7, font=("Segoe UI", 10))
        shell = ttk.Frame(root)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)
        canvas = tk.Canvas(shell, background="#f3f5f7", highlightthickness=0)
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        horizontal = ttk.Scrollbar(shell, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set)
        scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        canvas.grid(row=0, column=0, sticky="nsew")
        outer = ttk.Frame(canvas, padding=28)
        content_window = canvas.create_window((0, 0), window=outer, anchor="nw")
        outer.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(content_window,
            width=max(event.width, outer.winfo_reqwidth())))
        def scroll(event):
            if outer.winfo_height() > canvas.winfo_height():
                canvas.yview_scroll(-int(event.delta / 120), "units")
        root.bind_all("<MouseWheel>", scroll)
        outer.columnconfigure(0, weight=1)
        ttk.Label(outer, text="Connect your design assistant", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(outer, text="连接你的设计助手", font=("Microsoft YaHei UI", 13)).grid(row=1, column=0, sticky="w", pady=(3, 14))
        ttk.Label(outer, text="Your key is encrypted for this Windows account and stored locally.\n密钥使用当前 Windows 账户加密，仅保存在本机。", style="Sub.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 18))
        ttk.Label(outer, text="OpenAI API key / OpenAI API 密钥").grid(row=3, column=0, sticky="w")
        self.key = tk.StringVar()
        self.entry = ttk.Entry(outer, textvariable=self.key, show="•", font=("Segoe UI", 12))
        self.entry.grid(row=4, column=0, sticky="ew", pady=(7, 5), ipady=5)
        self.show = tk.BooleanVar(value=False)
        self.show_check = ttk.Checkbutton(outer, text="Show typed key / 显示输入的密钥", variable=self.show,
            command=lambda: self.entry.configure(show="" if self.show.get() else "•"))
        self.show_check.grid(row=5, column=0, sticky="w")
        ttk.Label(outer, text="Model / 模型").grid(row=6, column=0, sticky="w", pady=(18, 6))
        self.saved_model = store.load_settings()["model"]
        self.model = tk.StringVar(value=self.saved_model)
        self.combo = ttk.Combobox(outer, textvariable=self.model, values=MODELS, state="readonly")
        self.combo.grid(row=7, column=0, sticky="ew")
        ttk.Label(outer, text="Reasoning: High / 推理强度：高", style="Sub.TLabel").grid(row=8, column=0, sticky="w", pady=(5, 13))
        self.status = tk.StringVar(value=("A key is already saved. Leave the field empty to keep it.\n已保存密钥；保留输入框为空即可继续使用。" if store.has_key()
            else "No key saved yet. Paste your key above.\n尚未保存密钥，请在上方粘贴。"))
        self.status_label = ttk.Label(outer, textvariable=self.status, wraplength=590, justify="left")
        self.status_label.grid(row=9, column=0, sticky="ew", pady=(0, 14))
        actions = ttk.Frame(outer)
        actions.grid(row=10, column=0, sticky="ew")
        self.save_button = ttk.Button(actions, text="Save / 保存", command=self.save, style="Accent.TButton")
        self.save_button.pack(side="left", padx=(0, 8))
        self.test_button = ttk.Button(actions, text="Test connection / 测试连接", command=self.test)
        self.test_button.pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Done / 完成", command=self.close).pack(side="right")
        self.remove_button = ttk.Button(outer, text="Remove saved key / 移除已保存密钥", command=self.remove)
        self.remove_button.grid(row=11, column=0, sticky="w", pady=(14, 0))
        ttk.Label(outer, text="Connection test lists models; it does not generate a design.\n连接测试只读取模型列表，不生成设计。", style="Sub.TLabel").grid(row=12, column=0, sticky="w", pady=(14, 0))
        location = ttk.Label(outer, text=f"Encrypted storage / 加密保存位置\n{store.directory}",
                             style="Sub.TLabel", wraplength=590, justify="left")
        location.grid(row=13, column=0, sticky="ew", pady=(12, 0))
        def wrap_status(event):
            width = max(280, event.width - 56)
            self.status_label.configure(wraplength=width)
            location.configure(wraplength=width)
        outer.bind("<Configure>", wrap_status, add="+")
        root.update_idletasks()
        width = min(max(660, outer.winfo_reqwidth() + 32), root.winfo_screenwidth() - 100)
        height = min(max(660, outer.winfo_reqheight() + 40), root.winfo_screenheight() - 100)
        root.geometry(f"{width}x{height}")
        root.minsize(width, min(height, 540))
        self.entry.focus_set()
        root.after(100, self.poll)

    def save(self):
        key_was_saved = False
        try:
            typed = self.key.get().strip()
            if typed:
                self.store.save_key(typed)
                key_was_saved = True
            elif not self.store.has_key():
                raise CredentialError("Enter your API key first. / 请先输入 API 密钥。")
            self.store.save_settings(self.model.get(), "high")
            self.saved_model = self.model.get()
            self.key.set("")
            self.show.set(False)
            self.entry.configure(show="•")
            self.status.set("Saved securely. The design application can now use this key.\n已加密保存，设计应用现在可以使用此密钥。")
            return True
        except CredentialError as error:
            if key_was_saved:
                self.key.set("")
                self.show.set(False)
                self.entry.configure(show="•")
                self.status.set("Your encrypted key was saved; the model settings were not. Try Save again.\n"
                                "加密密钥已保存，但模型设置未保存，请再次点击保存。\n" + str(error))
            else:
                self.status.set(str(error))
            return False

    def set_busy(self, value: bool):
        self.busy = value
        for button in (self.test_button, self.save_button, self.remove_button):
            button.configure(state="disabled" if value else "normal")
        self.combo.configure(state="disabled" if value else "readonly")
        self.entry.configure(state="disabled" if value else "normal")
        self.show_check.configure(state="disabled" if value else "normal")

    def test(self):
        if self.busy:
            return
        try:
            key = self.key.get().strip() or self.store.load_key()
            if not key:
                raise CredentialError("Enter or save an API key first. / 请先输入或保存 API 密钥。")
        except CredentialError as error:
            self.status.set(str(error))
            return
        model = self.model.get()
        typed_key = bool(self.key.get().strip())
        self.set_busy(True)
        self.status.set("Checking account and model access…\n正在检查账户和模型权限……")
        def work():
            try:
                okay, message = check_connection(key, model)
                if typed_key:
                    message += "\nClick Save to keep the typed key. / 点击保存以保留输入的密钥。"
                self.events.put((okay, message))
            except Exception:
                self.events.put((False, "Connection check failed. Please try again.\n连接检查失败，请重试。"))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                _, message = self.events.get_nowait()
                self.status.set(message)
                self.set_busy(False)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def remove(self):
        if not self.store.has_key():
            self.status.set("No saved key to remove. / 没有可移除的已保存密钥。")
            return
        if messagebox.askyesno("Remove key / 移除密钥", "Remove this application's saved API key?\n移除此应用保存的 API 密钥？", parent=self.root):
            try:
                self.store.delete_key()
                self.key.set("")
                self.status.set("Saved key removed. / 已移除保存的密钥。")
            except CredentialError as error:
                self.status.set(str(error))

    def close(self):
        if self.key.get().strip() or self.model.get() != self.saved_model:
            choice = messagebox.askyesnocancel("Unsaved changes / 未保存的更改",
                "Save the key or model changes before closing?\n是否先保存密钥或模型更改再关闭？", parent=self.root)
            if choice is None:
                return
            if choice:
                if self.key.get().strip() or self.store.has_key():
                    if not self.save():
                        return
                else:
                    try:
                        self.store.save_settings(self.model.get(), "high")
                    except CredentialError as error:
                        self.status.set(str(error))
                        return
        self.key.set("")
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true", help="Print non-secret configuration only")
    parser.add_argument("--credential-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--diagnose-save", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--report", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.status or args.diagnose_save:
        if args.diagnose_save:
            from storage_diagnostics import diagnose_save
            result = diagnose_save(args.credential_dir)
        else:
            result = {**safe_status(args.credential_dir),
                      "storage_directory": str(CredentialStore(args.credential_dir).directory)}
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if sys.stdout is not None:
            print(json.dumps(result, ensure_ascii=True))
        return 0 if not args.diagnose_save or result["success"] else 2
    try:
        ctypes = __import__("ctypes")
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    try:
        KeySetup(root, CredentialStore(args.credential_dir))
        root.mainloop()
    except CredentialError as error:
        messagebox.showerror("Key setup / 密钥设置", str(error), parent=root)
        root.destroy()


if __name__ == "__main__":
    raise SystemExit(main())
