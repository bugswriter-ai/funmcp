# grayscale_server.py
"""
Grayscale Image Converter MCP Server with Bearer Token Authentication
Converts images to grayscale and uploads to S3 bucket
"""
import json
import logging
from io import BytesIO
from typing import Optional, Tuple

import requests
from fastmcp import FastMCP
from PIL import Image, UnidentifiedImageError

# Import common helpers
from helpers import (
    require_auth, 
    upload_to_s3, 
    CONTENT_TYPE_MAPPING, 
    HTTP_TIMEOUT
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# File extension to Pillow format mapping (specific to this server)
PILLOW_FORMAT_MAPPING = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".bmp": "BMP",
    ".tif": "TIFF",
    ".tiff": "TIFF",
    ".gif": "GIF",
}


def infer_extension_from_content_type(content_type: Optional[str]) -> str:
    """
    Infer file extension from HTTP Content-Type header.
    
    Args:
        content_type: The Content-Type header value
        
    Returns:
        str: File extension (e.g., '.jpg')
    """
    if not content_type:
        return ".jpg"
    
    ct = content_type.lower().split(";")[0].strip()
    return CONTENT_TYPE_MAPPING.get(ct, ".jpg")


def get_pillow_format(ext: str) -> str:
    """
    Convert file extension to Pillow format string.
    
    Args:
        ext: File extension (e.g., '.jpg')
        
    Returns:
        str: Pillow format string (e.g., 'JPEG')
    """
    return PILLOW_FORMAT_MAPPING.get(ext.lower(), "JPEG")


def download_image(url: str) -> Tuple[bytes, str]:
    """
    Download image from URL.
    
    Args:
        url: Image URL to download
        
    Returns:
        tuple: (image_bytes, file_extension)
        
    Raises:
        requests.exceptions.RequestException: If download fails
    """
    logger.info(f"Downloading image from: {url}")
    response = requests.get(url, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    
    content_type = response.headers.get("Content-Type", "")
    ext = infer_extension_from_content_type(content_type)
    
    logger.info(f"Downloaded {len(response.content)} bytes (type: {content_type})")
    return response.content, ext


def convert_to_grayscale(image_bytes: bytes, output_ext: str) -> bytes:
    """
    Convert image to grayscale.
    
    Args:
        image_bytes: Original image bytes
        output_ext: Desired output file extension
        
    Returns:
        bytes: Grayscale image bytes
        
    Raises:
        UnidentifiedImageError: If image cannot be decoded
    """
    logger.info("Converting image to grayscale...")
    
    with Image.open(BytesIO(image_bytes)) as im:
        gray = im.convert("L")
        
        output_buffer = BytesIO()
        save_format = get_pillow_format(output_ext)
        gray.save(output_buffer, format=save_format, optimize=True)
        output_buffer.seek(0)
        
        logger.info(f"Conversion complete (format: {save_format})")
        return output_buffer.getvalue()


# Initialize MCP server
mcp = FastMCP(
    name="Grayscale Image Converter",
    dependencies=["requests", "Pillow", "starlette"]
)


@mcp.tool()
@require_auth
async def grayscale_image(file_url: str, auth_token: Optional[str] = None) -> str:
    """
    Downloads an image from a URL, converts it to grayscale, uploads it to S3,
    and returns JSON with the S3 key for the uploaded image.

    Args:
        file_url: HTTP(S) URL of the image to convert
        auth_token: Bearer token (injected by decorator)
        
    Returns:
        str: JSON string with attachments list or error message
    """
    logger.info("=" * 60)
    logger.info("Tool 'grayscale_image' called")
    logger.info(f"file_url: {file_url}")
    logger.info(f"Authenticated with token: {auth_token[:10] if auth_token else 'None'}...")
    logger.info("=" * 60)
    
    if not (file_url.startswith("http://") or file_url.startswith("https://")):
        logger.error("Invalid URL format")
        return json.dumps({
            "error": "file_url must start with http:// or https://",
            "attachments": []
        })
    
    try:
        image_bytes, ext = download_image(file_url)
        grayscale_bytes = convert_to_grayscale(image_bytes, ext)
        
        # Use the helper function for uploading
        s3_key, file_size = upload_to_s3(grayscale_bytes, f"grayscale{ext}", auth_token)

        logger.info("=" * 60)
        logger.info(f"✅ SUCCESS: {s3_key} ({file_size} bytes)")
        logger.info("=" * 60)
        
        return json.dumps({
            "attachments": [{"s3_key": s3_key, "size": file_size}],
            "summary": "Image converted to grayscale and uploaded to S3 successfully.",
        }, indent=2)
        
    except UnidentifiedImageError:
        logger.error("Invalid image file")
        return json.dumps({"error": "Downloaded file is not a valid image.", "attachments": []})
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error: {e}")
        return json.dumps({"error": f"Network error: {str(e)}", "attachments": []})
        
    except Exception as e:
        logger.exception("Unexpected error")
        return json.dumps({"error": f"Unexpected error: {str(e)}", "attachments": []})


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Starting Grayscale Image Converter MCP Server")
    logger.info("Using common helpers for authentication and S3 uploads.")
    logger.info("=" * 60)
    
    mcp.run(transport="streamable-http")
