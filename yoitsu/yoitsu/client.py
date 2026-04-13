"""Thin httpx wrappers for pasloe and trenni HTTP APIs."""
from __future__ import annotations

from typing import Any

import httpx
from yoitsu_contracts.client import AsyncPasloeClient


class PasloeClient(AsyncPasloeClient):
    def __init__(self, url: str, api_key: str) -> None:
        super().__init__(
            base_url=url,
            api_key_env="",
            api_key=api_key,
            source_id="yoitsu-cli",
            timeout=10.0,
        )
        self._http = self._client

    async def check_ready(self) -> bool:
        """Return True if pasloe responds with HTTP 200."""
        try:
            r = await self._http.get("/health")
            return r.status_code == 200
        except Exception:
            return False

    async def get_stats(self) -> dict[str, Any] | None:
        """Return pasloe stats (total_events + by_type) or None on error."""
        try:
            r = await self._http.get("/events/stats")
            r.raise_for_status()
            raw = r.json()
            return {"total_events": raw["total_events"], "by_type": raw["by_type"]}
        except Exception:
            return None

    async def get_stats_strict(self) -> dict[str, Any]:
        r = await self._http.get("/events/stats")
        r.raise_for_status()
        raw = r.json()
        return {"total_events": raw["total_events"], "by_type": raw["by_type"]}

    async def post_event(self, *, type_: str, data: dict) -> str | None:
        """POST a single event; return event id or None on failure."""
        try:
            r = await self._http.post(
                "/events",
                json={"source_id": self.source_id, "type": type_, "data": data},
            )
            r.raise_for_status()
            return r.json().get("id")
        except Exception:
            return None

    async def list_events(self, *, limit: int = 20, source: str | None = None, type_: str | None = None) -> list[dict[str, Any]] | None:
        try:
            params: dict[str, Any] = {"limit": limit}
            if source:
                params["source"] = source
            if type_:
                params["type"] = type_
            r = await self._http.get("/events", params=params)
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    async def list_events_strict(self, *, limit: int = 20, source: str | None = None, type_: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if source:
            params["source"] = source
        if type_:
            params["type"] = type_
        r = await self._http.get("/events", params=params)
        r.raise_for_status()
        return r.json()

    async def list_jobs(self, **params: Any) -> list[dict[str, Any]] | None:
        try:
            r = await self._http.get("/jobs", params={k: v for k, v in params.items() if v is not None})
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    async def list_jobs_strict(self, **params: Any) -> list[dict[str, Any]]:
        r = await self._http.get("/jobs", params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        return r.json()

    async def list_tasks(self, **params: Any) -> list[dict[str, Any]] | None:
        try:
            r = await self._http.get("/tasks", params={k: v for k, v in params.items() if v is not None})
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    async def list_tasks_strict(self, **params: Any) -> list[dict[str, Any]]:
        r = await self._http.get("/tasks", params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        return r.json()

    async def get_llm_stats(self, **params: Any) -> dict[str, Any] | None:
        try:
            r = await self._http.get("/llm/stats", params={k: v for k, v in params.items() if v is not None})
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    async def get_llm_stats_strict(self, **params: Any) -> dict[str, Any]:
        r = await self._http.get("/llm/stats", params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        return r.json()

    async def aclose(self) -> None:
        await self.close()


class TrenniClient:
    def __init__(self, url: str) -> None:
        self._url = url.rstrip("/")
        self._http = httpx.AsyncClient(base_url=self._url, timeout=10.0)

    async def check_ready(self) -> bool:
        """Return True if trenni control API responds with HTTP 200."""
        try:
            r = await self._http.get("/control/status")
            return r.status_code == 200
        except Exception:
            return False

    async def get_status(self) -> dict[str, Any] | None:
        """Return trenni status dict or None on error."""
        try:
            r = await self._http.get("/control/status")
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    async def get_tasks(self, **params: Any) -> list[dict[str, Any]] | None:
        try:
            r = await self._http.get("/control/tasks", params={k: v for k, v in params.items() if v is not None})
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    async def get_tasks_strict(self, **params: Any) -> list[dict[str, Any]]:
        r = await self._http.get("/control/tasks", params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        return r.json()

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        try:
            r = await self._http.get(f"/control/tasks/{task_id}")
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    async def get_task_strict(self, task_id: str) -> dict[str, Any]:
        r = await self._http.get(f"/control/tasks/{task_id}")
        r.raise_for_status()
        return r.json()

    async def get_jobs(self, **params: Any) -> list[dict[str, Any]] | None:
        try:
            r = await self._http.get("/control/jobs", params={k: v for k, v in params.items() if v is not None})
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    async def get_jobs_strict(self, **params: Any) -> list[dict[str, Any]]:
        r = await self._http.get("/control/jobs", params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        return r.json()

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        try:
            r = await self._http.get(f"/control/jobs/{job_id}")
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    async def get_job_strict(self, job_id: str) -> dict[str, Any]:
        r = await self._http.get(f"/control/jobs/{job_id}")
        r.raise_for_status()
        return r.json()

    async def post_control(self, endpoint: str) -> str | None:
        """POST to /control/<endpoint>. Returns None on success, error string on failure."""
        try:
            r = await self._http.post(f"/control/{endpoint}")
            if r.status_code == 200:
                return None
            return f"trenni returned {r.status_code}: {r.text}"
        except httpx.ConnectError:
            return "trenni unreachable"
        except Exception as exc:
            return str(exc)

    async def aclose(self) -> None:
        await self._http.aclose()
