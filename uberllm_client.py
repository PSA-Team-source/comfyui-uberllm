"""Small HTTP client for the UberLLM API (https://uberllm.dev/docs/media).

Standard library only, so the pack adds no dependencies to ComfyUI. Nothing in
here imports ComfyUI, which keeps it testable on its own.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid

BASE_URL = os.environ.get("UBERLLM_BASE_URL", "https://api.uberllm.dev").rstrip("/")
USER_AGENT = "comfyui-uberllm/1.0.0"
KEYS_URL = "https://uberllm.dev/dashboard/keys"
CREDITS_URL = "https://uberllm.dev/dashboard/credits"


class UberLLMError(Exception):
    """An error with a message a person can act on."""


def resolve_key(node_key: str | None) -> str:
    key = (node_key or "").strip() or os.environ.get("UBERLLM_API_KEY", "").strip()
    if not key:
        raise UberLLMError(
            "No UberLLM API key. Set the UBERLLM_API_KEY environment variable before starting "
            f"ComfyUI (or fill in the node's api_key). Make a key at {KEYS_URL}."
        )
    return key


def _friendly(status: int, body: bytes) -> str:
    code, message = "", ""
    try:
        err = json.loads(body.decode("utf-8", "replace")).get("error") or {}
        code, message = err.get("code") or "", err.get("message") or ""
    except (ValueError, AttributeError):
        message = body.decode("utf-8", "replace")[:300]
    if status == 401:
        return f"UberLLM did not accept the API key. Check it, or make a new one at {KEYS_URL}."
    if status == 402 or code == "insufficient_credits":
        return f"Your UberLLM balance is too low for this. Add credit at {CREDITS_URL}. ({message})"
    if status == 429:
        return "Too many requests to UberLLM right now. Wait a few seconds and run it again."
    if code == "max_cost_too_low":
        return f"This can cost more than your max_cost, so nothing was made or charged. ({message})"
    return f"UberLLM: {message or 'HTTP ' + str(status)}" + (f" [{code}]" if code else "")


def request(method: str, path: str, key: str | None = None, body: dict | None = None,
            headers: dict | None = None, timeout: float = 120) -> tuple[int, dict]:
    """Send one request; answer (status, json). Non-2xx raises UberLLMError."""
    url = path if path.startswith("http") else BASE_URL + path
    data = json.dumps(body).encode() if body is not None else None
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if data is not None:
        h["Content-Type"] = "application/json"
    if key:
        h["Authorization"] = "Bearer " + key
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raise UberLLMError(_friendly(e.code, e.read())) from None
    except urllib.error.URLError as e:
        raise UberLLMError(f"Could not reach UberLLM ({e.reason}). Check your internet connection.") from None


def download(url: str, key: str, dest: str, timeout: float = 300) -> str:
    """Download a result file (results need the same key) to dest."""
    if url.startswith("/"):
        url = BASE_URL + url
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + key, "User-Agent": USER_AGENT})
    tmp = dest + ".part"
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
    except urllib.error.HTTPError as e:
        raise UberLLMError(_friendly(e.code, e.read())) from None
    os.replace(tmp, dest)
    return dest


TERMINAL = {"succeeded", "failed", "canceled", "expired"}


def submit_video(key: str, payload: dict) -> dict:
    # A fresh Idempotency-Key per run: a retried connection never starts a second paid job.
    _, job = request("POST", "/v1/video/generations", key, payload,
                     headers={"Idempotency-Key": str(uuid.uuid4())})
    return job


def wait_video(key: str, job: dict, on_tick=None, interval: float = 5, timeout: float = 1800) -> dict:
    """Poll a video job until it ends. on_tick(job, elapsed) may raise to stop (the job is then cancelled)."""
    job_id = job["id"]
    start = time.time()
    try:
        while True:
            if on_tick:
                on_tick(job, time.time() - start)
            if job.get("status") in TERMINAL:
                break
            if time.time() - start > timeout:
                raise UberLLMError(f"The video job {job_id} took longer than {int(timeout // 60)} minutes, "
                                   "so UberLLM was asked to stop it. See it in https://uberllm.dev/dashboard/activity")
            time.sleep(interval)
            _, job = request("GET", f"/v1/video/generations/{job_id}", key)
    except BaseException:
        # Interrupted in ComfyUI, timed out, or crashed: ask UberLLM to stop the job. A job the
        # provider has already started may still finish and be billed.
        if job.get("status") not in TERMINAL:
            try:
                request("DELETE", f"/v1/video/generations/{job_id}", key, timeout=15)
            except UberLLMError:
                pass
        raise
    if job["status"] != "succeeded":
        err = job.get("error") or {}
        raise UberLLMError(f"The video was not made ({job['status']}): {err.get('message') or 'no reason given'}. "
                           "A failed, cancelled or expired job costs nothing.")
    return job


def final_cost(key: str, job: dict, estimated: float | None = None, wait: float = 45) -> tuple[float | None, bool]:
    """The job's charge. The exact charge can land up to ~30 s after the file is ready.
    Answers (cost, exact). If it has not landed within `wait`, the listed price, exact=False."""
    deadline = time.time() + wait
    while True:
        usage = job.get("usage") or {}
        if usage.get("cost_usd") is not None:
            return float(usage["cost_usd"]), True
        if time.time() >= deadline:
            est = job.get("estimated_cost_usd", estimated)
            return (float(est) if est is not None else None), False
        time.sleep(5)
        _, job = request("GET", f"/v1/video/generations/{job['id']}", key)
