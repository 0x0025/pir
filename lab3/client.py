"""Клиент к чужому Strategies API (other_api/2) — лабораторная работа №3.

Запуск API (в другом терминале):
  cd other_api/2 && uvicorn main:app --port 8002

Запуск клиента:
  python client.py
"""

from __future__ import annotations

import json
import sys
from typing import Any, Optional

import httpx

BASE_URL = "http://127.0.0.1:8002"
API_KEY = "demo-key"
INTERNAL = "internal-secret"


class StrategiesClient:
    """Клиент Strategies API с обработкой ошибок, пагинации и идемпотентности."""

    def __init__(self, base_url: str = BASE_URL, api_key: str = API_KEY) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"X-API-Key": self.api_key},
            timeout=10.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "StrategiesClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _handle(self, response: httpx.Response) -> Any:
        remaining = response.headers.get("X-Limit-Remaining")
        retry_after = response.headers.get("Retry-After")
        total = response.headers.get("X-Total-Count")
        meta = {
            "status": response.status_code,
            "X-Limit-Remaining": remaining,
            "Retry-After": retry_after,
            "X-Total-Count": total,
        }
        if response.status_code == 429:
            raise RuntimeError(
                f"Rate limit. Retry-After={retry_after}. Headers: {meta}"
            )
        if response.status_code == 401:
            raise RuntimeError("Неверный API-ключ (401)")
        if response.status_code == 404:
            raise RuntimeError("Ресурс не найден (404)")
        if response.status_code >= 400:
            raise RuntimeError(f"Ошибка {response.status_code}: {response.text}")
        if response.status_code == 204:
            return {"meta": meta, "data": None}
        try:
            data = response.json()
        except json.JSONDecodeError:
            data = response.text
        return {"meta": meta, "data": data}

    def list_strategies(
        self,
        page: int = 1,
        page_size: int = 10,
        fields: Optional[str] = None,
        version: str = "v1",
    ) -> Any:
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if fields:
            params["fields"] = fields
        r = self._client.get(f"/api/{version}/strategies", params=params)
        return self._handle(r)

    def create_strategy(
        self,
        name: str,
        description: str = "",
        tags: Optional[list[str]] = None,
        idempotency_key: Optional[str] = None,
        version: str = "v1",
    ) -> Any:
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if version == "v2":
            body: dict[str, Any] = {
                "name": name,
                "description": description,
                "tags": tags or [],
            }
        else:
            body = {"name": name, "description": description}
        r = self._client.post(
            f"/api/{version}/strategies", json=body, headers=headers
        )
        return self._handle(r)

    def get_strategy(self, sid: str, version: str = "v1") -> Any:
        r = self._client.get(f"/api/{version}/strategies/{sid}")
        return self._handle(r)

    def update_strategy(
        self, sid: str, name: str, description: str = "", version: str = "v1"
    ) -> Any:
        r = self._client.put(
            f"/api/{version}/strategies/{sid}",
            json={"name": name, "description": description},
        )
        return self._handle(r)

    def delete_strategy(self, sid: str, version: str = "v1") -> Any:
        r = self._client.delete(f"/api/{version}/strategies/{sid}")
        return self._handle(r)

    def internal_stats(self) -> Any:
        r = self._client.get(
            "/internal/stats",
            headers={"X-Internal-Token": INTERNAL, "X-API-Key": self.api_key},
        )
        return self._handle(r)


def pretty(label: str, result: Any) -> None:
    print(f"\n=== {label} ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> int:
    print(f"Клиент Strategies API → {BASE_URL}")
    try:
        with StrategiesClient() as client:
            # проверка доступности
            try:
                httpx.get(f"{BASE_URL}/docs", timeout=3.0)
            except httpx.HTTPError as exc:
                print(
                    f"API недоступен на {BASE_URL}. "
                    f"Запустите: cd other_api/2 && uvicorn main:app --port 8002\n{exc}",
                    file=sys.stderr,
                )
                return 1

            created = client.create_strategy(
                "Momentum",
                "Трендовая стратегия",
                idempotency_key="demo-idem-1",
            )
            pretty("CREATE", created)
            sid = created["data"]["id"]

            again = client.create_strategy(
                "Momentum DUPLICATE",
                "Не должен создаться",
                idempotency_key="demo-idem-1",
            )
            pretty("CREATE (тот же Idempotency-Key)", again)
            assert again["data"]["id"] == sid, "Идемпотентность нарушена"

            listed = client.list_strategies(page=1, page_size=5, fields="id,name")
            pretty("LIST (pagination + fields)", listed)

            got = client.get_strategy(sid)
            pretty("GET", got)

            updated = client.update_strategy(sid, "Momentum v2", "Обновлено")
            pretty("UPDATE", updated)

            stats = client.internal_stats()
            pretty("INTERNAL /stats", stats)

            deleted = client.delete_strategy(sid)
            pretty("DELETE", deleted)

            print("\nВсе операции выполнены успешно.")
            return 0
    except Exception as exc:  # noqa: BLE001 — демо-клиент печатает любую ошибку
        print(f"Ошибка клиента: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
