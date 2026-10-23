"""The inbox as the prototype draws it (HANDOFF §3, Inbox).

What the redesign changed that is more than paint: the list's compact
timestamps and "You:" previews, the status bar's window countdown, the day
dividers, and the contact panel that now carries the thread's labels, the last
automation run and the panel toggle.
"""

from typing import Any

import pytest

from apps.inbox import services
from apps.messaging.models import Conversation

@pytest.mark.django_db
class TestTheList:
    def test_a_teammates_last_message_is_in_the_row(self, agent_client: Any, url_for: Any, outbound: Any) -> None:
        outbound("Sent the invoice again.")

        body = agent_client.get(url_for("rows")).content.decode()

        assert "Sent the invoice again." in body

    def test_a_contacts_last_message_is_in_the_row(self, agent_client: Any, url_for: Any, inbound: Any) -> None:
        inbound("How much is the large size?")

        body = agent_client.get(url_for("rows")).content.decode()

        assert "How much is the large size?" in body



@pytest.mark.django_db
class TestThePanel:
    def test_the_threads_labels_live_in_the_panel(
        self, tenancy: Any, agent_client: Any, url_for: Any, conversation: Conversation
    ) -> None:
        label = services.create_label(tenancy.workspace, name="Refunds", color="#3B82F6")
        services.create_label(tenancy.workspace, name="Billing", color="#22C55E")
        services.apply_label(conversation, label, by=None)

        panel = agent_client.get(url_for("sidebar", conversation_id=conversation.pk)).content.decode()

        assert "Refunds" in panel
        assert 'name="label" value=' in panel, "the + Add menu offers the labels not yet on the thread"
        assert "Billing" in panel

    def test_the_panel_renders_without_javascript(
        self, agent_client: Any, url_for: Any, conversation: Conversation
    ) -> None:
        """Opened and closed by class, not hidden by x-cloak until Alpine runs."""
        page = agent_client.get(url_for("thread", conversation_id=conversation.pk)).content.decode()
        aside = page[page.index('<aside id="inbox-sidebar"') :]
        aside = aside[: aside.index(">")]

        assert "x-cloak" not in aside
        assert "x-show" not in aside

