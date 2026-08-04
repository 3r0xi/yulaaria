from __future__ import annotations

import base64
import ctypes
import json
import os
import tempfile
from ctypes import wintypes
from pathlib import Path

from .paths import FACTORY_ROOT


DEFAULT_VAULT = FACTORY_ROOT / "secrets" / "providers.local.json"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _unprotect(value: str) -> str:
    encrypted = base64.b64decode(value)
    source_buffer = ctypes.create_string_buffer(encrypted)
    source = _DataBlob(len(encrypted), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    target = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)
    ):
        raise ctypes.WinError()
    try:
        plain = ctypes.string_at(target.pbData, target.cbData)
        return plain.decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


def _protect(value: str) -> str:
    plain = value.encode("utf-8")
    source_buffer = ctypes.create_string_buffer(plain)
    source = _DataBlob(len(plain), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    target = _DataBlob()
    cryptprotect_local_machine = 0x4
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), None, None, None, None, cryptprotect_local_machine, ctypes.byref(target)
    ):
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(target.pbData, target.cbData)
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


def _vault_path() -> Path:
    configured = os.environ.get("YULA_CREDENTIAL_VAULT", "").strip()
    return Path(configured).expanduser().resolve() if configured else DEFAULT_VAULT


def config_value(name: str, default: str = "") -> str:
    environment = os.environ.get(name, "").strip()
    if environment:
        return environment
    path = _vault_path()
    if not path.is_file():
        return default
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    entry = (payload.get("values") or {}).get(name)
    if not isinstance(entry, dict):
        return default
    if entry.get("type") == "plain":
        return str(entry.get("value", "")).strip()
    if entry.get("type") == "dpapi":
        return _unprotect(str(entry.get("value", ""))).strip()
    raise RuntimeError(f"Unsupported credential vault entry type for {name}")


def required_value(name: str) -> str:
    value = config_value(name)
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


def save_config_value(name: str, value: str, secret: bool = True) -> Path:
    if not name or not value:
        raise ValueError("Credential name and value are required")
    path = _vault_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "protection": "Windows DPAPI LocalMachine with inherited user-folder ACLs", "values": {}}
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        payload.setdefault("values", {})
    payload["values"][name] = {
        "type": "dpapi" if secret else "plain",
        "value": _protect(value) if secret else value,
    }
    payload["updated_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    handle, temp_name = tempfile.mkstemp(prefix="providers-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return path


def delete_config_value(name: str) -> bool:
    path = _vault_path()
    if not path.is_file():
        return False
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    values = payload.setdefault("values", {})
    if name not in values:
        return False
    del values[name]
    payload["updated_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    handle, temp_name = tempfile.mkstemp(prefix="providers-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return True
