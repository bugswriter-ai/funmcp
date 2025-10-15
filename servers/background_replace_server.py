"""
Bria Background Replace MCP Server with Bearer Token Authentication.
Calls fal-ai/bria/background/replace and uploads the resulting image to S3.
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
    infer_extension_from_content_type
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


def call_bria_replace(arguments: Dict[str, Any]) -> Dict[str, Any]:
    result = fal_client.subscribe(
        "fal-ai/bria/background/replace",
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
    # Some endpoints might return single image dicts
    if isinstance(result.get("image"), dict) and isinstance(result["image"].get("url"), str):
        return result["image"]["url"], result["image"].get("content_type")
    raise RuntimeError(f"Unexpected result format, no image URL found: {result}")


mcp = FastMCP(
    name="Bria Background Replace",
    dependencies=["requests", "fal-client", "python-dotenv", "starlette"]
)


@mcp.tool()
@require_auth
async def bria_background_replace(
    image_url: str,
    ref_image_url: str = "",
    prompt: str = "",
    negative_prompt: str = "",
    refine_prompt: bool = True,
    seed: Optional[int] = None,
    fast: bool = True,
    auth_token: Optional[str] = None,
) -> str:
    """
    Replace background of an input image using fal-ai Bria model.

    Args mirror the model schema. Provide either ref_image_url or prompt.
    Args:
        image_url (str): URL of the input image.
        ref_image_url (str): URL of the reference image.
        prompt (str): Prompt for the background replacement.
        negative_prompt (str): Negative prompt for the background replacement.
        refine_prompt (bool): Whether to refine the prompt.
        fast (bool): Whether to use fast mode.
        auth_token (str): Bearer token for authentication.

    Returns:
        str: JSON string containing the S3 key of the generated image.
    """
    if not image_url or not (image_url.startswith("http://") or image_url.startswith("https://")):
        return json.dumps({"error": "image_url must be a valid HTTP(S) URL"})

    if ref_image_url and prompt:
        return json.dumps({"error": "Provide either ref_image_url or prompt, not both"})

    arguments: Dict[str, Any] = {
        "image_url": image_url,
        "ref_image_url": ref_image_url,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "refine_prompt": refine_prompt,
        "fast": fast,
    }
    if seed is not None:
        arguments["seed"] = seed

    try:
        result = call_bria_replace(arguments)
        out_url, explicit_ct = extract_image_url(result)
        image_bytes, ext, _ct = download_image(out_url)
        if explicit_ct:
            # override ext if API told us precisely
            maybe_ext = infer_extension_from_content_type(explicit_ct)
            if maybe_ext:
                ext = maybe_ext
        filename = f"bria_background_replace{ext}"
        s3_key, file_size = upload_to_s3(image_bytes, filename, auth_token)

        return json.dumps({
            "attachments": [{"s3_key": s3_key, "size": file_size, "filename": filename}],
            "source_image_url": out_url,
            "summary": "Background replaced successfully.",
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
    logger.info("Starting Bria Background Replace MCP Server")
    mcp.run(transport="streamable-http")


