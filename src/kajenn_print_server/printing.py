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

"""The print application: HTML sources rendered to PDF documents."""

from __future__ import annotations

import base64
import re
import time
from importlib.metadata import version
from typing import Annotated, Any

from genro_builders.builder import element
from genro_routes import route
from pydantic import Field
from weasyprint import HTML
from weasyprint.urls import URLFetcher

from kajenn.application import ApplicationGrammar
from kajenn.applications.mcp import McpOpenApiApplication
from kajenn.exceptions import HTTPBadRequest
from kajenn.request import UploadedFile
from kajenn.response import Response
from kajenn.types import Receive, Scope, Send

__all__ = ["PRINT_ROUTES", "PRINT_TAG", "PrintApplication", "PrintGrammar", "render_pdf"]

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class PrintGrammar(ApplicationGrammar):
    """The print application's own vocabulary, on top of the inherited ``parameters``."""

    @element(node_label="pdf", sub_tags="")
    def pdf(self, remote_resources: bool = False, timeout: int = 10) -> None:
        """Rendering options, read back as ``applications.<code>.pdf.<attr>``.

        ``remote_resources`` lets a document load stylesheets, images and fonts
        over HTTP(S). Off by default: only ``data:`` URLs embedded in the source
        are resolved, so a caller cannot make the server fetch arbitrary URLs.
        Local ``file:`` URLs are never resolved. ``timeout`` bounds each fetch.
        """

    @element(node_label="access", sub_tags="")
    def access(self, public: bool = False) -> None:
        """Who may print, read back as ``applications.<code>.access.public``.

        By default a caller needs a credential carrying the ``print`` tag.
        ``public=True`` opens the routes to anonymous callers: only for an
        internal deployment whose network already restricts who reaches it.
        """


def render_pdf(
    html: str, base_url: str | None = None, remote_resources: bool = False, timeout: int = 10
) -> bytes:
    """Render an HTML source to PDF bytes. Blocking: call it off the event loop."""
    protocols = ("data", "http", "https") if remote_resources else ("data",)
    fetcher = URLFetcher(timeout=timeout, allowed_protocols=protocols)
    document: bytes = HTML(string=html, base_url=base_url, url_fetcher=fetcher).write_pdf()
    return document


def _safe_filename(filename: str) -> str:
    stem = _UNSAFE_FILENAME.sub("_", filename).strip("._") or "document"
    return stem if stem.lower().endswith(".pdf") else f"{stem}.pdf"


PRINT_TAG = "print"
"""The avatar tag a caller needs to reach the print routes."""


HtmlSource = Annotated[
    Any,
    Field(
        description="The HTML source (required): a string in a JSON or form body, "
        "or a multipart file part.",
        json_schema_extra={"type": "string"},
    ),
]
"""``html`` of the REST route: ``Any`` so a multipart ``UploadedFile`` validates too."""

PRINT_ROUTES = "pdf,html_to_pdf"
"""The routes guarded by ``PRINT_TAG``, comma-separated as the router targets them."""


class PrintApplication(McpOpenApiApplication):
    """Print API over REST, OpenAPI and MCP.

    - ``POST <mount>/pdf`` answers the PDF itself (REST only);
    - ``html_to_pdf`` is the MCP tool, answering the PDF base64-encoded in JSON;
    - ``<mount>/_meta/docs`` and ``<mount>/_meta/schema_json`` document the REST
      face, and ``<mount>/`` redirects to the docs; ``<mount>/mcp`` is the MCP
      JSON-RPC endpoint.

    Printing requires the ``print`` tag: issue callers a kajenn api key (or a
    configured bearer token) carrying it. ``access(public=True)`` turns that off.
    """

    grammar = PrintGrammar
    openapi_info = {
        "title": "kajenn print server",
        "version": version("kajenn-print-server"),
        "description": "Render HTML sources to PDF documents.",
    }
    mcp_name = "kajenn-print-server"
    mcp_version = openapi_info["version"]

    def on_startup(self) -> None:
        """Drop the ``print`` rule on a mount declared ``access(public=True)``."""
        if self.config("access.public", default=False):
            # The router binds its entries lazily, writing each decorator's
            # auth_rule then: bind first, or the binding overwrites the override.
            self.route.nodes()
            self.route.auth.configure(_target=PRINT_ROUTES, rule="")

    async def _render(self, html, base_url: str | None) -> tuple[bytes, float]:
        """Validate the source, render it off the loop; the PDF and its milliseconds."""
        if isinstance(html, UploadedFile):
            html = html.data
        if isinstance(html, bytes):
            try:
                html = html.decode("utf-8")
            except UnicodeDecodeError:
                raise HTTPBadRequest("the HTML source must be UTF-8 encoded") from None
        if not isinstance(html, str) or not html.strip():
            raise HTTPBadRequest("an HTML source is required in the 'html' field")
        server = self.server
        if server is None:
            raise RuntimeError(f"{type(self).__name__} is not attached to a server")
        started = time.perf_counter()
        document: bytes = await server.run_sync(
            render_pdf,
            html,
            base_url,
            bool(self.config("pdf.remote_resources", default=False)),
            int(self.config("pdf.timeout", default=10)),
        )
        return document, (time.perf_counter() - started) * 1000

    @property
    def docs_url(self) -> str | None:
        """Where the API documentation lives, ``None`` when it is turned off."""
        if self.docs_style == "off":
            return None
        return f"/{self.mount}/_meta/docs" if self.mount else "/_meta/docs"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """The application root sends a browser to the API documentation."""
        path = str(scope.get("path", "/"))
        method = scope.get("method")
        if path in ("", "/") and method in ("GET", "HEAD") and self.docs_url:
            redirect = Response(status_code=307, headers={"location": self.docs_url})
            await redirect(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

    @route()
    def health(self) -> dict[str, str]:
        """Public liveness probe for container healthchecks and orchestrators."""
        return {"status": "ok"}

    @route(auth_rule=PRINT_TAG, media_type="application/pdf", openapi_method="post")
    async def pdf(
        self,
        html: HtmlSource = None,
        base_url: str | None = None,
        filename: str = "document.pdf",
        _request=None,
    ) -> bytes:
        """Render ``html`` to PDF and answer it as ``application/pdf``.

        ``html`` is a JSON field or a multipart part (a file or a text field).
        ``base_url`` resolves relative URLs in the source; ``filename`` names
        the attachment in ``Content-Disposition``.
        """
        document, elapsed_ms = await self._render(html, base_url)
        if _request is not None:
            response = _request.response
            response.set_header(
                "Content-Disposition", f'attachment; filename="{_safe_filename(filename)}"'
            )
            # Lets a client tell rendering time from network and queueing time.
            response.set_header("Server-Timing", f"render;dur={elapsed_ms:.1f}")
        return document

    @route(auth_rule=PRINT_TAG, channel_channels="mcp")
    async def html_to_pdf(
        self, html: str, base_url: str | None = None, filename: str = "document.pdf"
    ) -> dict:
        """Render an HTML document to PDF.

        Returns the PDF base64-encoded in ``data_base64``, with its ``filename``,
        ``content_type`` and ``size`` in bytes. Only ``data:`` URLs are loaded
        unless the server allows remote resources; ``base_url`` resolves
        relative URLs.
        """
        document, elapsed_ms = await self._render(html, base_url)
        return {
            "filename": _safe_filename(filename),
            "content_type": "application/pdf",
            "size": len(document),
            "render_ms": round(elapsed_ms, 1),
            "data_base64": base64.b64encode(document).decode("ascii"),
        }
