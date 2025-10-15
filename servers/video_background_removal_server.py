"""
Bria Video Background Removal MCP Server.
Uses fal-ai/bria/video/background-removal to remove background from a video
and uploads the resulting video to S3.
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


def download_file(url: str) -> Tuple[bytes, str]:
    logger.info(f"Downloading result from: {url}")
    response = requests.get(url, timeout=AI_HTTP_TIMEOUT)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "application/octet-stream")
    # naive ext inference for common video types
    ext = ".webm" if "webm" in content_type else ".mp4" if "mp4" in content_type else ".bin"
    return response.content, ext


def call_bria_video_bg(arguments: Dict[str, Any]) -> Dict[str, Any]:
    result = fal_client.subscribe(
        "bria/video/background-removal",
        arguments=arguments,
        with_logs=True,
        on_queue_update=on_queue_update,
    )
    logger.info(f"Fal AI result: {json.dumps(result, indent=2)}")
    return result


def extract_video_url(result: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    # Expect result like {"video": {"url": ..., "content_type": ...}}
    video = result.get("video")
    if isinstance(video, dict) and isinstance(video.get("url"), str):
        return video["url"], video.get("content_type")
    # Some variants may return top-level url
    if isinstance(result.get("url"), str):
        return result["url"], None
    raise RuntimeError(f"Unexpected result format for video output: {result}")


mcp = FastMCP(
    name="Bria Video Background Removal",
    dependencies=["requests", "fal-client", "python-dotenv", "starlette"]
)


@mcp.tool()
@require_auth
async def bria_video_background_removal(
    video_url: str,
    background_color: str = "",
    output_container_and_codec: str = "",
    auth_token: Optional[str] = None,
) -> str:
    """
    Remove background from a video using fal-ai Bria model.
    Optional parameters map to the model schema when provided.
    Args:
        video_url (str): URL of the input video.
        background_color (str): Background color for the video.


    Returns:
        str: JSON string containing the S3 key of the generated video.
    """
    if not video_url or not (video_url.startswith("http://") or video_url.startswith("https://")):
        return json.dumps({"error": "video_url must be a valid HTTP(S) URL"})

    args: Dict[str, Any] = {"video_url": video_url}
    if background_color:
        args["background_color"] = background_color
    if output_container_and_codec:
        args["output_container_and_codec"] = output_container_and_codec

    try:
        result = call_bria_video_bg(args)
        out_url, _ct = extract_video_url(result)
        data, ext = download_file(out_url)
        filename = f"bria_video_bg_removed{ext}"
        s3_key, file_size = upload_to_s3(data, filename, auth_token)
        return json.dumps({
            "attachments": [{"s3_key": s3_key, "size": file_size, "filename": filename}],
            "source_video_url": out_url,
            "summary": "Background removed from video successfully.",
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
    logger.info("Starting Bria Video Background Removal MCP Server")
    mcp.run(transport="streamable-http")


