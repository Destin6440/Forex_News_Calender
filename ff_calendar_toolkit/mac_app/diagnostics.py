from __future__ import annotations
import platform
from . import __version__
def collect(metadata=None):
    try:
        from PySide6.QtCore import qVersion
        qt=qVersion()
    except ImportError: qt="not installed"
    return {"application_version":__version__,"python":platform.python_version(),"qt":qt,**(metadata or {})}
