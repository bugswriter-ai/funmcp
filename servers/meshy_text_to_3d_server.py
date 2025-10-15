"""
Meshy Text-to-3D MCP Server with Bearer Token Authentication.
Generates a 3D model from text using fal-ai/meshy/v6-preview/text-to-3d
and uploads the final 3D asset to S3.
"""
import json
import logging
from typing import Optional, Tuple

import fal_client
import requests
from fastmcp import FastMCP

from config import AI_HTTP_TIMEOUT
from helpers import (
    require_auth,
    upload_to_s3,
    infer_extension_from_content_type
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def on_queue_update(update):
    """Callback to print logs from the fal-client subscription in real-time."""
    if isinstance(update, fal_client.InProgress):
        for log in update.logs:
            print(log["message"])  # print for live feedback from fal queue


def download_asset(url: str) -> Tuple[bytes, str, str]:
    """
    Downloads a binary asset from a URL.

    Returns:
        tuple: (bytes, extension, content_type)
    """
    logger.info(f"Downloading 3D asset from: {url}")
    response = requests.get(url, timeout=AI_HTTP_TIMEOUT)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "application/octet-stream")

    # Try to infer file extension from content-type, fallback to common 3D formats
    ext = infer_extension_from_content_type(content_type)
    if ext == ".jpg":
        # For non-image assets, handle common 3D types based on content-type or URL
        lowered_ct = content_type.lower()
        lowered_url = url.lower()
        if "gltf-binary" in lowered_ct or lowered_url.endswith(".glb"):
            ext = ".glb"
        elif "gltf" in lowered_ct or lowered_url.endswith(".gltf"):
            ext = ".gltf"
        elif "obj" in lowered_ct or lowered_url.endswith(".obj"):
            ext = ".obj"
        elif "stl" in lowered_ct or lowered_url.endswith(".stl"):
            ext = ".stl"
        else:
            ext = ".bin"

    logger.info(f"Downloaded {len(response.content)} bytes (type: {content_type}, ext: {ext})")
    return response.content, ext, content_type


def generate_3d_with_fal(prompt: str) -> str:
    """
    Subscribes to the fal-ai meshy text-to-3d model and returns the asset URL.
    """
    logger.info("Submitting text-to-3D job to Fal AI (meshy v6-preview)...")
    result = fal_client.subscribe(
        "fal-ai/meshy/v6-preview/text-to-3d",
        arguments={
            "prompt": prompt,
        },
        with_logs=True,
        on_queue_update=on_queue_update,
    )

    logger.info(f"Fal AI result received: {json.dumps(result, indent=2)}")

    # Try common shapes of result structures
    # 1) {"model": {"url": "..."}}
    model_dict = result.get("model") if isinstance(result, dict) else None
    if isinstance(model_dict, dict) and model_dict.get("url"):
        return model_dict["url"]

    # 2) {"asset": {"url": "..."}}
    asset_dict = result.get("asset") if isinstance(result, dict) else None
    if isinstance(asset_dict, dict) and asset_dict.get("url"):
        return asset_dict["url"]

    # 3) Legacy/images-like: not expected for 3D, but be defensive
    url_candidate = result.get("url") if isinstance(result, dict) else None
    if isinstance(url_candidate, str) and url_candidate.startswith("http"):
        return url_candidate

    error_message = (
        f"Fal AI did not return a valid 3D asset URL in an expected format. Full response: {result}"
    )
    logger.error(error_message)
    raise RuntimeError(error_message)


mcp = FastMCP(
    name="Meshy Text-to-3D",
    dependencies=["requests", "fal-client", "python-dotenv", "starlette"]
)


@mcp.tool()
@require_auth
async def generate_text_to_3d(prompt: str, auth_token: Optional[str] = None) -> str:
    """
    Generates a 3D model from a text prompt using fal-ai meshy model, uploads
    the resulting asset to S3, and returns JSON with the S3 key.
    """
    logger.info("=" * 60)
    logger.info("Tool 'generate_text_to_3d' called.")
    logger.info("=" * 60)

    if not prompt or not isinstance(prompt, str) or len(prompt.strip()) < 3:
        return json.dumps({"error": "A non-empty prompt is required."})

    try:
        asset_url = generate_3d_with_fal(prompt.strip())

        asset_bytes, output_ext, content_type = download_asset(asset_url)
        filename = f"meshy_text_to_3d{output_ext}"

        s3_key, file_size = upload_to_s3(asset_bytes, filename, auth_token)

        logger.info("=" * 60)
        logger.info(f"✅ SUCCESS: 3D asset uploaded as {s3_key} ({file_size} bytes)")
        logger.info("=" * 60)

        return json.dumps(
            {
                "attachments": [
                    {"s3_key": s3_key, "size": file_size, "filename": filename}
                ],
                "source_asset_url": asset_url,
                "summary": "3D model generated from text and uploaded successfully.",
            },
            indent=2,
        )

    except requests.exceptions.RequestException as e:
        return json.dumps({"error": f"Network error: {str(e)}"})
    except RuntimeError as e:
        logger.error(f"Error during AI processing: {e}")
        return json.dumps({"error": f"AI Processing error: {str(e)}"})
    except Exception as e:
        logger.exception("An unexpected error occurred during 3D generation")
        return json.dumps({"error": f"An unexpected error occurred: {str(e)}"})


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Starting Meshy Text-to-3D MCP Server")
    logger.info("Using fal-ai/meshy/v6-preview/text-to-3d model.")
    logger.info("=" * 60)

    mcp.run(transport="streamable-http")


