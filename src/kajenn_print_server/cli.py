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

"""``kajenn-print``: send an HTML file to a print server and save the PDF it answers.

::

    kajenn-print invoice.html                      # writes invoice.pdf
    kajenn-print invoice.html -o out/invoice.pdf
    cat page.html | kajenn-print - -o - > page.pdf

The server defaults to ``http://127.0.0.1:8000``, the port the Docker image
publishes; ``--url`` or ``KAJENN_PRINT_URL`` points elsewhere. A server with
token authentication needs an api key carrying the ``print`` tag, read from
``KAJENN_PRINT_TOKEN`` (preferred: a ``--token`` argument is visible to other
local users in the process list).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx

__all__ = ["DEFAULT_URL", "main"]

DEFAULT_URL = "http://127.0.0.1:8000"
"""The address the Docker image publishes."""

DEFAULT_MOUNT = "print"


class PrintError(Exception):
    """A failure reported to the user as one line, exit status 1."""


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="kajenn-print",
        description="Send an HTML file to a kajenn print server and save the PDF.",
    )
    parser.add_argument("source", help="HTML file to print, or - for standard input")
    parser.add_argument(
        "-o", "--output",
        help="PDF to write, or - for standard output (default: the source name with .pdf)",
    )
    parser.add_argument(
        "--url", default=os.environ.get("KAJENN_PRINT_URL", DEFAULT_URL),
        help=f"print server address (default: $KAJENN_PRINT_URL or {DEFAULT_URL})",
    )
    parser.add_argument(
        "--mount", default=DEFAULT_MOUNT,
        help=f"mount of the print application (default: {DEFAULT_MOUNT})",
    )
    parser.add_argument(
        "--token", default=os.environ.get("KAJENN_PRINT_TOKEN"),
        help="api key sent as a bearer token (default: $KAJENN_PRINT_TOKEN)",
    )
    parser.add_argument(
        "--base-url", help="base for relative URLs in the source, resolved by the server"
    )
    parser.add_argument("--timeout", type=float, default=60.0, help="seconds (default: 60)")
    return parser.parse_args(argv)


def read_source(source: str) -> tuple[str, bytes]:
    """The upload's file name and bytes."""
    if source == "-":
        return "document.html", sys.stdin.buffer.read()
    path = Path(source)
    try:
        return path.name, path.read_bytes()
    except OSError as error:
        raise PrintError(f"cannot read {source}: {error.strerror or error}") from None


def output_path(source: str, output: str | None) -> str:
    if output:
        return output
    if source == "-":
        return "document.pdf"
    return str(Path(source).with_suffix(".pdf"))


def error_detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("error", response.text))
    except ValueError:
        return response.text.strip() or response.reason_phrase


def request_pdf(
    args: argparse.Namespace, name: str, html: bytes, transport: httpx.BaseTransport | None
) -> bytes:
    endpoint = f"{args.url.rstrip('/')}/{args.mount.strip('/')}/pdf"
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    data = {"filename": Path(name).with_suffix(".pdf").name}
    if args.base_url:
        data["base_url"] = args.base_url
    try:
        with httpx.Client(transport=transport, timeout=args.timeout) as client:
            response = client.post(
                endpoint,
                headers=headers,
                data=data,
                files={"html": (name, html, "text/html")},
            )
    except httpx.HTTPError as error:
        raise PrintError(f"cannot reach {endpoint}: {error}") from None
    if response.status_code == 401:
        hint = "" if args.token else "; set KAJENN_PRINT_TOKEN"
        raise PrintError(f"authentication required (401){hint}")
    if response.status_code == 403:
        raise PrintError("the token does not carry the print tag (403)")
    if response.status_code != 200:
        raise PrintError(f"server answered {response.status_code}: {error_detail(response)}")
    if response.headers.get("content-type", "").split(";")[0] != "application/pdf":
        raise PrintError(f"{endpoint} did not answer a PDF; check --url and --mount")
    return response.content


def write_output(target: str, pdf: bytes) -> None:
    if target == "-":
        sys.stdout.buffer.write(pdf)
        sys.stdout.buffer.flush()
        return
    try:
        Path(target).write_bytes(pdf)
    except OSError as error:
        raise PrintError(f"cannot write {target}: {error.strerror or error}") from None


def main(argv: list[str] | None = None, transport: httpx.BaseTransport | None = None) -> int:
    """Run the command; ``transport`` lets tests answer without a network."""
    args = parse_args(argv)
    try:
        name, html = read_source(args.source)
        if not html.strip():
            raise PrintError(f"{args.source} is empty")
        target = output_path(args.source, args.output)
        pdf = request_pdf(args, name, html, transport)
        write_output(target, pdf)
    except PrintError as error:
        print(f"kajenn-print: {error}", file=sys.stderr)
        return 1
    if target != "-":
        print(f"{target}: {len(pdf)} bytes", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
