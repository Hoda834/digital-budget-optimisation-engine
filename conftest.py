"""Put the src/ directory on sys.path so the package imports
(`from claro_engine.core...`, `from claro_engine.modules...`) resolve when tests run from the
repository root, mirroring how `streamlit run src/app.py` adds src/ to
the path at runtime.
"""
import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
