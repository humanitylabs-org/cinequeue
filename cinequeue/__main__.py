"""Entry point used by the packaged image: `python -m cinequeue`."""
import os

from cinequeue import server

server.run(
    port=int(os.environ.get("CINEQUEUE_PORT", "8765")),
    host=os.environ.get("CINEQUEUE_HOST", "127.0.0.1"),
)
