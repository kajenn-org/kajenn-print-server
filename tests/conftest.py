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

"""Print server fixtures: an isolated kajenn home and an in-process HTTP client."""

import base64
import struct
import zlib
from pathlib import Path

import httpx
import pytest
from kajenn import AsgiServer
from kajenn.config import HOME_ENV, AsgiConfigBuilder

from kajenn_print_server import PrintApplication


@pytest.fixture(autouse=True)
def kajenn_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "kajenn_home"
    home.mkdir()
    monkeypatch.setenv(HOME_ENV, str(home))
    monkeypatch.chdir(tmp_path)
    return home


PRINT_TOKEN = "print-token"
OTHER_TOKEN = "other-token"


def print_configuration(
    remote_resources: bool = False, public: bool = False
) -> type[AsgiConfigBuilder]:
    """The print application at /print and a second mount at /other, behind two tokens."""

    class Configuration(AsgiConfigBuilder):
        def main(self, root):
            cfg = root.configuration()
            credentials = cfg.authentication().credentials()
            credentials.bearer_token(identity="client", token=PRINT_TOKEN, tags="print")
            credentials.bearer_token(identity="other", token=OTHER_TOKEN, tags="other")
            apps = cfg.applications(default="print")
            decoded = apps.application(code="print", app_class=PrintApplication)
            decoded.pdf(remote_resources=remote_resources, timeout=5)
            decoded.access(public=public)
            apps.application(code="other", app_class=PrintApplication)

    return Configuration


async def started_client(server: AsgiServer, token: str | None) -> httpx.AsyncClient:
    """Run the server's startup hooks, then a client sending ``token`` as a bearer."""
    await server.lifespan.startup()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server), base_url="http://print.test", headers=headers
    )


@pytest.fixture
async def make_client():
    opened = []

    async def factory(
        remote_resources: bool = False, public: bool = False, token: str | None = PRINT_TOKEN
    ) -> httpx.AsyncClient:
        server = AsgiServer(config=print_configuration(remote_resources, public))
        client = await started_client(server, token)
        opened.append((server, client))
        return client

    yield factory
    for server, client in opened:
        await client.aclose()
        await server.lifespan.shutdown()


@pytest.fixture
async def client(make_client):
    return await make_client()


def png_bytes() -> bytes:
    """A 1x1 opaque PNG, built without an imaging dependency."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(
        b"IEND", b""
    )


def png_data_url() -> str:
    return "data:image/png;base64," + base64.b64encode(png_bytes()).decode()
