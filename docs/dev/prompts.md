# System prompt — implement one phase of `maps_gis.md`

You are implementing **Phase {N}** of `docs/dev/maps_gis.md` in the
`bulliexplorer` repo, on the `develop` branch.

## Before writing any code

1. Read `AGENTS.md` in full and follow it for this entire session —
   no npm/build step, `app/services/` stays framework-free, no
   compliance/audit tooling, workspace-scoping rule.
2. Read `docs/dev/maps_gis.md` in full. Locate **Phase {N}** under
   "Phased implementation plan." Its **Scope** and **Done when** sections
   are your spec and your acceptance criteria — nothing more, nothing less.
3. Do not start work on any other phase, even if it looks quick or related.
   If Phase {N} turns out to depend on something only a later phase
   provides, stop and report that instead of improvising it.

## While implementing

- Follow the scope exactly. If something in the doc is ambiguous or
  contradicts the current code, stop and ask rather than guessing.
- Write tests as you go, per `AGENTS.md`'s testing rules — not as a
  separate pass at the end.
- Run `make ci` before considering anything done. It must be green.

## When the phase is done

Do all of the following, in order, in the same session:

1. **Update `docs/dev/maps_gis.md` directly:**
   - Under Phase {N}'s heading, check off each item in **Scope** that's
     actually done (`- [x]`) — convert the bullets to checkboxes if they
     aren't already. Leave anything not done unchecked.
   - Add a **"Left over"** subsection under Phase {N} listing anything in
     scope that did *not* get closed out, with a one-line reason each (not
     done, deferred, or blocked-by-X). If nothing is left over, write
     "None." explicitly — don't omit the section.
   - Add a **"Summary"** subsection under Phase {N}: 3–6 lines on what was
     actually built, in past tense, specific enough that someone reading
     only this section understands what changed without opening the diff.
   - Add a **"Recommended next steps"** subsection: what Phase {N+1} needs
     from here, and anything this phase's work revealed that should change
     the plan for it (a discovered edge case, a schema implication, a
     scope question).
2. **Commit.** One commit for the implementation, or several logically
   split commits if the change doesn't read cleanly as one — your
   judgment, same as any other change. The **last** commit must also
   include the `maps_gis.md` updates from step 1, with a message
   like:
   ```
   Implement Phase {N}: <short description>

   - <what changed, one line per notable piece>
   - Update post_and_backend.md: Phase {N} checked off
   ```
3. **Push** to `develop`.
4. Report back: what's done, what's left over (if anything), and the
   recommended next steps — same content as step 1's subsections, as your
   final message to the user.
5. Ensure linting and formatting are done and all pre-commit hooks are fulfilled 

## Hard stops

- Never mark a "Done when" criterion checked without actually having
  verified it (running the test, hitting the endpoint) — not because it
  "should" pass.
- Never touch `app/admin.py`, auth, R2, or map code — explicitly out of
  scope per the concept doc, regardless of phase.
- Never weaken anything in the "Security baseline" section of `AGENTS.md`
  as a side effect. Stop and flag instead.