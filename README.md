# vit — git for video editing

**vit** is a version-control system for non-linear video editing timelines. It
tracks an edit's *structure* — cuts, trims, color grades, effects, markers,
speed changes — as small, diffable JSON documents inside a real git
repository, and merges two branches of edits at **clip and field
granularity** instead of leaving that structure to a line-based text merge.

**Vit Studio** is a small browser-based NLE (non-linear editor) shipped
alongside the library as a working demo: every edit you make in the browser
is written through vit's own models, so branching, diffing and merging a
real editing session can be seen and tried end to end without any external
NLE.

```bash
docker compose up --build
# → http://localhost:8765
```

---

## The problem

Code has git. Video has `final_v3_actual (1).mp4`.

Professional NLEs (Resolve, Premiere, Avid) store a project as one opaque
binary or a single large XML/JSON blob. That's fine for one editor working
alone, but it breaks down the moment two people need to work on the same
timeline in parallel:

- **Git can't diff it.** A single-file project means any change — trimming
  one clip by one frame — produces a diff that's either meaningless (binary)
  or unreadable (a multi-thousand-line JSON blob where the one real change is
  buried in reformatting noise).
- **Git can't merge it.** A line-based three-way merge conflicts whenever two
  edits land near each other in the file, even when the edits themselves
  don't actually conflict — two editors independently adding two different
  clips to two different points on the timeline still collide as a text
  merge, because their JSON entries happen to sit on adjacent lines.
- **The failure mode is silent or total.** Either the merge conflicts on
  everything (unusable) or a tool "resolves" it by picking one side entirely,
  silently discarding the other editor's work.

The abstraction needs to be powerful enough for real parallel work — two
editors, two branches, genuinely independent edits — without requiring
either of them to understand git internals, and without silently discarding
anyone's changes.

## The approach

The key realization: **an edit description is git-shaped.** It's small,
structured, and — if you stop treating it as one opaque file — decomposable
into independently mergeable pieces.

1. **Split the timeline into domains.** Instead of one project file, vit
   writes `cuts.json`, `color.json`, `audio.json`, `effects.json`,
   `markers.json`, `metadata.json`, one per concern. Two edits touching
   different domains (a color grade and a marker) never even reach the same
   file, so git's own merge already handles them.
2. **Key clips (and tracks, and grades) by a stable id, not by position.**
   Within a domain file, a three-way merge walks matched-by-id entries and
   merges *field by field*. Two edits to two different clips — or two
   different fields of the same clip — combine automatically. A conflict is
   reported only when the *same field* of the *same clip* was changed
   *differently* on both branches.
3. **Detect the conflict class that id-matching can't see.** Two branches
   each independently adding a *different* clip to the *same time range* of
   the *same track* never touches the same key, so id-based merging alone
   would let it through silently. A second pass runs overlap detection on
   the tentative merged result and surfaces it as a real conflict, with
   "keep one," "keep both back-to-back," or "keep both on a new track" as
   resolutions.
4. **Keep git as the engine, not a black box you're deferring to.** Every
   version is a real git commit; every merge is a real two-parent commit.
   vit only replaces *what content* gets written for a merge — the commit
   graph, branching and history are exactly git's, inspectable with
   `git log --graph` outside the app entirely.
5. **Reduce the remaining decision load, without ever deciding silently.**
   A pre-triage pass (deterministic heuristics, optionally backed by an LLM)
   proposes resolutions with a confidence score. Anything above a threshold
   is applied automatically — but always shown, always one click to undo.
   Nothing is ever resolved invisibly.

See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for the full design —
component diagram, data model, and the merge algorithm walked through step
by step with diagrams.

---

## Features

**Core version control**
- Domain-split, deterministically-formatted JSON timeline (byte-identical
  output for identical state → minimal git diffs)
- Real git commits and branches underneath; media bytes never enter git,
  only content-addressed references
- Human-readable diffs across every domain (`Trimmed 'clip' end: 00:00:08:00
  → 00:00:06:16`, not raw JSON)
- Post-edit/post-merge validation: orphaned refs, overlapping clips,
  audio/video sync drift, track-count mismatches, stale speed/duration data

**Clip-level three-way merge**
- Field-granular merge: independent edits combine automatically; only a
  genuinely contested field is a conflict
- Track-existence merging: deleting an empty track is a real, mergeable
  edit, not a "whichever branch has more tracks" count heuristic
- Manual-value resolution: resolve a conflict with a third value, neither
  side's
- Move/rename-aware diffing: a re-imported clip (same footage, new id) is
  reported as one "re-linked" line, not a spurious delete + add
- Timeline-overlap detection: two different clips landing on the same time
  range is caught during merge preview, with four resolution strategies
- "Keep both, back-to-back": splits a conflicted trim into two adjacent
  clips and ripples every later clip on the track so nothing overlaps

**Merge UX**
- All-branches-at-once status view — see every branch's conflict count
  before picking one, not a dropdown you repeat per branch
- Time-ranged conflicts, sorted chronologically, so scanning the list reads
  like scrubbing the timeline
- Rendered frame previews for each side of a conflict, not JSON
- AI-assisted pre-triage (deterministic heuristics + optional Gemini call),
  with every auto-applied resolution visible and one click from undo

**Studio editor**
- Full timeline editing: trim/split/move, transform, speed/retime,
  composite modes, color grading, effects, markers
- Branch/commit/checkout/merge/restore, all backed by real git
- Local-only security model (Host-header allowlist + custom write header —
  no auth needed for a `127.0.0.1`-only tool)
- Per-project request locking (keyed by project path, not one global lock)

---

## Quickstart

**Docker (recommended):**
```bash
docker compose up --build
# → http://localhost:8765
```

**Local:**
```bash
python3 demo/server.py            # → http://localhost:8765
```

**Tests:**
```bash
pip install pytest
python3 -m pytest tests/ -q
```

**Optional: AI-assisted merge suggestions.** Create a `.env` file at the repo
root (gitignored) with:
```
GEMINI_API_KEY=your-key-here
```
Without it, merge pre-triage still works — it just runs on the built-in
deterministic heuristics alone (`vit/merge/suggest.py`).

---

## Project layout

```
vit/                    the library — pure Python, no I/O beyond git/disk
  git.py                  thin wrapper over the system git binary
  project.py               VitProject: git repo + timeline files
  diff.py                  human-readable diffs across domain files
  validation.py            post-edit/post-merge checks
  timeline/
    models.py                dataclasses for the timeline domain
    store.py                 on-disk domain-split JSON, deterministic formatting
  merge/
    three_way.py              id-keyed field merge, track merge, keep-both ripple
    service.py                 merge orchestration (git + three_way + overlap detection)
    suggest.py                 pre-triage: heuristics + optional Gemini batch call

demo/                    Vit Studio — a browser NLE built on top of vit
  server.py                entry point
  studio/                  Python backend (HTTP API, workspace, media library)
  static/                  vanilla JS/CSS frontend, no build step

tests/                   pytest suite (backend), one file per module
docs/
  ARCHITECTURE.md          full design writeup with diagrams
  JSON_SCHEMAS.md          on-disk schema reference
```
