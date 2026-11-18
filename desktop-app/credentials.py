"""Windows-user-scoped OpenAI credential storage. Never persist a plaintext key."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

DEFAULT_MODEL = "gpt-6.1-terra"
MODELS = (DEFAULT_MODEL, "gpt-6.1-sol", "gpt-6-astra")
_ENTROPY = b"VancouverWoodCarving/OpenAI/credential/v1"


class CredentialError(RuntimeError):
    """A deliberately secret-free credential error."""

    def __init__(self, message: str, *, stage: str | None = None, code: int | None = None):
        super().__init__(message)
        self.stage = stage
        self.code = code


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


def _windows_local_appdata() -> Path:
    """Resolve persistent per-user app data, independent of the launcher environment.

    NO_PACKAGE_REDIRECTION asks for the desktop user's location; it changes no
    permissions and creates no directory. Normal user folder redirection is kept.
    """
    if sys.platform != "win32":
        raise OSError("Windows folder resolution is unavailable")
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    ole = ctypes.WinDLL("ole32", use_last_error=True)
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    shell.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(_GUID), wintypes.DWORD,
                                         wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    folder = _GUID.from_buffer_copy(uuid.UUID("f1b32785-6fba-4fcf-9d55-7b8e7f157091").bytes_le)
    value = ctypes.c_wchar_p()
    initialized = ole.CoInitializeEx(None, 0)
    try:
        result = shell.SHGetKnownFolderPath(ctypes.byref(folder), 0x00014000, None, ctypes.byref(value))
        if result < 0 or not value.value:
            raise OSError("Windows could not resolve the local data folder")
        return Path(value.value)
    finally:
        ole.CoTaskMemFree(value)
        if initialized >= 0:
            ole.CoUninitialize()


def _registry_local_appdata() -> Path | None:
    if sys.platform != "win32":
        return None
    import winreg
    for key in (r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
                value, _ = winreg.QueryValueEx(handle, "Local AppData")
            if isinstance(value, str):
                result = Path(os.path.expandvars(value))
                if result.is_absolute():
                    return result
        except OSError:
            continue
    return None


def _is_temporary_package_path(path: Path) -> bool:
    text = str(path).replace("\\", "/").lower()
    return "/packages/sandbox." in text


def default_credential_directory() -> Path:
    candidates = []
    try:
        candidates.append(_windows_local_appdata())
    except (OSError, AttributeError):
        pass
    if not candidates or _is_temporary_package_path(candidates[0]):
        registry = _registry_local_appdata()
        if registry is not None:
            candidates.append(registry)
    # Compatibility fallback only for a normal, absolute desktop app-data path.
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local))
    for candidate in candidates:
        if candidate.is_absolute() and not _is_temporary_package_path(candidate):
            return candidate / "VancouverWoodCarving" / "credentials"
    raise CredentialError("Windows local application data folder is unavailable. / 无法找到 Windows 本地应用数据目录。")


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data: bytes):
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def _transform(data: bytes, *, protect: bool) -> bytes:
    if sys.platform != "win32":
        raise CredentialError("Encrypted key storage requires Windows. / 加密密钥存储需要 Windows。")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    incoming, incoming_buffer = _blob(data)
    entropy, entropy_buffer = _blob(_ENTROPY)
    outgoing = _DataBlob()
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    function.argtypes = [ctypes.POINTER(_DataBlob), ctypes.c_void_p,
                         ctypes.POINTER(_DataBlob), ctypes.c_void_p,
                         ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob)]
    function.restype = wintypes.BOOL
    # CRYPTPROTECT_UI_FORBIDDEN; no machine-scope flag, so only this Windows user can decrypt.
    success = function(ctypes.byref(incoming), None, ctypes.byref(entropy), None,
                       None, 0x1, ctypes.byref(outgoing))
    if not success:
        raise CredentialError("Windows could not protect or unlock the saved key. / Windows 无法加密或解密已保存的密钥。")
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(outgoing.pbData, ctypes.c_void_p))


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = None
    stage = "create_directory"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        stage = "create_temporary_file"
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".vwc-", delete=False) as handle:
            temporary = Path(handle.name)
            stage = "write"
            handle.write(data)
            stage = "flush"
            handle.flush()
            stage = "fsync"
            os.fsync(handle.fileno())
        stage = "replace"
        os.replace(temporary, path)
    except OSError as error:
        code = getattr(error, "winerror", None) or error.errno
        target = "encrypted key / 加密密钥" if path.name == "openai-key.bin" else "model settings / 模型设置"
        number = str(code) if code is not None else "unknown"
        raise CredentialError(
            f"Could not save {target}. Windows/OS code: {number}; step: {stage}.\n"
            f"保存失败。Windows／系统错误码：{number}；步骤：{stage}。",
            stage=stage, code=code,
        ) from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


class CredentialStore:
    def __init__(self, directory: Path | None = None):
        if directory is None:
            directory = default_credential_directory()
        self.directory = Path(directory)
        self.key_path = self.directory / "openai-key.bin"
        self.settings_path = self.directory / "settings.json"

    def save_key(self, key: str) -> None:
        key = key.strip()
        if not key or len(key) < 20 or any(c.isspace() for c in key):
            raise CredentialError("Enter a complete API key without spaces. / 请输入完整且不含空格的 API 密钥。")
        if len(key) > 4096:
            raise CredentialError("The API key is too long. / API 密钥过长。")
        _atomic_write(self.key_path, _transform(key.encode("utf-8"), protect=True))

    def load_key(self) -> str | None:
        if not self.key_path.exists():
            return None
        try:
            result = _transform(self.key_path.read_bytes(), protect=False).decode("utf-8")
            if not result:
                raise CredentialError("The saved credential is empty. / 已保存的密钥为空。")
            return result
        except (OSError, UnicodeError):
            raise CredentialError("Could not read the saved key. Please save it again. / 无法读取已保存的密钥，请重新保存。") from None

    def delete_key(self) -> None:
        try:
            self.key_path.unlink(missing_ok=True)
        except OSError:
            raise CredentialError("Could not remove the saved key. / 无法移除已保存的密钥。") from None

    def has_key(self) -> bool:
        return self.key_path.is_file()

    def load_settings(self) -> dict[str, str]:
        try:
            raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
            model = raw.get("model", DEFAULT_MODEL)
            if model not in MODELS:
                model = DEFAULT_MODEL
            return {"model": model, "reasoning": "high"}
        except (OSError, ValueError, AttributeError):
            return {"model": DEFAULT_MODEL, "reasoning": "high"}

    def save_settings(self, model: str, reasoning: str = "high") -> None:
        if model not in MODELS or reasoning != "high":
            raise CredentialError("Choose Terra High, Sol High or Astra High. / 请选择 Terra High、Sol High 或 Astra High。")
        _atomic_write(self.settings_path, json.dumps(
            {"model": model, "reasoning": reasoning}, ensure_ascii=True, indent=2).encode("utf-8"))


def safe_status(directory: Path | None = None) -> dict:
    """No key is loaded or returned by this diagnostic."""
    store = CredentialStore(directory)
    return {"key_saved": store.has_key(), **store.load_settings()}


if __name__ == "__main__":
    print(json.dumps(safe_status(), ensure_ascii=True))
