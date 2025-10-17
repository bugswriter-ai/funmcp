# test_mcp_servers/fake_progress.py

import asyncio
import json
import logging
from typing import Annotated, Optional
from pydantic import Field

from fastmcp import FastMCP, Context
from fastmcp.server.dependencies import get_http_request
from starlette.requests import Request

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- 1. Define the FastMCP Server ---
mcp = FastMCP(
    name="MockProcessingService",
    instructions="This server provides a tool that simulates a long-running process with progress updates."
)

# --- 2. Define a Mock Tool with Progress Reporting ---
@mcp.tool(
    name="process_long_task",
    description="Simulates a multi-step task, reports progress, and returns a mock attachment.",
    tags={"testing", "simulation", "progress"},
)
# --- THIS IS THE FIX: The argument order is now correct ---
async def process_long_task(
    input_file_url: Annotated[str, Field(description="A mock URL of a file to process.")],
    ctx: Context, # The required 'ctx' argument now comes before any optional arguments.
    iterations: Annotated[int, Field(description="The number of simulated steps to perform.", default=5)]
) -> str:
    """
    This function simulates a long process by sleeping and reporting progress.
    It does not perform any real computation.
    """
    logger.info("=" * 60)
    logger.info(f"Tool 'process_long_task' called with URL: {input_file_url}")
    
    try:
        req: Optional[Request] = get_http_request()
        if req:
            auth_header = req.headers.get("Authorization", "Not provided")
            logger.info(f"Authorization header received: {auth_header[:20]}...")
    except Exception:
        logger.warning("Could not get HTTP request context (might be running in stdio).")

    logger.info(f"Simulating {iterations} processing steps...")
    logger.info("=" * 60)

    total_steps = max(1, iterations)

    try:
        await ctx.report_progress(progress=0, total=100, message="Initializing processing pipeline...")
        await asyncio.sleep(1)

        for i in range(total_steps):
            step = i + 1
            progress_percent = (step / total_steps) * 90
            
            await ctx.report_progress(
                progress=progress_percent,
                total=100,
                message=f"Step {step}/{total_steps}: Analyzing data chunk..."
            )
            logger.info(f"Reported progress: {progress_percent:.0f}%")
            await asyncio.sleep(1.5)

        await ctx.report_progress(progress=100, total=100, message="Processing complete. Generating report.")
        await asyncio.sleep(1)

        fake_attachment = {
            "s3_key": f"mock/processed/result_{iterations}_steps.zip",
            "size": 123456
        }
        
        logger.info("✅ Simulation successful. Returning mock attachment.")
        return json.dumps({
            "attachments": [fake_attachment],
            "summary": f"Successfully processed '{input_file_url}' in {iterations} steps."
        })

    except Exception as e:
        logger.error(f"An unexpected error occurred during simulation: {e}", exc_info=True)
        await ctx.error(f"Simulation failed with error: {e}")
        return json.dumps({ "error": f"An unexpected error occurred: {str(e)}" })


# --- 3. Run the Server ---
if __name__ == "__main__":
    port = 8002
    print("=" * 60)
    print(f"🚀 Starting Mock Progress MCP Server")
    print(f"   Listening on: http://127.0.0.1:{port}/mcp")
    print("   This server simulates a long task to test progress reporting.")
    print("=" * 60)
    
    mcp.run(transport="streamable-http", port=port)