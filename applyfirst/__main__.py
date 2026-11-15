"""`python -m applyfirst` works even when the `applyfirst` command is not on PATH (common on Windows)."""
import sys

from .cli import main

sys.exit(main())
