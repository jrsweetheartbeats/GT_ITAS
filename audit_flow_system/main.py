from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn


def main() -> None:
    package_root = Path(__file__).resolve().parent
    workspace_root = package_root.parent
    if str(workspace_root) not in sys.path:
        sys.path.insert(0, str(workspace_root))

    host = os.getenv("AUDIT_FLOW_HOST", "0.0.0.0")
    port = int(os.getenv("AUDIT_FLOW_PORT", "8010"))
    reload = os.getenv("AUDIT_FLOW_RELOAD", "0") in {"1", "true", "TRUE", "yes", "YES"}
    uvicorn.run("audit_flow_system.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
