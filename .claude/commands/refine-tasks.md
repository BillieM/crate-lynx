Analyse TASKS.md and propose splits, merges, missing implementation details, and gaps so each task fits a single Codex context window. Do NOT rewrite TASKS.md until the user accepts the proposal.

Steps in order:

1. **Read TASKS.md.** Note which items are checked vs. unchecked. If there are no unchecked tasks, stop and tell the user to run `/next-epic`.

2. **Get epic context.** In EPICS.md, find the epic marked `` `in progress` `` and read its description.

3. **Ground the analysis in the codebase.** For each unchecked task, locate the files / endpoints / functions it references and read enough of them to make concrete claims. Use the Explore agent for broad lookups and `grep` / Read for targeted ones. Specifically check:
   - File sizes (LOC) of files the task will edit — task scoping depends on this.
   - Whether referenced fields, endpoints, or symbols **already exist** (often "add X" turns out to be "stop discarding X").
   - Whether bulk / batch actions have backend support, or must fan out client-side.
   - Adjacent files that will conflict if two tasks edit the same module (a common reason to merge tasks).

4. **Identify flaws.** Look for:
   - Behaviours referenced in multiple tasks but not owned by any (e.g. a shared primitive sketched across two consumers).
   - Undefined UX decisions (e.g. selection persistence across filter changes, mobile column hiding).
   - Missing endpoints / data sources implied by the task description.
   - Catch-all "polish" / "validate" tasks that should be folded into per-task definitions of done.
   - Orphaned items left over from previous epics.
   - Concurrency, error-aggregation, or scale concerns that aren't addressed.

5. **Propose a re-org.** Suggest merges (same file or tightly coupled changes) and splits (any task that won't fit one Codex window — typically because it bundles a foundation + tests + multiple consumers). Aim for fewer, sharper tasks. Present as a small old-→-new table with one-line rationale per change.

6. **Add implementation details per task.** For each proposed task, include:
   - Concrete API surface (component props, function signatures) where a primitive is involved.
   - Locked behaviour decisions (with a recommendation if undecided).
   - File / line references for code that must change.
   - Bulk-action concurrency cap (default: `Promise.allSettled` over chunks of 5) when applicable.
   - Definition of done — the exact lint / test / build commands that prove the task is finished.

7. **Note non-goals.** Explicit "we are NOT doing X in v1" lines prevent scope creep and orphan tasks later.

8. **Present the proposal.** Structured as: overall observations → flaws/gaps → suggested re-org table → per-task implementation details → other suggestions. End with: *"Want me to rewrite TASKS.md to this structure, or would you rather adjust the proposal first?"*

9. **Wait for the user.** If they accept, rewrite TASKS.md preserving the epic header, with one section per task following the format established by the proposal (each task gets a `## T<n>. <title>` heading, body bullets, and a `**Definition of done:**` line). Do not commit — the user will run `/next-task` next.

Important:
- Do NOT modify TASKS.md, EPICS.md, or any source files during analysis.
- Do NOT spawn implementation agents — this command is research + planning only.
- Keep the proposal tight: prefer file:line references over prose, prefer tables over paragraphs, prefer concrete decisions over open questions.
