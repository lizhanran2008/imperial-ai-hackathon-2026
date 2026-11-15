import os
import sys
import json
import argparse
import asyncio
from pathlib import Path
from collections import defaultdict
from anthropic import AsyncAnthropic
from google import genai
from google.genai import types



def load_single_bot_file(bot_path: str = "bot.py") -> str:
    path_obj = Path(bot_path)
    if not path_obj.exists():
        print(f"[ERROR] Could not find '{bot_path}' in the current directory.")
        sys.exit(1)

    lines = path_obj.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    numbered = "".join(f"{idx + 1:04d} | {line}" for idx, line in enumerate(lines))
    return f"=== SINGLE-FILE CODEBASE: {path_obj.name} ({len(lines)} lines) ===\n```python\n{numbered}\n```"


def analyze_json_and_opponents(json_path: str, bot_name: str = "fishermen", max_raw_chars: int = 180_000) -> str:
    path_obj = Path(json_path)
    if not path_obj.exists():
        print(f"[ERROR] JSON input file '{json_path}' not found.")
        sys.exit(1)

    raw_text = path_obj.read_text(encoding="utf-8")
    try:
        data = json.loads(raw_text)
    except Exception as e:
        print(f"[!] JSON parse warning ({e}), passing raw text slice.")
        return f"=== RAW JSON INPUT ===\n{raw_text[:max_raw_chars]}"

    hands = data if isinstance(data, list) else data.get("hands", data.get("rounds", data.get("matches", [])))
    if not isinstance(hands, list) or not hands:
        return f"=== RAW JSON INPUT ===\n{raw_text[:max_raw_chars]}"

    opp = defaultdict(lambda: {
        "hands": 0, "net_chips": 0, "vpip_hands": 0, "pfr_hands": 0,
        "folds": 0, "checks": 0, "calls": 0, "raises": 0, "all_ins": 0,
        "showdowns": 0, "showdown_wins": 0, "raise_amounts": []
    })

    big_wins = []
    big_losses = []
    showdown_hands = []

    for idx, h in enumerate(hands):
        h_str = json.dumps(h, separators=(",", ":"))
        players = h.get("players", h.get("seats", h.get("results", [])))
        if isinstance(players, list):
            for p in players:
                if not isinstance(p, dict):
                    continue
                name = str(p.get("name", p.get("team", p.get("bot", p.get("id", "unknown")))))
                delta = p.get("net", p.get("delta", p.get("payoff", p.get("winnings", p.get("chips_won", 0)))))
                cards = p.get("cards", p.get("hole_cards", p.get("hand", None)))

                opp[name]["hands"] += 1
                if isinstance(delta, (int, float)):
                    opp[name]["net_chips"] += delta
                    if bot_name.lower() in name.lower():
                        if delta >= 400:
                            big_wins.append((delta, idx, h_str))
                        elif delta <= -400:
                            big_losses.append((delta, idx, h_str))

                if cards and not (bot_name.lower() in name.lower()):
                    opp[name]["showdowns"] += 1
                    if isinstance(delta, (int, float)) and delta > 0:
                        opp[name]["showdown_wins"] += 1
                    showdown_hands.append(h_str)

        actions = h.get("actions", h.get("history", h.get("events", [])))
        vpip_seen = set()
        pfr_seen = set()
        if isinstance(actions, list):
            for act in actions:
                if not isinstance(act, dict):
                    continue
                actor = str(act.get("player", act.get("name", act.get("seat", "unknown"))))
                move = str(act.get("action", act.get("type", ""))).lower()
                street = str(act.get("street", act.get("round", "preflop"))).lower()
                amt = act.get("amount", act.get("size", act.get("to", None)))

                if "fold" in move:
                    opp[actor]["folds"] += 1
                elif "check" in move:
                    opp[actor]["checks"] += 1
                elif "call" in move:
                    opp[actor]["calls"] += 1
                    if "pre" in street:
                        vpip_seen.add(actor)
                elif "all_in" in move or "allin" in move:
                    opp[actor]["all_ins"] += 1
                    if "pre" in street:
                        vpip_seen.add(actor)
                        pfr_seen.add(actor)
                elif "raise" in move or "bet" in move:
                    opp[actor]["raises"] += 1
                    if isinstance(amt, (int, float)):
                        opp[actor]["raise_amounts"].append(amt)
                    if "pre" in street:
                        vpip_seen.add(actor)
                        pfr_seen.add(actor)

        for actor in vpip_seen:
            opp[actor]["vpip_hands"] += 1
        for actor in pfr_seen:
            opp[actor]["pfr_hands"] += 1

    table_lines = [
        f"## DEEP OPPONENT & `{bot_name.upper()}` TELEMETRY (Total Hands in JSON: {len(hands)})",
        "| Bot Name | Hands | Net Chips | bb/100 | VPIP% | PFR% | Folds | Checks | Calls | Raises | All-Ins | Avg Raise | Showdowns | Detected Opponent Strategy |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"
    ]

    for name, st in sorted(opp.items(), key=lambda x: x[1]["net_chips"], reverse=True):
        h_cnt = max(st["hands"], 1)
        bb_100 = (st["net_chips"] / 20.0) / (h_cnt / 100.0) if st["hands"] > 0 else 0.0
        vpip_pct = (st["vpip_hands"] / h_cnt) * 100.0
        pfr_pct = (st["pfr_hands"] / h_cnt) * 100.0
        tot_acts = max(st["folds"] + st["checks"] + st["calls"] + st["raises"] + st["all_ins"], 1)
        passive_ratio = (st["folds"] + st["checks"]) / tot_acts
        avg_raise = sum(st["raise_amounts"]) / len(st["raise_amounts"]) if st["raise_amounts"] else 0

        if bot_name.lower() in name.lower():
            profile = f"**OUR BOT ({bot_name.upper()})**"
        elif passive_ratio >= 0.92 and st["raises"] == 0 and st["all_ins"] == 0:
            profile = "GAVE UP / AUTO-CHECK-FOLD BOT (100% STEAL TARGET)"
        elif st["all_ins"] / tot_acts >= 0.12:
            profile = "ALL-IN SHOVE MANIAC (TRAP WITH PREMIUMS)"
        elif st["calls"] / tot_acts >= 0.38 and pfr_pct < 10.0:
            profile = "PASSIVE CALLING STATION (RELENTLESS VALUE, 0 BLUFFS)"
        elif vpip_pct < 14.0 and st["folds"] / tot_acts >= 0.75:
            profile = "ULTRA-TIGHT NIT (STEAL BLINDS, FOLD TO THEIR BIG BETS)"
        elif pfr_pct >= 22.0 and st["raises"] / tot_acts >= 0.20:
            profile = "AGGRESSIVE SHARK / LAG (WIDEN 3-BET & TRAP)"
        else:
            profile = "BALANCED / STANDARD COMPETITOR"

        table_lines.append(
            f"| {name} | {st['hands']} | {st['net_chips']:+} | {bb_100:+.1f} | "
            f"{vpip_pct:.0f}% | {pfr_pct:.0f}% | {st['folds']} | {st['checks']} | "
            f"{st['calls']} | {st['raises']} | {st['all_ins']} | {avg_raise:.0f} | "
            f"{st['showdowns']} | {profile} |"
        )

    big_losses.sort(key=lambda x: x[0])
    big_wins.sort(key=lambda x: x[0], reverse=True)

    curated_json = []
    used_chars = 0
    for _, _, h_str in (big_losses[:20] + big_wins[:15]):
        if used_chars + len(h_str) < max_raw_chars // 2:
            curated_json.append(h_str)
            used_chars += len(h_str)

    for h_str in showdown_hands[:20]:
        if used_chars + len(h_str) < (max_raw_chars * 3) // 4:
            curated_json.append(h_str)
            used_chars += len(h_str)

    for h in hands:
        h_str = json.dumps(h, separators=(",", ":"))
        if used_chars + len(h_str) < max_raw_chars:
            curated_json.append(h_str)
            used_chars += len(h_str)
        else:
            break

    return (
        "\n".join(table_lines)
        + f"\n\n## VERBATIM JSON HAND HISTORIES (Big Wins, Big Losses, & Opponent Showdowns)\n"
        + "```json\n[\n" + ",\n".join(curated_json) + "\n]\n```"
    )


def build_argon_fable_prompts(bot_name: str):
    rules = f"""
IMPERIAL AI HACK POKERBOTS RULES:
- Our Bot Name: `{bot_name}` (Single file `bot.py` < 200 KB)
- Format: 7-8 handed No-Limit Hold'em, 1,000 hands per round against the same table.
- Stack Reset: Every hand resets all bots to 2,000 chips (100 BB) with 10/20 blinds (1 BB = 20 chips).
- Scoring: Pure Chip EV (`bb/100`). Folding every hand loses ~19 bb/100.
- Persistent Memory: `Agent` instance remembers all 1,000 hands via `on_table_start(info)`, `act(state)`, and `on_hand_end(summary)`.
- Sandbox: Python 3.12 Standard Library ONLY, 25 ms per decision, 10 s round bank.
- Timeouts, exceptions, or invalid 'raise to' amounts silently convert to passive check or fold.

STRICT GROUNDING & ZERO-CODE RULES:
1. DO NOT WRITE ANY PYTHON CODE OR PSEUDO-CODE. Output strict mathematical analysis and precise engineering directives for FABLE.
2. Cite exact line numbers in `bot.py` (e.g., `bot.py:L0042`) and exact hand IDs / opponent names from the JSON log.
"""
    return {
        "ARGON_LEAD_ANALYST": f"""You are ARGON (`gemini-4-argon`), the #1 Quantitative Poker Bot Analyst and Lead Strategist. {rules}
        Your responsibility is to audit `bot.py` and the JSON telemetry to determine:
        1. Exact win/loss lines in `bot.py` (what code paths are winning chip EV and must be protected).
        2. Exact tactical leaks bleeding `bb/100` (e.g., pre-flop positional overcalling, multi-way single-pair over-commitment, sizing inefficiencies, or timeout check/folds).""",

        "ARGON_OPPONENT_PROFILER": f"""You are ARGON-PROFILER (`gemini-4-argon` Stateless Instance #2: Deep Opponent Exploitation Analyst). {rules}
        Your responsibility is to analyze the opponent telemetry and JSON records:
        1. Pinpoint teams that gave up (auto-check/fold bots) and design precise blind-stealing/isolation thresholds.
        2. Dissect active opponents (Maniacs, Stations, Nits, Sharks) and formulate counter-exploits across the 1,000-hand round.""",

        "OPUS_MODERATOR": f"""You are CLAUDE-OPUS-MODERATOR (`claude-opus-5-5`: Debater #3, Moderator & Strategy Integrator). {rules}
        Challenge Argon-Lead and Argon-Profiler across the 3 debate rounds:
        - Ensure exploiting 'gave up' bots doesn't leak chips when aggressive sharks remain behind us.
        - Verify all adjustments execute within Python 3.12's 25ms time limit.
        - Drive the team toward a unified, coherent strategy ready for Fable to implement.""",

        "OPUS_FABLE_PROMPT_WRITER": f"""You are the MASTER PROMPT GENERATOR FOR FABLE (`claude-opus-5-5`). {rules}
        Your output will be copied and pasted directly as the prompt into **Fable** (our teammate's AI coding agent that edits `bot.py`).
        Write your entire response in the second person ("You are Fable, the lead pokerbot software engineer for team `{bot_name}`...") so our teammate can paste your output straight into Fable without editing a single word.
        Remember: DO NOT write the Python code yourself—give Fable the exact line numbers, mathematical formulas, state variables, and logic specifications so Fable writes the code."""
    }


async def call_stateless_gemini_argon(
    client: genai.Client, model: str, sys_prompt: str, bundle: str, task: str, thinking_level: str = "high"
) -> str:
    response = await client.aio.models.generate_content(
        model=model,
        contents=f"{bundle}\n\n---\n\n{task}",
        config=types.GenerateContentConfig(
            system_instruction=sys_prompt,
            thinking_config=types.ThinkingConfig(thinking_level=thinking_level),
        ),
    )
    return response.text


async def call_claude_opus(client: AsyncAnthropic, model: str, sys_prompt: str, bundle: str, task: str) -> str:
    response = await client.messages.create(
        model=model,
        max_tokens=16000,
        system=sys_prompt,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": bundle, "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": task},
                ],
            }
        ],
    )
    # Filter out ThinkingBlock objects and join only TextBlock objects
    text_blocks = [
        block.text for block in response.content 
        if getattr(block, "type", None) == "text" or hasattr(block, "text")
    ]
    return "\n".join(text_blocks)


async def main():
    parser = argparse.ArgumentParser(description="Gemini 4 Argon + Claude Opus 5.5 Debate Pipeline for fishermen")
    parser.add_argument("--bot-file", default="bot.py", help="Path to single bot.py file (default: bot.py)")
    parser.add_argument("--json", default="hands.json", help="Path to JSON hand log (default: hands.json)")
    parser.add_argument("--team", default="fishermen", help="Our bot/team name in the JSON (default: fishermen)")
    parser.add_argument("--thinking", default="high", choices=["low", "medium", "high"], help="Argon thinking level")
    parser.add_argument("--gemini-key", default=os.environ.get("GEMINI_API_KEY"), help="Gemini API Key")
    parser.add_argument("--anthropic-key", default=os.environ.get("ANTHROPIC_API_KEY"), help="Anthropic API Key")
    args = parser.parse_args()

    if not args.gemini_key or not args.anthropic_key:
        print("[ERROR] Missing API keys! Provide them via --gemini-key and --anthropic-key or set environment variables.")
        sys.exit(1)

    gemini_client_1 = genai.Client(api_key=args.gemini_key)
    gemini_client_2 = genai.Client(api_key=os.environ.get("GEMINI_API_KEY_2", args.gemini_key))
    anthropic_client = AsyncAnthropic(api_key=args.anthropic_key)

    gemini_model = os.environ.get("GEMINI_MODEL", "gemini-4-argon")
    claude_model = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")

    print(f"[*] Running with Gemini Model: {gemini_model} (thinking_level={args.thinking})")
    print(f"[*] Running with Claude Model: {claude_model}")
    print(f"[*] Loading '{args.bot_file}' and analyzing opponent matches in '{args.json}'...")

    bot_code_str = load_single_bot_file(args.bot_file)
    json_analysis_str = analyze_json_and_opponents(args.json, bot_name=args.team)

    shared_bundle = (
        f"# `{args.team}` SINGLE-FILE CODE (`bot.py`)\n{bot_code_str}\n\n"
        f"# JSON TELEMETRY & OPPONENT PROFILES\n{json_analysis_str}"
    )

    prompts = build_argon_fable_prompts(args.team)
    round_tasks = {
        1: (
            f"### DEBATE ROUND 1 OF 3: ARGON & OPPONENT STRATEGY AUDIT\n"
            f"1. **What is `{args.team}` winning vs. losing at in `bot.py`?** Cite exact line numbers and JSON hands.\n"
            f"2. **What are opponents doing in the JSON?** Profile gave-up teams, maniacs, stations, and sharks.\n"
            f"3. **What is the high-level exploit strategy?** (NO CODE)"
        ),
        2: (
            f"### DEBATE ROUND 2 OF 3: CROSS-EXAMINATION & TABLE REALITY\n"
            f"Critique Round 1 below. Resolve how to exploit gave-up teams safely when sharks remain behind, "
            f"protect winning code paths, and respect the 25ms runtime limit (NO CODE)."
        ),
        3: (
            f"### DEBATE ROUND 3 OF 3: FINAL STRATEGIC CONVERGENCE FOR FABLE\n"
            f"Lock in exact line numbers, opponent classification triggers, and mathematical thresholds before generating the prompt for Fable (NO CODE)."
        ),
    }

    debate_history = []
    for r in range(1, 4):
        print(f"\n================ RUNNING DEBATE ROUND {r} OF 3 ================")
        prior = "\n\n".join(debate_history) if debate_history else "No prior rounds."
        r_prompt = f"## DEBATE TRANSCRIPT SO FAR\n{prior}\n\n{round_tasks[r]}"

        argon_r, profiler_r, mod_r = await asyncio.gather(
            call_stateless_gemini_argon(gemini_client_1, gemini_model, prompts["ARGON_LEAD_ANALYST"], shared_bundle, r_prompt, args.thinking),
            call_stateless_gemini_argon(gemini_client_2, gemini_model, prompts["ARGON_OPPONENT_PROFILER"], shared_bundle, r_prompt, args.thinking),
            call_claude_opus(anthropic_client, claude_model, prompts["OPUS_MODERATOR"], shared_bundle, r_prompt),
        )

        block = (
            f"# ==================== ROUND {r} TRANSCRIPT ====================\n\n"
            f"### [Round {r}] ARGON-LEAD (`{gemini_model}` — Quantitative Code & Leak Analyst)\n{argon_r}\n\n"
            f"### [Round {r}] ARGON-PROFILER (`{gemini_model}` — Opponent Exploit Specialist)\n{profiler_r}\n\n"
            f"### [Round {r}] CLAUDE-OPUS-MODERATOR (`{claude_model}` — Moderator & Strategy Integrator)\n{mod_r}"
        )
        debate_history.append(block)
        print(f"[✓] Round {r} complete.")

    full_transcript = "\n\n".join(debate_history)
    print(f"\n================ GENERATING COPY-PASTE PROMPT FOR FABLE ({claude_model}) ================")
    fable_prompt_generator_task = (
        f"## COMPLETE 3-ROUND DEBATE TRANSCRIPT\n{full_transcript}\n\n"
        f"Based on the 3-round Argon & Opus debate above, generate a **Self-Contained Master Prompt for Fable** "
        f"(our teammate's coding agent). Write the entire output as a direct prompt addressed TO Fable so my teammate "
        f"can copy-paste the markdown file directly into Fable's chat box.\n\n"
        f"Use this exact structure in the prompt you write for Fable (DO NOT write Python code yourself; instruct Fable what code to write):\n"
        f"1. **Role & Mission for Fable:** Tell Fable it is refactoring `bot.py` for team `{args.team}` in the Imperial AI Hack Pokerbots competition, and state the hard sandbox rules (single file `bot.py` < 200KB, Python 3.12 standard library only, 25ms per decision, 100BB auto-reset, 'raise to' semantics).\n"
        f"2. **DO NOT TOUCH — Winning Logic to Preserve:** Give Fable the exact line numbers and behaviors in `bot.py` that are currently winning chips according to Argon's JSON audit and must NOT be broken.\n"
        f"3. **Priority Leak Fixes (Line-by-Line Directives):** Give Fable the exact line numbers in `bot.py` that are bleeding `bb/100` (with JSON evidence) and the exact mathematical formulas/thresholds Fable must replace them with.\n"
        f"4. **Opponent Tracking & Classification Spec (`on_table_start` & `on_hand_end`):** Give Fable the exact dictionary counters and numerical cutoffs to classify every opponent at the table into `GAVE_UP_FOLDER`, `ALL_IN_MANIAC`, `CALLING_STATION`, `TIGHT_NIT`, and `AGGRESSIVE_SHARK`.\n"
        f"5. **Exploitative Action Overrides (`act(state)`):** Give Fable the exact conditional logic for:\n"
        f"   - Ruthlessly stealing blinds and orphan pots from `GAVE_UP_FOLDER` bots (including the exact safety abort rule when an active shark is still behind us).\n"
        f"   - Countering `ALL_IN_MANIAC`, `CALLING_STATION`, `TIGHT_NIT`, and `AGGRESSIVE_SHARK` opponents.\n"
        f"6. **Fable Pre-Submission Verification Checklist:** Instruct Fable to verify 'raise to' bounds (`min_raise` to `max_raise`), <25ms execution speed, and `local_sim.py` testing before returning the updated `bot.py`."
    )

    final_prompt_for_fable = await call_claude_opus(
        anthropic_client, claude_model, prompts["OPUS_FABLE_PROMPT_WRITER"], shared_bundle, fable_prompt_generator_task
    )

    out_dir = Path("fable_out")
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = out_dir / "prompt_for_fable.md"
    trans_path = out_dir / "fishermen_3round_debate.md"

    prompt_path.write_text(final_prompt_for_fable, encoding="utf-8")
    trans_path.write_text(full_transcript, encoding="utf-8")

    print(f"\n================ READY-TO-PASTE PROMPT FOR FABLE ================\n")
    print(final_prompt_for_fable)
    print(f"\n[+] Saved Copy-Paste Prompt for Fable -> {prompt_path.resolve()}")
    print(f"[+] Saved Full 3-Round Debate         -> {trans_path.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())