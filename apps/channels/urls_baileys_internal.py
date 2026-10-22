"""Gateway-only callback route; mounted outside public provider webhook routes."""
from django.urls import path

from apps.channels.views_baileys_internal import baileys_internal_event

urlpatterns = [path("", baileys_internal_event, name="baileys_internal_event")]
