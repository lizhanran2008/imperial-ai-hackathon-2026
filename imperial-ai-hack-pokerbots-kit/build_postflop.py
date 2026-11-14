"""Build a standalone bot that includes the postflop strategy files.

    python build_postflop.py                 # writes bot_postflop.py
    python build_postflop.py path/to/out.py  # writes somewhere else

src/postflop.py selects one of src/postflop_<name>.py. build.py bundles a fixed
list of modules that does not include those files, so it cannot build this
layout. This script reuses build.py unchanged, with every src/postflop_*.py
added to the list just before postflop, and the same import validation, size
limit and load check.

It does not write bot.py: that generated file belongs to the integration lead.
"""
import glob
import os
import sys

import build


def strategy_modules():
    """Names of the strategy modules, e.g. postflop_champion, in a fixed order."""
    paths = glob.glob(os.path.join(build.SRC_DIR, "postflop_*.py"))
    return sorted(os.path.splitext(os.path.basename(p))[0] for p in paths)


def main():
    extra = strategy_modules()
    if not extra:
        raise SystemExit("No src/postflop_*.py strategy files found.")
    at = build.MODULES.index("postflop")
    build.MODULES = build.MODULES[:at] + tuple(extra) + build.MODULES[at:]
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(build.HERE, "bot_postflop.py")
    build.OUT_PATH = os.path.abspath(out)
    build.main()


if __name__ == "__main__":
    main()
