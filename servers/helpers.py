# helpers.py
"""
Common helper functions for MCP servers, including authentication and S3 upload.
"""
import os
import json
import logging
from functools import wraps
from io import BytesIO
from typing import Optional, Tuple
from urllib.parse import urlparse, unquote

import requests
from starlette.requests import Request
from fastmcp.server.dependencies import get_http_request
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

# --- Shared Constants ---
API_BASE_URL = os.getenv("API_BASE_URL")
HTTP_TIMEOUT = (15, 60)  # (connect, read) timeouts in seconds

# --- Shared Mappings ---

# Content type to file extension mapping
CONTENT_TYPE_MAPPING = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",  # common but non-standard
    "image/png": ".png",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
    "image/gif": ".gif",
    # 3D models
    "model/gltf-binary": ".glb",
    "model/gltf+json": ".gltf",
    "model/obj": ".obj",
    "model/stl": ".stl",
    # Video (standardized)
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/ogg": ".ogv",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
    "video/x-msvideo": ".avi",
    "video/mpeg": ".mpg",
    "video/x-flv": ".flv",
    "video/x-ms-wmv": ".wmv",
    # Audio (common)
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/ogg": ".ogg",
    "audio/webm": ".webm",
    "audio/flac": ".flac",
    "audio/aac": ".aac",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
}

# File extension to content type mapping for S3 uploads
EXT_TO_CONTENT_TYPE = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".gif": "image/gif",
    # 3D models
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".obj": "model/obj",
    ".stl": "model/stl",
    # Video (standardized)
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".ogv": "video/ogg",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".mpg": "video/mpeg",
    ".flv": "video/x-flv",
    ".wmv": "video/x-ms-wmv",
    # Audio (common)
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
    ".m4a": "audio/mp4",
}


# --- Authentication ---

def validate_token() -> Tuple[bool, Optional[str], str]:
    """
    Validate authorization token from request context.
    
    Returns:
        tuple: (is_valid, token, error_message)
    """
    try:
        req: Request = get_http_request()
        auth_header = req.headers.get("Authorization")

        if not auth_header:
            return False, None, "Missing Authorization header"
        
        token = auth_header.strip()
        if token.startswith("Bearer "):
            token = token.split("Bearer ", 1)[1].strip()
        
        if not token:
            logger.warning("Empty token provided")
            return False, None, "Empty authorization token"
        
        logger.info(f"Token validated successfully: {token[:10]}...")
        return True, token, ""
        
    except Exception as e:
        logger.error(f"Authentication error: {e}", exc_info=True)
        return False, None, f"Authentication error: {str(e)}"


def require_auth(func):
    """
    Decorator to require bearer token authentication.
    Injects the validated token into the function kwargs.
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        is_valid, token, error_msg = validate_token()
        
        if not is_valid:
            logger.warning(f"Authentication failed: {error_msg}")
            return json.dumps({
                "error": f"Authentication failed: {error_msg}",
                "attachments": []
            })
        
        kwargs["auth_token"] = token
        return await func(*args, **kwargs)
    
    return wrapper


# --- File Uploading ---

def upload_to_s3(file_bytes: bytes, filename: str, auth_token: str) -> Tuple[str, int]:
    """
    Upload a file to S3 bucket using the /upload API endpoint.

    Args:
        file_bytes: File data to upload
        filename: Filename to use for upload
        auth_token: Bearer token for authentication

    Returns:
        tuple: (s3_key, file_size_bytes)

    Raises:
        requests.exceptions.RequestException: If upload fails
    """
    file_size = len(file_bytes)
    logger.info(f"Uploading {file_size} bytes to S3 via API as '{filename}'...")

    ext = filename[filename.rfind('.'):].lower() if '.' in filename else '.jpg'
    content_type = EXT_TO_CONTENT_TYPE.get(ext, "application/octet-stream")

    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }

    upload_request_data = {
        "filename": filename,
        "content_type": content_type
    }

    logger.info(f"Requesting presigned URL for {filename} (type: {content_type})")
    response = requests.post(
        f"{API_BASE_URL}/files/upload",
        headers=headers,
        json=upload_request_data,
        timeout=HTTP_TIMEOUT
    )
    response.raise_for_status()
    presigned_data = response.json()

    logger.info(f"Got presigned URL: {presigned_data.get('url', 'N/A')}")

    files = {"file": (filename, BytesIO(file_bytes), content_type)}
    form_data = presigned_data.get("fields", {})

    logger.info(f"Uploading to S3 with {len(form_data)} form fields")
    s3_response = requests.post(
        presigned_data["url"],
        data=form_data,
        files=files,
        timeout=HTTP_TIMEOUT
    )
    s3_response.raise_for_status()

    s3_key = presigned_data["file_id"]
    logger.info(f"Upload successful: {s3_key} ({file_size} bytes)")

    return s3_key, file_size


def infer_extension_from_content_type(content_type: Optional[str]) -> str:
    """
    Infer file extension from HTTP Content-Type header.
    Defaults to '.jpg' if type is unknown or missing.

    Args:
        content_type: The Content-Type header value.

    Returns:
        str: File extension (e.g., '.jpg').
    """
    if not content_type:
        return ".jpg"

    ct = content_type.lower().split(";")[0].strip()
    return CONTENT_TYPE_MAPPING.get(ct, ".jpg")


def get_filename_from_url(url: str) -> str:
    """
    Extracts the filename from a given URL.
    Handles URLs with query strings or URL-encoded characters.
    """
    parsed = urlparse(url)
    path = parsed.path
    filename = unquote(os.path.basename(path))  # e.g. "photo (1).jpg"
    # split into ("photo (1)", ".jpg")
    name, _ = os.path.splitext(filename)
    return name
