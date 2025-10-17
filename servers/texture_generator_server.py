"""
MCP server for AI texture generation.
"""

import asyncio
import base64
from typing import Optional

import fal_client
from fastmcp import FastMCP, ToolContext
from pydantic import BaseModel

from .config import AI_HTTP_CONNECT_TIMEOUT, AI_HTTP_READ_TIMEOUT
from .helpers import require_auth, upload_to_s3

mcp = FastMCP(
    title="AI Texture Generation",
    description="Generates seamless textures from text prompts.",
    version="0.1.0",
)


class GenerateTextureParams(BaseModel):
    prompt: str
    style: Optional[str] = "seamless"
    resolution: Optional[str] = "1024x1024"
    seed: Optional[int] = None


@mcp.tool(params_model=GenerateTextureParams)
@require_auth
async def generate_texture(
    ctx: ToolContext,
    prompt: str,
    style: Optional[str] = "seamless",
    resolution: Optional[str] = "1024x1024",
    seed: Optional[int] = None,
    auth_token: Optional[str] = None,
) -> str:
    """
    Generates a texture image based on a text prompt.

    Args:
        prompt: A detailed description of the texture to generate.
        style: The style of the texture. Currently only "seamless" is supported.
        resolution: The resolution of the texture. e.g. "1024x1024".
        seed: A seed for the generation process for reproducibility.
        auth_token: The authentication token (injected by require_auth).

    Returns:
        A JSON string with the S3 key of the uploaded texture.
    """
    if style != "seamless":
        return '{"error": "Only seamless style is currently supported."}'

    try:
        width, height = map(int, resolution.split("x"))
    except ValueError:
        return '{"error": "Invalid resolution format. Expected format like 512x512."}'

    # Construct a prompt that encourages seamless tiling
    full_prompt = f"a seamless texture of {prompt}, tileable, PBR material"

    ctx.send_progress(f"Generating {resolution} seamless texture for: {prompt}")

    try:
        # Using a general-purpose model and prompting for seamlessness
        result = await asyncio.to_thread(
            fal_client.run,
            "fal-ai/fast-sdxl",
            arguments={
                "prompt": full_prompt,
                "width": width,
                "height": height,
                "seed": seed,
            },
            timeout=AI_HTTP_READ_TIMEOUT,
        )
        image_bytes = base64.b64decode(result["images"][0]["content"])
        content_type = "image/png"
        filename = f"texture_{seed or ''}.png"

    except Exception as e:
        return f'{{"error": "Failed to generate texture: {e}"}}'

    ctx.send_progress("Uploading generated texture...")

    return await upload_to_s3(image_bytes, content_type, filename, auth_token)
