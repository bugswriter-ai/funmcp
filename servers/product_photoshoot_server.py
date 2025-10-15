# product_photoshoot_server.py
"""
An MCP server that generates high-quality product photos using a given product image, scene description, and product placement instructions. Ideal for eCommerce product visualization and marketing content creation.
Generates high-quality product photo and uploads to S3 bucket
"""
from helpers import (
    require_auth,
    upload_to_s3,
    get_filename_from_url,
    infer_extension_from_content_type
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
    name="Create product advertisements banner with an example image of the product",
    dependencies=["requests", "fal_client", "starlette"]
)


class FalProductPhotoshoot:
    """
    A class to handle product photoshoot using fal.ai API
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the Fal Product Photoshoot client

        Args:
            api_key: Your fal.ai API key. If not provided, will use FAL_KEY env variable
        """
        if api_key:
            os.environ['FAL_KEY'] = api_key
        elif 'FAL_KEY' not in os.environ:
            raise ValueError(
                "API key must be provided or set as FAL_KEY environment variable")

    def generate_product_poster_async(
        self,
        product_image_url: str,
        scene_description: str,
        product_placement: str,
    ) -> str:
        """
    Submit an asynchronous product poster generation request.

    This method creates a realistic product poster by combining the given product image 
    with a scene description and specific product placement instructions. The request 
    is processed asynchronously, and a request ID is returned for job tracking.

    Args:
        product_image_url (str): URL of the product image to be placed in the generated scene.
        scene_description (str): Text description of the desired background or environment 
            (e.g., "a bright modern kitchen with natural light").
        product_placement (str): Instructions on how and where to position the product within 
            the scene (e.g., "place the glass on a wooden dining table at the center").

    Returns:
        str: A unique request ID that can be used to track the generation job status and 
        retrieve the final image once completed.
    """
        # Prepare input parameters
        input_data = {
            "product_image": product_image_url,
            "scene": scene_description,
            "product_placement": product_placement
        }
        # Submit request
        handler = fal_client.submit(
            "easel-ai/product-photoshoot",
            arguments=input_data,
        )

        request_id = handler.request_id
        print(f"Request submitted! Request ID: {request_id}")

        return request_id

    def get_status(self, request_id: str) -> Dict[str, Any]:
        """
        Check the status of an async request

        Args:
            request_id: The request ID returned from generate_product_poster_async

        Returns:
            Status information dictionary
        """
        status = fal_client.status(
            "easel-ai/product-photoshoot",
            request_id=request_id
        )

        return type(status).__name__

    def get_result(self, request_id: str) -> Dict[str, Any]:
        """
        Get the result of an async request

        Args:
            request_id: The request ID returned from generate_product_poster_async

        Returns:
            Result dictionary with generated photo banner URL
        """
        result = fal_client.result(
            "easel-ai/product-photoshoot", request_id=request_id
        )
        print("✓ Result retrieved!")

        return result

    def wait_for_completion(self, request_id: str, poll_interval: int = 2) -> Dict[str, Any]:
        """
        Poll for completion and return the result

        Args:
            request_id: The request ID returned from generate_product_poster_async 
            poll_interval: Seconds between status checks (default: 2)

        Returns:
            Result dictionary with generated banner image URL
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
            Tuple[str, str]: URL of the generated banner image, and content_type
        """
        try:
            return result['image']['url'], result["image"]['content_type']
        except (KeyError, IndexError) as e:
            raise ValueError(f"Could not extract image URL from result: {e}")


client = FalProductPhotoshoot()


@mcp.tool()
@require_auth
async def create_product_banner_photo(product_image_url: str, scene_description: str, product_placement_description: str, auth_token: str = None) -> str:
    """
    Generates a realistic product banner photo by placing the given product image into a 
    scene based on the provided description and placement instructions.

    This method uses an AI image generation model to create marketing-ready product visuals. 
    It combines the product image with a custom background scene and applies placement 
    guidance to position the product naturally within the generated environment.

    Args:
        product_image_url (str): URL of the product image to be placed into the generated banner.
        scene_description (str): Description of the desired background or setting 
            (e.g., "modern kitchen countertop with natural sunlight").
        product_placement_description (str): Instructions for how the product should be positioned 
            in the scene (e.g., "centered on the table with a slight shadow").
        auth_token (str, optional): Bearer token for authentication, if required by the API.

    Returns:
        str: A JSON string containing either the generated banner image URL or Data URI, 
        or an error message if the generation fails.
    """
    # if not image_model:
    # return json.dumps({"error": "Image generation model is not available."})

    print("\n" + "=" * 60)
    print("Asynchronous (submit and check later)")
    print("=" * 60)

    # Asynchronous approach - submit and get request ID
    request_id = client.generate_product_poster_async(
        product_image_url=product_image_url,
        scene_description=scene_description,
        product_placement=product_placement_description
    )

    # Wait for completion and get result
    result = client.wait_for_completion(request_id)
    output_url, mime_type = client.extract_output_url(result)
    print(f"\nGenereted image URL: {output_url} {mime_type}")

    result_response = requests.get(
        output_url)
    result_response.raise_for_status()
    image_data = result_response.content
    s3_key, file_size = upload_to_s3(
        image_data, f"{get_filename_from_url(product_image_url)}{infer_extension_from_content_type(mime_type)}", auth_token)

    logger.info("=" * 60)
    logger.info(f"✅ SUCCESS: {s3_key} ({file_size} bytes)")
    logger.info("=" * 60)

    return json.dumps({
        "attachments": [{
            "s3_key": s3_key,
            "size": file_size
        }],
        "summary": "Here is Generated Product Banner.",
    }, indent=2)


if __name__ == "__main__":
    logger.info("Starting Product Photo Banner Generator MCP Server")
    mcp.run(transport="streamable-http")
