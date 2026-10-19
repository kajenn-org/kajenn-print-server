# Copyright 2026 Softwell S.r.l.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Contract: printing needs a ``print`` credential unless the mount is public."""

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from kajenn import AsgiServer

from tests.conftest import OTHER_TOKEN, started_client

RECIPE = Path(__file__).resolve().parents[1] / "examples/print_server/config.py"
SOURCE = {"html": "<p>x</p>"}


async def test_anonymous_caller_is_challenged(make_client):
    client = await make_client(token=None)
    response = await client.post("/print/pdf", json=SOURCE)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_credential_without_the_print_tag_is_forbidden(make_client):
    client = await make_client(token=OTHER_TOKEN)
    assert (await client.post("/print/pdf", json=SOURCE)).status_code == 403


async def test_invalid_token_is_refused(make_client):
    client = await make_client(token="not-a-token")
    assert (await client.post("/print/pdf", json=SOURCE)).status_code == 401


async def test_public_mount_serves_anonymous_callers(make_client):
    client = await make_client(public=True, token=None)
    response = await client.post("/print/pdf", json=SOURCE)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    # Only the mount declared public opens; the other mount keeps its rule.
    assert (await client.post("/other/pdf", json=SOURCE)).status_code == 401


@pytest.fixture
def recipe_env(monkeypatch, tmp_path):
    for name in ("PRINT_AUTH", "KAJENN_ADMIN_TOKEN", "KAJENN_STORAGE_KEY"):
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("KAJENN_PRINT_HOME", str(home))
    return monkeypatch


async def recipe_client(token=None):
    server = AsgiServer(config=str(RECIPE))
    return server, await started_client(server, token)


async def test_recipe_issues_api_keys_that_print(recipe_env):
    recipe_env.setenv("KAJENN_ADMIN_TOKEN", "operator-secret")
    recipe_env.setenv("KAJENN_STORAGE_KEY", Fernet.generate_key().decode())
    server, operator = await recipe_client("operator-secret")
    async with operator:
        issued = await operator.post(
            "/_server/tokens/issue", json={"label": "erp", "tags": ["print"]}
        )
        key = issued.json()["key"]
        assert key.startswith("gak_")
        assert (await operator.post("/print/pdf", json=SOURCE)).status_code == 403
        response = await operator.post(
            "/print/pdf", json=SOURCE, headers={"Authorization": f"Bearer {key}"}
        )
        assert response.status_code == 200
    await server.lifespan.shutdown()


async def test_recipe_with_auth_off_is_public(recipe_env):
    recipe_env.setenv("PRINT_AUTH", "off")
    server, client = await recipe_client()
    async with client:
        assert (await client.post("/print/pdf", json=SOURCE)).status_code == 200
    await server.lifespan.shutdown()


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({}, "requires KAJENN_ADMIN_TOKEN, KAJENN_STORAGE_KEY"),
        ({"PRINT_AUTH": "maybe"}, "PRINT_AUTH must be one of"),
    ],
)
def test_recipe_refuses_an_incomplete_environment(recipe_env, env, message):
    for name, value in env.items():
        recipe_env.setenv(name, value)
    with pytest.raises(ValueError, match=message):
        AsgiServer(config=str(RECIPE))


async def test_health_is_public(make_client):
    client = await make_client(token=None)
    response = await client.get("/print/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_recipe_root_redirects_to_the_docs(recipe_env):
    recipe_env.setenv("PRINT_AUTH", "off")
    server, client = await recipe_client()
    async with client:
        response = await client.get("/?from=bookmark", follow_redirects=True)
        assert response.status_code == 200
        assert response.url.path == "/print/_meta/docs"
        assert [r.headers["location"] for r in response.history] == [
            "/print/?from=bookmark", "/print/_meta/docs"
        ]
    await server.lifespan.shutdown()
