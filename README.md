# comfyui-uberllm

ComfyUI nodes that make videos and pictures with your own [UberLLM](https://uberllm.dev) API key:
Veo 3.1, Kling, Seedance, Wan, Hailuo, Vidu, LTX and more for video; Flux, Seedream, Nano Banana,
Z-Image and more for pictures. One key and one prepaid balance for all of them, no GPU needed.

No UberLLM fee on requests. Adding credit by card costs 5.5% + $0.50.

## Nodes

| Node | What it does | Main inputs | Outputs |
|---|---|---|---|
| **UberLLM Text to Video** | A video from a prompt | model, prompt, duration, resolution, shape, sound, max cost | `VIDEO`, file path, cost in USD, job id |
| **UberLLM Image to Video** | A video that starts from a picture (or uses it as a reference) | image, optional end image, and the same settings | `VIDEO`, file path, cost in USD, job id |
| **UberLLM Image** | Pictures from a prompt | model, prompt, size, how many | `IMAGE`, cost in USD |
| **UberLLM Image Edit** | Changes a picture from a prompt | image, optional reference image, model, prompt | `IMAGE`, cost in USD |

- The model lists are read from UberLLM's public model list when ComfyUI starts (4-second limit), so new
  models show up without updating the pack. Offline, the list shipped in `models_cache.json` is used.
  Veo, Kling and Seedance are listed first.
- `auto` (and a length of 0) leaves a setting to the model. A length, size or shape a model does not make
  is refused before anything is charged, with a message that lists the ones it does.
- `max_cost` (US dollars, 0 = no limit): if the request can cost more, nothing is made or charged.
- The video nodes save the file to `ComfyUI/output/uberllm/` and show it in the node. Connect `video` to
  any node that takes `VIDEO` (for example **Save Video**). UberLLM keeps the file for about 3 hours,
  so the local copy is the one to keep.
- The console shows each job's id, its listed price and the most it can cost before it runs, then what it cost.

## Install

**ComfyUI-Manager:** search for `UberLLM` in *Custom Nodes Manager* and install.

**By hand:**

```sh
cd ComfyUI/custom_nodes
git clone https://github.com/PSA-Team-source/comfyui-uberllm
```

The pack needs nothing beyond what ComfyUI already has (Python standard library, torch, numpy, Pillow).
ComfyUI 0.3.31 or newer.

## Your API key

1. Sign in at [uberllm.dev](https://uberllm.dev) (email code), add credit, and make a key under
   [Dashboard → API keys](https://uberllm.dev/dashboard/keys).
2. Start ComfyUI with the key in the environment:

   ```sh
   export UBERLLM_API_KEY=ull_...      # Windows: set UBERLLM_API_KEY=ull_...
   python main.py
   ```

Each node also has an `api_key` field. It is for quick tests only: a key typed there is saved inside the
workflow file and in the metadata of the files ComfyUI makes, so anyone you share them with gets your key.

## Example workflows

Drag a file from [`examples/`](examples) onto the ComfyUI canvas.

| Workflow | Models | Listed price (checked 2026-10-30) |
|---|---|---|
| [`text_to_video_veo31_fast.json`](examples/text_to_video_veo31_fast.json) | Veo 3.1 Fast, 4 s, 720p, no sound | $0.30 |
| [`image_then_video_kling.json`](examples/image_then_video_kling.json) | Z-Image Turbo picture, then Kling 3 Standard image to video, 3 s, no sound | about $0.008 + $0.189 |

Prices change with the market; each model's current price is on its page at
[uberllm.dev](https://uberllm.dev/?type=video#models) and in the console when a job starts.

## What you pay

- What the provider charged for what was made, never more than the most-it-can-cost shown when the job
  starts. See every job in [Dashboard → Activity](https://uberllm.dev/dashboard/activity).
- A video job that fails or expires costs nothing.
- Stopping a run in ComfyUI asks UberLLM to stop the job. A job the provider has already started can
  still finish and be billed.

API details: [uberllm.dev/docs/media](https://uberllm.dev/docs/media).

## Settings

| Environment variable | Default | Use |
|---|---|---|
| `UBERLLM_API_KEY` | (none) | Your key |
| `UBERLLM_BASE_URL` | `https://api.uberllm.dev` | API address |
| `UBERLLM_MODELS_URL` | `https://api.uberllm.dev/api/v1/public/models` | Where the model lists are read from |

Refresh the shipped model list: `python3 uberllm_models.py --write-cache`. Offline checks:
`python3 tests/test_offline.py`.

## Publishing (maintainers)

The pack is published to the [Comfy Registry](https://registry.comfy.org), which feeds ComfyUI-Manager.
`pyproject.toml` names the publisher `uberllm`; that publisher has to exist on the registry first.

1. Sign in at [registry.comfy.org](https://registry.comfy.org) and create the publisher with id `uberllm`
   (it can't be changed later; if that id is taken, put the one you get in `[tool.comfy] PublisherId`).
2. On the registry, open the publisher and create an API key. Copy it; it is shown once.
3. Either run `pip install comfy-cli && comfy node publish` in this folder and paste the key, or publish
   from GitHub Actions: move `.github/publish_action.yml` to `.github/workflows/publish_action.yml`
   (pushing a workflow file needs a GitHub login with the `workflow` permission), add the key as the
   Actions secret `REGISTRY_ACCESS_TOKEN` (Settings → Secrets and variables → Actions), and run
   *Publish to Comfy registry*. It then also runs on every push to `main` that changes `pyproject.toml`.
4. For a new release, raise `version` in `pyproject.toml` and push.

## License

MIT
