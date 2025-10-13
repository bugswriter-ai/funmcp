"""
Image Upscaler MCP Server with Bearer Token Authentication
Downloads an image, upscales it using the fal-ai/esrgan model,
and uploads the result to an S3 bucket.
"""
import json
import logging
from typing import Optional, Tuple, Dict, Union, List

# NOTE: google.generativeai is not used in the current logic, so it's commented out
# import google.generativeai as genai 
import requests
from fastmcp import FastMCP
from PIL import UnidentifiedImageError
# --- FIX: Import fal_client ---
import fal_client # Import the necessary fal client

# --- Import from shared modules ---
# NOTE: Removed unused 'fal_api_key' from config import as it's not directly used here, 
# assuming fal_client is configured via environment variables or a global setup.
from config import AI_HTTP_TIMEOUT
from helpers import (
    require_auth,
    upload_to_s3,
    infer_extension_from_content_type,
    CONTENT_TYPE_MAPPING,
    EXT_TO_CONTENT_TYPE
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
    
    # FIX: Get the final result URL from the subscription
    if result.get("image_url"):
        return result["image_url"]
    else:
        raise RuntimeError("Fal AI did not return a valid 'image_url' result.")

# --- Helper to download the *upscaled* image ---
def download_upscaled_image(upscaled_url: str) -> Tuple[bytes, str]:
    """Download the final upscaled image from the Fal AI result URL."""
    # We can reuse the main download function for this.
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
        # 1. Download the *original* image (optional, but good for validation/initial step)
        # We download to ensure the URL is valid and to get the original extension.
        # NOTE: We don't use the bytes here, as the fal model takes the URL.
        _, original_ext = download_image(file_url)

        # 2. Upscale the image using Fal AI
        upscaled_image_url = upscale_with_fal(file_url)
        
        # 3. Download the *upscaled* image bytes
        revived_bytes, output_ext = download_upscaled_image(upscaled_image_url)

        # 4. Upload the final result to S3
        filename = f"upscaled_image{output_ext}"
        s3_key, file_size = upload_to_s3(revived_bytes, filename, auth_token)

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