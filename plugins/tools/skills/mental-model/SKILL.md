---
name: mental-model
description: Build a mental model of a whole system as one static HTML page, from the sky-high view down to the technical detail. Use when asked for a mental model or a big explanation: a user journey, how a system fits together, a whole workflow, which tool gets which job.
---

# Mental model

One page Raphaël can hold in his head: big cards in numbered bands, each band
one altitude lower than the one before. `example.html` in this skill's
directory is the reference: copy its tokens, its components and its responsive
rules.

## Steps

1. **Collect the real material.** The product's own labels, keys, commands,
   file paths and config names, read from the code, the docs or `--help`.
   Facts spread over many sources go to a subagent that checks each claim
   against a primary source and reports a verdict per claim. Done when every
   label on the page exists in the product.
2. **Find the core.** One sentence that the rest of the page unfolds, shown
   first as the page's banner, and, when the subject is a choice, the one
   question that decides it.
3. **Lay out the bands**, highest altitude first, each numbered:
   - the overview: the parts, side by side;
   - the decision or the journey: a **path** of cards joined by arrows, once;
   - a **loop**, what repeats every day, with its arrow back;
   - the mechanism: what happens inside, step by step;
   - the reference: a **table** for each comparison, inside a scroll wrapper;
   - a **grid** of "whenever you need it" to close.

   Keep the bands the subject needs. Done when each question Raphaël asked is
   answered by a named band.
4. **Write the page** from `example.html`: the product's colours, else
   Catppuccin Frappé; light and dark; on a narrow window the paths stack with
   downward arrows and the page never scrolls sideways. Write it to
   `~/Notes/artifacts/mental-models/YY-MM-DD-kebab-topic.html` and `open` it.
5. **Reply** with the page's full path, the core sentence, one line per band,
   and which claims were checked or corrected.
