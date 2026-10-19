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

"""Show where the PDF renderer spends its time on one HTML file.

    python tools/profile_render.py document.html [--remote] [--top 15] [--no-profile]

Prints each rendering step with its elapsed time, every warning (a resource that
failed or timed out shows up here), then the functions with the most cumulative
time. Rendering uses the same settings as the server: ``data:`` URLs only,
unless ``--remote`` allows HTTP(S) like ``PRINT_REMOTE_RESOURCES``.

The step timings come from the progress log of the current renderer, WeasyPrint.
"""

import argparse
import cProfile
import logging
import pstats
import sys
import time
from pathlib import Path

from kajenn_print_server.printing import render_pdf


class StepTimer(logging.Handler):
    """Print each renderer log record with the seconds since the start."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.started = time.perf_counter()

    def emit(self, record: logging.LogRecord) -> None:
        elapsed = time.perf_counter() - self.started
        print(f"{elapsed:8.2f}s  {record.levelname:7} {record.getMessage()}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("source", type=Path)
    parser.add_argument("--remote", action="store_true", help="allow HTTP(S) resources")
    parser.add_argument("--timeout", type=int, default=10, help="seconds per fetch")
    parser.add_argument("--top", type=int, default=15, help="functions to list")
    parser.add_argument(
        "--no-profile", action="store_true",
        help="time the steps only; the profiler roughly doubles the run time",
    )
    args = parser.parse_args()

    html = args.source.read_text(encoding="utf-8")
    base_url = args.source.resolve().parent.as_uri() + "/"
    timer = StepTimer()
    for name in ("weasyprint", "weasyprint.progress"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        logger.addHandler(timer)
        logger.propagate = False

    profile = None if args.no_profile else cProfile.Profile()
    if profile:
        profile.enable()
    pdf = render_pdf(html, base_url, remote_resources=args.remote, timeout=args.timeout)
    if profile:
        profile.disable()
    total = time.perf_counter() - timer.started
    print(f"{total:8.2f}s  done: {len(html)} characters in, {len(pdf)} bytes out\n",
          file=sys.stderr)
    if profile:
        stats = pstats.Stats(profile, stream=sys.stderr)
        stats.sort_stats("cumulative").print_stats(args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
