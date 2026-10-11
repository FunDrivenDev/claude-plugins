# Migrating from older versions

For an install from before 0.13.0. [Back to the README](../README.md)

**Moved in 0.13.0** from the `fundriven` marketplace (FunDrivenDev/skills). Install `handover@fundrivendev`, uninstall the old one with `claude plugin uninstall handover@fundriven --keep-data` (without `--keep-data`, Claude Code deletes its data folder, history included), and move its `pluginConfigs` entry to the new key: an uninstall removes the old entry. On its first session start the plugin imports `metrics.jsonl` and the YOLO audit logs from the old data folder, `handover-fundriven`.

**Renamed in 0.8.0**, from `handoff` (it collided with Matt Pocock's `handoff` skill). Uninstall `handoff@fundriven`, install `handover`, and move its `pluginConfigs` entry and options: `handoff_dir` → `handover_dir`, `model` → `writer_model`, `budget_chars` → `handover_chars`, `approach_tokens` → `warn_tokens`, `stale_tokens` → `refresh_tokens`, `relay_max` → `relay_limit`. The `HANDOFF_*` environment variables are now `HANDOVER_*`, the commands `/handover:relay|afk|stats`. On its first session start the plugin imports `metrics.jsonl` (its events renamed) and the YOLO audit logs from the old data folder, `handoff-<marketplace>`.
