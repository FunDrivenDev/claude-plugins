---
name: claude-config-audit-and-fix
description: Audit the always-loaded Claude Code context (CLAUDE.md and memory files, hook output, skill listing, settings) and slim it with your approval.
disable-model-invocation: true
---

# Claude config audit and fix

`S` below is `scripts/config_audit.py` in this skill's directory, run with `python3`.

The **always-loaded set** is all text that reaches context every session without the agent asking for it: the CLAUDE.md and memory files a session loads, hook output, and the skill listing. The audit makes that set carry the same meaning in the fewest words, with each **rule** (one fact, instruction or constraint) in exactly one place, and every line earning its load.

## Steps

1. **Inventory.** Run `python3 S inventory > <scratchpad>/config-inventory.json`, then read every file under `session.instructions` and `other_projects`, and every `session.hook_context` text. Done when you hold the text of every rule-bearing member plus the `skills` and `settings` lists.
2. **Rule map.** Split the rule-bearing text into rules and list every place each one appears. Done when every sentence belongs to a rule.
3. **Findings.** Invoke `mattpocock-skills:writing-for-agents`: its levers are the standard for the rule and description findings below. Judge every rule, every `skills` entry with `in_listing: true`, and every `settings` entry. Done when each is fine or a finding.
4. **Ask**, following the question format. Done when every finding has an answer.
5. **Apply** each answer from the action catalog. Before a file's first edit, run `python3 S backup FILE` (`S override` backs up the settings itself).
6. **Verify.** Run `python3 S probe`, plus `python3 S probe <project>` for each project whose files changed. Done when:
   - every rule in the step 2 map sits in exactly one place in the new set, or is listed as dropped with its reason;
   - every skill turned off is missing from `init_skills`, and every skill hidden from Claude is missing from `listed_skills`;
   - `hook_context` holds only run-time findings, and every edited hook runs under `/bin/bash`.

   A failure is reported with the probe output, never retried silently.
7. **Summary** in the chat: each finding with its choice and result; chars before (inventory) and after (probe) for each CLAUDE.md, memory file and hook; chars removed from the skill listing (the sum of `listing_chars` of the hidden skills); backup paths for undo.

## Rule findings

A rule is fine or one of:

- **Duplicate**: it appears in more than one place, including a project file or memory index restating the global CLAUDE.md. It stays in the broadest file it applies to; a hook keeps only what it computes at run time.
- **Contradiction**: it cannot be obeyed together with another rule that the same session loads (global files plus one project's).
- **Branch rule**: it bears only on some kinds of task (briefs, one tool, one workflow). It moves into the skill that handles that branch, or behind a one-line pointer saying when to read it; worth it only when the pointer is much shorter than the rule.
- **Harness default**: it restates what Claude Code's own instructions, in your context, already say.
- **Dead weight**: a no-op, a cache of an easy lookup, stale (a file, flag or fact it names no longer holds: check it), or a negation with no positive target.
- **Wordy**: the same meaning fits in fewer words.

## Skill findings

Usage counts cover `usage_window`; quote its `first_record` date in every question, since a short history weakens "unused". Owned skills are the ones with `owned: true`.

| Situation | Options, recommended first |
|---|---|
| Every listed skill of one plugin, or of the synced `anthropic-skills` set, has `model_calls` and `typed` at 0 | Disable the plugin (synced set: turn each off) · Decide skill by skill · Keep |
| Owned, `model_calls` = 0 | Set `disable-model-invocation` · Keep |
| Not owned, `model_calls` = 0 and `typed` = 0 | Turn off · User-invocable only · Keep |
| Not owned, `model_calls` = 0 and `typed` ≥ 1 | User-invocable only · Keep |
| Owned, `model_calls` ≥ 1, description fails a pointer rule | Trim the description · Keep |

The group row comes first; its "Decide skill by skill" answer sends each skill through the other rows. Skills with `model_calls` ≥ 1 that are not owned are fine.

## Settings findings

| `kind` | Options, recommended first |
|---|---|
| `missing-hook-script`, `missing-statusline-script` | Remove the entry · Keep |
| `hook-not-executable` | `chmod +x` the script · Keep |
| `permission-conflict` | Remove the allow or ask side (deny wins anyway) · Remove the deny side · Keep |
| `permission-duplicate` | Keep it in the broadest file only · Keep |
| `stale-backup` with `age_days` ≥ 14 | Delete · Keep |

## Question format

- One `AskUserQuestion` question per finding, in batches of at most 4. Wordy and dead-weight findings are grouped instead: one question per file, showing the file's full rewrite as a diff, with Apply · Adjust · Skip.
- `header`: the file, skill or plugin name, cut to 12 characters.
- `question`: the evidence (where it appears, counts, chars, history start), then "What should I do?".
- `options`: the row's options in order, the first with a "(Recommended)" suffix. Each `description` names the file or setting changed and how to undo it.

## Action catalog

| Action | How · undo |
|---|---|
| Set `disable-model-invocation` | Add `disable-model-invocation: true` to the SKILL.md frontmatter · remove the line |
| Turn off / User-invocable only | `python3 S override NAME off` or `user-invocable-only` · `python3 S override NAME on` |
| Disable the plugin | Set `enabledPlugins["<plugin id>"]` to `false` in `~/.claude/settings.json` · set it back to `true` |
| Move a branch rule | Add it to the target skill's SKILL.md, then delete it at the source · restore both backups |
| Edit a rule-bearing file or hook | Apply the approved rewrite · restore the backup |
| Remove a settings entry | Edit the JSON file named in the finding · restore the backup |
| Delete a backup | `mv` it to `~/.Trash/` · move it back |

## Gotchas

- Plugin and synced SKILL.md files are overwritten on update: change those skills only through `S override` or `enabledPlugins`.
- CLAUDE.md is re-read after compaction, so a hook restating a rule "to survive compaction" is a duplicate.
- `probe` runs headless, which condenses the skill listing: compare its skill names, not its sizes.
- The inventory reflects its transcript's session start; `chars_on_disk_now` shows edits made since. Changes apply to new sessions only.
