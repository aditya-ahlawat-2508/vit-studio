"""Pre-triage for merge conflicts: propose a resolution and a confidence score
before a conflict reaches the human.

`heuristic_source` is pure — no I/O. `gemini_batch_source` is the one
network-backed source: it's a *batch* source (one call per merge covering
every still-unresolved conflict, not one call per conflict) and it fails soft
— any network error, missing API key, or malformed model response makes it
return no suggestions rather than raise, so a live merge is never blocked by
an LLM having a bad day.
"""

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .three_way import Conflict

# Above this confidence, a suggestion is applied automatically instead of
# being shown as a conflict. Kept as a module-level constant, not buried in
# a call site, so it's easy to find and tune.
AUTO_APPLY_THRESHOLD = 0.85


@dataclass
class Suggestion:
    path: str                      # matches Conflict["path"]
    choice: str                    # "ours" | "theirs" | "value" | "keep_both"
    value: Optional[object] = None  # populated only when choice == "value"
    order: Optional[str] = None     # populated only when choice == "keep_both": "ours_first" | "theirs_first"
    confidence: float = 0.0         # 0.0-1.0
    reason: str = ""                # short human-readable justification, shown in UI

    def as_resolution(self) -> object:
        """Convert to the shape `_merge_value`'s `resolutions` dict expects."""
        if self.choice == "value":
            return {"value": self.value}
        if self.choice == "keep_both":
            return {"op": "keep_both", "order": self.order or "ours_first"}
        return self.choice  # "ours" or "theirs"

    def to_dict(self) -> dict:
        d = {"path": self.path, "choice": self.choice, "confidence": self.confidence, "reason": self.reason}
        if self.value is not None:
            d["value"] = self.value
        if self.order is not None:
            d["order"] = self.order
        return d


SuggestionSource = Callable[[Conflict], Optional[Suggestion]]


def heuristic_source(conflict: Conflict) -> Optional[Suggestion]:
    """Cheap, deterministic rules. Runs first, no cost, no network."""
    category = conflict.get("category", "field")
    domain = conflict.get("domain")
    base = conflict.get("base")

    if category == "field":
        # A value that didn't exist in the common ancestor and was added on
        # exactly one side, with the other side unchanged, isn't really
        # contested — but three_way.py's _merge_value already resolves that
        # case (ours==base or theirs==base). If it reached us as a Conflict,
        # both sides genuinely diverged from a real base value. So heuristics
        # here stay narrow and explicit:
        if domain in ("color", "effects") and base is None:
            return Suggestion(
                path=conflict["path"], choice="theirs", confidence=0.55,
                reason="both sides added a new grade/effect independently",
            )
        return None

    if category == "timeline_overlap":
        # Structural conflicts (two different clips colliding on the same
        # track) are deliberately NOT auto-applied by default — "keep_both"
        # ripples every later clip on the track, exactly the kind of silent
        # side effect the auto-apply threshold exists to avoid. Still return
        # a suggestion (so the UI can show a hint), just keep confidence
        # below AUTO_APPLY_THRESHOLD.
        clip_a, clip_b = conflict.get("clip_a") or {}, conflict.get("clip_b") or {}
        if clip_a.get("media_ref") != clip_b.get("media_ref"):
            return Suggestion(
                path=conflict["path"], choice="keep_both", order="ours_first",
                confidence=0.4,
                reason="different source clips overlap — likely both intentional",
            )
        return None

    return None


BatchSuggestionSource = Callable[[List[Conflict]], Dict[str, "Suggestion"]]

GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
GEMINI_MODEL = os.environ.get("VIT_GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
GEMINI_TIMEOUT_S = 8

_VALID_FIELD_CHOICES = {"ours", "theirs"}


def _gemini_prompt(conflicts: List[Conflict]) -> str:
    """One prompt describing every still-open field conflict at once."""
    items = []
    for c in conflicts:
        if c.get("category", "field") != "field":
            continue  # timeline_overlap conflicts are never sent to the model — see gemini_batch_source
        items.append({
            "path": c["path"], "domain": c.get("domain"),
            "base": c.get("base"), "ours": c.get("ours"), "theirs": c.get("theirs"),
        })
    return (
        "You are triaging merge conflicts in a video-editing timeline (not code). "
        "Each conflict below is one property that changed differently on two branches "
        "('ours' and 'theirs'), starting from a common 'base' value. "
        "For each conflict, decide whether 'ours' or 'theirs' is more likely the value "
        "the editor actually wants kept, and how confident you are (0.0-1.0). "
        "If you have no real basis for a preference, give it low confidence rather than "
        "guessing 0.9 — a wrong high-confidence call gets auto-applied without review. "
        "Respond with ONLY a JSON array, no prose, no markdown fences, shaped like: "
        '[{"path": "...", "choice": "ours"|"theirs", "confidence": 0.0-1.0, "reason": "one short sentence"}]\n\n'
        f"Conflicts:\n{json.dumps(items, indent=2)}"
    )


def _parse_gemini_response(raw: dict) -> List[dict]:
    text = raw["candidates"][0]["content"]["parts"][0]["text"].strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def gemini_batch_source(conflicts: List[Conflict]) -> Dict[str, "Suggestion"]:
    """One Gemini call covering every open field conflict. Fails soft: any
    problem (no API key, network error, bad JSON back) returns {} — the
    heuristic source alone is already a complete, functioning feature, so a
    model outage degrades the pre-triage, it never blocks a merge.

    The API key is read ONLY from the GEMINI_API_KEY environment variable —
    never hardcoded, never accepted as a function argument, so there's no
    code path that could end up writing it to disk or into a log line.
    """
    api_key = os.environ.get(GEMINI_API_KEY_ENV)
    if not api_key:
        return {}

    field_conflicts = [c for c in conflicts if c.get("category", "field") == "field"]
    if not field_conflicts:
        return {}

    body = json.dumps({
        "contents": [{"parts": [{"text": _gemini_prompt(field_conflicts)}]}],
        "generationConfig": {"temperature": 0.0},
    }).encode()
    req = urllib.request.Request(
        f"{GEMINI_URL}?key={api_key}", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=GEMINI_TIMEOUT_S) as resp:
            raw = json.loads(resp.read())
        rows = _parse_gemini_response(raw)
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError, json.JSONDecodeError):
        return {}

    valid_paths = {c["path"] for c in field_conflicts}
    suggestions: Dict[str, Suggestion] = {}
    for row in rows:
        path = row.get("path")
        choice = row.get("choice")
        if path not in valid_paths or choice not in _VALID_FIELD_CHOICES:
            continue
        try:
            confidence = float(row.get("confidence", 0.0))
        except (TypeError, ValueError):
            continue
        suggestions[path] = Suggestion(
            path=path, choice=choice, confidence=max(0.0, min(1.0, confidence)),
            reason=str(row.get("reason", "") or "")[:200] or "gemini suggestion",
        )
    return suggestions


DEFAULT_SOURCES: List[SuggestionSource] = [heuristic_source]
DEFAULT_BATCH_SOURCES: List[BatchSuggestionSource] = [gemini_batch_source]


def suggest_resolutions(
    conflicts: List[Conflict],
    sources: List[SuggestionSource] = DEFAULT_SOURCES,
    batch_sources: List[BatchSuggestionSource] = DEFAULT_BATCH_SOURCES,
) -> Dict[str, Suggestion]:
    """Per-conflict sources run first (cheap, no network); anything still
    unresolved goes to the batch sources in one shot each. First match wins,
    same precedence either way. Returns {path: Suggestion}."""
    suggestions: Dict[str, Suggestion] = {}
    unresolved: List[Conflict] = []
    for conflict in conflicts:
        matched = None
        for source in sources:
            matched = source(conflict)
            if matched is not None:
                break
        if matched is not None:
            suggestions[conflict["path"]] = matched
        else:
            unresolved.append(conflict)

    for batch_source in batch_sources:
        if not unresolved:
            break
        batch_result = batch_source(unresolved)
        for path, suggestion in batch_result.items():
            if path not in suggestions:
                suggestions[path] = suggestion
        unresolved = [c for c in unresolved if c["path"] not in batch_result]

    return suggestions
