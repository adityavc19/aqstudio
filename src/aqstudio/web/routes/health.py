"""System routes."""

from importlib.metadata import version

from fastapi import APIRouter

from aqstudio.schemas import HealthResponse

router = APIRouter()


@router.get("/health")
def health() -> HealthResponse:
    """Report liveness and the deployed version."""
    return HealthResponse(status="ok", version=version("aqstudio"))
