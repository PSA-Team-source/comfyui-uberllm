"""Model lists for the node dropdowns.

Read once when ComfyUI starts, from UberLLM's public model list (no key needed),
with a 4-second limit so a slow network never holds up startup. If it cannot be
read, the list shipped in models_cache.json is used. Refresh that file with:

    python3 uberllm_models.py --write-cache
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

PUBLIC_MODELS_URL = os.environ.get(
    "UBERLLM_MODELS_URL", "https://api.uberllm.dev/api/v1/public/models")
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models_cache.json")

# Shown first, in this order; everything else follows alphabetically.
FAMILY_ORDER = ("veo", "kling", "seedance", "fal-ai/")


def classify(m: dict) -> str | None:
    """'t2v', 'i2v', 'image' or 'image_edit' for a usable model; None to leave it out."""
    if not m.get("available") or m.get("nsfw"):
        return None
    out = m.get("output_modalities") or []
    inp = m.get("input_modalities") or []
    if "video" in inp:  # video-to-video (upscalers): not covered by these nodes
        return None
    if "video" in out:
        return "i2v" if "image" in inp else "t2v"
    if "image" in out:
        return "image_edit" if "image" in inp else "image"
    return None


def _rank(model_id: str) -> tuple:
    low = model_id.lower()
    for i, fam in enumerate(FAMILY_ORDER):
        if fam in low:
            return (i, low)
    return (len(FAMILY_ORDER), low)


def group(models: list[dict]) -> dict[str, list[str]]:
    lists: dict[str, list[str]] = {"t2v": [], "i2v": [], "image": [], "image_edit": []}
    for m in models:
        kind = classify(m)
        if kind:
            lists[kind].append(m["id"])
    return {k: sorted(set(v), key=_rank) for k, v in lists.items()}


def fetch(timeout: float = 4) -> list[dict]:
    req = urllib.request.Request(PUBLIC_MODELS_URL, headers={"User-Agent": "comfyui-uberllm/1.0.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["models"]


def load() -> dict[str, list[str]]:
    try:
        lists = group(fetch())
        if all(lists.values()):
            return lists
    except Exception:  # offline, blocked, or a bad answer: fall back to the shipped list
        pass
    with open(CACHE_FILE, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__" and "--write-cache" in sys.argv:
    lists = group(fetch(timeout=30))
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(lists, f, indent=1)
        f.write("\n")
    print({k: len(v) for k, v in lists.items()})
