import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction

from apps.ai_agents.models import (
    AgentStatus,
    AIAgent,
    AIProposalDraft,
    AIProviderConnection,
    AIToolGrant,
    ApprovalPolicy,
    ProviderKind,
    ProviderStatus,
    ToolName,
)
from apps.contacts.models import Contact

pytestmark = pytest.mark.django_db


class TestAgentPersistence:
    def test_agents_and_provider_connections_are_disabled_by_default(self, tenancy):
        provider = AIProviderConnection.objects.create(
            workspace=tenancy.workspace, name="Primary", provider=ProviderKind.OPENAI, model="configured-by-admin"
        )
        agent = AIAgent.objects.create(workspace=tenancy.workspace, name="Sales", provider_connection=provider)

        assert settings.AI_AGENTS_ENABLED is False
        assert tenancy.workspace.ai_agents_enabled is False
        assert provider.status == ProviderStatus.DISABLED
        assert agent.status == AgentStatus.DRAFT

    def test_provider_credentials_are_encrypted_at_rest(self, tenancy):
        secret = "sk-live-secret-for-storage-test"
        provider = AIProviderConnection.objects.create(
            workspace=tenancy.workspace,
            name="OpenAI",
            provider=ProviderKind.OPENAI,
            model="gpt-configured-by-admin",
            credentials={"api_key": secret},
        )

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT credentials FROM ai_agents_aiproviderconnection WHERE id = %s", [str(provider.pk)]
            )
            ciphertext = cursor.fetchone()[0]

        assert secret not in ciphertext
        assert AIProviderConnection.objects.for_workspace(tenancy.workspace).get(pk=provider.pk).credentials == {
            "api_key": secret
        }

    def test_tool_grants_deny_by_default_and_are_unique_per_agent(self, tenancy):
        agent = AIAgent.objects.create(workspace=tenancy.workspace, name="Support")
        grant = AIToolGrant.objects.create(agent=agent, workspace=tenancy.workspace, tool_name=ToolName.PROPOSAL_DRAFT)

        assert grant.enabled is False
        assert grant.approval_policy == ApprovalPolicy.DENY
        with pytest.raises(IntegrityError), transaction.atomic():
            AIToolGrant.objects.create(agent=agent, workspace=tenancy.workspace, tool_name=ToolName.PROPOSAL_DRAFT)

    def test_provider_from_another_workspace_is_rejected(self, tenancy, other_tenancy):
        provider = AIProviderConnection.objects.create(
            workspace=other_tenancy.workspace, name="Private", provider=ProviderKind.GEMINI, model="configured"
        )
        agent = AIAgent(workspace=tenancy.workspace, name="Sales", provider_connection=provider)

        with pytest.raises(ValidationError, match="mesmo espaço de trabalho"):
            agent.save()

    def test_workspace_managers_cannot_list_another_tenants_rows(self, tenancy, other_tenancy):
        AIAgent.objects.create(workspace=other_tenancy.workspace, name="Private agent")

        assert list(AIAgent.objects.for_workspace(tenancy.workspace).values_list("name", flat=True)) == []
        with pytest.raises(RuntimeError, match="without a workspace scope"):
            AIAgent.objects.count()

    def test_erasing_a_contact_removes_its_proposal_draft(self, tenancy):
        contact = Contact.objects.create(workspace=tenancy.workspace, first_name="Customer")
        proposal = AIProposalDraft.objects.create(
            workspace=tenancy.workspace,
            contact=contact,
            items=[{"sku": "web-five-pages", "price": "1500.00"}],
            total="1500.00",
            currency="BRL",
        )

        contact.delete()

        assert not AIProposalDraft.objects.for_workspace(tenancy.workspace).filter(pk=proposal.pk).exists()
