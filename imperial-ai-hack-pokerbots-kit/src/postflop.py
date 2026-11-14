"""Postflop entry point (owned by Macro1027).

The strategies live in src/postflop_<name>.py, each with its own
decide(state, profiles). This file picks the one the bot plays; the Agent
calls postflop.decide and nothing else. To switch, change SELECTED.

Every strategy listed here is bundled into bot.py by build.py, selected or
not, so each new file also needs adding to MODULES there.
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
