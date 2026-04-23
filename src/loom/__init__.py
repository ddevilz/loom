from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("loom")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"


def _install_fast_event_loop() -> None:
    if sys.platform == "win32":
        return
        try:
            import winloop  # type: ignore

            winloop.install()
        except ImportError:
            pass
        return

    try:
        import uvloop  # type: ignore

        uvloop.install()
    except ImportError:
        pass


_install_fast_event_loop()
