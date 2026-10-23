"""The flow list's "when does this run" sentences.

Written after the real thing broke and the suite did not notice: every flow in
the fixtures had zero triggers, so `describe_triggers` never reached the branch
that reads a trigger's config and the wrong field name survived until the page
was opened by hand. Every test here builds a flow that actually has triggers.
"""

import pytest

from apps.flows.models import Trigger, TriggerType
from apps.flows.services import create_flow
from apps.flows.triggers.phrasing import describe_trigger, describe_triggers, sentence_case


def _trigger(workspace, flow, trigger_type, config=None, *, enabled=True):
    return Trigger.objects.create(
        workspace=workspace,
        flow=flow,
        type=trigger_type,
        config_json=config or {},
        enabled=enabled,
    )



def test_sentence_case_uppercases_only_the_first_character():
    assert sentence_case("xYz") == "XYz"

@pytest.mark.django_db
class TestOneTrigger:

    def test_a_keyword_trigger_quotes_its_words(self, tenancy):
        flow = create_flow(workspace=tenancy.workspace, name="FAQ")
        trigger = _trigger(
            tenancy.workspace,
            flow,
            TriggerType.KEYWORD,
            {"keywords": [{"text": "hours", "mode": "any_word"}, {"text": "returns", "mode": "any_word"}]},
        )

        summary = describe_trigger(trigger)
        assert "“hours”" in summary
        assert "“returns”" in summary

    def test_a_comment_trigger_reads_its_own_config_key(self, tenancy):
        """A comment trigger stores a plain list under `include_keywords` while
        a keyword trigger stores objects under `keywords`. Both are "words that
        start this flow" to a reader."""
        flow = create_flow(workspace=tenancy.workspace, name="Price")
        trigger = _trigger(tenancy.workspace, flow, TriggerType.COMMENT, {"include_keywords": ["price"]})

        assert "“price”" in describe_trigger(trigger)

    def test_a_long_keyword_list_counts_instead_of_listing(self, tenancy):
        flow = create_flow(workspace=tenancy.workspace, name="Everything")
        trigger = _trigger(
            tenancy.workspace,
            flow,
            TriggerType.KEYWORD,
            {"keywords": [{"text": word} for word in ["a", "b", "c", "d", "e"]]},
        )

        summary = describe_trigger(trigger)
        assert "“a”" in summary
        assert "4" in summary
        assert "“b”" not in summary



@pytest.mark.django_db
class TestTheListPageRendersIt:
    def test_a_flow_with_a_trigger_renders_its_sentence(self, tenancy, client_for):
        """The regression test for the original bug: the field name was wrong,
        every unit above would have passed against a mock, and only rendering
        the real page with a real trigger caught it."""
        flow = create_flow(workspace=tenancy.workspace, name="Price replies")
        _trigger(tenancy.workspace, flow, TriggerType.COMMENT, {"include_keywords": ["price"]})

        body = (
            client_for(tenancy.owner)
            .get(
                f"/w/{tenancy.workspace.pk}/flows/",
            )
            .content.decode()
        )

        assert "“price”" in body
