"""Postflop entry point (owned by Macro1027).

The strategies live in src/postflop_<name>.py, each with its own
decide(state, profiles). This file picks the one the bot plays; the Agent
calls postflop.decide and nothing else. To switch, change SELECTED.

build.py does not know about the strategy files, so build this layout with
`python build_postflop.py`, which bundles every src/postflop_*.py, selected
or not.
"""
from . import postflop_champion, postflop_ranges

STRATEGIES = {
    "champion": postflop_champion,
    "ranges": postflop_ranges,
}
SELECTED = "champion"


def decide(state, profiles):
    """Return the selected strategy's action for a flop, turn or river state."""
    return STRATEGIES[SELECTED].decide(state, profiles)
