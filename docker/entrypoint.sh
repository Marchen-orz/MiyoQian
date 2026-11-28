#!/bin/sh
set -e

CONFIG_PATH="${MIYOUQIAN_CONFIG_PATH:-/app/state/config.yaml}"
CONFIG_DIR="$(dirname "$CONFIG_PATH")"

umask 077

# 创建必要的目录
mkdir -p "$CONFIG_DIR" "$CONFIG_DIR/data" "$CONFIG_DIR/logs"

# 如果 config.yaml 不存在，从示例配置复制
if [ ! -f "$CONFIG_PATH" ]; then
  echo "[entrypoint] config.yaml not found, copying from config.example.yaml"
  cp /app/config.example.yaml "$CONFIG_PATH"
fi

chmod 700 "$CONFIG_DIR" "$CONFIG_DIR/data" "$CONFIG_DIR/logs"
chmod 600 "$CONFIG_PATH"

# 当 compose 以 root 启动（为了兼容不同宿主机的 docker.sock 权限）时，
# 统一修正状态卷归属并尽可能降权到 myq 运行；仅当 docker.sock 为 0600 仅 root 可访问时保留 root。
if [ "$(id -u)" = "0" ]; then
  chown -R myq:myq "$CONFIG_DIR"
  exec python -c '
import os, pwd, stat, sys
cmd = sys.argv[1:]
sock = "/var/run/docker.sock"
pw = pwd.getpwnam("myq")
keep_root = False
extra_gids = [pw.pw_gid]
if os.path.exists(sock):
    st = os.stat(sock)
    mode = stat.S_IMODE(st.st_mode)
    if (mode & 0o060) == 0o060:
        if st.st_gid not in extra_gids:
            extra_gids.append(st.st_gid)
    elif (mode & 0o006) != 0o006:
        keep_root = True
if not keep_root:
    os.setgroups(extra_gids)
    os.setgid(pw.pw_gid)
    os.setuid(pw.pw_uid)
os.execvp(cmd[0], cmd)
' "$@"
fi

exec "$@"
