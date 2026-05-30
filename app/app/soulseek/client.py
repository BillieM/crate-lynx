from __future__ import annotations

from dataclasses import dataclass
import json
import socket
import ssl
import time
from typing import Any
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.soulseek.config import SlskdConfig


class SlskdClientError(RuntimeError):
    pass


class SlskdHttpError(SlskdClientError):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"slskd request failed with status {status_code}: {detail}")


class SlskdTimeoutError(SlskdClientError):
    pass


class SlskdMalformedResponseError(SlskdClientError):
    pass


@dataclass(frozen=True, slots=True)
class SlskdSearchResult:
    search: dict[str, Any]
    responses: list[dict[str, Any]]


class SlskdClient:
    def __init__(self, config: SlskdConfig) -> None:
        self._config = config

    def status(self) -> dict[str, Any]:
        return self._get_json("/api/v0/session")

    def start_search(self, *, search_id: str, search_text: str) -> dict[str, Any]:
        search = self._post_json(
            "/api/v0/searches",
            {
                "id": search_id,
                "searchText": search_text,
                "searchTimeout": max(0, self._config.search_timeout_seconds * 1000),
                "responseLimit": self._config.response_limit,
                "fileLimit": self._config.file_limit,
                "filterResponses": True,
                "minimumResponseFileCount": 1,
                "maximumPeerQueueLength": self._config.maximum_peer_queue_length,
                "minimumPeerUploadSpeed": self._config.minimum_peer_upload_speed,
            },
        )
        return search if isinstance(search, dict) else {}

    def search(self, *, search_id: str, search_text: str) -> SlskdSearchResult:
        search = self.start_search(search_id=search_id, search_text=search_text)
        responses = self.poll_search_responses(search_id)
        return SlskdSearchResult(search=search, responses=responses)

    def poll_search_responses(
        self,
        search_id: str,
        *,
        interval_seconds: float | None = None,
        timeout_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        interval = (
            self._config.search_poll_interval_seconds
            if interval_seconds is None
            else interval_seconds
        )
        timeout = (
            self._config.search_poll_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        deadline = time.monotonic() + max(0.0, timeout)
        responses: list[dict[str, Any]] = []

        while True:
            responses = self.search_responses(search_id)
            if responses or time.monotonic() >= deadline:
                return responses

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return responses
            time.sleep(max(0.0, min(interval, remaining)))

    def search_responses(self, search_id: str) -> list[dict[str, Any]]:
        payload = self._get_json(f"/api/v0/searches/{search_id}/responses")
        if not isinstance(payload, list):
            raise SlskdMalformedResponseError("slskd search responses were not a list")
        return [item for item in payload if isinstance(item, dict)]

    def delete_search(self, search_id: str) -> None:
        self._request_json("DELETE", f"/api/v0/searches/{search_id}")

    def enqueue_download(
        self,
        *,
        username: str,
        filename: str,
        size: int,
    ) -> dict[str, Any]:
        return self._post_json(
            f"/api/v0/transfers/downloads/{quote(username, safe='')}",
            [{"filename": filename, "size": size}],
        )

    def download(self, *, username: str, transfer_id: str) -> dict[str, Any]:
        return self._get_json(
            f"/api/v0/transfers/downloads/"
            f"{quote(username, safe='')}/{quote(transfer_id, safe='')}"
        )

    def _get_json(self, path: str) -> Any:
        return self._request_json("GET", path)

    def _post_json(self, path: str, body: dict[str, Any] | list[Any]) -> Any:
        return self._request_json("POST", path, body)

    def _request_json(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | list[Any] | None = None,
    ) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            self._config.base_url + path,
            data=data,
            headers={
                "Accept": "application/json",
                "X-API-Key": self._config.api_key,
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
            method=method,
        )
        context = None if self._config.verify_ssl else ssl._create_unverified_context()

        try:
            with urlopen(  # noqa: S310 - slskd base URL is explicit deployment config.
                request,
                context=context,
                timeout=self._config.request_timeout_seconds,
            ) as response:
                payload = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = _read_error_detail(exc)
            raise SlskdHttpError(exc.code, detail) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise SlskdTimeoutError("slskd request timed out") from exc
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError | socket.timeout):
                raise SlskdTimeoutError("slskd request timed out") from exc
            raise SlskdClientError(f"slskd request failed: {exc.reason}") from exc

        if payload.strip() == "":
            return {}

        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SlskdMalformedResponseError(
                "slskd response was not valid JSON"
            ) from exc


def _read_error_detail(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8").strip()
    except Exception:
        body = ""
    return body or exc.reason or "unknown error"
