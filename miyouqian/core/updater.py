# -*- coding: utf-8 -*-
"""版本检查与自动更新（支持直接部署与 Docker 容器）。"""

from __future__ import annotations

import argparse
import io
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, Callable
from urllib.parse import quote, urlparse

import httpx

GITHUB_OWNER = "Marchen-orz"
GITHUB_REPO_NAME = "MiyoQian"
GITHUB_REPO = f"{GITHUB_OWNER}/{GITHUB_REPO_NAME}"
GITHUB_BRANCH = "master"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_REPO}.git"
GITHUB_ATOM_URL = f"https://github.com/{GITHUB_REPO}/commits/{GITHUB_BRANCH}.atom"
GITHUB_API_COMMIT_URL = f"https://api.github.com/repos/{GITHUB_REPO}/commits/{GITHUB_BRANCH}"
GITHUB_ARCHIVE_URL = f"https://github.com/{GITHUB_REPO}/archive/refs/heads/{GITHUB_BRANCH}.zip"

GHCR_REGISTRY = "ghcr.io"
GHCR_IMAGE_PATH = f"{GITHUB_OWNER.lower()}/{GITHUB_REPO_NAME.lower()}"
GHCR_DEFAULT_IMAGE = f"{GHCR_REGISTRY}/{GHCR_IMAGE_PATH}:latest"
DEFAULT_GHCR_MIRROR = "ghcr.nju.edu.cn"

# 国内访问 GitHub 失败时自动回退的加速前缀
DEFAULT_GITHUB_MIRRORS: tuple[str, ...] = (
    "https://gh-proxy.org/",
    "https://hk.gh-proxy.org/",
)

DOCKER_SOCKET_PATH = "/var/run/docker.sock"
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
VERSION_MARKER_FILE = ".miyouqian_version.json"

# 压缩包更新时只覆盖项目代码与文档，绝不触碰用户配置、凭证、日志和虚拟环境
ARCHIVE_ALLOWED_FILES = {
    "main.py",
    "index.py",
    "pyproject.toml",
    "uv.lock",
    "requirements.txt",
    "config.example.yaml",
    "README.md",
    "LICENSE",
}
ARCHIVE_ALLOWED_DIRS = ("miyouqian", "docker")
DEPENDENCY_FILES = {"pyproject.toml", "uv.lock", "requirements.txt"}

ProgressCallback = Callable[[str], None]


def normalize_github_mirror(value: str) -> str:
    """规范化 GitHub 加速前缀，要求空字符串或 http(s) URL。"""
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("GitHub 加速地址需为合法的 http(s) URL，例如 https://gh-proxy.org/")
    if any(ch.isspace() for ch in text):
        raise ValueError("GitHub 加速地址不能包含空白字符")
    return text.rstrip("/") + "/"


def normalize_ghcr_mirror(value: str) -> str:
    """规范化 GHCR 镜像加速域名，例如 ghcr.nju.edu.cn。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" in text:
        parsed = urlparse(text)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("GHCR 加速地址格式不正确，例如 ghcr.nju.edu.cn")
        host = parsed.netloc.strip()
    else:
        host = text.strip("/")
    if not host or any(ch.isspace() or ch in "/\\" for ch in host):
        raise ValueError("GHCR 加速地址需为域名（可含端口），例如 ghcr.nju.edu.cn")
    if not re.fullmatch(r"[A-Za-z0-9.-]+(?::\d+)?", host):
        raise ValueError("GHCR 加速地址包含非法字符")
    return host.lower()


def wrap_github_url(url: str, mirror_prefix: str) -> str:
    prefix = normalize_github_mirror(mirror_prefix)
    if not prefix:
        return url
    return f"{prefix}{url}"


def is_in_docker() -> bool:
    if os.environ.get("MIYOUQIAN_IN_DOCKER") == "1":
        return True
    if pathlib.Path("/.dockerenv").exists():
        return True
    cgroup = pathlib.Path("/proc/1/cgroup")
    if cgroup.is_file():
        try:
            content = cgroup.read_text(encoding="utf-8", errors="ignore")
            if any(token in content for token in ("docker", "containerd", "kubepods")):
                return True
        except OSError:
            pass
    return False


def detect_deploy_mode(project_root: pathlib.Path | None = None) -> str:
    root = project_root or PROJECT_ROOT
    if is_in_docker():
        return "docker"
    if (root / ".git").exists():
        return "git"
    return "source"


def short_sha(commit: str) -> str:
    text = str(commit or "").strip()
    return text[:7] if len(text) >= 7 else text


def split_image_ref(image_ref: str) -> tuple[str, str]:
    """拆分镜像名为 (repository, tag)，如 ghcr.io/a/b:latest -> ('ghcr.io/a/b', 'latest')。"""
    text = str(image_ref or "").strip()
    if not text:
        return f"{GHCR_REGISTRY}/{GHCR_IMAGE_PATH}", "latest"
    if "@" in text:
        repo = text.split("@", 1)[0]
        return repo, "latest"
    last_slash = text.rfind("/")
    last_colon = text.rfind(":")
    if last_colon > last_slash:
        return text[:last_colon], text[last_colon + 1 :] or "latest"
    return text, "latest"


def mirror_image_ref(image_ref: str, mirror_host: str) -> str:
    """把 ghcr.io/<repo>:<tag> 改写为 <mirror_host>/<repo>:<tag>。"""
    repo, tag = split_image_ref(image_ref)
    host = normalize_ghcr_mirror(mirror_host)
    if not host:
        return f"{repo}:{tag}"
    parts = repo.split("/", 1)
    if len(parts) == 2 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        path = parts[1]
    else:
        path = GHCR_IMAGE_PATH
    return f"{host}/{path}:{tag}"


def build_docker_manual_command(
    image_ref: str = GHCR_DEFAULT_IMAGE,
    ghcr_mirror: str = "",
) -> str:
    """生成给未挂载 docker.sock 用户的宿主机更新命令提示。"""
    mirror = normalize_ghcr_mirror(ghcr_mirror) or DEFAULT_GHCR_MIRROR
    mirrored = mirror_image_ref(image_ref or GHCR_DEFAULT_IMAGE, mirror)
    return (
        "docker compose pull && docker compose up -d\n"
        f"# 如国内直连 ghcr.io 失败，可将 compose 里的 image 改为 {mirrored} 后再执行上述命令"
    )


# ---------------------------------------------------------------------------
# 远程版本查询（GitHub Atom / API + 国内加速镜像 + NJU GHCR OCI 兜底）
# ---------------------------------------------------------------------------

def parse_github_atom(xml_text: str, limit: int = 20) -> list[dict[str, str]]:
    """解析 GitHub commits Atom feed，返回按时间倒序排列的提交列表。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(f"解析 GitHub Atom 失败: {exc}") from exc

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns)
    if not entries:
        entries = root.findall("entry")

    commits: list[dict[str, str]] = []
    for entry in entries[:limit]:
        entry_id = (entry.findtext("atom:id", default="", namespaces=ns) or entry.findtext("id") or "").strip()
        match = re.search(r"([0-9a-fA-F]{40})$", entry_id)
        link_el = entry.find("atom:link[@rel='alternate']", ns)
        if link_el is None:
            link_el = entry.find("atom:link", ns)
        if link_el is None:
            link_el = entry.find("link")
        url = (link_el.attrib.get("href", "") if link_el is not None else "").strip()
        if not match and url:
            match = re.search(r"/commit/([0-9a-fA-F]{40})", url)
        if not match:
            continue
        sha = match.group(1).lower()
        title = (entry.findtext("atom:title", default="", namespaces=ns) or entry.findtext("title") or "").strip()
        title = re.sub(r"\s+", " ", title)
        updated = (entry.findtext("atom:updated", default="", namespaces=ns) or entry.findtext("updated") or "").strip()
        author = (
            entry.findtext("atom:author/atom:name", default="", namespaces=ns)
            or entry.findtext("author/name")
            or ""
        ).strip()
        commits.append(
            {
                "sha": sha,
                "short_sha": short_sha(sha),
                "message": title,
                "date": updated,
                "author": author,
                "url": url or f"https://github.com/{GITHUB_REPO}/commit/{sha}",
            }
        )
    if not commits:
        raise RuntimeError("Atom feed 中未解析到提交记录")
    return commits


def parse_github_api_commit(data: dict[str, Any]) -> dict[str, str]:
    sha = str(data.get("sha") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("GitHub API 返回中缺少有效的 commit SHA")
    commit_obj = data.get("commit") if isinstance(data.get("commit"), dict) else {}
    message = str(commit_obj.get("message") or "").strip().splitlines()[0] if commit_obj.get("message") else ""
    committer = commit_obj.get("committer") if isinstance(commit_obj.get("committer"), dict) else {}
    author = commit_obj.get("author") if isinstance(commit_obj.get("author"), dict) else {}
    date = str(committer.get("date") or author.get("date") or "").strip()
    author_name = str(author.get("name") or "").strip()
    url = str(data.get("html_url") or f"https://github.com/{GITHUB_REPO}/commit/{sha}").strip()
    return {
        "sha": sha,
        "short_sha": short_sha(sha),
        "message": message,
        "date": date,
        "author": author_name,
        "url": url,
    }


def _fetch_oci_revision(client: httpx.Client, registry_host: str, image_path: str = GHCR_IMAGE_PATH) -> dict[str, str]:
    """从 OCI Registry（如 ghcr.nju.edu.cn）读取 latest 镜像的 git revision 标签。"""
    headers = {
        "Accept": (
            "application/vnd.oci.image.index.v1+json, "
            "application/vnd.docker.distribution.manifest.list.v2+json, "
            "application/vnd.oci.image.manifest.v1+json, "
            "application/vnd.docker.distribution.manifest.v2+json"
        ),
        "User-Agent": "MiyoQian-Updater",
    }
    manifest_url = f"https://{registry_host}/v2/{image_path}/manifests/latest"
    resp = client.get(manifest_url, headers=headers)
    if resp.status_code == 401 and registry_host == GHCR_REGISTRY:
        token_resp = client.get(
            f"https://{registry_host}/token?scope=repository:{image_path}:pull",
            headers={"User-Agent": "MiyoQian-Updater"},
        )
        token_resp.raise_for_status()
        token = str(token_resp.json().get("token") or "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
            resp = client.get(manifest_url, headers=headers)
    resp.raise_for_status()
    payload = resp.json()

    if isinstance(payload.get("manifests"), list) and payload["manifests"]:
        chosen = next(
            (m for m in payload["manifests"] if (m.get("platform") or {}).get("architecture") == "amd64"),
            payload["manifests"][0],
        )
        sub_digest = str(chosen.get("digest") or "")
        sub_resp = client.get(f"https://{registry_host}/v2/{image_path}/manifests/{sub_digest}", headers=headers)
        sub_resp.raise_for_status()
        payload = sub_resp.json()

    config_digest = str((payload.get("config") or {}).get("digest") or "")
    if not config_digest:
        raise RuntimeError(f"{registry_host} 镜像 manifest 缺少 config digest")

    blob_headers = {"User-Agent": "MiyoQian-Updater"}
    if "Authorization" in headers:
        blob_headers["Authorization"] = headers["Authorization"]
    cfg_resp = client.get(f"https://{registry_host}/v2/{image_path}/blobs/{config_digest}", headers=blob_headers)
    cfg_resp.raise_for_status()
    cfg = cfg_resp.json()
    labels = ((cfg.get("config") or {}).get("Labels") or {}) if isinstance(cfg, dict) else {}
    sha = str(labels.get("org.opencontainers.image.revision") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError(f"{registry_host} 镜像未包含 revision 标签")
    created = str(labels.get("org.opencontainers.image.created") or cfg.get("created") or "").strip()
    return {
        "sha": sha,
        "short_sha": short_sha(sha),
        "message": "最新已构建 Docker 镜像",
        "date": created,
        "author": GITHUB_OWNER,
        "url": f"https://github.com/{GITHUB_REPO}/commit/{sha}",
    }


def fetch_remote_commits(
    github_mirror: str = "",
    ghcr_mirror: str = "",
    timeout: float = 8.0,
) -> dict[str, Any]:
    """查询 GitHub 仓库最新提交，直连失败时自动通过加速镜像与 NJU GHCR 源回退。"""
    custom_gh = normalize_github_mirror(github_mirror) if github_mirror else ""
    custom_ghcr = normalize_ghcr_mirror(ghcr_mirror) if ghcr_mirror else ""

    candidates: list[tuple[str, str, str]] = []
    if custom_gh:
        candidates.append((f"自定义加速源 ({urlparse(custom_gh).netloc})", "atom", wrap_github_url(GITHUB_ATOM_URL, custom_gh)))
    candidates.append(("GitHub", "atom", GITHUB_ATOM_URL))
    candidates.append(("GitHub API", "api", GITHUB_API_COMMIT_URL))
    for prefix in DEFAULT_GITHUB_MIRRORS:
        if prefix == custom_gh:
            continue
        candidates.append((f"加速源 ({urlparse(prefix).netloc})", "atom", wrap_github_url(GITHUB_ATOM_URL, prefix)))
    oci_hosts: list[str] = []
    if custom_ghcr:
        oci_hosts.append(custom_ghcr)
    if DEFAULT_GHCR_MIRROR not in oci_hosts:
        oci_hosts.append(DEFAULT_GHCR_MIRROR)
    for host in oci_hosts:
        candidates.append((f"镜像仓库 ({host})", "oci", host))

    errors: list[str] = []
    headers = {"User-Agent": "MiyoQian-Updater", "Accept": "application/atom+xml, application/json"}
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for source_label, kind, target in candidates:
            try:
                if kind == "atom":
                    resp = client.get(target, headers=headers)
                    resp.raise_for_status()
                    commits = parse_github_atom(resp.text)
                    return {"source": source_label, "latest": commits[0], "commits": commits}
                if kind == "api":
                    resp = client.get(
                        target,
                        headers={"User-Agent": "MiyoQian-Updater", "Accept": "application/vnd.github+json"},
                    )
                    resp.raise_for_status()
                    latest = parse_github_api_commit(resp.json())
                    return {"source": source_label, "latest": latest, "commits": [latest]}
                if kind == "oci":
                    latest = _fetch_oci_revision(client, target)
                    return {"source": source_label, "latest": latest, "commits": [latest]}
            except Exception as exc:
                errors.append(f"{source_label}: {exc}")
                continue

    detail = "；".join(errors[:4])
    raise RuntimeError(f"无法获取最新版本信息（所有检测源均失败）：{detail}")


# ---------------------------------------------------------------------------
# Docker Engine Unix Socket 客户端
# ---------------------------------------------------------------------------

class DockerSocketClient:
    """直接通过 /var/run/docker.sock 调用 Docker Engine HTTP API，无需 docker CLI。"""

    def __init__(self, socket_path: str = DOCKER_SOCKET_PATH, timeout: float = 30.0) -> None:
        self.socket_path = socket_path
        self.timeout = timeout

    def _client(self, timeout: float | None = None) -> httpx.Client:
        transport = httpx.HTTPTransport(uds=self.socket_path)
        return httpx.Client(
            transport=transport,
            base_url="http://docker",
            timeout=timeout or self.timeout,
        )

    def ping(self) -> tuple[bool, str]:
        if not os.path.exists(self.socket_path):
            return False, f"未挂载 {self.socket_path}"
        try:
            with self._client(timeout=3.0) as client:
                resp = client.get("/_ping")
                if resp.status_code == 200:
                    return True, ""
                return False, f"Docker API 返回 HTTP {resp.status_code}"
        except PermissionError:
            return False, f"无权限访问 {self.socket_path}"
        except Exception as exc:
            return False, str(exc)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        timeout: float | None = None,
    ) -> Any:
        with self._client(timeout=timeout) as client:
            resp = client.request(method, path, params=params, json=json_body)
            if resp.status_code >= 400:
                message = resp.text.strip()
                try:
                    data = resp.json()
                    if isinstance(data, dict) and data.get("message"):
                        message = str(data["message"])
                except ValueError:
                    pass
                raise RuntimeError(f"Docker API {method} {path} 失败 ({resp.status_code}): {message}")
            if not resp.content:
                return {}
            return resp.json()

    def inspect_container(self, container_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/containers/{quote(container_id, safe='')}/json")

    def list_containers(self, all_containers: bool = False) -> list[dict[str, Any]]:
        data = self._request_json("GET", "/containers/json", params={"all": "1" if all_containers else "0"})
        return data if isinstance(data, list) else []

    def inspect_image(self, image_ref: str) -> dict[str, Any]:
        return self._request_json("GET", f"/images/{quote(image_ref, safe='/:@')}/json")

    def pull_image(
        self,
        repo: str,
        tag: str = "latest",
        on_progress: ProgressCallback | None = None,
    ) -> None:
        """拉取镜像并解析 NDJSON 流中的错误（Docker 在拉取中途失败时仍返回 HTTP 200）。"""
        last_status = ""
        with self._client(timeout=300.0) as client:
            with client.stream(
                "POST",
                "/images/create",
                params={"fromImage": repo, "tag": tag},
            ) as resp:
                if resp.status_code >= 400:
                    body = resp.read().decode("utf-8", errors="ignore").strip()
                    raise RuntimeError(f"拉取镜像 {repo}:{tag} 失败 ({resp.status_code}): {body}")
                for raw_line in resp.iter_lines():
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    if event.get("error") or (isinstance(event.get("errorDetail"), dict) and event["errorDetail"].get("message")):
                        err_msg = str(event.get("error") or event["errorDetail"].get("message"))
                        raise RuntimeError(f"拉取镜像 {repo}:{tag} 失败: {err_msg}")
                    status = str(event.get("status") or "").strip()
                    if status and status != last_status and on_progress:
                        last_status = status
                        on_progress(f"正在拉取镜像 {repo}:{tag}（{status}）")

    def tag_image(self, source_ref: str, target_repo: str, target_tag: str) -> None:
        self._request_json(
            "POST",
            f"/images/{quote(source_ref, safe='/:@')}/tag",
            params={"repo": target_repo, "tag": target_tag},
        )

    def create_container(self, body: dict[str, Any], name: str = "") -> str:
        params = {"name": name} if name else None
        data = self._request_json("POST", "/containers/create", params=params, json_body=body)
        container_id = str(data.get("Id") or "")
        if not container_id:
            raise RuntimeError("Docker 创建容器未返回容器 ID")
        return container_id

    def start_container(self, container_id: str) -> None:
        self._request_json("POST", f"/containers/{quote(container_id, safe='')}/start")

    def stop_container(self, container_id: str, timeout_seconds: int = 15) -> None:
        self._request_json(
            "POST",
            f"/containers/{quote(container_id, safe='')}/stop",
            params={"t": str(timeout_seconds)},
            timeout=float(timeout_seconds) + 15.0,
        )

    def rename_container(self, container_id: str, new_name: str) -> None:
        self._request_json(
            "POST",
            f"/containers/{quote(container_id, safe='')}/rename",
            params={"name": new_name},
        )

    def remove_container(self, container_id: str, force: bool = False) -> None:
        self._request_json(
            "DELETE",
            f"/containers/{quote(container_id, safe='')}",
            params={"force": "1" if force else "0"},
        )

    def connect_network(self, network_name: str, container_id: str, endpoint_config: dict[str, Any] | None = None) -> None:
        body: dict[str, Any] = {"Container": container_id}
        if endpoint_config:
            body["EndpointConfig"] = endpoint_config
        self._request_json("POST", f"/networks/{quote(network_name, safe='')}/connect", json_body=body)


def detect_self_container_id(client: DockerSocketClient | None = None) -> str:
    """在 Docker 容器内识别当前容器 ID。"""
    for proc_file in ("/proc/self/mountinfo", "/proc/self/cgroup"):
        path = pathlib.Path(proc_file)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        match = re.search(r"/docker/containers/([0-9a-f]{64})/", text)
        if not match:
            match = re.search(r"docker[-/]([0-9a-f]{64})", text)
        if match:
            return match.group(1)

    hostname = socket.gethostname().strip()
    if client is not None:
        if hostname:
            try:
                inspected = client.inspect_container(hostname)
                if inspected.get("Id"):
                    return str(inspected["Id"])
            except Exception:
                pass
        try:
            for item in client.list_containers():
                cid = str(item.get("Id") or "")
                names = [str(n).lstrip("/") for n in (item.get("Names") or [])]
                image = str(item.get("Image") or "").lower()
                if (hostname and cid.startswith(hostname)) or "miyouqian" in names or "miyouqian" in image:
                    return cid
        except Exception:
            pass
    return hostname


def find_docker_socket_host_source(inspected: dict[str, Any], container_socket_path: str = DOCKER_SOCKET_PATH) -> str:
    """从容器 Mounts 中找到 docker.sock 在宿主机上的真实路径。"""
    for mount in inspected.get("Mounts") or []:
        if isinstance(mount, dict) and str(mount.get("Destination") or "") == container_socket_path:
            source = str(mount.get("Source") or "").strip()
            if source:
                return source
    return container_socket_path


def build_recreate_payload(inspected: dict[str, Any], new_image: str) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]]:
    """根据旧容器 inspect 信息构造重建载荷与额外网络列表，保留卷、端口、环境变量与 Compose 标签。"""
    old_id = str(inspected.get("Id") or "")
    short_old = old_id[:12]
    old_config = dict(inspected.get("Config") or {})
    old_host_config = dict(inspected.get("HostConfig") or {})

    create_body: dict[str, Any] = {}
    config_keys = (
        "User",
        "ExposedPorts",
        "Tty",
        "OpenStdin",
        "StdinOnce",
        "Env",
        "Cmd",
        "Healthcheck",
        "Volumes",
        "WorkingDir",
        "Entrypoint",
        "Labels",
        "StopSignal",
        "StopTimeout",
        "Domainname",
    )
    for key in config_keys:
        if key in old_config and old_config[key] is not None:
            create_body[key] = old_config[key]

    # 移除镜像内置的版本环境变量，确保新容器继承新镜像自己的 BUILD_COMMIT / BUILD_DATE，
    # 避免旧镜像的提交号覆盖新镜像导致重启后一直误报有更新
    if isinstance(create_body.get("Env"), list):
        create_body["Env"] = [
            item
            for item in create_body["Env"]
            if not str(item).startswith(("MIYOUQIAN_BUILD_COMMIT=", "MIYOUQIAN_BUILD_DATE=", "MIYOUQIAN_IN_DOCKER="))
        ]

    # 仅保留用户显式设置的自定义 Hostname；默认等于旧短容器 ID 的交由 Docker 重新生成
    old_hostname = str(old_config.get("Hostname") or "")
    if old_hostname and short_old and old_hostname != short_old:
        create_body["Hostname"] = old_hostname

    create_body["Image"] = new_image
    create_body["HostConfig"] = old_host_config

    network_mode = str(old_host_config.get("NetworkMode") or "")
    networks = ((inspected.get("NetworkSettings") or {}).get("Networks") or {})
    extra_networks: list[tuple[str, dict[str, Any]]] = []
    if (
        isinstance(networks, dict)
        and networks
        and network_mode not in ("host", "none")
        and not network_mode.startswith("container:")
    ):
        network_items = list(networks.items())
        primary_name, primary_raw = network_items[0]
        create_body["NetworkingConfig"] = {
            "EndpointsConfig": {
                primary_name: _sanitize_endpoint_config(primary_raw, short_old, network_name=primary_name),
            }
        }
        for net_name, net_raw in network_items[1:]:
            extra_networks.append((net_name, _sanitize_endpoint_config(net_raw, short_old, network_name=net_name)))

    return create_body, extra_networks


def _sanitize_endpoint_config(raw: Any, old_short_id: str, *, network_name: str = "") -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    endpoint: dict[str, Any] = {}
    if isinstance(raw.get("IPAMConfig"), dict) and raw["IPAMConfig"]:
        endpoint["IPAMConfig"] = raw["IPAMConfig"]
    if isinstance(raw.get("Links"), list) and raw["Links"]:
        endpoint["Links"] = raw["Links"]
    # Docker 只允许在用户自定义网络上设置 Aliases，默认 bridge/host/none 传 Aliases 会报 400
    if network_name not in ("bridge", "host", "none") and isinstance(raw.get("Aliases"), list):
        aliases = [a for a in raw["Aliases"] if a and a != old_short_id]
        if aliases:
            endpoint["Aliases"] = aliases
    return endpoint


def run_docker_recreate_helper(
    target_id: str,
    new_image: str,
    socket_path: str = DOCKER_SOCKET_PATH,
    delay_seconds: float = 1.5,
) -> str:
    """在临时 helper 容器中执行安全替换：停旧容器 -> 重命名备份 -> 建新启动 -> 失败自动回滚。"""
    if delay_seconds > 0:
        time.sleep(delay_seconds)
    client = DockerSocketClient(socket_path=socket_path)
    inspected = client.inspect_container(target_id)
    full_old_id = str(inspected.get("Id") or target_id)
    original_name = str(inspected.get("Name") or "").lstrip("/")
    if not original_name:
        raise RuntimeError("无法获取原容器名称")

    create_body, extra_networks = build_recreate_payload(inspected, new_image)
    backup_name = f"{original_name}-old-{int(time.time())}"
    new_container_id = ""
    renamed = False
    stopped = False

    try:
        client.stop_container(full_old_id, timeout_seconds=15)
        stopped = True
        client.rename_container(full_old_id, backup_name)
        renamed = True
        new_container_id = client.create_container(create_body, name=original_name)
        for net_name, endpoint_cfg in extra_networks:
            client.connect_network(net_name, new_container_id, endpoint_cfg)
        client.start_container(new_container_id)
    except Exception as exc:
        # 任何一步失败都尽力把旧容器恢复并重新拉起，避免服务失联
        if new_container_id:
            try:
                client.remove_container(new_container_id, force=True)
            except Exception:
                pass
        if renamed:
            try:
                client.rename_container(full_old_id, original_name)
            except Exception:
                pass
        if stopped:
            try:
                client.start_container(full_old_id)
            except Exception:
                pass
        raise RuntimeError(f"容器重建失败，已尝试回滚旧容器: {exc}") from exc

    try:
        client.remove_container(full_old_id, force=False)
    except Exception:
        pass
    return new_container_id


# ---------------------------------------------------------------------------
# 本地版本识别与更新检查
# ---------------------------------------------------------------------------

def _run_git(args: list[str], cwd: pathlib.Path, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def get_local_version(
    project_root: pathlib.Path | None = None,
    socket_path: str = DOCKER_SOCKET_PATH,
) -> dict[str, Any]:
    """读取当前部署模式与版本提交信息。"""
    root = project_root or PROJECT_ROOT
    mode = detect_deploy_mode(root)
    info: dict[str, Any] = {
        "mode": mode,
        "commit": "",
        "short_commit": "",
        "commit_time": "",
        "commit_message": "",
        "branch": GITHUB_BRANCH,
        "dirty": False,
        "dirty_files": [],
        "image": "",
        "docker_socket_available": False,
        "docker_socket_error": "",
        "can_auto_update": False,
    }

    if mode == "docker":
        info["commit"] = str(os.environ.get("MIYOUQIAN_BUILD_COMMIT") or "").strip().lower()
        info["commit_time"] = str(os.environ.get("MIYOUQIAN_BUILD_TIME") or "").strip()
        info["image"] = GHCR_DEFAULT_IMAGE

        client = DockerSocketClient(socket_path=socket_path)
        ok, err = client.ping()
        info["docker_socket_available"] = ok
        info["docker_socket_error"] = err
        info["can_auto_update"] = ok

        if ok:
            try:
                cid = detect_self_container_id(client)
                if cid:
                    inspected = client.inspect_container(cid)
                    cfg_image = str((inspected.get("Config") or {}).get("Image") or "").strip()
                    if cfg_image:
                        info["image"] = cfg_image
                    if not info["commit"]:
                        img_id = str(inspected.get("Image") or "")
                        if img_id:
                            img_info = client.inspect_image(img_id)
                            labels = ((img_info.get("Config") or {}).get("Labels") or {}) if isinstance(img_info, dict) else {}
                            rev = str(labels.get("org.opencontainers.image.revision") or "").strip().lower()
                            if rev:
                                info["commit"] = rev
                            if not info["commit_time"]:
                                info["commit_time"] = str(
                                    labels.get("org.opencontainers.image.created") or img_info.get("Created") or ""
                                ).strip()
            except Exception:
                pass

        info["short_commit"] = short_sha(info["commit"])
        return info

    if mode == "git":
        info["can_auto_update"] = True
        try:
            head = _run_git(["rev-parse", "HEAD"], root, timeout=10.0)
            if head.returncode == 0:
                info["commit"] = head.stdout.strip().lower()
                info["short_commit"] = short_sha(info["commit"])
            branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], root, timeout=10.0)
            if branch.returncode == 0 and branch.stdout.strip():
                info["branch"] = branch.stdout.strip()
            meta = _run_git(["show", "-s", "--format=%cI%n%s", "HEAD"], root, timeout=10.0)
            if meta.returncode == 0:
                lines = meta.stdout.splitlines()
                if lines:
                    info["commit_time"] = lines[0].strip()
                if len(lines) > 1:
                    info["commit_message"] = lines[1].strip()
            status = _run_git(["status", "--porcelain", "--untracked-files=no"], root, timeout=10.0)
            if status.returncode == 0:
                dirty_files = [line[3:].strip() for line in status.stdout.splitlines() if line.strip()]
                info["dirty_files"] = dirty_files
                info["dirty"] = bool(dirty_files)
        except Exception:
            pass
        return info

    # 压缩包 / 源码直接部署
    info["can_auto_update"] = True
    marker = root / VERSION_MARKER_FILE
    if marker.is_file():
        try:
            saved = json.loads(marker.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                info["commit"] = str(saved.get("commit") or "").strip().lower()
                info["short_commit"] = short_sha(info["commit"])
                info["commit_time"] = str(saved.get("commit_time") or "").strip()
                info["commit_message"] = str(saved.get("commit_message") or "").strip()
        except Exception:
            pass
    return info


def _is_git_ancestor(project_root: pathlib.Path, older_sha: str, newer_ref: str = "HEAD") -> bool:
    if not older_sha:
        return False
    try:
        res = _run_git(["merge-base", "--is-ancestor", older_sha, newer_ref], project_root, timeout=10.0)
        return res.returncode == 0
    except Exception:
        return False


def check_for_updates(
    *,
    github_mirror: str = "",
    ghcr_mirror: str = "",
    project_root: pathlib.Path | None = None,
    socket_path: str = DOCKER_SOCKET_PATH,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """检查 GitHub 最新提交并与本地版本对比。"""
    root = project_root or PROJECT_ROOT
    local = get_local_version(project_root=root, socket_path=socket_path)
    remote = fetch_remote_commits(github_mirror=github_mirror, ghcr_mirror=ghcr_mirror, timeout=timeout)
    latest = remote["latest"]
    commits = remote["commits"]
    local_commit = local["commit"]
    remote_commit = latest["sha"]

    if local_commit and local_commit == remote_commit:
        has_update = False
        ahead_commits: list[dict[str, str]] = []
    elif local_commit and local["mode"] == "git" and _is_git_ancestor(root, remote_commit, "HEAD"):
        # 本地开发分支已经包含了远端最新提交
        has_update = False
        ahead_commits = []
    else:
        has_update = True
        ahead_commits = []
        for item in commits:
            if local_commit and item["sha"] == local_commit:
                break
            ahead_commits.append(item)
            if len(ahead_commits) >= 8:
                break

    result: dict[str, Any] = {
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "local": local,
        "remote": {
            "repo": GITHUB_REPO,
            "branch": GITHUB_BRANCH,
            "commit": remote_commit,
            "short_commit": latest["short_sha"],
            "commit_time": latest["date"],
            "commit_message": latest["message"],
            "author": latest["author"],
            "url": latest["url"],
            "source": remote["source"],
        },
        "has_update": has_update,
        "new_commits": ahead_commits,
        "manual_command": (
            build_docker_manual_command(local.get("image") or GHCR_DEFAULT_IMAGE, ghcr_mirror=ghcr_mirror)
            if local["mode"] == "docker"
            else ""
        ),
    }
    return result


# ---------------------------------------------------------------------------
# 执行更新：Git / 源码压缩包 / Docker 容器
# ---------------------------------------------------------------------------

def _sync_dependencies(project_root: pathlib.Path, on_progress: ProgressCallback | None = None) -> str:
    """依赖文件变化时同步 Python 依赖。"""
    if on_progress:
        on_progress("检测到依赖变更，正在同步依赖…")
    uv_bin = shutil.which("uv")
    if uv_bin and (project_root / "uv.lock").is_file():
        cmd = [uv_bin, "sync", "--frozen", "--no-dev"]
        res = subprocess.run(cmd, cwd=str(project_root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180.0)
        if res.returncode == 0:
            return "uv sync 完成"
        # 回退清华 PyPI 源
        res2 = subprocess.run(
            [*cmd, "--index-url", "https://pypi.tuna.tsinghua.edu.cn/simple"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180.0,
        )
        if res2.returncode == 0:
            return "uv sync 完成（清华源）"
        raise RuntimeError(f"uv sync 失败: {(res2.stderr or res.stderr).strip()[:300]}")

    req_file = project_root / "requirements.txt"
    if req_file.is_file():
        cmd = [sys.executable, "-m", "pip", "install", "-r", str(req_file)]
        res = subprocess.run(cmd, cwd=str(project_root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180.0)
        if res.returncode == 0:
            return "pip 依赖同步完成"
        res2 = subprocess.run(
            [*cmd, "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180.0,
        )
        if res2.returncode == 0:
            return "pip 依赖同步完成（清华源）"
        raise RuntimeError(f"依赖安装失败: {(res2.stderr or res.stderr).strip()[:300]}")
    return ""


def _resolve_git_remote(project_root: pathlib.Path) -> tuple[str, str]:
    """返回当前分支跟踪的 (remote_name, remote_branch)，若未跟踪则返回 ('', GITHUB_BRANCH)。"""
    upstream = _run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], project_root, timeout=10.0)
    if upstream.returncode == 0 and "/" in upstream.stdout.strip():
        remote_name, branch_name = upstream.stdout.strip().split("/", 1)
        return remote_name, branch_name
    remotes = _run_git(["remote"], project_root, timeout=10.0)
    if remotes.returncode == 0:
        names = [line.strip() for line in remotes.stdout.splitlines() if line.strip()]
        if "origin" in names:
            return "origin", GITHUB_BRANCH
        if names:
            return names[0], GITHUB_BRANCH
    return "", GITHUB_BRANCH


def apply_git_update(
    *,
    github_mirror: str = "",
    project_root: pathlib.Path | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """在 Git 源码部署下执行 fetch + fast-forward pull，直连失败自动切加速镜像。"""
    root = project_root or PROJECT_ROOT
    local = get_local_version(project_root=root)
    if local["dirty"]:
        sample = "、".join(local["dirty_files"][:5])
        raise RuntimeError(f"工作区有未提交的本地修改（{sample}），为避免覆盖已中止更新")

    old_commit = local["commit"]
    custom_mirror = normalize_github_mirror(github_mirror) if github_mirror else ""
    remote_name, remote_branch = _resolve_git_remote(root)

    fetch_targets: list[tuple[str, str]] = []
    if custom_mirror:
        fetch_targets.append((f"自定义加速源 ({urlparse(custom_mirror).netloc})", wrap_github_url(GITHUB_REPO_URL, custom_mirror)))
    if remote_name:
        fetch_targets.append((f"Git 远端 ({remote_name})", remote_name))
    else:
        fetch_targets.append(("GitHub", GITHUB_REPO_URL))
    for prefix in DEFAULT_GITHUB_MIRRORS:
        if prefix == custom_mirror:
            continue
        fetch_targets.append((f"加速源 ({urlparse(prefix).netloc})", wrap_github_url(GITHUB_REPO_URL, prefix)))

    fetch_errors: list[str] = []
    used_source = ""
    for label, target in fetch_targets:
        if on_progress:
            on_progress(f"正在通过 {label} 拉取代码…")
        try:
            res = _run_git(["fetch", "--no-tags", target, remote_branch], root, timeout=60.0)
        except subprocess.TimeoutExpired:
            fetch_errors.append(f"{label}: 连接超时")
            continue
        if res.returncode == 0:
            used_source = label
            break
        err_text = (res.stderr or res.stdout).strip().splitlines()[-1:] or ["拉取失败"]
        fetch_errors.append(f"{label}: {err_text[0]}")

    if not used_source:
        raise RuntimeError("拉取代码失败：" + "；".join(fetch_errors[:4]))

    fetch_head = _run_git(["rev-parse", "FETCH_HEAD"], root, timeout=10.0)
    if fetch_head.returncode != 0:
        raise RuntimeError("无法解析拉取到的提交（FETCH_HEAD）")
    target_commit = fetch_head.stdout.strip().lower()

    if old_commit and (old_commit == target_commit or _is_git_ancestor(root, target_commit, "HEAD")):
        return {
            "mode": "git",
            "updated": False,
            "restart_required": False,
            "old_commit": old_commit,
            "new_commit": old_commit,
            "source": used_source,
            "deps_synced": "",
            "message": "当前代码已是最新版本",
        }

    if on_progress:
        on_progress(f"正在合并到 {short_sha(target_commit)}…")
    merge = _run_git(["merge", "--ff-only", "FETCH_HEAD"], root, timeout=30.0)
    if merge.returncode != 0:
        raise RuntimeError(f"无法快进合并（本地分支可能已分叉）: {(merge.stderr or merge.stdout).strip()}")

    changed_files: set[str] = set()
    if old_commit:
        diff = _run_git(["diff", "--name-only", old_commit, target_commit], root, timeout=15.0)
        if diff.returncode == 0:
            changed_files = {line.strip() for line in diff.stdout.splitlines() if line.strip()}

    deps_note = ""
    if changed_files & DEPENDENCY_FILES:
        deps_note = _sync_dependencies(root, on_progress=on_progress)

    return {
        "mode": "git",
        "updated": True,
        "restart_required": True,
        "old_commit": old_commit,
        "new_commit": target_commit,
        "source": used_source,
        "deps_synced": deps_note,
        "message": f"代码已更新至 {short_sha(target_commit)}（来源：{used_source}）" + (f"，{deps_note}" if deps_note else ""),
    }


def _is_allowed_archive_member(rel_path: pathlib.PurePosixPath) -> bool:
    if rel_path.is_absolute() or ".." in rel_path.parts or not rel_path.parts:
        return False
    top = rel_path.parts[0]
    if len(rel_path.parts) == 1 and top in ARCHIVE_ALLOWED_FILES:
        return True
    if top in ARCHIVE_ALLOWED_DIRS:
        return True
    return False


def apply_archive_update(
    *,
    github_mirror: str = "",
    ghcr_mirror: str = "",
    project_root: pathlib.Path | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """在非 Git 源码包部署下，通过下载 GitHub 分支压缩包覆盖更新代码文件。"""
    root = project_root or PROJECT_ROOT
    check = check_for_updates(github_mirror=github_mirror, ghcr_mirror=ghcr_mirror, project_root=root)
    old_commit = check["local"]["commit"]
    remote = check["remote"]
    if not check["has_update"]:
        return {
            "mode": "source",
            "updated": False,
            "restart_required": False,
            "old_commit": old_commit,
            "new_commit": old_commit,
            "source": remote["source"],
            "deps_synced": "",
            "message": "当前版本已是最新",
        }

    custom_mirror = normalize_github_mirror(github_mirror) if github_mirror else ""
    download_urls: list[tuple[str, str]] = []
    if custom_mirror:
        download_urls.append((f"自定义加速源 ({urlparse(custom_mirror).netloc})", wrap_github_url(GITHUB_ARCHIVE_URL, custom_mirror)))
    download_urls.append(("GitHub", GITHUB_ARCHIVE_URL))
    for prefix in DEFAULT_GITHUB_MIRRORS:
        if prefix == custom_mirror:
            continue
        download_urls.append((f"加速源 ({urlparse(prefix).netloc})", wrap_github_url(GITHUB_ARCHIVE_URL, prefix)))

    zip_bytes = b""
    used_source = ""
    errors: list[str] = []
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        for label, url in download_urls:
            if on_progress:
                on_progress(f"正在通过 {label} 下载最新源码包…")
            try:
                resp = client.get(url, headers={"User-Agent": "MiyoQian-Updater"})
                resp.raise_for_status()
                zip_bytes = resp.content
                used_source = label
                break
            except Exception as exc:
                errors.append(f"{label}: {exc}")

    if not zip_bytes:
        raise RuntimeError("下载最新源码包失败：" + "；".join(errors[:4]))

    if on_progress:
        on_progress("正在解压覆盖程序文件…")
    deps_changed = False
    old_dep_contents = {
        name: (root / name).read_bytes() if (root / name).is_file() else b""
        for name in DEPENDENCY_FILES
    }

    root_resolved = root.resolve()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            # 跳过符号链接，防止逃逸
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                continue
            parts = pathlib.PurePosixPath(info.filename).parts
            if len(parts) < 2:
                continue
            rel = pathlib.PurePosixPath(*parts[1:])
            if not _is_allowed_archive_member(rel):
                continue
            dest = (root_resolved / pathlib.Path(*rel.parts)).resolve()
            if root_resolved not in dest.parents:
                raise RuntimeError(f"压缩包包含非法路径: {info.filename}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = archive.read(info)
            dest.write_bytes(data)
            if str(rel) in DEPENDENCY_FILES and old_dep_contents.get(str(rel)) != data:
                deps_changed = True

    marker = {
        "commit": remote["commit"],
        "commit_time": remote["commit_time"],
        "commit_message": remote["commit_message"],
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (root_resolved / VERSION_MARKER_FILE).write_text(
        json.dumps(marker, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    deps_note = _sync_dependencies(root, on_progress=on_progress) if deps_changed else ""
    return {
        "mode": "source",
        "updated": True,
        "restart_required": True,
        "old_commit": old_commit,
        "new_commit": remote["commit"],
        "source": used_source,
        "deps_synced": deps_note,
        "message": f"源码已更新至 {remote['short_commit']}（来源：{used_source}）" + (f"，{deps_note}" if deps_note else ""),
    }


def apply_docker_update(
    *,
    ghcr_mirror: str = "",
    socket_path: str = DOCKER_SOCKET_PATH,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """在 Docker 容器内拉取最新镜像并拉起临时 helper 容器完成安全重建。"""
    client = DockerSocketClient(socket_path=socket_path)
    ok, err = client.ping()
    if not ok:
        raise RuntimeError(
            f"无法自动拉取镜像（{err}）。请挂载 {socket_path}，或在宿主机执行 docker compose pull && docker compose up -d"
        )

    container_id = detect_self_container_id(client)
    if not container_id:
        raise RuntimeError("无法识别当前容器 ID")
    inspected = client.inspect_container(container_id)
    full_id = str(inspected.get("Id") or container_id)
    old_image_id = str(inspected.get("Image") or "")
    current_image_ref = str((inspected.get("Config") or {}).get("Image") or GHCR_DEFAULT_IMAGE).strip()
    orig_repo, orig_tag = split_image_ref(current_image_ref)

    custom_mirror = normalize_ghcr_mirror(ghcr_mirror) if ghcr_mirror else ""
    pull_candidates: list[tuple[str, str, str]] = []
    if custom_mirror:
        m_repo, m_tag = split_image_ref(mirror_image_ref(current_image_ref, custom_mirror))
        pull_candidates.append((f"自定义加速源 ({custom_mirror})", m_repo, m_tag))
    pull_candidates.append((f"当前配置源 ({orig_repo})", orig_repo, orig_tag))
    if orig_repo.startswith(f"{GHCR_REGISTRY}/") or orig_repo == GHCR_IMAGE_PATH:
        default_m_repo, default_m_tag = split_image_ref(mirror_image_ref(current_image_ref, DEFAULT_GHCR_MIRROR))
        if default_m_repo != orig_repo and all(item[1] != default_m_repo for item in pull_candidates):
            pull_candidates.append((f"国内加速源 ({DEFAULT_GHCR_MIRROR})", default_m_repo, default_m_tag))

    pulled_ref = ""
    used_source = ""
    pull_errors: list[str] = []
    for label, repo, tag in pull_candidates:
        if on_progress:
            on_progress(f"正在通过 {label} 拉取镜像 {repo}:{tag}…")
        try:
            client.pull_image(repo, tag, on_progress=on_progress)
            pulled_ref = f"{repo}:{tag}"
            used_source = label
            break
        except Exception as exc:
            pull_errors.append(f"{label}: {exc}")

    if not pulled_ref:
        raise RuntimeError("拉取新镜像失败：" + "；".join(pull_errors[:3]))

    # 如果通过回退加速源拉取，把镜像打标回容器原本引用的镜像名，保持 compose 配置一致
    if pulled_ref != f"{orig_repo}:{orig_tag}":
        client.tag_image(pulled_ref, orig_repo, orig_tag)
    target_image_ref = f"{orig_repo}:{orig_tag}"

    new_img_info = client.inspect_image(target_image_ref)
    new_image_id = str(new_img_info.get("Id") or "")
    new_labels = ((new_img_info.get("Config") or {}).get("Labels") or {}) if isinstance(new_img_info, dict) else {}
    new_commit = str(new_labels.get("org.opencontainers.image.revision") or "").strip().lower()

    if not force and old_image_id and new_image_id == old_image_id:
        return {
            "mode": "docker",
            "updated": False,
            "restart_required": False,
            "old_image_id": old_image_id,
            "new_image_id": new_image_id,
            "new_commit": new_commit,
            "source": used_source,
            "message": "当前容器镜像已是最新构建版本（若 GitHub 刚刚有新提交，请等待约 1-2 分钟镜像构建完成后再试）",
        }

    if on_progress:
        on_progress("镜像拉取完成，正在启动临时更新容器重建服务…")
    host_socket_source = find_docker_socket_host_source(inspected, socket_path)
    # 临时更新容器优先使用当前运行中的镜像，保证与当前代码的 --docker-recreate 参数完全匹配
    helper_body: dict[str, Any] = {
        "Image": old_image_id or target_image_ref,
        "User": "0:0",
        "WorkingDir": "/app",
        "Entrypoint": ["/opt/venv/bin/python"],
        "Cmd": [
            "-m",
            "miyouqian.core.updater",
            "--docker-recreate",
            "--target-id",
            full_id,
            "--new-image",
            target_image_ref,
            "--socket",
            socket_path,
        ],
        "HostConfig": {
            "Binds": [f"{host_socket_source}:{socket_path}"],
            "AutoRemove": True,
        },
        "Labels": {
            "com.miyouqian.updater": "true",
        },
    }
    helper_name = f"miyouqian-updater-{int(time.time())}"
    helper_id = client.create_container(helper_body, name=helper_name)
    client.start_container(helper_id)

    return {
        "mode": "docker",
        "updated": True,
        "restart_required": True,
        "old_image_id": old_image_id,
        "new_image_id": new_image_id,
        "new_commit": new_commit,
        "helper_id": helper_id,
        "source": used_source,
        "message": f"新镜像已拉取（来源：{used_source}），正在重建容器…",
    }


def apply_update(
    *,
    github_mirror: str = "",
    ghcr_mirror: str = "",
    project_root: pathlib.Path | None = None,
    socket_path: str = DOCKER_SOCKET_PATH,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """根据当前部署方式自动执行更新。"""
    root = project_root or PROJECT_ROOT
    mode = detect_deploy_mode(root)
    if mode == "docker":
        return apply_docker_update(
            ghcr_mirror=ghcr_mirror,
            socket_path=socket_path,
            force=force,
            on_progress=on_progress,
        )
    if mode == "git":
        return apply_git_update(
            github_mirror=github_mirror,
            project_root=root,
            on_progress=on_progress,
        )
    return apply_archive_update(
        github_mirror=github_mirror,
        ghcr_mirror=ghcr_mirror,
        project_root=root,
        on_progress=on_progress,
    )


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="米游签容器重建辅助入口")
    parser.add_argument("--docker-recreate", action="store_true", help="由临时更新容器调用以重建目标容器")
    parser.add_argument("--target-id", default="", help="目标容器 ID")
    parser.add_argument("--new-image", default="", help="新镜像引用")
    parser.add_argument("--socket", default=DOCKER_SOCKET_PATH, help="Docker socket 路径")
    parser.add_argument("--delay", type=float, default=1.5, help="重建前等待秒数")
    args = parser.parse_args(argv)
    if args.docker_recreate:
        if not args.target_id or not args.new_image:
            print("[updater] 缺少 --target-id 或 --new-image", file=sys.stderr)
            return 2
        run_docker_recreate_helper(
            target_id=args.target_id,
            new_image=args.new_image,
            socket_path=args.socket,
            delay_seconds=args.delay,
        )
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
