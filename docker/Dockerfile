FROM python:3.11-slim-bookworm

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:${PATH}"

# 安装固定版本 uv，避免 latest 变化导致构建结果不可预测
COPY --from=ghcr.io/astral-sh/uv:0.7.3 /uv /usr/local/bin/uv

# 先复制依赖文件，利用 Docker 缓存层
COPY pyproject.toml uv.lock ./

# 安装依赖（不包含开发依赖）
RUN uv sync --frozen --no-dev --no-install-project

# 复制项目源码
COPY miyouqian/ ./miyouqian/
COPY main.py .
COPY config.example.yaml .
COPY docker/entrypoint.sh /entrypoint.sh
# 对entrypoint.sh做兼容性修复，防止windows环境下因CRLF问题报错。
RUN sed -i 's/\r$//' /entrypoint.sh

RUN groupadd --system myq \
    && useradd --system --gid myq --home-dir /app --shell /usr/sbin/nologin myq \
    && mkdir -p /app/state/data /app/state/logs \
    && chmod +x /entrypoint.sh \
    && chown -R myq:myq /app /app/state /entrypoint.sh /opt/venv

EXPOSE 5890

VOLUME ["/app/state"]

USER myq

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5890/api/auth/status', timeout=3).read()"

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "main.py", "--config", "/app/state/config.yaml", "serve", "--host", "0.0.0.0", "--port", "5890"]
