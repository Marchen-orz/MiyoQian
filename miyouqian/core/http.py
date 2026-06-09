# -*- coding: utf-8 -*-
"""HTTP 客户端封装。"""

from __future__ import annotations

from typing import Any

import httpx


class ApiError(RuntimeError):
    """接口或网络错误。"""


class ApiClient:
    def __init__(self, timeout: float = 30.0) -> None:
        transport = httpx.HTTPTransport(retries=3)
        self._client = httpx.Client(
            timeout=timeout,
            transport=transport,
            follow_redirects=True,
        )

    def get_json(self, url: str, **kwargs: Any) -> dict[str, Any]:
        return self._request_json("GET", url, **kwargs)

    def post_json(self, url: str, **kwargs: Any) -> dict[str, Any]:
        return self._request_json("POST", url, **kwargs)

    def get_json_with_headers(self, url: str, **kwargs: Any) -> tuple[dict[str, Any], httpx.Headers]:
        return self._request_json_with_headers("GET", url, **kwargs)

    def post_json_with_headers(self, url: str, **kwargs: Any) -> tuple[dict[str, Any], httpx.Headers]:
        return self._request_json_with_headers("POST", url, **kwargs)

    def _request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        data, _headers = self._request_json_with_headers(method, url, **kwargs)
        return data

    def _request_json_with_headers(
        self, method: str, url: str, **kwargs: Any
    ) -> tuple[dict[str, Any], httpx.Headers]:
        try:
            response = self._client.request(method, url, **kwargs)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise ApiError(f"网络请求失败: {url} ({exc})") from exc
        except ValueError as exc:
            raise ApiError(f"接口返回不是 JSON: {url}") from exc
        if not isinstance(data, dict):
            raise ApiError(f"接口返回格式异常: {url}")
        return data, response.headers

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ApiClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
