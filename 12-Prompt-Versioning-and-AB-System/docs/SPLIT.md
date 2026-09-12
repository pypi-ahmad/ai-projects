# Traffic split

Implemented in `src/promptreg/split/`. Same `user_key` always lands on the
same arm — via a stored `Assignment` row, not a re-derived hash.

## Hashing

```
bucket = int(sha256(f"{user_key}{sticky_salt}").hexdigest(), 16) % 100
```

`sticky_salt` is per-experiment (generated at creation, or pinned
explicitly). A different experiment on the same prompt gets a different
salt, so the same user isn't correlated across experiments.

## Weights

Arms carry an integer `weight`; `Experiment` requires them to sum to
exactly 100 (`validate_arms` in `split/models.py`) — that's what makes `%
100` a safe bucket space with no gap. Cumulative ranges follow **arm list
order as given at creation** (not re-sorted):

```
[Arm(control, weight=70), Arm(treat_a, weight=30)]
control: [0, 70), treat_a: [70, 100)
```

## Sticky assignment

- On first resolve for a `user_key` under a **running** experiment, the
  hash above picks an arm and an `assignments` row is written
  `(experiment_id, user_key) -> (arm, version)` — `INSERT OR IGNORE`, so a
  concurrent duplicate resolve can't clobber it.
- Every later resolve for that `(experiment_id, user_key)` reads the
  stored row instead of re-hashing. Changing `sticky_salt` or the weights
  later never moves an already-assigned user — only new user_keys see the
  new layout.
- **paused**: existing assignment rows still resolve to their arm. A
  user_key with no prior assignment does **not** get a new one — falls
  through to the plain env pointer instead.
- **draft** / **stopped**: no experiment involvement at all; every
  resolve falls through to the pointer, including for user_keys that had
  an assignment while it was running (a stopped experiment is retired).
- Only one `running` experiment per prompt at a time (a partial unique
  index enforces it) — `resolve` picks the most recent running/paused
  experiment for the prompt when deciding whether a `user_key` is sticky.
