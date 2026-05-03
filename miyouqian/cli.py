# -*- coding: utf-8 -*-
"""命令行界面。"""

from __future__ import annotations

import argparse
import pathlib
import sys

from . import __version__
from .auth.login import QRLogin, print_qrcode
from .core.config import (
    create_config,
    credentials_path,
    load_config,
    log_path,
    save_config,
    upsert_account,
)
from .core.http import ApiClient
from .core.logs import append_log, configure_logger, format_line
from .service.notifier import send_push
from .service.runner import run_tasks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="米游签", description="简洁的米游社签到工具")
    parser.add_argument("-c", "--config", default="config.yaml", help="配置文件路径，默认 config.yaml")
    parser.add_argument("-v", "--version", action="version", version=f"米游签 {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="生成默认配置")
    init_parser.add_argument("--force", action="store_true", help="覆盖已有配置")

    login_parser = subparsers.add_parser("login", help="米游社 APP 扫码登录并写入凭证")
    login_parser.add_argument("--account", default="main", help="账号名，默认 main")
    login_parser.add_argument("--timeout", type=int, default=120, help="扫码等待秒数，默认 120")
    login_parser.add_argument("--no-image", action="store_true", help="不保存 qrcode.png")

    run_parser = subparsers.add_parser("run", help="执行签到任务")
    run_parser.add_argument("--account", help="只执行指定账号，默认执行全部账号")
    run_parser.add_argument("--games-only", action="store_true", help="只执行游戏签到")
    run_parser.add_argument("--bbs-only", action="store_true", help="只执行米游币社区任务")
    run_parser.add_argument("--game", action="append", help="只执行指定游戏，可重复传入")

    serve_parser = subparsers.add_parser("serve", help="启动常驻 Web 控制台和每日调度器")
    serve_parser.add_argument("--host", default=None, help="监听地址，默认读取配置文件")
    serve_parser.add_argument("--port", type=int, default=None, help="监听端口，默认读取配置文件")

    subparsers.add_parser("show", help="显示当前启用配置摘要")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config_path = pathlib.Path(args.config)
    try:
        if args.command == "init":
            return command_init(config_path, args.force)
        if args.command == "login":
            return command_login(config_path, args.account, args.timeout, not args.no_image)
        if args.command == "run":
            return command_run(config_path, args.account, args.games_only, args.bbs_only, args.game)
        if args.command == "serve":
            return command_serve(config_path, args.host, args.port)
        if args.command == "show":
            return command_show(config_path)
    except Exception as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1
    return 0


def command_init(config_path: pathlib.Path, force: bool) -> int:
    created = create_config(config_path, force=force)
    print(f"已生成配置: {created.resolve()}")
    print("填写 cookie/stoken，或运行 `python main.py login` 扫码写入凭证。")
    return 0


def command_login(config_path: pathlib.Path, account_name: str, timeout: int, save_image: bool) -> int:
    config = load_config(config_path)
    device = config["device"]
    image_path = config_path.parent / "qrcode.png" if save_image else None
    with ApiClient() as client:
        login = QRLogin(client, str(device["id"]), str(device["fp"]))
        url, ticket = login.fetch()
        print("请用米游社 APP 扫码：我的 -> 右上角扫一扫")
        print_qrcode(url, image_path=image_path)
        if image_path:
            print(f"二维码图片已保存: {image_path.resolve()}")
        scan = login.wait(ticket, timeout=timeout)
        account_data = login.exchange_tokens(scan["uid"], scan["game_token"])
    upsert_account(config, account_name, account_data)
    save_config(config_path, config)
    print(f"账号 {account_name} 凭证已写入: {credentials_path(config_path, config).resolve()}")
    return 0


def command_run(
    config_path: pathlib.Path,
    account_name: str | None,
    games_only: bool,
    bbs_only: bool,
    only_games: list[str] | None,
) -> int:
    if games_only and bbs_only:
        raise ValueError("--games-only 和 --bbs-only 不能同时使用")
    config = load_config(config_path)
    log_file = log_path(config_path, config)
    configure_logger(log_file)
    append_log(log_file, format_line("开始执行签到任务", "cli"), component="cli")
    task_lines = run_tasks(
        config,
        str(config_path),
        account_name,
        games_only,
        bbs_only,
        only_games,
        emit_component=lambda message, component: append_log(
            log_file,
            format_line(message, component),
            component=component,
        ),
    )
    append_log(log_file, format_line("签到任务执行完成", "cli"), component="cli")
    push_result = send_push(config, "米游签任务完成", "\n".join(task_lines), success=not any("失败" in line for line in task_lines))
    if push_result:
        append_log(log_file, format_line(push_result, "push"), component="push")
    return 0


def command_serve(config_path: pathlib.Path, host: str | None, port: int | None) -> int:
    from .service.web import serve

    config = load_config(config_path)
    web = config.get("web", {})
    effective_host = host or str(web.get("host", "127.0.0.1"))
    effective_port = port or int(web.get("port", 5890))
    serve(config_path, effective_host, effective_port)
    return 0


def command_show(config_path: pathlib.Path) -> int:
    config = load_config(config_path)
    accounts = ", ".join(str(item.get("name", "未命名")) for item in config.get("accounts", []))
    games = ", ".join(config.get("games", {}).get("enabled", []))
    print(f"配置文件: {config_path.resolve()}")
    print(f"总开关: {config.get('enable', True)}")
    print(f"账号: {accounts}")
    print(f"游戏签到: {config.get('features', {}).get('game_checkin', True)} ({games})")
    print(f"米游币社区任务: {config.get('features', {}).get('bbs_tasks', False)}")
    schedule = config.get("schedule", {})
    print(
        "每日调度: "
        f"{schedule.get('enable', True)} "
        f"{schedule.get('time', '09:00')} +/- {schedule.get('jitter_minutes', 45)} 分钟"
    )
    print(f"凭证文件: {credentials_path(config_path, config).resolve()}")
    print(f"日志文件: {log_path(config_path, config).resolve()}")
    web = config.get("web", {})
    print(f"Web 控制台: {web.get('host', '127.0.0.1')}:{web.get('port', 5890)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
