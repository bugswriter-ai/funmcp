#!/bin/sh

setsid uv run fastmcp run servers/old_image_reviver.py:mcp --transport http --port 9001 &
setsid uv run fastmcp run servers/grayscale_server.py:mcp --transport http --port 9002 &
