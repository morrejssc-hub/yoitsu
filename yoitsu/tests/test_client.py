"""Tests for PasloeClient and TrenniClient."""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from yoitsu.client import PasloeClient, TrenniClient


class TestPasloeClient:
    def _client(self) -> PasloeClient:
        return PasloeClient(url="http://localhost:8000", api_key="test-key")

    async def test_check_ready_returns_true_on_200(self):
        c = self._client()
        mock_resp = MagicMock(status_code=200)
        with patch.object(c._http, "get", new=AsyncMock(return_value=mock_resp)):
            assert await c.check_ready() is True

    async def test_check_ready_returns_false_on_connect_error(self):
        c = self._client()
        with patch.object(c._http, "get", new=AsyncMock(
                side_effect=httpx.ConnectError("refused"))):
            assert await c.check_ready() is False

    async def test_get_stats_returns_dict(self):
        c = self._client()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "total_events": 5,
            "by_source": {},
            "by_type": {"task.submit": 3},
        }
        with patch.object(c._http, "get", new=AsyncMock(return_value=mock_resp)):
            stats = await c.get_stats()
        assert stats["total_events"] == 5
        assert "by_source" not in stats  # stripped by client
        assert stats["by_type"]["task.submit"] == 3

    async def test_get_stats_returns_none_on_error(self):
        c = self._client()
        with patch.object(c._http, "get", new=AsyncMock(
                side_effect=httpx.ConnectError("refused"))):
            assert await c.get_stats() is None

    async def test_post_event_sends_correct_body(self):
        c = self._client()
        mock_resp = MagicMock(status_code=201)
        mock_resp.json.return_value = {"id": "abc"}
        with patch.object(c._http, "post", new=AsyncMock(return_value=mock_resp)) as mock_post:
            event_id = await c.post_event(type_="task.submit", data={"task": "hello"})
        assert event_id == "abc"
        body = mock_post.call_args.kwargs["json"]
        assert body["type"] == "task.submit"
        assert body["source_id"] == "yoitsu-cli"
        assert body["data"]["task"] == "hello"


class TestTrenniClient:
    def _client(self) -> TrenniClient:
        return TrenniClient(url="http://localhost:8100")

    async def test_check_ready_returns_true_on_200(self):
        c = self._client()
        mock_resp = MagicMock(status_code=200)
        with patch.object(c._http, "get", new=AsyncMock(return_value=mock_resp)):
            assert await c.check_ready() is True

    async def test_get_status_returns_dict(self):
        c = self._client()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "running": True, "paused": False,
            "running_jobs": 2, "max_workers": 4,
            "pending_jobs": 0, "ready_queue_size": 0,
        }
        with patch.object(c._http, "get", new=AsyncMock(return_value=mock_resp)):
            status = await c.get_status()
        assert status["running"] is True
        assert status["running_jobs"] == 2

    async def test_post_control_stop_returns_none_on_success(self):
        c = self._client()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"ok": True}
        with patch.object(c._http, "post", new=AsyncMock(return_value=mock_resp)):
            err = await c.post_control("stop")
        assert err is None  # None = success

    async def test_post_control_returns_error_string_on_connect_error(self):
        c = self._client()
        with patch.object(c._http, "post", new=AsyncMock(
                side_effect=httpx.ConnectError("refused"))):
            err = await c.post_control("pause")
        assert err is not None
        assert "unreachable" in err.lower()

    async def test_post_control_surfaces_non_200_status_and_body(self):
        c = self._client()
        mock_resp = MagicMock(status_code=409)
        mock_resp.text = "already paused"
        with patch.object(c._http, "post", new=AsyncMock(return_value=mock_resp)):
            err = await c.post_control("pause")
        assert err is not None
        assert "409" in err
        assert "already paused" in err
