"""
Compatibility wrapper for the fixed walk-forward OOS split.

Prefer the explicit command for new milestone checks:
  python3 scratch/walk_forward.py --split test --milestone "Change XX"
"""

import sys

from walk_forward import main


if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.extend(["--split", "test", "--milestone", "legacy-oos-wrapper"])
    main()
