from __future__ import annotations

import sys


def _install_fast_event_loop() -> None:
    if sys.platform == "win32":
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


def hello() -> str:
    return "Hello from loom!"
