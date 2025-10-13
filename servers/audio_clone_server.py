# audio_clone_server.py
"""
Clone voice of any person and speak anything in their voice using zonos' voice cloning.
Generates clone audio and uploads to S3 bucket
"""
from helpers import (
    require_auth,
    upload_to_s3,
    get_filename_from_url
)
import json
import logging
from io import BytesIO
from typing import Optional, Tuple

import requests
from fastmcp import FastMCP
from PIL import Image, UnidentifiedImageError
import fal_client
import os
import time
from typing import Optional, Dict, Any, Tuple
# Import common helpers

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Initialize MCP server
mcp = FastMCP(
    name="Clone voice of any person and speak anything in their voice",
    dependencies=["requests", "fal_client", "starlette"]
)


class FalAudioClone:
    """
    A class to handle photo restoration using fal.ai API
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the Fal Photo Restoration client

        Args:
            api_key: Your fal.ai API key. If not provided, will use FAL_KEY env variable
        """
        if api_key:
            os.environ['FAL_KEY'] = api_key
        elif 'FAL_KEY' not in os.environ:
            raise ValueError(
                "API key must be provided or set as FAL_KEY environment variable")

    def clone_audio_async(
        self,
        audio_url: str,
        prompt: str,
    ) -> str:
        """
        Submit a photo restoration request asynchronously

        Args:
            image_url: URL of the old or damaged photo to restore
            enhance_resolution: Whether to enhance the resolution (default: True)
            fix_colors: Whether to fix colors (default: True)
            remove_scratches: Whether to remove scratches (default: True)
            aspect_ratio: Aspect ratio for 4K output (e.g., "4:3", "16:9", "1:1", "9:16", "3:4")
            webhook_url: Optional webhook URL to receive results

        Returns:
            Request ID for tracking the job
        """
        # Prepare input parameters
        input_data = {
            "reference_audio_url": audio_url,
            "prompt": prompt,
        }
        # Submit request
        handler = fal_client.submit(
            "fal-ai/zonos",
            arguments=input_data,
        )

        request_id = handler.request_id
        print(f"Request submitted! Request ID: {request_id}")

        return request_id

    def get_status(self, request_id: str) -> Dict[str, Any]:
        """
        Check the status of an async request

        Args:
            request_id: The request ID returned from restore_photo_async

        Returns:
            Status information dictionary
        """
        status = fal_client.status(
            "fal-ai/zonos",
            request_id=request_id
        )

        return type(status).__name__

    def get_result(self, request_id: str) -> Dict[str, Any]:
        """
        Get the result of an async request

        Args:
            request_id: The request ID returned from restore_photo_async

        Returns:
            Result dictionary with restored image URL
        """
        result = fal_client.result(
            "fal-ai/zonos", request_id=request_id
        )
        print("✓ Result retrieved!")

        return result

    def wait_for_completion(self, request_id: str, poll_interval: int = 2) -> Dict[str, Any]:
        """
        Poll for completion and return the result

        Args:
            request_id: The request ID returned from restore_photo_async
            poll_interval: Seconds between status checks (default: 2)

        Returns:
            Result dictionary with restored image URL
        """
        print(f"Waiting for request {request_id} to complete...")

        while True:
            status = self.get_status(request_id)
            if status == 'Completed':
                return self.get_result(request_id)
            elif status in ['InProgress', 'Queued']:
                time.sleep(poll_interval)
            else:
                raise Exception(f"Request : {status}")

    @staticmethod
    def _log_queue_update(update):
        """Callback to log queue updates"""
        if isinstance(update, dict):
            status = update.get('status', 'UNKNOWN')
            print(f"Status: {status}")

            # Print logs if available
            if 'logs' in update:
                for log in update['logs']:
                    if isinstance(log, dict) and 'message' in log:
                        print(f"  Log: {log['message']}")

    @staticmethod
    def extract_output_url(result: Dict[str, Any]) -> Tuple[str, str]:
        """
        Extract the restored image URL from the result

        Args:
            result: Result dictionary from the API

        Returns:
            URL of the restored image
        """
        try:
            return result['audio']['url'], result["audio"]['content_type']
        except (KeyError, IndexError) as e:
            raise ValueError(f"Could not extract image URL from result: {e}")


client = FalAudioClone()


@mcp.tool()
@require_auth
async def clone_audio(audio_url: str, prompt: str, auth_token: str = None) -> str:
    """
    Downloads an image from a URL, and uses Nano Banana (Gemini) with prompt engineering to restore it.

    Args:
        image_url: The URL of the old or torn image to be restored.
        user_prompt: An optional user-provided description of the damage or desired outcome.
        auth_token: The bearer token for authentication (injected by the decorator).

    Returns:
        A JSON string containing the Data URI of the restored image or an error message.
    """
    # if not image_model:
    # return json.dumps({"error": "Image generation model is not available."})

    print("\n" + "=" * 60)
    print("Asynchronous (submit and check later)")
    print(f'Prompt : {prompt}')
    print("=" * 60)

    # Asynchronous approach - submit and get request ID
    request_id = client.clone_audio_async(
        audio_url=audio_url,
        prompt=prompt
    )

    # Wait for completion and get result
    result = client.wait_for_completion(request_id)
    output_url, mime_type = client.extract_output_url(result)
    print(f"\nGenereted Audio URL: {output_url} {mime_type}")

    result_response = requests.get(
        output_url)
    result_response.raise_for_status()
    image_data = result_response.content
    s3_key, file_size = upload_to_s3(
        image_data, f"{get_filename_from_url(audio_url)}.wav", auth_token)

    logger.info("=" * 60)
    logger.info(f"✅ SUCCESS: {s3_key} ({file_size} bytes)")
    logger.info("=" * 60)

    return json.dumps({
        "attachments": [{
            "s3_key": s3_key,
            "size": file_size
        }],
        "summary": "Here is Generated Audio.",
    }, indent=2)


if __name__ == "__main__":
    logger.info("Starting Revive-AI MCP Server")
    mcp.run(transport="streamable-http")
