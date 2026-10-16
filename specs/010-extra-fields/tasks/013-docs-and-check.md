# 013 - Docs and the final check

Spec: `../spec.md` (Docs). Depends on: tasks 001 to 012.

## Goal

The README and AGENTS.md describe the feature, and the whole repo passes its gates.

## Steps

1. `README.md`: usage with `ExtraField`, `FieldGroup` and `ExtraFields`; the added columns
   (`<name>`, `<name>__grounding`, `<name>__coverage`, `<name>__source_page`) and the collision
   rule; the carry rule and its switch, stating that `carry_forward` is **off** by default; the
   missed-header check in two sentences, including that it runs whether or not the carry is on;
   groups and what they clear; and the "Not handled" list from the spec.
2. `AGENTS.md`: project state (spec 010 implemented, in a few sentences), the file tree
   (`extra_fields.py`, `tests/score_extra_fields.py`, the `extra-*` fixture family), the
   `score-extra-fields` recipe (if task 011 did not add it already), and the test count (run
   `just test`, use the printed number). Spec 010 uses the name `quotable`, so no history note is
   needed.
3. Set the spec's Status to `implemented` only after the user approves the change.
4. Stage the new files by name (not `git add .`) so the hooks see them, then `just check`.
5. Run `git status` and confirm nothing unexpected is modified, in particular the 154 earlier
   fixture files.

## Done when

`just check` passes, README.md and AGENTS.md agree with the code, and the user has what they need to
review the change.
