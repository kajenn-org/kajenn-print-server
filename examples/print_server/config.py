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

"""The print server recipe, also run by the Docker image.

``PRINT_AUTH`` chooses how callers are admitted:

``token`` (the default)
    Callers need a credential carrying the ``print`` tag. ``KAJENN_ADMIN_TOKEN``
    authenticates the operator, who issues kajenn api keys tagged ``print``
    through ``/_server/tokens/issue``; clients send them as
    ``Authorization: Bearer gak_...``. Keys are stored encrypted with
    ``KAJENN_STORAGE_KEY`` under ``KAJENN_PRINT_HOME`` (default: the working
    directory). Both variables are required.

``off``
    The print route is public, for an internal deployment whose network
    already restricts who reaches it. No token or storage key is needed.

Run from the repository root::

    PRINT_AUTH=off kajenn serve examples/print_server/config.py --port 8000
"""

import os

from genro_bag.resolvers import EnvResolver
from kajenn.config.templates import CONFIGURATION_TEMPLATES

from kajenn_print_server import PrintApplication

AUTH_MODES = {"token": True, "off": False}


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def token_auth() -> bool:
    """Read ``PRINT_AUTH``; with tokens on, the secrets it needs must be present."""
    mode = os.environ.get("PRINT_AUTH", "token").strip().lower()
    if mode not in AUTH_MODES:
        raise ValueError(f"PRINT_AUTH must be one of {sorted(AUTH_MODES)}, not {mode!r}")
    if AUTH_MODES[mode]:
        missing = [n for n in ("KAJENN_ADMIN_TOKEN", "KAJENN_STORAGE_KEY") if not os.environ.get(n)]
        if missing:
            raise ValueError(f"PRINT_AUTH=token requires {', '.join(missing)}")
    return AUTH_MODES[mode]


class PrintServerConfiguration(CONFIGURATION_TEMPLATES["default"]):
    """One print application at ``/print``, with token authentication or none."""

    token_auth = token_auth()
    storage_key = EnvResolver("KAJENN_STORAGE_KEY") if token_auth else None
    site_home = os.environ.get("KAJENN_PRINT_HOME") or None

    def main(self, root):
        cfg = root.configuration()
        self.site_section(cfg)
        self.server_section(cfg)
        self.storage_section(cfg)
        if self.token_auth:
            self.authentication_section(cfg)
        self.applications_section(cfg)

    def server_section(self, cfg):
        cfg.server(host="127.0.0.1", port=8000)

    def authentication_section(self, cfg):
        """Api keys in the home volume; one static operator token from the environment."""
        section = cfg.authentication()
        section.tokens(mount="home", prefix="api_keys")
        section.credentials().bearer_token(
            identity="operator",
            token=EnvResolver("KAJENN_ADMIN_TOKEN"),
            tags="SUPERADMIN,SERVER_ADMIN",
        )

    def applications_section(self, cfg):
        # The site root redirects to /print/, which redirects to its API docs.
        apps = cfg.applications(default="print")
        app = apps.application(code="print", app_class=PrintApplication)
        app.pdf(
            remote_resources=env_flag("PRINT_REMOTE_RESOURCES"),
            timeout=int(os.environ.get("PRINT_FETCH_TIMEOUT", "10")),
        )
        app.access(public=not self.token_auth)
