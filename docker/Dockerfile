FROM python:3.11-slim-bookworm

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:${PATH}"

RUN python -m venv /opt/venv

COPY requirements.txt ./
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY miyouqian/ ./miyouqian/
COPY main.py .
COPY config.example.yaml .
COPY docker/entrypoint.sh /entrypoint.sh
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
