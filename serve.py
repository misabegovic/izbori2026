#!/usr/bin/env python3
"""Static file server for Railway (serves dist/ on $PORT)."""
import http.server
import os
import functools

port = int(os.environ.get("PORT", "8000"))
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory="dist")
with http.server.ThreadingHTTPServer(("0.0.0.0", port), handler) as srv:
    print(f"serving dist/ on :{port}")
    srv.serve_forever()
