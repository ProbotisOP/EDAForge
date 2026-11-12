"""Start the EDAForge web application on this machine: ``python -m edaforge.server``.

Binds to 127.0.0.1 by default. Set ``EDAFORGE_PORT`` to change the port and ``EDAFORGE_HOME`` to
change where projects are stored.
"""

from __future__ import annotations

import os

import uvicorn

from edaforge.server.app import create_app


def main() -> None:
    host = os.environ.get("EDAFORGE_HOST", "127.0.0.1")
    port = int(os.environ.get("EDAFORGE_PORT", "8000"))
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
