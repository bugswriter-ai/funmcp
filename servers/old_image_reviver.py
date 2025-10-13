"""
Old Image Reviver MCP Server with Bearer Token Authentication
Revives old images using Gemini, enhances them, and uploads to an S3 bucket.
"""
import json
import logging
from typing import Optional, Tuple

import google.generativeai as genai
import requests
from fastmcp import FastMCP
from PIL import UnidentifiedImageError

# --- Import from shared modules ---
from ..config import GEMINI_API_KEY, AI_HTTP_TIMEOUT
from ..helpers import (
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

gemini_model = None

def init_gemini():
    """Initializes the Gemini client."""
    global gemini_model
    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY not found. The image revival service will not work.")
        raise ValueError("GEMINI_API_KEY is not set in the configuration.")

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel('gemini-1.5-flash')
        logger.info("Gemini client initialized successfully with model 'gemini-1.5-flash'.")
    except Exception as e:
        logger.error(f"Failed to initialize Gemini client: {e}", exc_info=True)
        raise

# Initialize Gemini on script start
try:
    init_gemini()
except ValueError as e:
    logger.critical(e)


# --- Core Logic (Specific to this server) ---

def download_image(url: str) -> Tuple[bytes, str]:
    """Download image from URL, using a longer timeout for potentially large files."""
    logger.info(f"Downloading image from: {url}")
    response = requests.get(url, timeout=AI_HTTP_TIMEOUT) # Use long timeout
    response.raise_for_status()
    
    content_type = response.headers.get("Content-Type", "")
    ext = infer_extension_from_content_type(content_type)
    
    logger.info(f"Downloaded {len(response.content)} bytes (type: {content_type})")
    return response.content, ext


def revive_with_gemini(image_bytes: bytes, original_ext: str) -> Tuple[bytes, str]:
    """Uses Gemini to enhance, colorize, and restore an old image."""
    if not gemini_model:
        raise ConnectionError("Gemini model is not initialized. Check API key and initial setup.")

    logger.info("Calling Gemini API to revive image...")
    mime_type = EXT_TO_CONTENT_TYPE.get(original_ext.lower(), "image/jpeg")

    prompt = """
    You are an expert digital image restoration specialist. Your task is to revive the provided old image.
    Follow these instructions carefully:
    1.  **Colorize**: If the image is black and white or sepia, apply natural and historically plausible colors.
    2.  **Restore**: Remove scratches, dust, folds, and other physical damage.
    3.  **Enhance**: Improve sharpness, clarity, lighting, and contrast without creating an artificial look.
    4.  **Preserve**: Maintain the original composition, subjects, and character of the photo. Do not add or remove any elements.
    Return only the final, restored image. Do not return any text, explanation, or commentary.
    """

    image_part = {"mime_type": mime_type, "data": image_bytes}
    response = gemini_model.generate_content([prompt, image_part])

    try:
        image_part = response.parts[0]
        if 'image' not in image_part.mime_type:
             raise ValueError("API did not return an image part.")
        
        revived_bytes = image_part.blob.data
        output_mime_type = image_part.blob.mime_type
        output_ext = CONTENT_TYPE_MAPPING.get(output_mime_type, ".png")
        
        logger.info(f"Gemini processing successful. Received {len(revived_bytes)} bytes of type {output_mime_type}.")
        return revived_bytes, output_ext

    except (IndexError, AttributeError, ValueError) as e:
        logger.error(f"Gemini API did not return valid image data. Error: {e}")
        if hasattr(response, 'prompt_feedback'):
            logger.error(f"Prompt Feedback: {response.prompt_feedback}")
        raise Exception("Image revival failed: The AI model did not return a valid image.")


# --- MCP Server and Tool Definition ---

mcp = FastMCP(
    name="Old Image Reviver",
    dependencies=["requests", "Pillow", "google-generativeai", "python-dotenv", "starlette"]
)

@mcp.tool()
@require_auth
async def revive_old_image(file_url: str, auth_token: Optional[str] = None) -> str:
    """
    Downloads an image, uses an AI model to restore it, uploads it to S3,
    and returns JSON with the S3 key.

    Args:
        file_url: HTTP(S) URL of the old image to revive.
        auth_token: Bearer token (injected by decorator).
    """
    logger.info("=" * 60)
    logger.info("Tool 'revive_old_image' called for URL: %s", file_url)
    logger.info("=" * 60)
    
    if not (file_url.startswith("http://") or file_url.startswith("https://")):
        return json.dumps({"error": "file_url must start with http:// or https://", "attachments": []})
    
    try:
        image_bytes, original_ext = download_image(file_url)
        revived_bytes, output_ext = revive_with_gemini(image_bytes, original_ext)
        
        filename = f"revived_image{output_ext}"
        s3_key, file_size = upload_to_s3(revived_bytes, filename, auth_token)

        logger.info("=" * 60)
        logger.info(f"✅ SUCCESS: Revived image uploaded as {s3_key} ({file_size} bytes)")
        logger.info("=" * 60)
        
        return json.dumps({
            "attachments": [{"s3_key": s3_key, "size": file_size, "filename": filename}],
            "summary": "The old image has been successfully restored, colorized, and enhanced.",
        }, indent=2)
        
    except UnidentifiedImageError:
        return json.dumps({"error": "Downloaded file is not a valid image.", "attachments": []})
    except requests.exceptions.RequestException as e:
        return json.dumps({"error": f"Network error: {str(e)}", "attachments": []})
    except Exception as e:
        logger.exception("An unexpected error occurred during image revival")
        return json.dumps({"error": f"An unexpected error occurred: {str(e)}", "attachments": []})


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Starting Old Image Reviver MCP Server")
    if not gemini_model:
        logger.warning("WARNING: Gemini model failed to initialize. The tool will not be operational.")
    logger.info("Using shared helpers for auth and S3 uploads.")
    logger.info("=" * 60)
    
    mcp.run(transport="streamable-http")
