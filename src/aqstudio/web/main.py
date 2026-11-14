"""ASGI entry point: `uvicorn aqstudio.web.main:app`."""

from aqstudio.web.app import create_app

app = create_app()
