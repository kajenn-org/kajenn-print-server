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

"""Contract: the OpenAPI document and the MCP tool, each filtered by the caller's tags."""

import base64
import io
import json

from kajenn import AsgiServer
from kajenn.config import AsgiConfigBuilder
from pypdf import PdfReader

from kajenn_print_server import PrintApplication
from tests.conftest import OTHER_TOKEN, started_client


def rpc(method, **params):
    message = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params:
        message["params"] = params
    return message


async def test_schema_documents_the_rest_face(client):
    response = await client.get("/print/_meta/schema_json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "kajenn print server"
    assert schema["servers"] == [{"url": "/print"}]
    operation = schema["paths"]["/pdf"]["post"]
    assert operation["security"] == [{"BearerAuth": []}]
    assert "application/pdf" in operation["responses"]["200"]["content"]
    body = operation["requestBody"]["content"]["application/json"]["schema"]
    assert set(body["properties"]) == {
        "html", "base_url", "filename", "stylesheets", "presentational_hints"
    }
    assert "get" in schema["paths"]["/health"]
    assert "/html_to_pdf" not in schema["paths"]  # an MCP tool, not a REST route


async def test_schema_lists_only_what_the_caller_may_execute(make_client):
    anonymous = await make_client(token=None)
    paths = (await anonymous.get("/print/_meta/schema_json")).json()["paths"]
    assert "/pdf" not in paths and "/health" in paths


async def test_swagger_page(make_client):
    client = await make_client(token=None)
    response = await client.get("/print/_meta/docs")
    assert response.status_code == 200
    assert "/print/_meta/schema_json" in response.text


async def test_tool_is_listed_for_print_callers_only(make_client):
    anonymous = await make_client(token=None)
    assert (await anonymous.post("/print/mcp", json=rpc("tools/list"))).json()["result"] == {
        "tools": []
    }
    other = await make_client(token=OTHER_TOKEN)
    assert (await other.post("/print/mcp", json=rpc("tools/list"))).json()["result"] == {
        "tools": []
    }
    printer = await make_client()
    tools = (await printer.post("/print/mcp", json=rpc("tools/list"))).json()["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["html_to_pdf"]
    assert tools[0]["inputSchema"]["required"] == ["html"]


async def test_tool_answers_the_pdf_base64_encoded(client):
    arguments = {"html": "<h1>MCP</h1>", "filename": "agent report"}
    message = rpc("tools/call", name="html_to_pdf", arguments=arguments)
    result = (await client.post("/print/mcp", json=message)).json()["result"]
    assert not result.get("isError")
    payload = json.loads(result["content"][0]["text"])
    pdf = base64.b64decode(payload["data_base64"])
    assert pdf.startswith(b"%PDF-")
    assert payload["size"] == len(pdf)
    assert payload["filename"] == "agent_report.pdf"
    assert payload["content_type"] == "application/pdf"


async def test_tool_takes_stylesheets(client):
    arguments = {"html": "<p>x</p>", "stylesheets": ["@page { size: A5 }"],
                 "presentational_hints": True}
    message = rpc("tools/call", name="html_to_pdf", arguments=arguments)
    result = (await client.post("/print/mcp", json=message)).json()["result"]
    assert not result.get("isError")
    pdf = base64.b64decode(json.loads(result["content"][0]["text"])["data_base64"])
    box = PdfReader(io.BytesIO(pdf)).pages[0].mediabox
    assert round(float(box.width)) == 420


async def test_tool_reports_a_missing_source(client):
    message = rpc("tools/call", name="html_to_pdf", arguments={"html": " "})
    result = (await client.post("/print/mcp", json=message)).json()["result"]
    assert result["isError"] is True
    assert "an HTML source is required" in result["content"][0]["text"]


async def test_tool_is_not_a_rest_route(client):
    response = await client.post("/print/html_to_pdf", json={"html": "<p>x</p>"})
    assert response.status_code == 404


async def test_public_mount_opens_the_tool_too(make_client):
    client = await make_client(public=True, token=None)
    message = rpc("tools/call", name="html_to_pdf", arguments={"html": "<p>x</p>"})
    result = (await client.post("/print/mcp", json=message)).json()["result"]
    assert not result.get("isError")


async def test_site_root_leads_to_the_api_docs(make_client):
    client = await make_client(token=None)
    first = await client.get("/")
    assert (first.status_code, first.headers["location"]) == (307, "/print/")
    second = await client.get("/print/")
    assert (second.status_code, second.headers["location"]) == (307, "/print/_meta/docs")
    final = await client.get("/", follow_redirects=True)
    assert final.status_code == 200
    assert str(final.url) == "http://print.test/print/_meta/docs"
    assert "/print/_meta/schema_json" in final.text


async def test_root_redirect_is_for_reading_only(make_client):
    client = await make_client(token=None)
    assert (await client.head("/print/")).status_code == 307
    assert (await client.post("/print/", json={})).status_code == 404


async def test_no_redirect_when_docs_are_off():
    class Configuration(AsgiConfigBuilder):
        def main(self, root):
            apps = root.configuration().applications()
            apps.application(code="print", app_class=PrintApplication, docs="off")

    server = AsgiServer(config=Configuration)
    client = await started_client(server, None)
    async with client:
        assert (await client.get("/print/")).status_code == 404
        assert (await client.get("/print/_meta/docs")).status_code == 404
    await server.lifespan.shutdown()
