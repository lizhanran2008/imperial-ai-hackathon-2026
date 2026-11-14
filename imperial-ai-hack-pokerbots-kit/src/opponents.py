"""Opponent modelling stub (owned by Davidlikestoprogram)."""

from . import common


class OpponentModel:
    """Per-round opponent tracker returning population defaults (stub)."""

    def __init__(self):
        self._num_players = 8
        self._profiles = {}

    def start(self, info):
        """Initialise table state once before the first hand."""
        self._num_players = int(info.get("num_players", 8)) if isinstance(info, dict) else 8
        self._profiles = {
            seat: dict(common.DEFAULT_PROFILE) for seat in range(self._num_players)
        }

    def observe(self, summary):
        """Record a completed hand summary (stub no-op, never raises)."""
        if not isinstance(summary, dict):
            return

    def profiles(self):
        """Return per-seat profile dicts for all seats at the table."""
        if not self._profiles:
            return {
                seat: dict(common.DEFAULT_PROFILE) for seat in range(self._num_players)
            }
        return {seat: dict(prof) for seat, prof in self._profiles.items()}
