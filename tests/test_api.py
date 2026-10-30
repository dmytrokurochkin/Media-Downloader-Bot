import logging

import pytest
from aiohttp.test_utils import TestClient, TestServer

from core import api, telegram_auth
from tests.test_telegram_auth import TOKEN, make_init_data


@pytest.fixture
async def client(db, monkeypatch):
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", TOKEN)
    await db.get_or_create_user(1, "alice", "Alice Liddell", "en")
    await db.get_or_create_user(2, "bob", "50% Bob", "en")
    await db.get_or_create_user(3, "hidden", "Hidden Alice", "en")
    await db.update_user_settings(3, "en", "best", True, "standard", "bottom_right")

    test_client = TestClient(TestServer(api.create_api_app()))
    await test_client.start_server()
    yield test_client
    await test_client.close()


def _auth():
    return {"Authorization": f"tma {make_init_data()}"}


async def test_search_requires_init_data(client):
    resp = await client.get("/api/search_users", params={"q": "alice"})
    assert resp.status == 401


async def test_search_accepts_authorization_header(client):
    resp = await client.get("/api/search_users", params={"q": "alice"}, headers=_auth())
    assert resp.status == 200
    names = [r["full_name"] for r in (await resp.json())["results"]]
    # Анонімний профіль у пошук не потрапляє.
    assert names == ["Alice Liddell"]


async def test_search_still_accepts_legacy_query_param(client):
    resp = await client.get("/api/search_users", params={"q": "alice", "initData": make_init_data()})
    assert resp.status == 200


async def test_search_rejects_forged_init_data(client):
    forged = make_init_data(token="999:OTHER")
    resp = await client.get("/api/search_users", params={"q": "alice"}, headers={"Authorization": f"tma {forged}"})
    assert resp.status == 401


@pytest.mark.parametrize("query", ["a", "x" * 65])
async def test_search_rejects_bad_query_length(client, query):
    resp = await client.get("/api/search_users", params={"q": query}, headers=_auth())
    assert resp.status == 400


async def test_search_treats_like_wildcards_literally(client):
    # «%%» раніше збігалося б з усіма; тепер — лише з іменами, де справді є «%%».
    resp = await client.get("/api/search_users", params={"q": "%%"}, headers=_auth())
    assert (await resp.json())["results"] == []

    resp = await client.get("/api/search_users", params={"q": "0%"}, headers=_auth())
    assert [r["full_name"] for r in (await resp.json())["results"]] == ["50% Bob"]


async def test_profile_endpoint(client):
    resp = await client.get("/api/get_profile", params={"id": "1"}, headers=_auth())
    assert resp.status == 200
    assert (await resp.json())["profile"]["full_name"] == "Alice Liddell"

    resp = await client.get("/api/get_profile", params={"id": "3"}, headers=_auth())
    assert resp.status == 404


def test_access_logger_drops_query_string(caplog):
    class _Req:
        method = "GET"
        path = "/api/search_users"
        path_qs = "/api/search_users?q=x&initData=SECRET"

    class _Resp:
        status = 200

    logger = logging.getLogger("test.access")
    access_logger = api.PathOnlyAccessLogger(logger, "")
    with caplog.at_level(logging.INFO, logger="test.access"):
        access_logger.log(_Req(), _Resp(), 0.01)

    assert "/api/search_users" in caplog.text
    assert "SECRET" not in caplog.text
