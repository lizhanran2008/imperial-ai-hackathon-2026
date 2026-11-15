# Postflop experiments

Earlier postflop strategies, kept for reference. None of them is in the bot: `build.py` bundles only the modules in `src/`, and nothing imports these files.

| File | What it tried |
| --- | --- |
| `postflop_ranges.py` | The first version built on opponent ranges and sampled equity |
| `postflop_value.py` | The same model, betting made hands bigger and thinner and never bluffing |
| `postflop_ranges_v2.py` | Ranges with one set of stratified trials and one table of expected chips |
| `postflop_ranges_v3.py` | The `ranges_v2` model at about half the time per decision. The postflop module now in `src/` grew out of it |

Each file's docstring describes its design and what was measured.

To try one again, copy it back into `src/`, add its name to `MODULES` in `build.py` and call its `decide(state, profiles)` from `src/agent.py`. `postflop_ranges.py` and `postflop_value.py` import `handeval` relative to `src/`, so they only load from there.
