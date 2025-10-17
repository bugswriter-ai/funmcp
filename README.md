# MCP Servers (funmcp)

This folder contains a collection of Model Context Protocol (MCP) micro-servers built with `fastmcp`. Each server exposes one or more tools over HTTP that can be called by MCP-compatible clients (e.g., AI agents) to perform media processing tasks. Outputs are uploaded to your backend via a presigned S3 upload flow.

## Contents
- Shared modules: `servers/config.py`, `servers/helpers.py`
- Individual servers (HTTP tools):
  - `old_image_reviver.py` — Restore/colourize old photos via Gemini
  - `grayscale_server.py` — Convert image to grayscale
  - `ai-upscale.py` — Image upscaling via fal-ai ESRGAN
  - `audio_clone_server.py` — Clone a voice and speak a prompt (fal-ai/zonos)
  - `product_photoshoot_server.py` — Generate product banner (easel-ai/product-photoshoot)
  - `try_fashion.py` — AI fashion photoshoot (easel-ai/fashion-photoshoot)
  - `background_replace_server.py` — Replace image background (fal-ai/bria/background/replace)
  - `video_background_removal_server.py` — Remove video background (fal-ai/bria/video/background-removal)
  - `genfill_server.py` — Inpainting (fal-ai/bria/genfill)
  - `texture_generator_server.py` — AI texture generation from text (fal-ai/fast-sdxl)

## Requirements
- Python 3.13+
- Dependencies (managed via `pyproject.toml`):
  - `fastmcp`, `requests`, `Pillow`, `fal-client`, `google-generativeai`, `python-dotenv`, `starlette`
- Network access to model providers (Fal AI, Google Gemini)
- Access to your backend API for presigned S3 uploads

## Environment Variables
Create a `.env` (loaded by `servers/config.py` / `servers/helpers.py`):

- `API_BASE_URL` (required): Base URL for your backend API providing `/files/upload` presigned endpoint. Default: `http://localhost:5000/api/v1`.
- `GEMINI_API_KEY` (required for `old_image_reviver.py`)
- `FAL_KEY` (required for Fal AI based servers)
- Optional timeouts:
  - `HTTP_CONNECT_TIMEOUT` (default 15)
  - `HTTP_READ_TIMEOUT` (default 60)
  - `AI_HTTP_CONNECT_TIMEOUT` (default 15)
  - `AI_HTTP_READ_TIMEOUT` (default 180)

## How uploads work
Servers call `POST {API_BASE_URL}/files/upload` to obtain a presigned S3 form. They then upload the processed file bytes directly to S3 and return JSON like:

```json
{
  "attachments": [
    { "s3_key": "<file_id>", "size": 123456, "filename": "output.png" }
  ],
  "summary": "..."
}
```

Your caller should read `attachments[0].s3_key` to reference the uploaded asset.

## Running the servers

### Linux/macOS (run all)
Use the provided script which launches each server on a dedicated port using `fastmcp` HTTP transport:

```bash
bash run.sh
```

Ports (by default in `run.sh`):
- 9001 `old_image_reviver.py`
- 9002 `grayscale_server.py`
- 9003 `ai-upscale.py`
- 9004 `audio_clone_server.py`
- 9005 `product_photoshoot_server.py`
- 9006 `try_fashion.py`
- 9007 `meshy_text_to_3d_server.py` (if present)
- 9008 `background_replace_server.py`
- 9009 `video_background_removal_server.py`
- 9010 `genfill_server.py`
- 9012 `texture_generator_server.py`

Logs are written to `$HOME/funmcp/logs/` by the script.

### Windows (run individually)
The script uses `setsid`/Bash and is tailored to Linux. On Windows, run servers individually from the `mcp servers` directory after creating and activating a virtual environment and installing deps.

Example (PowerShell cmdlets shown generically):

```powershell
# From: mcp servers
# 1) Create/activate venv and install
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -U pip
pip install -e .

# 2) Ensure .env is set (API_BASE_URL, FAL_KEY, GEMINI_API_KEY as needed)

# 3) Start one server over HTTP on port 9002
python -m fastmcp run "servers/grayscale_server.py:mcp" --transport http --port 9002
```

Repeat with other `servers/<file>.py` and ports (matching the Linux list or your own). You can run multiple terminals or use a process manager.

## Authentication
All tools require a Bearer token in the `Authorization` header. The `helpers.require_auth` decorator injects a validated token (`auth_token`) into tool functions. Provide headers when calling the HTTP tool endpoint via MCP client.

Example header:
```
Authorization: Bearer <YOUR_TOKEN>
```

## Tool reference
Below are the tools exposed by each server and their parameters. All return a JSON string with `attachments` on success or `{ "error": "..." }` on failure.

- old_image_reviver.py
  - Tool: `revive_old_image(file_url)`
  - Requires: `GEMINI_API_KEY`
  - Input: `file_url` (http/https image URL)
  - Output: Restored image uploaded; returns `attachments[0].s3_key`

- grayscale_server.py
  - Tool: `grayscale_image(file_url)`
  - Input: `file_url` (http/https image URL)
  - Output: Grayscale image uploaded

- ai-upscale.py
  - Tool: `process_image(file_url)`
  - Provider: `fal-ai/esrgan`
  - Input: `file_url` (http/https image URL)
  - Output: Upscaled image uploaded

- audio_clone_server.py
  - Tool: `clone_audio(audio_url, prompt)`
  - Provider: `fal-ai/zonos`
  - Inputs: `audio_url` (sample voice), `prompt` (text to speak)
  - Output: Cloned voice audio uploaded

- product_photoshoot_server.py
  - Tool: `create_product_banner_photo(product_image_url, scene_description, product_placement_description)`
  - Provider: `easel-ai/product-photoshoot`
  - Output: Banner image uploaded

- try_fashion.py
  - Tool: `generate_photoshoot(garment_image_url, face_image_url, gender)`
  - Provider: `easel-ai/fashion-photoshoot`
  - Output: Generated fashion photo uploaded

- background_replace_server.py
  - Tool: `bria_background_replace(image_url, ref_image_url?, prompt?, negative_prompt?, refine_prompt?, seed?, fast?)`
  - Provider: `fal-ai/bria/background/replace`
  - Output: Image with replaced background uploaded

- video_background_removal_server.py
  - Tool: `bria_video_background_removal(video_url, background_color?, output_container_and_codec?)`
  - Provider: `fal-ai/bria/video/background-removal`
  - Output: Processed video uploaded

- genfill_server.py
  - Tool: `bria_genfill(image_url, mask_url, prompt, num_images?, negative_prompt?, refine_prompt?, seed?, fast?)`
  - Provider: `fal-ai/bria/genfill`
  - Output: Inpainted image uploaded

- texture_generator_server.py
  - Tool: `generate_texture(prompt, style?, resolution?, seed?)`
  - Provider: `fal-ai/fast-sdxl`
  - Inputs: `prompt` (text description), `style` ("seamless"), `resolution` (e.g., "1024x1024"), `seed` (integer)
  - Output: Generated texture uploaded

## Development notes
- Shared logic (`helpers.py`) handles token validation and S3 upload via your backend. It maps content-types to file extensions and infers missing types.
- `config.py` centralizes timeouts and provider keys. Adjust `AI_HTTP_READ_TIMEOUT` for large media downloads.
- Each server declares a `FastMCP` instance named `mcp` which the runner targets (`servers/<file>.py:mcp`).

## Troubleshooting
- 401/Authentication failed: Ensure you send `Authorization: Bearer <token>` and the server sees it (reverse proxy may strip headers).
- 403/Upload denied: Check your backend auth and `API_BASE_URL`.
- Model errors: Validate `FAL_KEY`/`GEMINI_API_KEY`, inspect server logs (Linux script writes to `$HOME/funmcp/logs/`).
- Timeouts on large media: increase `AI_HTTP_READ_TIMEOUT`.
