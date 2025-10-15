"""
Bria GenFill MCP Server with Bearer Token Authentication.
Calls fal-ai/bria/genfill to inpaint based on a mask and uploads the result to S3.
"""
import json
import logging
from typing import Optional, Tuple, Any, Dict

import fal_client
import requests
from fastmcp import FastMCP

from config import AI_HTTP_TIMEOUT
from helpers import (
    require_auth,
    upload_to_s3,
    infer_extension_from_content_type,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def on_queue_update(update):
    if isinstance(update, fal_client.InProgress):
        for log in update.logs:
            print(log["message"])


def download_image(url: str) -> Tuple[bytes, str, str]:
    logger.info(f"Downloading generated image from: {url}")
    response = requests.get(url, timeout=AI_HTTP_TIMEOUT)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "image/jpeg")
    ext = infer_extension_from_content_type(content_type) or ".jpg"
    return response.content, ext, content_type


def call_bria_genfill(arguments: Dict[str, Any]) -> Dict[str, Any]:
    result = fal_client.subscribe(
        "fal-ai/bria/genfill",
        arguments=arguments,
        with_logs=True,
        on_queue_update=on_queue_update,
    )
    logger.info(f"Fal AI result: {json.dumps(result, indent=2)}")
    return result


def extract_image_url(result: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    images = result.get("images")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, dict) and isinstance(first.get("url"), str):
            return first["url"], first.get("content_type")
    if isinstance(result.get("image"), dict) and isinstance(result["image"].get("url"), str):
        return result["image"]["url"], result["image"].get("content_type")
    raise RuntimeError(f"Unexpected result format, no image URL found: {result}")


mcp = FastMCP(
    name="Bria GenFill",
    dependencies=["requests", "fal-client", "python-dotenv", "starlette"]
)


@mcp.tool()
@require_auth
async def bria_genfill(
    image_url: str,
    mask_url: str,
    prompt: str,
    num_images: int = 1,
    negative_prompt: str = "",
    refine_prompt: bool = True,
    seed: Optional[int] = None,
    fast: bool = True,
    auth_token: Optional[str] = None,
) -> str:
    """
    GenFill/inpainting with Bria model.

    Args:
        image_url: URL of the source image.
        mask_url: URL of the mask image.
        prompt: Text prompt for inpainting.

    """
    for url, label in [(image_url, "image_url"), (mask_url, "mask_url")]:
        if not url or not (url.startswith("http://") or url.startswith("https://")):
            return json.dumps({"error": f"{label} must be a valid HTTP(S) URL"})

    if not prompt or not isinstance(prompt, str):
        return json.dumps({"error": "prompt is required"})

    arguments: Dict[str, Any] = {
        "image_url": image_url,
        "mask_url": mask_url,
        "prompt": prompt,
        "num_images": num_images,
        "negative_prompt": negative_prompt,
        "refine_prompt": refine_prompt,
        "fast": fast,
    }
    if seed is not None:
        arguments["seed"] = seed

    try:
        result = call_bria_genfill(arguments)
        out_url, explicit_ct = extract_image_url(result)
        image_bytes, ext, _ct = download_image(out_url)
        if explicit_ct:
            maybe_ext = infer_extension_from_content_type(explicit_ct)
            if maybe_ext:
                ext = maybe_ext
        filename = f"bria_genfill{ext}"
        s3_key, file_size = upload_to_s3(image_bytes, filename, auth_token)

        return json.dumps({
            "attachments": [{"s3_key": s3_key, "size": file_size, "filename": filename}],
            "source_image_url": out_url,
            "summary": "GenFill completed successfully.",
        }, indent=2)
    except requests.exceptions.RequestException as e:
        return json.dumps({"error": f"Network error: {str(e)}"})
    except RuntimeError as e:
        logger.error(f"Processing error: {e}")
        return json.dumps({"error": str(e)})
    except Exception as e:
        logger.exception("Unexpected error")
        return json.dumps({"error": f"Unexpected error: {str(e)}"})


if __name__ == "__main__":
    logger.info("Starting Bria GenFill MCP Server")
    mcp.run(transport="streamable-http")


