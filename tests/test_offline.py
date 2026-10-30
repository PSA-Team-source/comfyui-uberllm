"""Offline checks (no ComfyUI, no network): python3 tests/test_offline.py"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import uberllm_client as ull  # noqa: E402
import uberllm_models as um  # noqa: E402


def m(id, out, inp, available=True, nsfw=False):
    return {"id": id, "output_modalities": out, "input_modalities": inp, "available": available, "nsfw": nsfw}


lists = um.group([
    m("wan/x-text-to-video", ["video"], ["text"]),
    m("fal-ai/veo3.1/fast", ["video"], ["text"]),
    m("kling/k-text-to-video", ["video"], ["text"]),
    m("fal-ai/kling/i2v", ["video"], ["text", "image"]),
    m("topaz/upscale", ["video"], ["text", "video"]),
    m("venice/z-image-turbo", ["image"], ["text"]),
    m("google/nano-banana-pro-edit", ["image"], ["text", "image"]),
    m("off/model", ["video"], ["text"], available=False),
    m("adult/model", ["video"], ["text"], nsfw=True),
    m("chat/model", ["text"], ["text"]),
])
assert lists["t2v"] == ["fal-ai/veo3.1/fast", "kling/k-text-to-video", "wan/x-text-to-video"], lists["t2v"]
assert lists["i2v"] == ["fal-ai/kling/i2v"], lists
assert lists["image"] == ["venice/z-image-turbo"] and lists["image_edit"] == ["google/nano-banana-pro-edit"], lists

cache = json.load(open(um.CACHE_FILE))
assert all(cache[k] for k in ("t2v", "i2v", "image", "image_edit")), "shipped model list is empty"

err = json.dumps({"error": {"code": "insufficient_credits", "message": "needs $0.40"}}).encode()
assert "balance is too low" in ull._friendly(402, err)
assert "did not accept the API key" in ull._friendly(401, b"{}")
assert ull._friendly(400, json.dumps({"error": {"code": "invalid_request", "message": "1 to 16 seconds"}}).encode()) \
    == "UberLLM: 1 to 16 seconds [invalid_request]"

os.environ.pop("UBERLLM_API_KEY", None)
try:
    ull.resolve_key("")
    raise AssertionError("missing key not caught")
except ull.UberLLMError as e:
    assert "UBERLLM_API_KEY" in str(e)
assert ull.resolve_key("  ull_abc ") == "ull_abc"
print("ok")
