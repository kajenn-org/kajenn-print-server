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

"""Contract: ``kajenn-print`` uploads an HTML file and saves the PDF the server answers."""

import io

import httpx
import pytest

from kajenn_print_server.cli import DEFAULT_URL, main

PDF = b"%PDF-1.7 fake"


class Server:
    """A mock print server recording the requests it receives."""

    def __init__(self, status=200, content=PDF, content_type="application/pdf"):
        self.requests = []
        self.status, self.content, self.content_type = status, content, content_type

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            self.status, content=self.content, headers={"Content-Type": self.content_type}
        )

    @property
    def transport(self):
        return httpx.MockTransport(self)


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.delenv("KAJENN_PRINT_URL", raising=False)
    monkeypatch.delenv("KAJENN_PRINT_TOKEN", raising=False)
    path = tmp_path / "invoice.html"
    path.write_text("<h1>Invoice</h1>")
    return path


def test_uploads_to_the_docker_port_and_writes_beside_the_source(source):
    server = Server()
    assert main([str(source)], transport=server.transport) == 0
    request = server.requests[0]
    assert DEFAULT_URL == "http://127.0.0.1:8000"
    assert str(request.url) == "http://127.0.0.1:8000/print/pdf"
    assert "authorization" not in request.headers
    body = request.read()
    assert b'name="html"; filename="invoice.html"' in body
    assert b"<h1>Invoice</h1>" in body
    assert b'name="filename"\r\n\r\ninvoice.pdf' in body
    assert source.with_suffix(".pdf").read_bytes() == PDF


def test_token_url_mount_and_base_url(source, tmp_path, monkeypatch):
    monkeypatch.setenv("KAJENN_PRINT_TOKEN", "gak_secret")
    monkeypatch.setenv("KAJENN_PRINT_URL", "https://print.example.com/")
    server = Server()
    output = tmp_path / "out.pdf"
    argv = [str(source), "-o", str(output), "--mount", "docs", "--base-url", "https://cdn/"]
    assert main(argv, transport=server.transport) == 0
    request = server.requests[0]
    assert str(request.url) == "https://print.example.com/docs/pdf"
    assert request.headers["authorization"] == "Bearer gak_secret"
    assert b'name="base_url"\r\n\r\nhttps://cdn/' in request.read()
    assert output.read_bytes() == PDF


def test_stdin_to_stdout(monkeypatch, capsysbinary):
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"<p>piped</p>")))
    server = Server()
    assert main(["-", "-o", "-"], transport=server.transport) == 0
    assert capsysbinary.readouterr().out == PDF
    assert b'filename="document.html"' in server.requests[0].read()


@pytest.mark.parametrize(
    ("server", "message"),
    [
        (Server(401, b'{"error":"Unauthorized"}', "application/json"), "set KAJENN_PRINT_TOKEN"),
        (Server(403, b'{"error":"Forbidden"}', "application/json"), "print tag (403)"),
        (Server(400, b'{"error":"bad html"}', "application/json"), "answered 400: bad html"),
        (Server(200, b"<html>", "text/html"), "did not answer a PDF"),
    ],
)
def test_server_refusals_exit_1_without_writing(source, capsys, server, message):
    assert main([str(source)], transport=server.transport) == 1
    assert message in capsys.readouterr().err
    assert not source.with_suffix(".pdf").exists()


def test_unreachable_server(source, capsys):
    def refuse(request):
        raise httpx.ConnectError("Connection refused", request=request)

    assert main([str(source)], transport=httpx.MockTransport(refuse)) == 1
    assert "cannot reach http://127.0.0.1:8000/print/pdf" in capsys.readouterr().err


def test_missing_and_empty_sources(tmp_path, capsys):
    assert main([str(tmp_path / "nope.html")], transport=Server().transport) == 1
    assert "cannot read" in capsys.readouterr().err
    empty = tmp_path / "empty.html"
    empty.write_text("  \n")
    assert main([str(empty)], transport=Server().transport) == 1
    assert "is empty" in capsys.readouterr().err


def test_the_client_does_not_load_the_renderer():
    """A client machine needs no Pango: importing the CLI leaves WeasyPrint unloaded."""
    import subprocess
    import sys

    probe = "import sys, kajenn_print_server.cli; print('weasyprint' in sys.modules)"
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert result.stdout.strip() == "False", result.stderr
