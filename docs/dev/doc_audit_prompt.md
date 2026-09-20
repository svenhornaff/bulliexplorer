# Doc-vs-codebase drift audit — `docs/dev/`

> Companion to `prompts.md` (that one drives implementing a single
> phase of a multi-phase doc; this one drives periodically checking
> whether the whole `docs/dev/` set still tells the truth). Not tied to
> one feature — reusable process, same as `prompts.md`.

For each file in `docs/dev/`, extract every concrete, checkable claim:
checkbox states, phrases like "not started"/"shipped"/"signed off"/
"still needed", and specific technical assertions ("column X exists",
"Bootstrap removed", "endpoint Y requires a parameter"). For each
claim, verify it against the actual code — `grep`, `git log --
<path>`, or running the relevant command — never trust the doc's own
text as evidence of its own accuracy.

Check three places drift has repeatedly hit in this project:

1. **A doc's own header/summary contradicting its own body** (a
   top-line "not started" next to a fully-checked-off phase further
   down, in the same file).
2. **`README.md`'s index entry contradicting the doc it points to**
   (or contradicting the real codebase directly).
3. **A doc silently missing from `README.md` entirely** despite being
   real, current work.

Where a doc's own historical narrative describes a specific bug or
investigation, verify the *technical claim*, not the narrative — a
well-written war story is not evidence its root-cause diagnosis was
correct.

For each confirmed discrepancy: correct the stale text (header,
checkbox, or README entry) to match verified reality, in the same
edit. Don't touch phrasing, organization, or completeness elsewhere —
an edit that doesn't correct a real, checkable discrepancy wasn't worth
making. Note what changed and why in one line per fix, same
evidence-first style already used throughout `docs/dev/`.

Skip anything you can't independently verify (env-gated behavior, an
operator's own account state, live external services) — flag it as
"unverifiable from here," don't guess at its status either direction.

**Done when**: every checkable claim in every doc has been checked
against real code at least once, every confirmed drift is corrected,
and `README.md` accurately reflects both what's shipped and what's
genuinely still open.