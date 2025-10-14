"""
Image Upscaler MCP Server with Bearer Token Authentication
Downloads an image, upscales it using the fal-ai/esrgan model,
and uploads the result to an S3 bucket.
"""
import json
import logging
from typing import Optional, Tuple

import fal_client
import requests
from fastmcp import FastMCP
from PIL import UnidentifiedImageError

# --- Import from shared modules ---
from config import AI_HTTP_TIMEOUT
from helpers import (
    require_auth,
    upload_to_s3,
    infer_extension_from_content_type
)

# --- Configuration & Initialization ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# --- Initialization ---
def on_queue_update(update):
    """Callback for fal-client logs."""
    if isinstance(update, fal_client.InProgress):
        for log in update.logs:
            # Using print() here for cleaner log output from the fal library
            print(log["message"])

# --- Core Logic ---
def download_image(url: str) -> Tuple[bytes, str]:
    """Download image from URL, using a longer timeout for potentially large files."""
    logger.info(f"Downloading image from: {url}")
    response = requests.get(url, timeout=AI_HTTP_TIMEOUT)
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "")
    # Fallback to a common extension if content type is missing
    ext = infer_extension_from_content_type(content_type) or ".jpg"

    logger.info(f"Downloaded {len(response.content)} bytes (type: {content_type})")
    return response.content, ext


def upscale_with_fal(image_url: str) -> str:
    """
    Subscribes to the fal-ai/esrgan model to upscale an image.

    Args:
        image_url: Public URL of the image to process.

    Returns:
        The URL of the upscaled image result.
    """
    logger.info(f"Submitting upscale job for: {image_url}")
    result = fal_client.subscribe(
        "fal-ai/esrgan", # Model for upscaling
        arguments={
            "image_url": image_url
        },
        with_logs=True,
        on_queue_update=on_queue_update,
    )

    # Add diagnostic logging to see the exact response from Fal AI
    logger.info(f"Fal AI result received: {json.dumps(result, indent=2)}")

    # --- START OF FINAL FIX ---
    # The actual response is {"image": {"url": "..."}}. We parse this structure.
    image_dict = result.get("image")
    if image_dict and isinstance(image_dict, dict) and image_dict.get("url"):
        upscaled_url = image_dict["url"]
        logger.info(f"Successfully extracted upscaled image URL: {upscaled_url}")
        return upscaled_url
    else:
        # If the structure is not what we expect, log the error and raise it.
        error_message = f"Fal AI did not return a valid image URL in the expected format. Full response: {result}"
        logger.error(error_message)
        raise RuntimeError(error_message)
    # --- END OF FINAL FIX ---

# --- Helper to download the *upscaled* image ---
def download_upscaled_image(upscaled_url: str) -> Tuple[bytes, str]:
    """Download the final upscaled image from the Fal AI result URL."""
    return download_image(upscaled_url)


# --- MCP Server Definition ---
mcp = FastMCP(
    name="Image Upscaler",
    dependencies=["requests", "Pillow", "fal-client", "python-dotenv", "starlette"]
)


@mcp.tool()
@require_auth
async def process_image(file_url: str, auth_token: Optional[str] = None) -> str:
    """
    Downloads an image, uses an AI model (fal-ai/esrgan) to upscale it,
    uploads the final result to S3, and returns JSON with the S3 key.

    Args:
        file_url: HTTP(S) URL of the image to upscale.
        auth_token: Bearer token (injected by decorator).
    """
    logger.info("=" * 60)
    logger.info("Tool 'process_image' called for URL: %s", file_url)
    logger.info("=" * 60)

    if not (file_url.startswith("http://") or file_url.startswith("https://")):
        return json.dumps({"error": "file_url must start with http:// or https://", "attachments": []})

    try:
        # 1. Upscale the image using Fal AI, which returns the URL of the new image
        upscaled_image_url = upscale_with_fal(file_url)

        # 2. Download the *upscaled* image bytes from the result URL
        upscaled_bytes, output_ext = download_upscaled_image(upscaled_image_url)

        # 3. Upload the final result to S3
        filename = f"upscaled_image{output_ext}"
        s3_key, file_size = upload_to_s3(upscaled_bytes, filename, auth_token)

        logger.info("=" * 60)
        logger.info(f"✅ SUCCESS: Upscaled image uploaded as {s3_key} ({file_size} bytes)")
        logger.info("=" * 60)

        return json.dumps(
            {
                "attachments": [{"s3_key": s3_key, "size": file_size, "filename": filename}],
                "summary": "The image has been successfully upscaled and enhanced.",
            },
            indent=2,
        )

    except UnidentifiedImageError:
        return json.dumps({"error": "Downloaded file is not a valid image.", "attachments": []})
    except requests.exceptions.RequestException as e:
        return json.dumps({"error": f"Network error during download or upload: {str(e)}", "attachments": []})
    except RuntimeError as e: # Catch Fal AI specific errors
        logger.error(f"Error during AI processing: {e}")
        return json.dumps({"error": f"AI Processing error: {str(e)}", "attachments": []})
    except Exception as e:
        logger.exception("An unexpected error occurred during image processing")
        return json.dumps({"error": f"An unexpected error occurred: {str(e)}", "attachments": []})


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Starting Image Upscaler MCP Server")
    logger.info("Using fal-ai/esrgan for upscaling.")
    logger.info("=" * 60)

    mcp.run(transport="streamable-http")
