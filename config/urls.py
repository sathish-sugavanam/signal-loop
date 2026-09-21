"""URL routing for Signal Loop."""

from django.http import JsonResponse
from django.urls import path


def health(_: object) -> JsonResponse:
    """Return the service availability without requiring database access."""
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("health/", health, name="health"),
]
