# Dashboard redesign concepts, 2026-08-27

Scratch. Not part of the renderer. Safe to delete.

- concept-a.html, concept-b.html, concept-c.html, concept-b-plus-schedule.html: the four artifacts, self-contained, data embedded.
- review.html: critique, rationale, recommendation.
- common.js / common.css: shared helpers (absence vocabulary, chips, lane rule, drawer, sparkline).
- a|b|c|d.js and .css: per-concept code. d = b + a's schedule column.
- prep.py: builds concept-data.json from _scratch/fleet-model-full.json (dump-model.py), the export, the inventory and history/. Nothing typed in.
- build.py: assembles each concept (no doctype/html/head/body; the artifact host adds them).

Chosen direction (Doug, 2026-08-27): B (evidence matrix) with A's schedule column as a second tab. Implementation is a separate step and has not started.
