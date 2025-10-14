#!/bin/sh

setsid uv run fastmcp run servers/old_image_reviver.py:mcp --transport http --port 9001 &
setsid uv run fastmcp run servers/grayscale_server.py:mcp --transport http --port 9002 &
setsid uv run fastmcp run servers/ai-upscale.py:mcp --transport http --port 9003 &
setsid uv run fastmcp run servers/audio_clone_server.py:mcp --transport http --port 9004 &
setsid uv run fastmcp run servers/product_photoshoot_server.py:mcp --transport http --port 9005 &
