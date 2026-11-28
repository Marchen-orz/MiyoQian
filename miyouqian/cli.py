# -*- coding: utf-8 -*-
"""命令行界面。"""

from __future__ import annotations

import argparse
import pathlib
import sys

from . import __version__
from .auth.login import QRLogin, print_qrcode
from .core import cookies
from .core import device as devicelib
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
from .core.region import REGION_OS, account_region
from .service.notifier import send_task_push
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
    run_parser.add_argument("--games-only", action="store_true", help="只执行游戏社区签到和云游戏签到")
    run_parser.add_argument("--bbs-only", action="store_true", help="只执行米游币社区任务")
    run_parser.add_argument("--game", action="append", help="只执行指定游戏，可重复传入")

    serve_parser = subparsers.add_parser("serve", help="启动常驻 Web 控制台和每日调度器")
    serve_parser.add_argument("--host", default=None, help="监听地址，默认读取配置文件")
    serve_parser.add_argument("--port", type=int, default=None, help="监听端口，默认读取配置文件")

    subparsers.add_parser("show", help="显示当前启用配置摘要")

    update_parser = subparsers.add_parser("update", help="检查并更新到 GitHub 最新版本")
    update_parser.add_argument("--check", action="store_true", help="仅检查更新，不执行拉取")
    update_parser.add_argument("--force", action="store_true", help="强制拉取更新（即使本地已是最新）")
    update_parser.add_argument("--mirror", default="", help="临时指定 GitHub 加速前缀，例如 https://gh-proxy.org/")
    update_parser.add_argument("--ghcr-mirror", default="", help="临时指定 GHCR 镜像加速域名，例如 ghcr.nju.edu.cn")
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
        if args.command == "update":
            return command_update(
                config_path,
                check_only=args.check,
                force=args.force,
                github_mirror=args.mirror,
                ghcr_mirror=args.ghcr_mirror,
            )
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
        ok, reason = devicelib.ensure_device_fp(client, device)
        if not ok:
            print(f"[提示] device_fp 暂时无法获取（{reason}），登录请求将不带 x-rpc-device_fp")
        login = QRLogin(client, device)
        url, ticket = login.fetch()
        print("请用米游社 APP 扫码：我的 -> 左上角扫一扫")
        print_qrcode(url, image_path=image_path)
        if image_path:
            print(f"二维码图片已保存: {image_path.resolve()}")
        scan = login.wait(ticket, timeout=timeout)
        account_data = {**scan, **login.get_additional_tokens(scan["stoken"], scan["mid"])}
        account_data["cookie"] = cookies.build_cookie(
            account_data["stuid"],
            account_data["mid"],
            account_data["ltoken"],
            account_data["cookie_token"],
        )
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
    push_result = send_task_push(config, task_lines)
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
    accounts = ", ".join(
        str(item.get("name", "未命名")) + ("(国际服)" if account_region(item) == REGION_OS else "")
        for item in config.get("accounts", [])
    )
    games = ", ".join(config.get("games", {}).get("enabled", []))
    cloud_games = ", ".join(config.get("cloud_games", {}).get("enabled", []))
    enabled_cloud_games = set(config.get("cloud_games", {}).get("enabled", []))
    cloud_account_count = sum(
        1
        for account in config.get("accounts", [])
        if any(
            str(((account.get("cloud_games") or {}).get("tokens") or {}).get(key) or "").strip()
            for key in enabled_cloud_games
        )
    )
    print(f"配置文件: {config_path.resolve()}")
    print(f"总开关: {config.get('enable', True)}")
    print(f"账号: {accounts}")
    print(f"游戏社区签到: {config.get('features', {}).get('game_checkin', True)} ({games})")
    print(
        f"云游戏签到: {config.get('features', {}).get('cloud_game_checkin', False)} "
        f"({cloud_games or '未选择'}; 已配置 {cloud_account_count} 个账号)"
    )
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
    print(f"Web 控制台（配置文件中的值，启动时可被命令行参数覆盖）: {web.get('host', '127.0.0.1')}:{web.get('port', 5890)}")
    return 0


def command_update(
    config_path: pathlib.Path,
    *,
    check_only: bool = False,
    force: bool = False,
    github_mirror: str = "",
    ghcr_mirror: str = "",
) -> int:
    from .core.updater import apply_update, check_for_updates

    config = load_config(config_path)
    update_cfg = config.get("update", {}) if isinstance(config.get("update"), dict) else {}
    effective_gh_mirror = github_mirror or str(update_cfg.get("github_mirror") or "")
    effective_ghcr_mirror = ghcr_mirror or str(update_cfg.get("ghcr_mirror") or "")

    info = check_for_updates(github_mirror=effective_gh_mirror, ghcr_mirror=effective_ghcr_mirror)
    local = info["local"]
    remote = info["remote"]
    mode_label = {"docker": "Docker 容器", "git": "Git 源码部署", "source": "源码包部署"}.get(local["mode"], local["mode"])
    print(f"部署方式: {mode_label}")
    print(f"当前提交: {local['short_commit'] or '未知'}")
    print(f"最新提交: {remote['short_commit']} ({remote['commit_time'] or '-'}) [{remote['source']}]")
    if remote.get("commit_message"):
        print(f"提交说明: {remote['commit_message']}")

    if not info["has_update"] and not force:
        print("当前已是最新版本。")
        return 0

    if info["new_commits"]:
        print("最近新增提交:")
        for item in info["new_commits"][:5]:
            print(f"  - {item['short_sha']} {item['message']}")

    if check_only:
        print("发现新版本，可运行 `python main.py update` 执行更新。")
        if local["mode"] == "docker" and not local.get("docker_socket_available"):
            print("提示: 当前容器未挂载 /var/run/docker.sock，请在宿主机执行:")
            print(info["manual_command"])
        return 0

    result = apply_update(
        github_mirror=effective_gh_mirror,
        ghcr_mirror=effective_ghcr_mirror,
        force=force,
        on_progress=lambda msg: print(f"[更新] {msg}"),
    )
    print(result["message"])
    if result.get("updated") and local["mode"] != "docker":
        print("请重新启动程序以加载新版本。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
