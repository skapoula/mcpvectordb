"""Entry point for 'python -m mcpvectordb' and for PyInstaller-frozen executables.

PyInstaller uses this file as the Analysis entry script so that the frozen .exe
starts with multiprocessing freeze support set up before any other import runs.
"""

import multiprocessing

# Required on Windows for frozen executables that use multiprocessing internally
# (lancedb and onnxruntime both spawn worker processes for heavy operations).
if hasattr(multiprocessing, "freeze_support"):
    multiprocessing.freeze_support()

from mcpvectordb.server import main  # noqa: E402

if __name__ == "__main__":
    main()
