# Handover benchmark

Compares ways of handing a Claude Code session over to a fresh one, at the points where real sessions auto-compacted. It picked the method the `handover` plugin uses.

## Method

- **Samples**: 8 auto-compaction points, taken from 417 compactions in local transcripts (median 143K tokens before compaction). The 8 differ in size, project and kind of work.
- **Methods**: each one writes a handover from what the session held at that point. The baseline is the summary that the built-in compaction actually wrote, as recorded in the transcript.
- **Questions**: Opus writes 14 questions per sample from the transcript: goal, user instructions, decisions, state, references, pitfalls, next steps. Each question has a short gold answer.
  - Set **A** is written from the session before the cut only.
  - Set **AB** also sees what the session did after the cut. It is biased toward the baseline: after the cut, the session only knew what the built-in summary had kept.
- **Scoring**: a fresh Sonnet answers each question from the handover alone, or answers UNKNOWN. A second Sonnet grades each answer against the gold: correct 1, partial 0.5, unknown 0, wrong −0.5. There are two grading runs per handover, and the two runs gave the same grade 85% of the time.

| Method | What writes the handover |
|---|---|
| `external` | A separate `claude -p` (Sonnet 5.5), from a condensed render of the transcript: tool calls and results are clipped, user and assistant messages are kept whole. Template in `plugins/handover/scripts/template.md`, 8K-character budget. |
| `external-opus`, `external-haiku` | Same, with Opus 5.5 or Haiku 4.5. |
| `external-long` | Same, with a 16K-character budget. |
| `external-full` | Same, with a less-clipped render. |
| `external+` | `external`, plus the user's messages appended verbatim. |
| `inline` | The session itself, resumed as a fork at the cut, with the same template. |
| `inline-pocock` | The session itself, with Matt Pocock's `handoff` skill prompt. |
| `hybrid` | The session itself, correcting the `external` draft. |
| `deterministic` | No model: the user's messages, the files written and the last assistant message. |
| `autocompact` | The built-in compaction summary (baseline). |

## Results

Set A, the unbiased one: 224 graded answers per method.

| Method | Score | Median size | Median time | Mean cost |
|---|---|---|---|---|
| **external** | **0.819** | 6.9K chars | 20 s | $0.15 |
| external+ | 0.812 | 14.2K | 20 s | $0.15 |
| external-opus | 0.812 | 8.5K | 35 s | $0.33 |
| external-long | 0.801 | 9.3K | 30 s | $0.17 |
| autocompact | 0.783 | 16.8K | 95 s | — |
| hybrid | 0.614 | 8.3K | 74 s | $2.39 |
| inline | 0.529 | 7.9K | 51 s | $2.41 |
| external-haiku | 0.516 | 5.8K | 43 s | $0.07 |
| inline-pocock | 0.453 | 6.6K | 46 s | $2.33 |
| deterministic | 0.234 | 7.5K | 0 | 0 |

A bootstrap over the questions gives `external` minus `autocompact` = +0.036 on set A (95% CI −0.031 to +0.105) and −0.058 on set AB (−0.112 to −0.007). On set AB, `autocompact` scores 0.855, `external-opus` 0.808 and `external` 0.797. `external-full` was graded on set AB only, and on part of the samples: 0.770.

Scores by category, set A:

| Method | Goal | Instructions | Decisions | State | References | Pitfalls | Next step |
|---|---|---|---|---|---|---|---|
| external | 0.91 | 0.85 | 0.66 | 0.91 | 0.89 | 0.77 | 0.79 |
| external-opus | 0.93 | 0.83 | 0.78 | 0.86 | 0.79 | 0.73 | 0.71 |
| autocompact | 0.93 | 0.75 | 0.75 | 0.84 | 0.75 | 0.75 | 0.71 |
| inline | 0.64 | 0.60 | 0.49 | 0.48 | 0.48 | 0.48 | 0.46 |

## Findings

- A separate model that reads a render of the transcript writes a handover as good as the built-in compaction summary, at less than half its size. It is ahead on user instructions and references, and behind on decisions. Sonnet matches Opus at half the cost; Haiku falls well behind.
- Asking the nearly-full session to write its own handover is the worst option that uses a model. It is also the most expensive, because the whole context is sent again. In 2 of the 8 samples, the session produced no handover at all: it kept trying to act on background tasks instead. Asking it to correct a good draft (`hybrid`) made the draft worse.
- A bigger budget or a less-clipped render does not help.

## Limits

- 8 samples, all from one person's sessions. The questions and gold answers were written by a model and not reviewed by hand.
- The `inline` methods run in a forked resume, whose harness state differs from the original moment: for example, background jobs appear stopped. This penalises them on state questions. Leaving the state and next-step questions out, on the 6 samples where `inline` produced a handover, still gives `external` 0.817 against `inline` 0.728.

## Running it

Transcripts contain private data, so every intermediate file stays in `$HANDOFF_BENCH_DIR` (default `~/.cache/handoff-bench`). Only aggregates leave that folder.

```
python3 bench/handover/bench.py select
python3 bench/handover/bench.py prep
HANDOFF_BENCH_QSET=a python3 bench/handover/bench.py qgen
python3 bench/handover/bench.py gen external inline    # prep already extracts the autocompact baseline
HANDOFF_BENCH_QSET=a python3 bench/handover/bench.py eval external autocompact inline
HANDOFF_BENCH_QSET=a python3 bench/handover/bench.py report
```
