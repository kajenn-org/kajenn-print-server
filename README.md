# kajenn-print-server

A print network service, mounted as a [kajenn](https://github.com/kajenn-org/kajenn)
application. The first endpoint turns an HTML source into a PDF.

**Status:** alpha, `0.1.0a1`, not published.

## Run with Docker

```bash
docker build -t kajenn-print-server .
docker run -d -p 8000:8000 -v print-data:/data \
  -e KAJENN_ADMIN_TOKEN="$(openssl rand -hex 24)" \
  -e KAJENN_STORAGE_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  kajenn-print-server
```

CI publishes the image to `ghcr.io/kajenn-org/kajenn-print-server` from `main`
and `v*` tags. Keep `KAJENN_STORAGE_KEY` stable: it decrypts the api keys in `/data`.

## Local testing with Docker Compose

```bash
docker compose up --build              # http://127.0.0.1:8000, authentication off
kajenn-print some.html                 # in another terminal
```

To test token authentication, copy `.env.example` to `.env` (git-ignored), set
`PRINT_AUTH=token` and both secrets, and run `docker compose up --build` again.
Api keys persist in the `print-data` volume; `docker compose down -v` removes them.

## Authentication

Authentication uses kajenn tokens. The operator authenticates with
`KAJENN_ADMIN_TOKEN` and issues api keys carrying the `print` tag:

```bash
curl -H "Authorization: Bearer $KAJENN_ADMIN_TOKEN" -H 'Content-Type: application/json' \
     -d '{"label":"erp","tags":["print"]}' http://127.0.0.1:8000/_server/tokens/issue
```

The `gak_...` key is returned once. Clients send it as a bearer token. List and
revoke keys with `/_server/tokens/list` and `/_server/tokens/revoke?key_id=...`.

For an internal deployment whose network already restricts access, run with
`PRINT_AUTH=off`: printing is public and neither secret is needed.

| Variable | Default | Meaning |
|---|---|---|
| `PRINT_AUTH` | `token` | `token` or `off` |
| `KAJENN_ADMIN_TOKEN` | — | Operator bearer token (required with `token`) |
| `KAJENN_STORAGE_KEY` | — | Fernet key encrypting the api-key store (required with `token`) |
| `KAJENN_PRINT_HOME` | `/data` in the image | Folder holding `api_keys/` |
| `PRINT_REMOTE_RESOURCES` | off | Let documents load HTTP(S) stylesheets, images and fonts |
| `PRINT_FETCH_TIMEOUT` | `10` | Seconds per remote fetch |

## Print

```bash
curl -H "Authorization: Bearer $PRINT_KEY" -H 'Content-Type: application/json' \
     -d '{"html": "<h1>Hello</h1>", "filename": "hello.pdf"}' \
     -o hello.pdf http://127.0.0.1:8000/print/pdf
curl -H "Authorization: Bearer $PRINT_KEY" -F html=@invoice.html \
     -o invoice.pdf http://127.0.0.1:8000/print/pdf
```

`POST <mount>/pdf` takes `html` (required), `base_url` and `filename`, as JSON
or multipart, and answers `application/pdf` as an attachment.
`GET <mount>/health` is a public liveness probe.

## API documentation and MCP

The application is a kajenn `McpOpenApiApplication`:

- `GET /print/_meta/docs` — Swagger UI; `GET /print/_meta/schema_json` — OpenAPI 3.1.
  The site root `/` (and `/print/`) redirects there.
- `POST /print/mcp` — MCP endpoint with one tool, `html_to_pdf`, answering the
  PDF base64-encoded in JSON (`data_base64`, `filename`, `size`, ...).

Both list only what the caller may execute: the `pdf` route and the tool need
the `print` tag, like REST.

Only `data:` URLs are loaded by default; `file:` URLs are never loaded.
See [Getting started](docs/getting-started.md) for the full contract.

## Command line

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

## Run from a checkout

The PDF renderer needs Pango (`sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0`
on Debian/Ubuntu).

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,docs]"
PRINT_AUTH=off kajenn serve examples/print_server/config.py --port 8000
```

## Use it in your own recipe

```python
from kajenn.config import AsgiConfigBuilder
from kajenn_print_server import PrintApplication


class SiteConfiguration(AsgiConfigBuilder):
    def main(self, root):
        cfg = root.configuration()
        app = cfg.applications().application(code="print", app_class=PrintApplication)
        app.pdf(remote_resources=False, timeout=10)
        app.access(public=False)  # True: no credential required
```

The routes require the `print` tag; configure kajenn authentication
(`cfg.authentication()`) to give callers credentials carrying it.

## Contributing

```bash
git config core.hooksPath hooks
pytest -q
ruff check src tests examples tools
python tools/check_boundary.py
sphinx-build -W -b html docs docs/_build/html
```

Apache-2.0 · Copyright Softwell S.r.l.
