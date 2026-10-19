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

"""Contract: POST /print/pdf answers a PDF rendered from the submitted HTML."""

import http.server
import io
import re
import threading

import pytest
from pypdf import PdfReader

from kajenn_print_server import render_pdf
from tests.conftest import png_bytes, png_data_url


def pdf_text(content: bytes) -> str:
    return "".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)


def pdf_images(content: bytes) -> int:
    return sum(len(page.images) for page in PdfReader(io.BytesIO(content)).pages)


async def test_json_source_renders_a_pdf_attachment(client):
    response = await client.post(
        "/print/pdf", json={"html": "<h1>Quarterly report</h1>", "filename": "Q3 report"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="Q3_report.pdf"'
    assert response.content.startswith(b"%PDF-")
    assert "Quarterly report" in pdf_text(response.content)
    assert re.fullmatch(r"render;dur=\d+\.\d", response.headers["server-timing"])


async def test_multipart_file_source(client):
    files = {"html": ("invoice.html", b"<p>Invoice 42</p>", "text/html")}
    response = await client.post("/print/pdf", files=files)
    assert response.status_code == 200
    assert "Invoice 42" in pdf_text(response.content)
    assert response.headers["content-disposition"] == 'attachment; filename="document.pdf"'


@pytest.mark.xfail(
    strict=True, reason="kajenn decodes urlencoded bodies with genro_tytx.from_qs, which "
    "does not percent-decode values"
)
async def test_form_field_source(client):
    response = await client.post("/print/pdf", data={"html": "<p>Form body</p>"})
    assert response.status_code == 200
    assert "Form body" in pdf_text(response.content)


@pytest.mark.parametrize("body", [{}, {"html": "   "}])
async def test_missing_source_is_a_bad_request(client, body):
    response = await client.post("/print/pdf", json=body)
    assert response.status_code == 400


async def test_non_utf8_upload_is_a_bad_request(client):
    files = {"html": ("latin1.html", b"<p>\xe8</p>", "text/html")}
    assert (await client.post("/print/pdf", files=files)).status_code == 400


async def test_plain_html_bodies_are_refused(client):
    response = await client.post(
        "/print/pdf", content=b"<p>x</p>", headers={"Content-Type": "text/html"}
    )
    assert response.status_code == 415


@pytest.mark.parametrize(
    ("filename", "expected"),
    [("../../etc/passwd", "etc_passwd.pdf"), ('a"b', "a_b.pdf"), ("...", "document.pdf")],
)
async def test_attachment_name_is_sanitized(client, filename, expected):
    response = await client.post("/print/pdf", json={"html": "<p>x</p>", "filename": filename})
    assert response.headers["content-disposition"] == f'attachment; filename="{expected}"'


def test_data_urls_are_embedded_and_local_files_are_not(tmp_path):
    image = tmp_path / "pixel.png"
    image.write_bytes(png_bytes())
    assert pdf_images(render_pdf(f'<img src="{png_data_url()}">')) == 1
    assert pdf_images(render_pdf(f'<img src="{image.as_uri()}">')) == 0
    assert pdf_images(render_pdf(f'<img src="{image.as_uri()}">', remote_resources=True)) == 0
    assert pdf_images(render_pdf('<img src="pixel.png">', base_url=str(tmp_path) + "/")) == 0


@pytest.fixture
def image_server():
    hits = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            body = png_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", hits
    server.shutdown()
    server.server_close()


async def test_remote_resources_are_not_fetched_by_default(client, image_server):
    url, hits = image_server
    response = await client.post("/print/pdf", json={"html": f'<img src="{url}/pixel.png">'})
    assert response.status_code == 200
    assert hits == []
    assert pdf_images(response.content) == 0


async def test_remote_resources_when_enabled(make_client, image_server):
    url, hits = image_server
    client = await make_client(remote_resources=True)
    response = await client.post(
        "/print/pdf", json={"html": '<img src="pixel.png">', "base_url": f"{url}/"}
    )
    assert response.status_code == 200
    assert hits == ["/pixel.png"]
    assert pdf_images(response.content) == 1
