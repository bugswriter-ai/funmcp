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
    A class to handle clone audio using fal.ai API
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the Fal Audio Clone client

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
    Submit an asynchronous audio cloning request.

    This method generates a new audio clip that mimics the voice and style of the 
    provided sample audio while speaking the given prompt as the transcript. The 
    request is processed asynchronously, and a unique request ID is returned to 
    track the generation job.

    Args:
        sample_audio_url (str): URL of the reference audio sample whose voice characteristics 
            (tone, accent, pitch, style) will be cloned.
        prompt (str): Text content that should be spoken in the generated audio, using 
            the cloned voice from the sample.

    Returns:
        str: A unique request ID that can be used to check the status of the job and 
        retrieve the generated audio once processing is complete.
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
            request_id: The request ID returned from clone_audio_async

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
            request_id: The request ID returned from clone_audio_async 

        Returns:
            Result dictionary with generated audio URL
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
            Result dictionary with generated audio URL
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
        Extract the generated audio URL from the result

        Args:
            result: Result dictionary from the API

        Returns:
            Tuple[str, str] : URL of the generated audio, and content_type 
        """
        try:
            return result['audio']['url'], result["audio"]['content_type']
        except (KeyError, IndexError) as e:
            raise ValueError(f"Could not extract audio URL from result: {e}")


client = FalAudioClone()


@mcp.tool()
@require_auth
async def clone_audio(audio_url: str, prompt: str, auth_token: str = None) -> str:
    """
    Generates a new audio clip by cloning the voice from a given sample audio and speaking the provided prompt.

    This method downloads the reference audio from the given URL, analyzes its voice characteristics 
    (tone, pitch, accent, style), and then uses them to generate a new audio clip where the prompt 
    text is spoken in the cloned voice.

    Args:
        audio_url (str): URL of the reference audio sample whose voice will be cloned.
        prompt (str): Text content to be spoken in the generated audio using the cloned voice.
        auth_token (str, optional): Bearer token for authentication, if required by the API.

    Returns:
        str: A JSON string containing either the generated audio URL or Data URI, or an error message 
        if the cloning process fails.
    """
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
    logger.info("Starting Audio Clone MCP Server")
    mcp.run(transport="streamable-http")
