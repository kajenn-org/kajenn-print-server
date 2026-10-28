# Getting started

## Install

The PDF renderer needs Pango at runtime. On Debian or Ubuntu:

```bash
sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0
```

Then, from a checkout:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,docs]"
```

## Serve

```bash
PRINT_AUTH=off kajenn serve examples/print_server/config.py --port 8000
```

The recipe mounts `PrintApplication` with the code `print`, so the endpoint is
`POST /print/pdf`. `PRINT_AUTH=off` makes it public; the default, `token`, is
described under [access control](#access-control). The Docker image runs the
same recipe; see the README for its variables.

## Render a PDF

The HTML source travels in the `html` field, as JSON or as a multipart part:

```bash
curl -H 'Content-Type: application/json' \
     -d '{"html": "<h1>Hello</h1>", "filename": "hello.pdf"}' \
     -o hello.pdf http://127.0.0.1:8000/print/pdf

curl -F html=@invoice.html -o invoice.pdf http://127.0.0.1:8000/print/pdf

# With token authentication, add: -H "Authorization: Bearer $PRINT_KEY"
```

| Argument | Meaning |
|---|---|
| `html` | The HTML source (required) |
| `base_url` | Base for relative URLs in the source |
| `filename` | Attachment name in `Content-Disposition`, default `document.pdf` |
| `stylesheets` | List of CSS sources applied as user stylesheets, in order (JSON body only) |
| `presentational_hints` | Honour HTML attributes such as `width`, `align` or `bgcolor`; default `false` |

User stylesheets come after the document in the cascade but lose to its rules
unless declared `!important`, so a caller can impose a page size or margins on a
document that sets its own. Their URLs follow the same fetching rules as the
document's: only `data:` URLs unless the server allows remote resources.

The answer is `200` with `Content-Type: application/pdf` and a `Server-Timing:
render;dur=<ms>` header. A missing, empty or non-UTF-8 source is `400`; a body
kajenn cannot decode, such as a bare `text/html` body, is `415`.

### From the command line

Installing the package adds `kajenn-print`, which uploads an HTML file and
saves the PDF. It targets `http://127.0.0.1:8000`, the port the Docker image
publishes:

```bash
export KAJENN_PRINT_TOKEN=gak_...        # not needed with PRINT_AUTH=off
kajenn-print invoice.html                # writes invoice.pdf
kajenn-print invoice.html -o out.pdf --url https://print.example.com
cat page.html | kajenn-print - -o - > page.pdf
```

`--url` (or `KAJENN_PRINT_URL`) selects another server, `--mount` another
mount, and `--base-url` the base for relative URLs. Prefer the
`KAJENN_PRINT_TOKEN` variable to `--token`, which other local users can see in
the process list. Failures print one line on stderr and exit with status 1.

## API documentation

`PrintApplication` is a kajenn `McpOpenApiApplication`. Under its mount:

| Path | What |
|---|---|
| `GET /` | Redirects to `/print/`, which redirects to the Swagger UI |
| `GET /print/_meta/docs` | Swagger UI |
| `GET /print/_meta/schema_json` | OpenAPI 3.1 document |
| `POST /print/mcp` | MCP endpoint (JSON-RPC over Streamable HTTP) |
| `GET /print/health` | Public liveness probe |

The schema lists only what the caller may execute: without a `print`
credential it shows `health` but not `pdf`.

## MCP tool

The MCP endpoint offers one tool, `html_to_pdf`, with the same arguments as
the REST route. MCP results are JSON, so the tool answers the PDF
base64-encoded:

```json
{"filename": "report.pdf", "content_type": "application/pdf",
 "size": 2792, "render_ms": 24.2, "data_base64": "JVBERi0xLjcK..."}
```

Register `http://127.0.0.1:8000/print/mcp` in an MCP client, with the
`Authorization: Bearer gak_...` header when tokens are on. The tool is listed
only to callers carrying the `print` tag. To check it by hand:

```bash
curl -H "Authorization: Bearer $PRINT_KEY" -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"html_to_pdf","arguments":{"html":"<h1>Hi</h1>"}}}' \
     http://127.0.0.1:8000/print/mcp
```

## Resources referenced by the source

By default only `data:` URLs embedded in the source are loaded. Stylesheets,
images and fonts over HTTP(S) are ignored, so callers cannot make the server
fetch arbitrary URLs. Enable them per mount:

```python
app.pdf(remote_resources=True, timeout=10)
```

`file:` URLs are never loaded, whatever the setting.

## Access control

`POST <mount>/pdf` and the `html_to_pdf` tool require a credential whose avatar carries the `print` tag:
anonymous callers get `401`, callers without the tag `403`. Any kajenn header
credential works; the shipped recipe uses api keys:

1. Start with `KAJENN_ADMIN_TOKEN` and `KAJENN_STORAGE_KEY` set. The first is
   the operator's bearer token (tags `SUPERADMIN,SERVER_ADMIN`); the second
   encrypts the key store under `KAJENN_PRINT_HOME`, which must exist.
2. Issue a key: `POST /_server/tokens/issue` with
   `{"label": "erp", "tags": ["print"]}`, authenticated as the operator.
   The `gak_...` key is returned once.
3. Clients send `Authorization: Bearer gak_...`. Revoke with
   `POST /_server/tokens/revoke?key_id=...`.

A mount declared `app.access(public=True)` drops the requirement; the recipe
does this with `PRINT_AUTH=off`. Use it only where the network already
restricts who reaches the server. `GET <mount>/health` is always public.
