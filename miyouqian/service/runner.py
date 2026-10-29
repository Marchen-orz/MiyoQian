# -*- coding: utf-8 -*-
"""任务执行编排。"""

from __future__ import annotations

from typing import Any, Callable

from ..core import device as devicelib
from ..core.config import find_account, save_config
from ..core.http import ApiClient
from ..core.region import REGION_CN, REGION_OS, account_region
from ..overseas.checkin import HoyolabCheckin
from ..tasks.bbs import BbsTasks
from ..tasks.cloud_games import CloudGameCheckin
from ..tasks.games import GameCheckin

EmitFn = Callable[[str], None]
ComponentEmitFn = Callable[[str, str], None]


def run_tasks(
    config: dict[str, Any],
    config_path: str,
    account_name: str | None = None,
    games_only: bool = False,
    bbs_only: bool = False,
    only_games: list[str] | None = None,
    emit: EmitFn | None = None,
    emit_component: ComponentEmitFn | None = None,
) -> list[str]:
    output: list[str] = []

    def add(message: str, component: str = "task") -> None:
        output.append(message)
        if emit_component:
            emit_component(message, component)
        elif emit:
            emit(message)

    def run_stage(stage: str, component: str, failed_prefix: str, run: Callable[[], list[str]]) -> None:
        try:
            lines = run()
        except Exception as exc:
            # 某个阶段整体异常也只记为该阶段失败，后面的阶段和账号照常执行
            add(f"{failed_prefix}{stage}执行异常: {exc}", component)
            return
        if not should_emit:
            output.extend(lines)

    if games_only and bbs_only:
        raise ValueError("games_only 和 bbs_only 不能同时启用")
    if not config.get("enable", True):
        add("配置 enable=false，已跳过。")
        return output
    accounts = [find_account(config, account_name)] if account_name else list(config.get("accounts", []))
    if not accounts:
        add("没有配置账号，已跳过。")
        return output
    should_emit = bool(emit or emit_component)
    features = config.get("features", {})

    def run_cn_account(client: ApiClient, account: dict[str, Any]) -> None:
        if not bbs_only and features.get("game_checkin", True):
            run_stage(
                "游戏社区签到",
                "game",
                "游戏社区失败项：",
                lambda: GameCheckin(
                    client,
                    config,
                    account,
                    emit=(lambda message: add(message, "game")) if should_emit else None,
                ).run(only_games=only_games),
            )
        if not bbs_only and features.get("cloud_game_checkin", False):
            run_stage(
                "云游戏签到",
                "cloud",
                "云游戏失败项：",
                lambda: CloudGameCheckin(
                    client,
                    config,
                    account,
                    emit=(lambda message: add(message, "cloud")) if should_emit else None,
                ).run(),
            )
        if not games_only and features.get("bbs_tasks", False):
            run_stage(
                "米游币任务",
                "bbs",
                "米游币失败项：",
                lambda: BbsTasks(
                    client,
                    config,
                    account,
                    emit=(lambda message: add(message, "bbs")) if should_emit else None,
                ).run(),
            )

    def run_os_account(client: ApiClient, account: dict[str, Any]) -> None:
        if not bbs_only and features.get("game_checkin", True):
            run_stage(
                "游戏社区签到",
                "game",
                "游戏社区失败项：",
                lambda: HoyolabCheckin(
                    client,
                    config,
                    account,
                    emit=(lambda message: add(message, "game")) if should_emit else None,
                ).run(only_games=only_games),
            )
        unsupported = [
            label
            for label, wanted in (
                ("云游戏签到", not bbs_only and features.get("cloud_game_checkin", False)),
                ("米游币任务", not games_only and features.get("bbs_tasks", False)),
            )
            if wanted
        ]
        if unsupported:
            add(f"国际服账号暂不支持{'、'.join(unsupported)}，已跳过")

    # 国服 / 国际服共用一份账号列表和配置，只在这里按账号的 region 分发到各自的实现
    runners = {REGION_CN: run_cn_account, REGION_OS: run_os_account}
    # 米游币任务的请求头会带 x-rpc-device_fp：开跑前确认有可信的 fp，没有就向服务器申请一次。
    # 申请失败也照常执行，只是请求里不带这个头
    device = config.get("device")
    wants_bbs_fp = (
        not games_only
        and features.get("bbs_tasks", False)
        and isinstance(device, dict)
        and any(account_region(account) == REGION_CN for account in accounts)
    )
    with ApiClient() as client:
        if wants_bbs_fp and devicelib.needs_fp(device):
            ok, reason = devicelib.ensure_device_fp(client, device, emit=add)
            if not ok:
                consequence = "沿用配置里已有的 device_fp" if devicelib.effective_fp(device) else "请求里不带 x-rpc-device_fp"
                add(f"device_fp 暂时无法获取（{reason}），本次米游币任务{consequence}", "bbs")
        for index, account in enumerate(accounts, start=1):
            region = account_region(account)
            suffix = "（国际服）" if region == REGION_OS else ""
            add(f"# 账号 {index}/{len(accounts)}: {account.get('name', '未命名')}{suffix}")
            runners[region](client, account)
    save_config(config_path, config)
    return output
