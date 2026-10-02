# -*- coding: utf-8 -*-
r"""
Лицензирование Printer Profiler.

Схема:
- HWID = SHA-256(MachineGuid|VolumeSerial)[:16].upper()
- POST на LICENSE_SERVER_URL с {action, key, hwid, product}
- Сервер отвечает {payload: {...}, signature: base64}
- Подпись Ed25519 проверяется публичным ключом
- Кэш лицензии в реестре HKCU\Software\<APP>\license_cache (TTL 24 ч)
- Trial: N запусков без регистрации

v2.8:
- Добавлен APP_PRODUCT = "printer_profiler".
- В verify_key_online добавлено поле product в запрос.
- Если сервер вернёт reason="wrong_product" — ключ чужого продукта.
"""
import base64
import ctypes
import ctypes.wintypes
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import winreg  # type: ignore
    _HAS_WINREG = True
except ImportError:
    winreg = None  # type: ignore
    _HAS_WINREG = False

# ─── Ed25519 (опционально) ───
_ED25519_AVAILABLE = False
_public_key = None

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PublicKey,
    )
    _ED25519_AVAILABLE = True
except ImportError:
    Ed25519PublicKey = None  # type: ignore


# ═══════════════════════════════════════════════════════════════
# КОНСТАНТЫ
# ═══════════════════════════════════════════════════════════════
LICENSE_SERVER_URL = (
    "https://functions.yandexcloud.net/d4es27v66uoqe58ae792"
)
LICENSE_PUBLIC_KEY_B64 = "YehJt3jS55blp8gOzURA+NYlw/FrbzQE6XQT2+Jvm4k="
LICENSE_CACHE_TTL = 86400
LICENSE_CACHE_REG_KEY = "license_cache"

SELLER_EMAIL = "voroshilov64221@gmail.com"
APP_NAME = "PrinterProfiler"           # используется в пути реестра
APP_PRODUCT = "printer_profiler"       # ← код продукта для сервера
APP_VERSION = "3.2.0"

TRIAL_LIMIT = 5                         # ← 5 запусков без регистрации

_REG_SETTINGS_SUBKEY = rf"Software\{APP_NAME}"


# ═══════════════════════════════════════════════════════════════
# РЕЕСТР
# ═══════════════════════════════════════════════════════════════
def _settings_read(name: str, default: str = "") -> str:
    if not _HAS_WINREG:
        return default
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             _REG_SETTINGS_SUBKEY) as k:
            v, _ = winreg.QueryValueEx(k, name)
            return v if isinstance(v, str) else str(v)
    except OSError:
        return default


def _settings_write(name: str, value: str) -> None:
    if not _HAS_WINREG:
        return
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                               _REG_SETTINGS_SUBKEY) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, str(value))
    except OSError:
        pass


# ═══════════════════════════════════════════════════════════════
# HWID
# ═══════════════════════════════════════════════════════════════
def _get_machine_guid() -> str:
    if not _HAS_WINREG:
        return ""
    try:
        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography") as k:
            v, _ = winreg.QueryValueEx(k, "MachineGuid")
            return str(v)
    except OSError:
        return ""


def _get_volume_serial() -> str:
    if os.name != "nt":
        return ""
    try:
        name_buf = ctypes.create_unicode_buffer(261)
        fs_buf = ctypes.create_unicode_buffer(261)
        serial = ctypes.c_ulong()
        max_len = ctypes.c_ulong()
        flags = ctypes.c_ulong()
        sys_drive = os.environ.get("SystemDrive", "C:").rstrip("\\")
        res = ctypes.windll.kernel32.GetVolumeInformationW(
            sys_drive + "\\",
            name_buf, 261,
            ctypes.byref(serial),
            ctypes.byref(max_len),
            ctypes.byref(flags),
            fs_buf, 261)
        if res:
            return f"{serial.value:08X}"
    except Exception:
        pass
    return ""


def get_hwid() -> str:
    raw = "|".join([_get_machine_guid(), _get_volume_serial()])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()


# ═══════════════════════════════════════════════════════════════
# ПОДПИСЬ
# ═══════════════════════════════════════════════════════════════
def _init_public_key():
    global _public_key
    if not _ED25519_AVAILABLE:
        return
    try:
        _public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(LICENSE_PUBLIC_KEY_B64))
    except Exception:
        _public_key = None


_init_public_key()


def _canonical_json(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True,
                       separators=(",", ":"),
                       ensure_ascii=False).encode("utf-8")


def _verify_signature(payload: dict, signature_b64: str) -> bool:
    if not _ED25519_AVAILABLE or _public_key is None:
        return False
    if not isinstance(payload, dict) or not signature_b64:
        return False
    try:
        _public_key.verify(base64.b64decode(signature_b64),
                            _canonical_json(payload))
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════
# РЕЗУЛЬТАТ
# ═══════════════════════════════════════════════════════════════
@dataclass
class LicenseResult:
    valid: bool
    owner: str = ""
    lifetime: bool = False
    expires_at: Optional[str] = None
    reason: str = ""
    cached: bool = False

    @classmethod
    def invalid(cls, reason: str = "invalid") -> "LicenseResult":
        return cls(valid=False, reason=reason)

    def as_tuple(self) -> tuple:
        return (self.valid, self.owner if self.valid else None)


# ═══════════════════════════════════════════════════════════════
# КЭШ
# ═══════════════════════════════════════════════════════════════
def _license_cache_read() -> dict:
    try:
        raw = _settings_read(LICENSE_CACHE_REG_KEY, "")
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _license_cache_write(data: dict) -> None:
    try:
        _settings_write(LICENSE_CACHE_REG_KEY,
                         json.dumps(data, ensure_ascii=False))
    except Exception:
        pass


def _license_cache_clear() -> None:
    try:
        _settings_write(LICENSE_CACHE_REG_KEY, "")
    except Exception:
        pass


def _license_cache_valid(key: str, hwid: str) -> dict:
    c = _license_cache_read()
    if not c:
        return {}
    payload = c.get("payload")
    signature = c.get("signature")
    if not isinstance(payload, dict) or not signature:
        return {}
    if not _verify_signature(payload, signature):
        return {}
    if payload.get("hwid") != hwid:
        return {}
    try:
        ts = float(c.get("ts", 0))
    except (ValueError, TypeError):
        ts = 0
    if time.time() - ts > LICENSE_CACHE_TTL:
        return {}
    if payload.get("key") != key:
        return {}
    exp = payload.get("expires_at")
    if exp:
        try:
            exp_dt = datetime.fromisoformat(
                str(exp).replace("Z", "+00:00"))
            if exp_dt < datetime.now(exp_dt.tzinfo):
                return {}
        except Exception:
            pass
    return payload


# ═══════════════════════════════════════════════════════════════
# ОНЛАЙН-ПРОВЕРКА
# ═══════════════════════════════════════════════════════════════
def verify_key_online(key: str) -> LicenseResult:
    key = (key or "").strip().upper()
    if not key:
        return LicenseResult.invalid("empty")

    hwid = get_hwid()

    cached = _license_cache_valid(key, hwid)
    if cached:
        return LicenseResult(
            valid=bool(cached.get("valid", True)),
            owner=cached.get("owner") or "Покупатель",
            lifetime=bool(cached.get("lifetime", False)),
            expires_at=cached.get("expires_at"),
            cached=True,
        )

    try:
        payload = json.dumps({
            "action": "activate",
            "key": key,
            "hwid": hwid,
            "product": APP_PRODUCT,   # ← важно: сервер проверит продукт
        }).encode("utf-8")

        req = urllib.request.Request(
            LICENSE_SERVER_URL,
            data=payload,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": f"{APP_NAME}/{APP_VERSION}",
            },
            method="POST")

        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            result = json.loads(raw) if raw.strip() else None

        if not isinstance(result, dict):
            return LicenseResult.invalid("bad_response")

        server_payload = result.get("payload")
        server_signature = result.get("signature")

        if not isinstance(server_payload, dict) or not server_signature:
            # Сервер вернул valid=False — берём reason
            reason = result.get("reason") or "invalid"
            return LicenseResult.invalid(reason)

        if not _verify_signature(server_payload, server_signature):
            return LicenseResult.invalid("bad_signature")
        if server_payload.get("hwid") != hwid:
            return LicenseResult.invalid("hwid_mismatch")

        _license_cache_write({
            "payload": server_payload,
            "signature": server_signature,
            "ts": time.time(),
        })

        return LicenseResult(
            valid=bool(server_payload.get("valid", False)),
            owner=server_payload.get("owner") or "Покупатель",
            lifetime=bool(server_payload.get("lifetime", False)),
            expires_at=server_payload.get("expires_at"),
        )

    except urllib.error.HTTPError as e:
        return LicenseResult.invalid(f"http_{e.code}")
    except urllib.error.URLError as e:
        return LicenseResult.invalid(f"network_{e.reason}")
    except Exception as e:
        return LicenseResult.invalid(f"error_{e}")


# ═══════════════════════════════════════════════════════════════
# СОХРАНЕНИЕ КЛЮЧА
# ═══════════════════════════════════════════════════════════════
def save_license(key: str) -> None:
    key = (key or "").strip().upper()
    _settings_write("license", key)
    _settings_write("hwid", get_hwid())


def load_license() -> tuple:
    return (_settings_read("license", ""),
            _settings_read("hwid", ""))


def reset_license() -> None:
    _license_cache_clear()
    _settings_write("license", "")
    _settings_write("hwid", "")


def is_activated() -> tuple:
    key, _ = load_license()
    if not key:
        return False, None
    r = verify_key_online(key)
    if r.valid:
        return True, r.owner
    reason = r.reason or ""
    is_offline = ("network" in reason
                   or "timeout" in reason.lower()
                   or reason.startswith("http_5"))
    if is_offline:
        c = _license_cache_read()
        if c:
            payload = c.get("payload")
            signature = c.get("signature", "")
            if (isinstance(payload, dict)
                    and payload.get("key") == key
                    and payload.get("hwid") == get_hwid()
                    and _verify_signature(payload, signature)):
                return True, payload.get("owner") or \
                    "Покупатель (офлайн)"
    return False, None


# ═══════════════════════════════════════════════════════════════
# TRIAL
# ═══════════════════════════════════════════════════════════════
def _file_path() -> Path:
    base = Path(os.environ.get("APPDATA",
                                os.path.expanduser("~"))) / APP_NAME
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return base / "state.dat"


def _read_file() -> dict:
    try:
        data = json.loads(_file_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_file(data: dict) -> None:
    try:
        _file_path().write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def get_launch_count() -> int:
    a = _settings_read("launches", "0")
    b = _read_file().get("launches", 0)
    try:
        a = int(a)
    except (ValueError, TypeError):
        a = 0
    try:
        b = int(b)
    except (ValueError, TypeError):
        b = 0
    return max(a, b)


def bump_launch_count() -> int:
    n = get_launch_count() + 1
    _settings_write("launches", str(n))
    data = _read_file()
    data["launches"] = n
    _write_file(data)
    return n


def get_trial_left() -> int:
    return max(0, TRIAL_LIMIT - get_launch_count())