# -*- coding: utf-8 -*-
"""持久日志工具。"""

from __future__ import annotations

import pathlib
import sys
from collections import deque
from datetime import datetime
from typing import Any

from loguru import logger

_configured_path: pathlib.Path | None = None
_file_sink_id: int | None = None
_console_sink_id: int | None = None

DEFAULT_BANNER_TEXT = "MYQ"
DEFAULT_CONSOLE_LOGO = r"""
        __  __  _                  ___  _
        |  \/  (_)_   _  ___      / _ \(_) __ _ _ __
        | |\/| | | | | |/ _ \    | | | | |/ _` | '_ \
        | |  | | | |_| | (_) |   | |_| | | (_| | | | |
        |_|  |_|_|\__, |\___/     \__\_\_|\__,_|_| |_|
                  |___/
                    米游签 / MiYoQian
                    
""".strip("\n")


def format_line(message: str, component: str = "app") -> str:
    return f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  [{clean_component(component)}]  {message}"


def append_log(path: str | pathlib.Path, line: str, component: str | None = None) -> None:
    try:
        #查看当前启动方式，如果发现是通过index.py启动，则禁用日志改为输出到终端，因为在serverless环境下文件系统是只读的
        if pathlib.Path(sys.modules['__main__'].__file__).name == "index.py":
            print(line)
            return
    except (AttributeError, KeyError):
        pass
    configure_logger(path)
    parsed_component, message = parse_log_line(line)
    logger.bind(component=clean_component(component or parsed_component)).info(message)


def tail_log(path: str | pathlib.Path, lines: int = 120) -> list[str]:
    log_file = pathlib.Path(path)
    if not log_file.exists():
        return []
    buffer: deque[str] = deque(maxlen=max(lines, 1))
    with log_file.open("r", encoding="utf-8", errors="replace") as file:
        for line in file:
            buffer.append(line.rstrip("\n"))
    return list(buffer)


def configure_logger(path: str | pathlib.Path) -> None:
    global _configured_path, _file_sink_id, _console_sink_id
    log_file = pathlib.Path(path)
    if _configured_path == log_file:
        return
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.configure(extra={"component": "app"})
    _console_sink_id = logger.add(
        sys.stdout,
        colorize=True,
        enqueue=False,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green>  "
            "<cyan>[{extra[component]}]</cyan>  <level>{message}</level>"
        ),
    )
    _file_sink_id = logger.add(
        log_file,
        encoding="utf-8",
        rotation="00:00",
        retention="30 days",
        compression=None,
        enqueue=False,
        format="{time:YYYY-MM-DD HH:mm:ss}  [{extra[component]}]  {message}",
    )
    _configured_path = log_file


def strip_log_prefix(line: str) -> str:
    return parse_log_line(line)[1]


def parse_log_line(line: str) -> tuple[str, str]:
    text = line.strip()
    component = "app"
    if len(text) >= 21 and text[4:5] == "-" and text[7:8] == "-" and text[13:14] == ":":
        text = text[21:].strip()
    if text.startswith("[") and "]" in text:
        raw_component, rest = text[1:].split("]", 1)
        component = clean_component(raw_component)
        text = rest.strip()
    return component, text


def clean_component(component: Any) -> str:
    text = str(component or "app").strip().lower()
    return "".join(char for char in text if char.isalnum() or char in {"_", "-"})[:24] or "app"


def render_banner(text: str = "MYQ") -> str:
    if text.strip().lower() in {"myq", "miyouqian", "米游签"}:
        return DEFAULT_CONSOLE_LOGO
    try:
        from pyfiglet import Figlet

        return Figlet(font="slant").renderText(text).rstrip()
    except Exception:
        return f"=== {text} ==="


def print_startup_banner(text: str = "MYQ") -> None:
    banner = render_banner(text)
    if sys.stdout.isatty():
        sys.stdout.write(f"\033[36m{banner}\033[0m\n")
    else:
        sys.stdout.write(f"{banner}\n")
    sys.stdout.flush()
