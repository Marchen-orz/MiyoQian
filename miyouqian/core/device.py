# -*- coding: utf-8 -*-
"""设备档案：本地设备信息、服务器签发的 device_fp、真机信息导入。

device_id 在本地生成并长期保存。device_fp 只认两种来源：向官方 getFp 接口申请到的，
或用户从真机抓包导入的；申请失败时不再用随机串顶替，请求里干脆不带 x-rpc-device_fp。
品牌、型号、系统版本来自自洽的机型预设或用户导入的真机信息，
不生成传感器、电量这类遥测数据（真机的这类数据只能随导入的 ext_fields 一起发出）。
"""

from __future__ import annotations

import json
import random
import re
import threading
import time
import uuid
from typing import Any, Callable

from .. import constants as c
from .http import ApiClient

PROFILE_PRESET = "preset"
PROFILE_IMPORTED = "imported"

FP_SERVER = "server"
FP_IMPORTED = "imported"
FP_LEGACY = "legacy"
FP_SOURCES = (FP_SERVER, FP_IMPORTED, FP_LEGACY)
# 只有这两种来源算「可信」：旧版本留下的 fp 多半是随机串，会在下次有机会时被换掉
TRUSTED_FP_SOURCES = (FP_SERVER, FP_IMPORTED)

DEFAULT_OS_VERSION = "13"

# 系统版本按机型首发时的版本填写，品牌取 Build.BRAND 的写法（x-rpc-device_name 是 品牌 + 型号）；
# board 是 Build.BOARD（SoC 平台代号），getFp 要求它非空，内容服务器不校验，这里按机型的 SoC 填
DEVICE_PRESETS: tuple[dict[str, str], ...] = (
    {"label": "Xiaomi 14", "brand": "Xiaomi", "model": "23127PN0CC", "os_version": "14", "board": "pineapple"},
    {"label": "Xiaomi 13", "brand": "Xiaomi", "model": "2211133C", "os_version": "13", "board": "kalama"},
    {"label": "Redmi K70", "brand": "Redmi", "model": "2311DRK48C", "os_version": "14", "board": "kalama"},
    {"label": "Redmi K60", "brand": "Redmi", "model": "23013RK75C", "os_version": "13", "board": "cape"},
    {"label": "OnePlus 12", "brand": "OnePlus", "model": "PJD110", "os_version": "14", "board": "pineapple"},
    {"label": "OPPO Find X7", "brand": "OPPO", "model": "PHZ110", "os_version": "14", "board": "mt6989"},
    {"label": "vivo X100", "brand": "vivo", "model": "V2309A", "os_version": "14", "board": "mt6989"},
    {"label": "Samsung Galaxy S23", "brand": "samsung", "model": "SM-S9110", "os_version": "13", "board": "kalama"},
)

UNKNOWN_BOARD = "unknown"

MANUFACTURERS = {"Redmi": "Xiaomi", "POCO": "Xiaomi"}

# getFp 的 platform：2 是 Android，app_name 对应国服米游社 App
FP_PLATFORM = "2"
FP_APP_NAME = "bbs_cn"
FP_RETRY_DELAYS = (0.5, 1.5)
# 申请失败后这段时间内不再重试，免得登录、任务连着触发时每次都白等一轮
FP_FAIL_COOLDOWN = 60.0

_STATE_LOCK = threading.Lock()
_ISSUE_LOCK = threading.Lock()
_FAILED_AT: dict[str, float] = {}

_FP_RE = re.compile(r"^[0-9a-fA-F]{13}$")
_ID_RE = re.compile(r"^[0-9A-Za-z-]{16,64}$")
_OAID_RE = re.compile(r"^[0-9A-Za-z-]{8,64}$")
_OS_RE = re.compile(r"^\d{1,2}(\.\d+){0,2}$")

_IMPORT_PROFILE_KEYS = ("name", "brand", "os_version")
MAX_IMPORT_CHARS = 200_000
MAX_EXT_FIELDS = 200


def new_device_id() -> str:
    return str(uuid.uuid4())


def find_preset(model: str) -> dict[str, str] | None:
    model = str(model or "").strip().lower()
    if not model:
        return None
    for preset in DEVICE_PRESETS:
        if preset["model"].lower() == model:
            return preset
    return None


def preset_options() -> list[dict[str, str]]:
    return [dict(preset) for preset in DEVICE_PRESETS]


def sdk_for(os_version: str) -> int:
    """Android 主版本号换算成 API Level：10-12 差 19，13 起差 20（12L 的 32 单独出现，不在这里处理）。"""
    match = re.match(r"\d+", str(os_version or ""))
    if not match:
        return 0
    major = int(match.group())
    return major + 19 if major <= 12 else major + 20


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _brand_from_name(name: str, model: str) -> str:
    if not name:
        return ""
    if model and name.lower().endswith(model.lower()):
        return name[: len(name) - len(model)].strip()
    return name.split()[0]


# ---------------------------------------------------------------------------
# 档案规整与迁移
# ---------------------------------------------------------------------------


def apply_preset(device: dict[str, Any], preset: dict[str, str]) -> None:
    for key in ("ua", "oaid", "android_id", "ext_fields"):
        device.pop(key, None)
    device.update(
        {
            "source": PROFILE_PRESET,
            "brand": preset["brand"],
            "model": preset["model"],
            "name": f"{preset['brand']} {preset['model']}",
            "os_version": preset["os_version"],
            "sdk": sdk_for(preset["os_version"]),
        }
    )


def normalize_device(config: dict[str, Any]) -> None:
    """补齐并整理 config["device"]。能自洽的信息都在这里补好，调用方只管读。"""
    device = config.get("device")
    if not isinstance(device, dict):
        device = {}
        config["device"] = device
    # 机型预设改为内置，不再写进配置文件
    device.pop("presets", None)
    device["id"] = _text(device.get("id")) or new_device_id()
    with _STATE_LOCK:
        _normalize_profile(device)
        _normalize_fp(device)


def _normalize_profile(device: dict[str, Any]) -> None:
    model = _text(device.get("model"))
    source = device.get("source")
    if source not in (PROFILE_PRESET, PROFILE_IMPORTED):
        # 没有 source 的是旧版配置，或者是全新配置
        if not model:
            apply_preset(device, random.choice(DEVICE_PRESETS))
            return
        preset = find_preset(model)
        if preset:
            # 旧版 name 填的是营销名（Xiaomi 14），请求里应该是 品牌 + 型号，所以整体按预设重写
            apply_preset(device, preset)
            return
        source = PROFILE_IMPORTED
        # 旧版 name 填的是营销名：品牌取它的第一个词，请求里的名字改成 品牌 + 型号
        if not _text(device.get("brand")):
            device["brand"] = _brand_from_name(_text(device.get("name")), model)
        device["name"] = ""
    if not model:
        apply_preset(device, random.choice(DEVICE_PRESETS))
        return
    preset = find_preset(model)
    name = _text(device.get("name"))
    brand = _text(device.get("brand")) or (preset["brand"] if preset else _brand_from_name(name, model))
    os_version = _text(device.get("os_version")) or (preset["os_version"] if preset else DEFAULT_OS_VERSION)
    device["source"] = source
    device["model"] = model
    device["brand"] = brand
    device["name"] = name or f"{brand} {model}".strip()
    device["os_version"] = os_version
    device["sdk"] = sdk_for(os_version)
    for key in ("ua", "oaid", "android_id"):
        if key in device:
            device[key] = _text(device[key])
    if not isinstance(device.get("ext_fields"), dict):
        device.pop("ext_fields", None)


def _normalize_fp(device: dict[str, Any]) -> None:
    fp = _text(device.get("fp"))
    device["fp"] = fp
    if not fp:
        device["fp_source"] = ""
        device["fp_time"] = 0
        return
    if device.get("fp_source") not in FP_SOURCES:
        device["fp_source"] = FP_LEGACY
    try:
        device["fp_time"] = max(int(device.get("fp_time") or 0), 0)
    except (TypeError, ValueError):
        device["fp_time"] = 0


# ---------------------------------------------------------------------------
# 请求里用到的设备字段（容忍 {"id": "dev"} 这类只有部分字段的字典）
# ---------------------------------------------------------------------------


def device_model(device: dict[str, Any]) -> str:
    return _text(device.get("model")) or DEVICE_PRESETS[0]["model"]


def device_name(device: dict[str, Any]) -> str:
    name = _text(device.get("name"))
    if name:
        return name
    brand = _text(device.get("brand")) or DEVICE_PRESETS[0]["brand"]
    return f"{brand} {device_model(device)}"


def sys_version(device: dict[str, Any]) -> str:
    return _text(device.get("os_version")) or DEFAULT_OS_VERSION


def effective_fp(device: dict[str, Any]) -> str:
    """请求里该带的 device_fp。没有就是空串，调用方据此省略 x-rpc-device_fp。"""
    return _text(device.get("fp"))


def has_trusted_fp(device: dict[str, Any]) -> bool:
    return bool(effective_fp(device)) and device.get("fp_source") in TRUSTED_FP_SOURCES


def is_app_ua(ua: str) -> bool:
    return 0 < len(ua) <= 512 and "Mozilla/5.0" in ua and "miHoYoBBS" in ua


def mobile_ua(device: dict[str, Any]) -> str:
    """App 内 WebView 的 UA。导入的真机 UA 优先，否则按档案里的系统版本和型号拼。"""
    imported = _text(device.get("ua"))
    if is_app_ua(imported):
        return imported
    return (
        f"Mozilla/5.0 (Linux; Android {sys_version(device)}; {device_model(device)}) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        f"Chrome/{c.WEBVIEW_CHROME_VERSION} Mobile Safari/537.36 miHoYoBBS/{c.BBS_VERSION}"
    )


def device_view(device: dict[str, Any]) -> dict[str, Any]:
    """给 Web 控制台展示的档案摘要。"""
    return {
        "id": _text(device.get("id")),
        "fp": effective_fp(device),
        "fp_source": _text(device.get("fp_source")),
        "fp_time": device.get("fp_time") or 0,
        "trusted_fp": has_trusted_fp(device),
        "source": _text(device.get("source")),
        "brand": _text(device.get("brand")),
        "model": device_model(device),
        "name": device_name(device),
        "os_version": sys_version(device),
        "sdk": device.get("sdk") or sdk_for(sys_version(device)),
        "has_ua": is_app_ua(_text(device.get("ua"))),
        "has_ext_fields": isinstance(device.get("ext_fields"), dict) and bool(device.get("ext_fields")),
        "presets": preset_options(),
    }


# ---------------------------------------------------------------------------
# 向服务器申请 device_fp
# ---------------------------------------------------------------------------


def seed_device_id(device: dict[str, Any]) -> str:
    """getFp 的 device_id 是 16 位十六进制（Android ID 的形态）：导入过就用导入的，否则由 device_id 稳定推出。"""
    imported = _text(device.get("android_id"))
    if re.fullmatch(r"[0-9a-fA-F]{16}", imported):
        return imported.lower()
    return uuid.uuid5(uuid.NAMESPACE_URL, f"android_id:{_text(device.get('id'))}").hex[:16]


def device_oaid(device: dict[str, Any]) -> str:
    """服务器不收空的 oaid：导入过就用导入的，否则由 device_id 稳定推出。"""
    imported = _text(device.get("oaid"))
    if imported:
        return imported
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"oaid:{_text(device.get('id'))}"))


def device_board(device: dict[str, Any]) -> str:
    """服务器不收空的 board：预设机型用预设里的，导入的机型不在预设里又没给 ext_fields 就只能填 unknown。"""
    preset = find_preset(_text(device.get("model")))
    return preset["board"] if preset else UNKNOWN_BOARD


def ext_fields(device: dict[str, Any]) -> dict[str, Any]:
    """getFp 的 ext_fields：只放设备标识类字段；导入的真机 ext_fields 整体保留，缺的标识再补上。

    实测服务器要求 oaid 和 board 都非空，缺任何一个都会回 code 500。
    """
    imported = device.get("ext_fields")
    fields: dict[str, Any] = dict(imported) if isinstance(imported, dict) else {}
    brand = _text(device.get("brand")) or DEVICE_PRESETS[0]["brand"]
    defaults = {
        "oaid": device_oaid(device),
        "board": device_board(device),
        "brand": brand,
        "manufacturer": MANUFACTURERS.get(brand, brand),
        "model": device_model(device),
        "osVersion": sys_version(device),
        "sdkVersion": str(device.get("sdk") or sdk_for(sys_version(device))),
        "packageName": "com.mihoyo.hyperion",
        "packageVersion": c.BBS_VERSION,
    }
    for key, value in defaults.items():
        if fields.get(key) in (None, ""):
            fields[key] = value
    return fields


def build_fp_request(device: dict[str, Any], now_ms: int | None = None) -> dict[str, str]:
    return {
        "device_id": seed_device_id(device),
        "seed_id": str(uuid.uuid4()),
        "seed_time": str(now_ms if now_ms is not None else int(time.time() * 1000)),
        "platform": FP_PLATFORM,
        # 请求里自带的 device_fp 只是种子，不是最终指纹，服务器会另给一个
        "device_fp": "".join(random.choice("0123456789abcdef") for _ in range(13)),
        "app_name": FP_APP_NAME,
        "ext_fields": json.dumps(ext_fields(device), ensure_ascii=False, separators=(",", ":")),
        "bbs_device_id": _text(device.get("id")),
    }


def request_device_fp(client: ApiClient, device: dict[str, Any]) -> str:
    """申请一次，失败抛 ValueError / ApiError。code 不是 200 时 device_fp 字段可能原样回显种子，必须校验。"""
    data = client.post_json(c.DEVICE_FP_URL, json=build_fp_request(device), retries=1)
    raw = data.get("data")
    raw = raw if isinstance(raw, dict) else {}
    fp = _text(raw.get("device_fp"))
    if data.get("retcode") != 0 or str(raw.get("code")) != "200" or not _FP_RE.match(fp):
        raise ValueError(str(raw.get("msg") or data.get("message") or "接口没有返回有效的 device_fp"))
    return fp


def needs_fp(device: dict[str, Any]) -> bool:
    return not has_trusted_fp(device)


def ensure_device_fp(
    client: ApiClient,
    device: dict[str, Any],
    *,
    force: bool = False,
    attempts: int = 3,
    emit: Callable[[str], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bool, str]:
    """保证设备有一枚可信的 device_fp，没有就向服务器申请，结果写回 device。

    返回 (是否已有可信 fp, 失败原因)。从不抛异常；调用方负责保存配置。
    force=True 时即使已有也重新申请，并且忽略失败冷却。
    """
    if not force and not needs_fp(device):
        return True, ""
    with _ISSUE_LOCK:
        # 排队期间别人可能已经申请好了
        if not force and not needs_fp(device):
            return True, ""
        device_id = _text(device.get("id"))
        failed_at = _FAILED_AT.get(device_id)
        if not force and failed_at is not None and time.monotonic() - failed_at < FP_FAIL_COOLDOWN:
            return False, "刚刚申请失败，稍后再试"
        fp, reason = "", ""
        for attempt in range(max(attempts, 1)):
            try:
                fp = request_device_fp(client, device)
                break
            except Exception as exc:
                reason = str(exc)
                if attempt + 1 < max(attempts, 1):
                    sleep(FP_RETRY_DELAYS[min(attempt, len(FP_RETRY_DELAYS) - 1)])
        if not fp:
            _FAILED_AT[device_id] = time.monotonic()
            if emit:
                emit(f"向服务器申请 device_fp 失败: {reason}")
            return False, reason
        with _STATE_LOCK:
            if _text(device.get("id")) != device_id:
                # 申请期间设备被换掉了，这枚 fp 属于旧设备，不能写给新设备
                return False, "设备在申请期间已更换"
            device.update({"fp": fp, "fp_source": FP_SERVER, "fp_time": int(time.time())})
        _FAILED_AT.pop(device_id, None)
        if emit:
            emit("已向服务器申请并保存 device_fp")
        return True, ""


# ---------------------------------------------------------------------------
# 真机信息导入
# ---------------------------------------------------------------------------

_TOKEN = r"[0-9A-Za-z_\-]+"
_FREE = r"[^\r\n'\"^\\]+"

# (字段, 取值正则, 别名)；别名靠前的优先。键前不能紧跟字母、数字、下划线、连字符，
# 这样 device_id 不会匹配到 bbs_device_id 或 x-rpc-device_id 的中间
_TEXT_FIELDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("id", _TOKEN, ("x-rpc-device_id", "bbs_device_id", "device_id", "deviceid")),
    ("fp", _TOKEN, ("x-rpc-device_fp", "device_fp", "devicefp", "devicefingerprint")),
    ("name", _FREE, ("x-rpc-device_name", "device_name", "devicename")),
    ("model", _FREE, ("x-rpc-device_model", "device_model", "devicemodel")),
    ("os_version", _FREE, ("x-rpc-sys_version", "sys_version", "osversion")),
    ("oaid", _TOKEN, ("oaid",)),
    ("ua", _FREE, ("user-agent",)),
)

_JSON_ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("bbsdeviceid", "xrpcdeviceid", "deviceid", "id"),
    "fp": ("xrpcdevicefp", "devicefp", "devicefingerprint", "fp"),
    "name": ("xrpcdevicename", "devicename", "name"),
    "model": ("xrpcdevicemodel", "devicemodel", "model"),
    "os_version": ("xrpcsysversion", "sysversion", "osversion"),
    "brand": ("brand",),
    "oaid": ("oaid",),
    "ua": ("useragent", "ua"),
}


def _clean_import_value(field: str, value: Any) -> str:
    text = _text(value)
    if field == "id":
        return text if _ID_RE.match(text) else ""
    if field == "fp":
        return text.lower() if _FP_RE.match(text) else ""
    if field == "oaid":
        return text if _OAID_RE.match(text) else ""
    if field == "os_version":
        return text if _OS_RE.match(text) else ""
    if field == "ua":
        return text if is_app_ua(text) else ""
    return text if 0 < len(text) <= 64 and text.isprintable() else ""


def _find_json_object(text: str) -> dict[str, Any] | None:
    """整段文本就是 JSON，或者 JSON 嵌在 cURL 的 --data-raw '...' 这类文本里。"""
    candidates = [text]
    embedded = re.search(r"\{.*\}", text, re.S)
    if embedded and embedded.group() != text:
        candidates.append(embedded.group())
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _normalized_keys(obj: dict[str, Any]) -> dict[str, Any]:
    return {re.sub(r"[^a-z0-9]", "", str(key).lower()): value for key, value in obj.items()}


def _parse_json_import(obj: dict[str, Any], found: dict[str, Any]) -> tuple[bool, bool]:
    """从 JSON 里取字段。返回 (这是不是 getFp 请求体, JSON 里的 device_fp 能不能信)。

    getFp 请求体的 device_id 是 Android ID，不是 x-rpc-device_id，它的 device_fp 只是种子；
    getFp 响应的 code 不是 200 时 device_fp 是原样回显的种子。这两种 device_fp 都不是服务器签发的。
    """
    layers = [_normalized_keys(obj)]
    if isinstance(obj.get("data"), dict):
        layers.append(_normalized_keys(obj["data"]))
    flat = {key: value for layer in reversed(layers) for key, value in layer.items()}
    is_fp_body = "extfields" in flat or "seedid" in flat
    code = flat.get("code")
    fp_usable = not is_fp_body and (code is None or str(code) == "200")
    ext: dict[str, Any] = {}
    raw_ext = flat.get("extfields")
    if isinstance(raw_ext, str):
        try:
            raw_ext = json.loads(raw_ext)
        except ValueError:
            raw_ext = None
    if isinstance(raw_ext, dict) and len(raw_ext) <= MAX_EXT_FIELDS:
        ext = raw_ext
        found["ext_fields"] = ext
    ext_flat = _normalized_keys(ext)
    for field, aliases in _JSON_ALIASES.items():
        if field == "fp" and not fp_usable:
            continue
        for alias in aliases:
            if is_fp_body and field == "id" and alias in ("deviceid", "id"):
                continue
            value = _clean_import_value(field, flat.get(alias))
            if value:
                found.setdefault(field, value)
                break
    if is_fp_body:
        android_id = _text(flat.get("deviceid"))
        if re.fullmatch(r"[0-9a-fA-F]{16}", android_id):
            found["android_id"] = android_id.lower()
    # ext_fields 里的机型信息作兜底
    for field, key in (("brand", "brand"), ("model", "model"), ("os_version", "osversion"), ("oaid", "oaid")):
        value = _clean_import_value(field, ext_flat.get(key))
        if value:
            found.setdefault(field, value)
    return is_fp_body, fp_usable


def _parse_text_import(text: str, found: dict[str, Any], skip_plain_id: bool, skip_fp: bool) -> None:
    for field, value_re, aliases in _TEXT_FIELDS:
        if field in found or (field == "fp" and skip_fp):
            continue
        for alias in aliases:
            if skip_plain_id and field == "id" and alias in ("device_id", "deviceid"):
                continue
            pattern = re.compile(
                rf"(?<![\w-]){re.escape(alias)}[\"']?\s*[:=]\s*[\"']?({value_re})", re.I
            )
            for match in pattern.finditer(text):
                value = _clean_import_value(field, match.group(1))
                if value:
                    found[field] = value
                    break
            if field in found:
                break


def parse_device_import(text: str) -> dict[str, Any]:
    """从抓包文本里提取设备信息。

    支持：请求头原文、「复制为 cURL」、JSON（含 getFp 的请求体 / 响应）、device_id=…、device_fp=… 这类键值。
    返回只含识别到字段的字典；一个都没识别到抛 ValueError。
    """
    text = str(text or "").strip()
    if not text:
        raise ValueError("请先粘贴抓包得到的设备信息")
    if len(text) > MAX_IMPORT_CHARS:
        raise ValueError("内容太长，请只粘贴请求头或 getFp 请求体")
    found: dict[str, Any] = {}
    obj = _find_json_object(text)
    is_fp_body, fp_usable = _parse_json_import(obj, found) if obj is not None else (False, True)
    _parse_text_import(text, found, skip_plain_id=is_fp_body, skip_fp=not fp_usable)
    if not any(found.get(key) for key in ("id", "fp", "model", "name", "ext_fields")):
        raise ValueError(
            "没有识别到设备信息，请粘贴包含 x-rpc-device_id / x-rpc-device_fp 的请求头、cURL，"
            "或 getFp 的请求体 / 响应 JSON"
        )
    return found


def apply_device_import(device: dict[str, Any], parsed: dict[str, Any]) -> list[str]:
    """把导入的信息写进档案并返回变动项。导入的字段一律优先于预设，没给的字段保持原值。"""
    changed: list[str] = []
    with _STATE_LOCK:
        new_id = _text(parsed.get("id"))
        id_changed = bool(new_id) and new_id != _text(device.get("id"))
        if id_changed:
            device["id"] = new_id
            # 旧设备留下的 fp、oaid 等都属于旧 device_id，不能带到新的上面
            for key in ("oaid", "android_id", "ext_fields", "ua"):
                device.pop(key, None)
            device.update({"fp": "", "fp_source": "", "fp_time": 0})
            changed.append("device_id")
        new_model = _text(parsed.get("model"))
        if new_model and new_model != _text(device.get("model")):
            # 换了机型，原来的品牌、系统版本不再适用，交给规整按预设或默认值重新补
            for key in _IMPORT_PROFILE_KEYS:
                device.pop(key, None)
            device["model"] = new_model
            changed.append("型号")
        for key, label in (
            ("name", "设备名"),
            ("brand", "品牌"),
            ("os_version", "系统版本"),
            ("oaid", "oaid"),
            ("android_id", "Android ID"),
            ("ua", "WebView UA"),
        ):
            value = parsed.get(key)
            if value and value != device.get(key):
                device[key] = value
                changed.append(label)
        if isinstance(parsed.get("ext_fields"), dict) and parsed["ext_fields"]:
            device["ext_fields"] = dict(parsed["ext_fields"])
            changed.append("ext_fields")
        if changed:
            device["source"] = PROFILE_IMPORTED
        fp = _text(parsed.get("fp"))
        if fp and fp != _text(device.get("fp")):
            device.update({"fp": fp, "fp_source": FP_IMPORTED, "fp_time": int(time.time())})
            changed.append("device_fp")
        elif fp and device.get("fp_source") != FP_IMPORTED:
            device["fp_source"] = FP_IMPORTED
            changed.append("device_fp")
        _normalize_profile(device)
        _normalize_fp(device)
    return changed


def reset_device(device: dict[str, Any], model: str = "") -> None:
    """换一台全新的虚拟设备：新 device_id、按所选（缺省随机）预设重写档案，旧 fp 作废。"""
    preset = find_preset(model) if model else random.choice(DEVICE_PRESETS)
    if preset is None:
        raise ValueError(f"未知的预设机型: {model}")
    with _STATE_LOCK:
        device["id"] = new_device_id()
        apply_preset(device, preset)
        device.update({"fp": "", "fp_source": "", "fp_time": 0})
