"""Entry point for ``python -m astra``.

Exists so the CLI is reachable without the console script the wheel installs.
That matters in exactly the situation the CLI is most useful: diagnosing an
installation where ``pip install`` did not complete, or running from a source
checkout before the package has been installed at all.
"""

from __future__ import annotations

import sys

from astra.bootstrap.cli import main

if __name__ == "__main__":
    sys.exit(main())
