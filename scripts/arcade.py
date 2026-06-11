"""arcade.py — ARC-AGI-3 local arcade harness (eng #19 / tracker #47).

Per research/world-choice-r2.md: the policy-world candidate is blocked on
harness infra — game API + judge separate from the t1_probe sandbox. This
is that minimal harness:

- Game API: arc_agi.Arcade in OFFLINE mode over local environment files
  (no network, no scorecard server). Engine = arcengine (the competition
  SDK already installed on both sides of this box).
- Judge: the ENGINE verdict only — GameState (WIN / GAME_OVER /
  NOT_FINISHED) and levels_completed off every frame. No model-judged
  anything (receipts-only truth).
- Policy interface: `choose_action(obs, action_space, rng) -> (GameAction,
  data)` — pluggable. RandomPolicy ships as the no-model floor reference;
  an ember-core policy plugs in at the floor probe (its spec lands as its
  own issue per the §7 rule — NO training commitment without a measured
  floor; this harness carries no training code).

Provenance: the MIT exploration baseline named in the draft
(github.com/dolphin-in-a-coma/arc-agi-3-just-explore, MIT, verified via
GitHub API @c2d98318ecca 2026-06-10) is a STARTING-POINT REFERENCE only —
no code from it is vendored here; the harness talks to the engine API
directly.

Receipt: receipts/arcade-<tag>-<ts>.json — per-game {steps,
levels_completed, final_state, resets, elapsed_s} + aggregate.
Selftest (`--selftest`, no engine import): policy/action plumbing,
receipt shape, seed determinism.
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
GRID = 64  # ARC-AGI-3 frame is 64x64; clicks address that plane


class RandomPolicy:
    """Uniform over the game's available actions; clicks get uniform x/y.
    The no-model reference floor — any learned policy must beat this."""

    name = "random"

    def choose_action(self, obs, action_space, rng):
        avail = list(getattr(obs, "available_actions", None) or action_space)
        action = rng.choice(avail)
        data = {}
        if getattr(action, "name", str(action)).endswith("6"):  # click
            data = {"x": rng.randrange(GRID), "y": rng.randrange(GRID)}
        return action, data


def state_name(state):
    return getattr(state, "name", str(state))


def run_episode(env, policy, max_steps, seed, game_id):
    """One budgeted episode: policy acts until WIN or step budget; on
    GAME_OVER the harness (not the policy) issues RESET — level progress
    is the engine's to keep, the judge only reads it."""
    from arcengine.enums import GameAction, GameState

    rng = random.Random(seed)
    t0 = time.time()
    obs = env.reset()
    steps = resets = 0
    levels = 0
    final = "NO_OBS"
    while obs is not None and steps < max_steps:
        levels = max(levels, int(getattr(obs, "levels_completed", 0) or 0))
        final = state_name(obs.state)
        if obs.state == GameState.WIN:
            break
        if obs.state == GameState.GAME_OVER:
            obs = env.step(GameAction.RESET, data={})
            resets += 1
            steps += 1
            continue
        action, data = policy.choose_action(obs, env.action_space, rng)
        obs = env.step(action, data=data)
        steps += 1
    if obs is not None:
        levels = max(levels, int(getattr(obs, "levels_completed", 0) or 0))
        final = state_name(obs.state)
    return {"game": game_id, "policy": policy.name, "seed": seed,
            "steps": steps, "resets": resets, "levels_completed": levels,
            "final_state": final, "win": final == "WIN",
            "elapsed_s": round(time.time() - t0, 2)}


def list_games(envs_dir):
    return sorted(d for d in os.listdir(envs_dir)
                  if os.path.isdir(os.path.join(envs_dir, d))
                  and not d.startswith("_"))


def _selftest():
    # policy plumbing on a stub obs/action space — no engine import
    class _A:  # stands in for GameAction members
        def __init__(self, name):
            self.name = name

    class _Obs:
        available_actions = None
        state = "NOT_FINISHED"

    acts = [_A("ACTION1"), _A("ACTION6")]
    rng = random.Random(16)
    pol = RandomPolicy()
    picks = [pol.choose_action(_Obs(), acts, rng) for _ in range(20)]
    assert all(a in acts for a, _ in picks)
    clicked = [d for a, d in picks if a.name == "ACTION6"]
    assert clicked and all(
        0 <= d["x"] < GRID and 0 <= d["y"] < GRID for d in clicked)
    assert all(d == {} for a, d in picks if a.name == "ACTION1")
    # seed determinism: same seed -> same pick sequence
    seq = [RandomPolicy().choose_action(_Obs(), acts, random.Random(7))[0]
           .name for _ in range(1)]
    seq2 = [RandomPolicy().choose_action(_Obs(), acts, random.Random(7))[0]
            .name for _ in range(1)]
    assert seq == seq2
    # receipt row shape
    row = {"game": "xx00", "policy": "random", "seed": 16, "steps": 0,
           "resets": 0, "levels_completed": 0, "final_state": "NOT_PLAYED",
           "win": False, "elapsed_s": 0.0}
    assert set(row) == {"game", "policy", "seed", "steps", "resets",
                        "levels_completed", "final_state", "win",
                        "elapsed_s"}
    print("ARCADE_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--envs-dir",
                    default="/mnt/b/M/the-search/environment_files",
                    help="local ARC-AGI-3 environment files (one dir per "
                         "game; the-search copy is the complete 25-game "
                         "set on this box)")
    ap.add_argument("--receipts-dir", default=f"{NC}/receipts")
    ap.add_argument("--games", nargs="*", default=None,
                    help="game ids; default = every dir in --envs-dir")
    ap.add_argument("--max-steps", type=int, default=200)
    ap.add_argument("--seed", type=int, default=16)
    ap.add_argument("--tag", default="random-smoke")
    args, _unknown = ap.parse_known_args()  # daemon appends args; ignore

    from arc_agi import Arcade, OperationMode
    arcade = Arcade(operation_mode=OperationMode.OFFLINE,
                    environments_dir=args.envs_dir)
    games = args.games or list_games(args.envs_dir)
    print(f"arcade harness: {len(games)} games x max_steps="
          f"{args.max_steps} policy=random seed={args.seed}", flush=True)

    policy = RandomPolicy()
    rows = []
    for i, gid in enumerate(games, 1):
        try:
            env = arcade.make(gid, seed=args.seed)
            if env is None:
                rows.append({"game": gid, "error": "make returned None"})
                continue
            row = run_episode(env, policy, args.max_steps, args.seed, gid)
        except Exception as e:  # noqa: BLE001 — per-game verdict, run continues
            row = {"game": gid, "error": f"{type(e).__name__}: {e}"[:200]}
        rows.append(row)
        print(f"[{i}/{len(games)}] {gid}: "
              f"{row.get('final_state', row.get('error'))} "
              f"levels={row.get('levels_completed', '-')}", flush=True)

    ok = [r for r in rows if "error" not in r]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "ARCADE-HARNESS", "ts": ts, "args": vars(args),
        "engine": "arc_agi OFFLINE + arcengine (local, no network)",
        "judge": "engine GameState + levels_completed only",
        "baseline_ref": {"repo": "dolphin-in-a-coma/arc-agi-3-just-explore",
                         "license": "MIT (GitHub API, 2026-06-10)",
                         "commit": "c2d98318ecca", "code_vendored": False},
        "n_games": len(games), "n_ran": len(ok),
        "n_errors": len(rows) - len(ok),
        "wins": sum(1 for r in ok if r.get("win")),
        "games_with_level_progress": sum(
            1 for r in ok if r.get("levels_completed", 0) > 0),
        "total_steps": sum(r.get("steps", 0) for r in ok),
        "per_game": rows,
    }
    os.makedirs(args.receipts_dir, exist_ok=True)
    path = f"{args.receipts_dir}/arcade-{args.tag}-{ts}.json"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps({k: receipt[k] for k in
                      ("n_games", "n_ran", "n_errors", "wins",
                       "games_with_level_progress", "total_steps")},
                     indent=2))
    print(f"RECEIPT: {path}")
    print("ARCADE_DONE")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
