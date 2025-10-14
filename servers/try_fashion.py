"""
AI Fashion Photoshoot MCP Server with Bearer Token Authentication.
Generates a fashion photoshoot image using the easel-ai/fashion-photoshoot model,
and uploads the final result to an S3 bucket.
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
            print(log["message"])


def download_image(url: str) -> Tuple[bytes, str]:
    """Downloads an image from a URL, returning its bytes and file extension."""
    logger.info(f"Downloading image from: {url}")
    response = requests.get(url, timeout=AI_HTTP_TIMEOUT)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "")
    ext = infer_extension_from_content_type(content_type) or ".jpg"
    logger.info(f"Downloaded {len(response.content)} bytes (type: {content_type})")
    return response.content, ext


def generate_fashion_photo_with_fal(
    garment_image_url: str,
    face_image_url: str,
    gender: str
) -> str:
    """
    Subscribes to the easel-ai/fashion-photoshoot model to generate an image.
    """
    logger.info(f"Submitting fashion photoshoot job to Fal AI...")
    result = fal_client.subscribe(
        "easel-ai/fashion-photoshoot",
        arguments={
            "garment_image": garment_image_url,
            "face_image": face_image_url,
            "gender": gender
        },
        with_logs=True,
        on_queue_update=on_queue_update,
    )

    logger.info(f"Fal AI result received: {json.dumps(result, indent=2)}")

    # --- THIS IS THE FIX ---
    # The actual response is {"image": {"url": "..."}}. We now parse this structure
    # instead of the old {"images": [...]}.
    image_dict = result.get("image")
    if image_dict and isinstance(image_dict, dict) and image_dict.get("url"):
        generated_url = image_dict["url"]
        logger.info(f"Successfully extracted generated image URL: {generated_url}")
        return generated_url
    
    # If the structure is not what we expect, raise a clear error.
    error_message = f"Fal AI did not return a valid image URL in the expected format. Full response: {result}"
    logger.error(error_message)
    raise RuntimeError(error_message)


mcp = FastMCP(
    name="AI Fashion Photoshoot",
    dependencies=["requests", "Pillow", "fal-client", "python-dotenv", "starlette"]
)


@mcp.tool()
@require_auth
async def generate_photoshoot(
    garment_image_url: str,
    face_image_url: str,
    gender: str,
    auth_token: Optional[str] = None
) -> str:
    """
    Generates a fashion photoshoot image using an AI model, uploads the result
    to S3, and returns JSON with the S3 key.
    """
    logger.info("=" * 60)
    logger.info("Tool 'generate_photoshoot' called.")
    logger.info("=" * 60)

    if not garment_image_url.startswith("http"):
        return json.dumps({"error": "garment_image_url must be a valid HTTP(S) URL."})
    if not face_image_url.startswith("http"):
        return json.dumps({"error": "face_image_url must be a valid HTTP(S) URL."})
    if gender not in ["male", "female"]:
        return json.dumps({"error": "gender must be either 'male' or 'female'."})

    try:
        generated_image_url = generate_fashion_photo_with_fal(
            garment_image_url=garment_image_url,
            face_image_url=face_image_url,
            gender=gender
        )

        generated_bytes, output_ext = download_image(generated_image_url)

        filename = f"fashion_photoshoot{output_ext}"
        s3_key, file_size = upload_to_s3(generated_bytes, filename, auth_token)

        logger.info("=" * 60)
        logger.info(f"✅ SUCCESS: Photoshoot image uploaded as {s3_key} ({file_size} bytes)")
        logger.info("=" * 60)

        return json.dumps(
            {
                "attachments": [{"s3_key": s3_key, "size": file_size, "filename": filename}],
                "summary": "The fashion photoshoot image has been successfully generated.",
            },
            indent=2,
        )

    except requests.exceptions.RequestException as e:
        return json.dumps({"error": f"Network error: {str(e)}"})
    except RuntimeError as e:
        logger.error(f"Error during AI processing: {e}")
        return json.dumps({"error": f"AI Processing error: {str(e)}"})
    except Exception as e:
        logger.exception("An unexpected error occurred during image processing")
        return json.dumps({"error": f"An unexpected error occurred: {str(e)}"})


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Starting AI Fashion Photoshoot MCP Server")
    logger.info("Using easel-ai/fashion-photoshoot model.")
    logger.info("=" * 60)

    mcp.run(transport="streamable-http")
