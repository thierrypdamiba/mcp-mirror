#!/usr/bin/env python3
"""Serve the local talk presenter and open its console."""

from __future__ import annotations

import argparse
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4180)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    talk_directory = Path(__file__).resolve().parents[1] / "talk"
    handler = partial(SimpleHTTPRequestHandler, directory=str(talk_directory))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    presenter_url = f"http://127.0.0.1:{args.port}/present.html"

    print(f"Presenter: {presenter_url}")
    print(f"Audience:  http://127.0.0.1:{args.port}/deck.html?mode=audience")
    print("Press Ctrl-C to stop.")
    if not args.no_open:
        webbrowser.open(presenter_url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
