"""PyInstaller entry point for the standalone ``kan`` binary (KAN-46).

PyInstaller freezes a *script*, not a module, so it can't be pointed at
``pandan_cli/__main__.py`` directly — that file uses a relative import
(``from .cli import run``) which fails once it is executed as the top-level
``__main__`` with no parent package. This tiny launcher imports the console
entry point *absolutely* and calls it, which is exactly what the ``kan``
console-script (``kan = pandan_cli.__main__:main``) does.
"""
from __future__ import annotations

from pandan_cli.__main__ import main

if __name__ == "__main__":
    main()
