import sys
from . import error_handler

if sys.version_info[0] != 3:
    estr  = "python3 (ideally >= v3.7) required!\n"
    estr += "  Found python version: %s"%sys.version
    raise error_handler.MsgError(estr)

def run(*args, **kwargs):
    """Load the legacy command dispatcher only when the CLI is invoked.

    Keeping this import lazy lets the lightweight CP2K cube parser and GUI run
    without importing optional legacy dependencies such as pycolt/openbabel.
    """

    from .actions import run as action_run

    return action_run(*args, **kwargs)
