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

"""A print network service mounted as a kajenn application."""

from typing import TYPE_CHECKING, Any

__all__ = ["PRINT_ROUTES", "PRINT_TAG", "PrintApplication", "PrintGrammar", "render_pdf"]

if TYPE_CHECKING:
    from .printing import PRINT_ROUTES, PRINT_TAG, PrintApplication, PrintGrammar, render_pdf


def __getattr__(name: str) -> Any:
    """Load the server side on first use: ``kajenn-print`` needs no PDF renderer."""
    if name in __all__:
        from . import printing

        return getattr(printing, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
