# Repository instructions

Read the parent [kajenn-meta instructions](https://github.com/kajenn-org/kajenn-meta/blob/main/CLAUDE.md)
and [naming policy](https://github.com/kajenn-org/kajenn-meta/blob/main/NAMING.md).

Distribution: `kajenn-print-server`. Import package: `kajenn_print_server`.
The application depends on kajenn; kajenn must not import this package.
`tools/kajenn-imports.txt` declares the kajenn surface used by runtime code.
Do not vendor server code or import server test helpers.

The PDF renderer is an implementation detail, currently WeasyPrint, and is
meant to be replaceable: keep its name out of user-facing docs, API
descriptions, messages and metadata. Code and developer tools that depend on it
directly may name it.

Rendering is blocking: run the renderer through `self.server.run_sync(...)`,
never on the event loop. Resource fetching stays deny-by-default
(`data:` only; never `file:`).

Run `ruff check src tests examples tools`, `pytest`,
`python tools/check_boundary.py`, and `sphinx-build -W -b html docs docs/_build/html`.
Type checking is advisory. Every Python source carries the Apache license header.
Install hooks with `git config core.hooksPath hooks`.

`PrintApplication` is a `McpOpenApiApplication` in direct mode: `pdf` is REST
only (bytes), `html_to_pdf` is the MCP tool (`channel_channels="mcp"`, base64
JSON). Both require the `print` tag, listed in `PRINT_ROUTES`;
`access(public=True)` clears them in `on_startup` (bind the router first:
genro-routes applies decorator rules lazily). `html` on `pdf` is annotated
`Any` so multipart `UploadedFile` parts validate; keep its schema description. The Docker image runs `examples/print_server/config.py`; keep the
recipe, the Dockerfile and `.github/workflows/docker.yml` smoke tests in step.
