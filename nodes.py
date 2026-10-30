"""ComfyUI nodes for UberLLM: text to video, image to video, image and image edit."""
from __future__ import annotations

import base64
import io
import os
import tempfile
import time

import numpy as np
import torch
from PIL import Image

import folder_paths
import comfy.model_management
import comfy.utils

from . import uberllm_client as ull
from .uberllm_models import load as load_models

try:  # the VIDEO type (ComfyUI 0.3.31+)
    from comfy_api.input_impl import VideoFromFile
except ImportError:  # pragma: no cover
    VideoFromFile = None

MODELS = load_models()
CATEGORY = "UberLLM"
SUBFOLDER = "uberllm"
AUTO = "auto"

KEY_INPUT = ("STRING", {
    "default": "",
    "tooltip": "Leave empty to use the UBERLLM_API_KEY environment variable (recommended). "
               "A key typed here is saved inside the workflow file and the files it makes.",
})
MAX_COST_INPUT = ("FLOAT", {
    "default": 0.0, "min": 0.0, "max": 100.0, "step": 0.01,
    "tooltip": "Most this may cost in US dollars; 0 = no limit. Above it, nothing is made or charged.",
})


def _default(kind: str, preferred: str) -> str:
    return preferred if preferred in MODELS[kind] else MODELS[kind][0]


def _image_data_uri(image: torch.Tensor, max_pixels: int = 2048 * 2048) -> str:
    """First picture of a ComfyUI IMAGE batch ([B,H,W,C] floats 0..1) as a data: URI."""
    arr = (image[0].cpu().numpy().clip(0, 1) * 255).astype(np.uint8)
    pil = Image.fromarray(arr)
    if pil.width * pil.height > max_pixels:
        scale = (max_pixels / (pil.width * pil.height)) ** 0.5
        pil = pil.resize((int(pil.width * scale), int(pil.height * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    mime = "image/png"
    if buf.tell() > 6 * 1024 * 1024:  # keep the request well under the 10 MB limit
        buf = io.BytesIO()
        pil.convert("RGB").save(buf, format="JPEG", quality=92)
        mime = "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()


def _to_tensor(raw: bytes) -> torch.Tensor:
    pil = Image.open(io.BytesIO(raw)).convert("RGB")
    return torch.from_numpy(np.array(pil).astype(np.float32) / 255.0).unsqueeze(0)


def _common(payload: dict, duration: int, resolution: str, aspect_ratio: str, audio: str, max_cost: float):
    if duration > 0:
        payload["duration_seconds"] = duration
    if resolution != AUTO:
        payload["resolution"] = resolution
    if aspect_ratio != AUTO:
        payload["aspect_ratio"] = aspect_ratio
    if audio != AUTO:
        payload["audio"] = audio == "on"
    if max_cost > 0:
        payload["max_cost"] = round(max_cost, 4)
    return payload


def _run_video(payload: dict, api_key: str):
    key = ull.resolve_key(api_key)
    bar = comfy.utils.ProgressBar(100)  # before submit: nothing after submit may fail before polling starts
    job = ull.submit_video(key, payload)
    estimated = job.get("estimated_cost_usd")
    print(f"[UberLLM] video job {job['id']} started on {job.get('model')}; "
          f"listed price ${estimated}, most it can cost ${job.get('max_cost_usd')}")

    def tick(j, elapsed):
        comfy.model_management.throw_exception_if_processing_interrupted()
        p = j.get("progress")
        # The model reports progress on some jobs; otherwise show time against a 3-minute guess.
        pct = int(p * 100) if isinstance(p, (int, float)) and p > 0 else min(95, int(elapsed / 180 * 100))
        bar.update_absolute(pct)

    job = ull.wait_video(key, job, on_tick=tick)
    out_dir = os.path.join(folder_paths.get_output_directory(), SUBFOLDER)
    os.makedirs(out_dir, exist_ok=True)
    filename = f"uberllm_{time.strftime('%Y%m%d-%H%M%S')}_{job['id'][:8]}.mp4"
    path = ull.download(job["results"][0]["url"], key, os.path.join(out_dir, filename))
    bar.update_absolute(100)
    cost, exact = ull.final_cost(key, job, estimated)
    print(f"[UberLLM] video saved to {path}; cost ${cost}" + ("" if exact else " (listed price; final charge not in yet)"))
    video = VideoFromFile(path) if VideoFromFile else None
    return {
        "ui": {"images": [{"filename": filename, "subfolder": SUBFOLDER, "type": "output"}], "animated": (True,)},
        "result": (video, path, float(cost or 0.0), job["id"]),
    }


VIDEO_OUTPUTS = ("VIDEO", "STRING", "FLOAT", "STRING")
VIDEO_OUTPUT_NAMES = ("video", "file_path", "cost_usd", "job_id")


def _video_options():
    return {
        "duration_seconds": ("INT", {"default": 0, "min": 0, "max": 60,
                                     "tooltip": "Clip length. 0 = the model's shortest. A length the model "
                                                "does not make is refused (with the lengths it does) before any charge."}),
        "resolution": ([AUTO, "360p", "480p", "540p", "720p", "768P", "1080p", "1440p", "2160p", "4k"],
                       {"default": AUTO, "tooltip": "auto = the model's default."}),
        "aspect_ratio": ([AUTO, "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"],
                         {"default": AUTO, "tooltip": "auto = the model's default."}),
        "audio": ([AUTO, "on", "off"], {"default": AUTO,
                                        "tooltip": "Sound track, where the model offers it. Sound often costs more."}),
    }


class UberLLMTextToVideo:
    DESCRIPTION = "Makes a video from a prompt with Veo, Kling, Seedance and more, on your UberLLM key."
    CATEGORY = CATEGORY
    RETURN_TYPES = VIDEO_OUTPUTS
    RETURN_NAMES = VIDEO_OUTPUT_NAMES
    FUNCTION = "run"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": (MODELS["t2v"], {"default": _default("t2v", "fal-ai/veo3.1/fast")}),
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                **_video_options(),
                "max_cost": MAX_COST_INPUT,
            },
            "optional": {"api_key": KEY_INPUT},
        }

    def run(self, model, prompt, duration_seconds, resolution, aspect_ratio, audio, max_cost,
            api_key=""):
        payload = _common({"model": model, "prompt": prompt}, duration_seconds, resolution,
                          aspect_ratio, audio, max_cost)
        return _run_video(payload, api_key)


class UberLLMImageToVideo:
    DESCRIPTION = "Makes a video that starts from a picture (or from reference pictures), on your UberLLM key."
    CATEGORY = CATEGORY
    RETURN_TYPES = VIDEO_OUTPUTS
    RETURN_NAMES = VIDEO_OUTPUT_NAMES
    FUNCTION = "run"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {"tooltip": "First frame (or the reference picture for a reference-to-video model)."}),
                "model": (MODELS["i2v"], {"default": _default("i2v", "fal-ai/kling-video/v3/standard/image-to-video")}),
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                **_video_options(),
                "max_cost": MAX_COST_INPUT,
            },
            "optional": {
                "end_image": ("IMAGE", {"tooltip": "Last frame, for models that blend two pictures."}),
                "api_key": KEY_INPUT,
            },
        }

    def run(self, image, model, prompt, duration_seconds, resolution, aspect_ratio, audio, max_cost,
            end_image=None, api_key=""):
        payload = {"model": model, "prompt": prompt}
        uri = _image_data_uri(image)
        if "reference" in model:
            payload["input_images"] = [{"url": uri, "role": "reference"}]
        else:
            payload["image_url"] = uri
        if end_image is not None:
            payload["end_image_url"] = _image_data_uri(end_image)
        _common(payload, duration_seconds, resolution, aspect_ratio, audio, max_cost)
        return _run_video(payload, api_key)


SIZES = [AUTO, "1024x1024", "1024x768", "768x1024", "1536x1024", "1024x1536"]


def _run_image(path: str, payload: dict, api_key: str):
    key = ull.resolve_key(api_key)
    payload["response_format"] = "b64_json"
    _, res = ull.request("POST", path, key, payload, timeout=300)
    tensors = []
    for item in res.get("data") or []:
        if item.get("b64_json"):
            raw = base64.b64decode(item["b64_json"])
        elif item.get("url"):
            raw = _fetch_bytes(item["url"], key)
        else:
            continue
        tensors.append(_to_tensor(raw))
    if not tensors:
        raise ull.UberLLMError("UberLLM answered without a picture. Nothing was charged for an empty answer.")
    # A batch needs one size; pictures of another size are fitted to the first.
    h, w = tensors[0].shape[1:3]
    tensors = [t if t.shape[1:3] == (h, w) else
               torch.nn.functional.interpolate(t.movedim(-1, 1), size=(h, w), mode="bilinear").movedim(1, -1)
               for t in tensors]
    cost = (res.get("usage") or {}).get("cost_usd")
    print(f"[UberLLM] {len(tensors)} picture(s) from {payload['model']}; cost ${cost}")
    return (torch.cat(tensors, 0), float(cost or 0.0))


def _fetch_bytes(url: str, key: str) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        p = ull.download(url, key, os.path.join(d, "img"))
        with open(p, "rb") as f:
            return f.read()


class UberLLMImage:
    DESCRIPTION = "Makes pictures from a prompt (Flux, Seedream, Nano Banana and more) on your UberLLM key."
    CATEGORY = CATEGORY
    RETURN_TYPES = ("IMAGE", "FLOAT")
    RETURN_NAMES = ("image", "cost_usd")
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": (MODELS["image"], {"default": _default("image", "venice/z-image-turbo")}),
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "size": (SIZES, {"default": AUTO, "tooltip": "auto = the model's default size."}),
                "n": ("INT", {"default": 1, "min": 1, "max": 10, "tooltip": "How many pictures."}),
                "max_cost": MAX_COST_INPUT,
            },
            "optional": {"api_key": KEY_INPUT},
        }

    def run(self, model, prompt, size, n, max_cost, api_key=""):
        payload = {"model": model, "prompt": prompt, "n": n}
        if size != AUTO:
            payload["size"] = size
        if max_cost > 0:
            payload["max_cost"] = round(max_cost, 4)
        return _run_image("/v1/images/generations", payload, api_key)


class UberLLMImageEdit:
    DESCRIPTION = "Changes a picture from a prompt (Nano Banana, Flux, Seedream edit models) on your UberLLM key."
    CATEGORY = CATEGORY
    RETURN_TYPES = ("IMAGE", "FLOAT")
    RETURN_NAMES = ("image", "cost_usd")
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "model": (MODELS["image_edit"], {"default": _default("image_edit", "google/nano-banana-2-edit")}),
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "n": ("INT", {"default": 1, "min": 1, "max": 10}),
                "max_cost": MAX_COST_INPUT,
            },
            "optional": {
                "reference_image": ("IMAGE", {"tooltip": "An extra picture the model can borrow from."}),
                "api_key": KEY_INPUT,
            },
        }

    def run(self, image, model, prompt, n, max_cost, reference_image=None, api_key=""):
        images = [_image_data_uri(image)]
        if reference_image is not None:
            images.append(_image_data_uri(reference_image))
        payload = {"model": model, "prompt": prompt, "n": n, "input_images": images}
        if max_cost > 0:
            payload["max_cost"] = round(max_cost, 4)
        return _run_image("/v1/images/edits", payload, api_key)


NODE_CLASS_MAPPINGS = {
    "UberLLMTextToVideo": UberLLMTextToVideo,
    "UberLLMImageToVideo": UberLLMImageToVideo,
    "UberLLMImage": UberLLMImage,
    "UberLLMImageEdit": UberLLMImageEdit,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "UberLLMTextToVideo": "UberLLM Text to Video",
    "UberLLMImageToVideo": "UberLLM Image to Video",
    "UberLLMImage": "UberLLM Image",
    "UberLLMImageEdit": "UberLLM Image Edit",
}
