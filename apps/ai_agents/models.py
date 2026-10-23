"""Tenant-scoped persistence for AI agents (PR-01 of the implementation RFC).

Execution is intentionally absent in this phase. Every opt-in is false, and
provider credentials use the existing authenticated-encryption field.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from apps.common.encryption import EncryptedJSONField
from apps.common.scoping import WorkspaceScopedModel


class AgentKind(models.TextChoices):
    SALES = "sales", "Vendas"
    SUPPORT = "support", "Atendimento"
    GENERAL = "general", "Geral"


class ProviderAuthMethod(models.TextChoices):
    API_KEY = "api_key", "Chave oficial de API"


class AgentStatus(models.TextChoices):
    DRAFT = "draft", "Rascunho"
    ACTIVE = "active", "Ativo"
    PAUSED = "paused", "Pausado"


class ProviderKind(models.TextChoices):
    OPENAI = "openai", "OpenAI API"
    GEMINI = "gemini", "Gemini API"
    LOCAL = "local", "Modelo local"


class ProviderStatus(models.TextChoices):
    DISABLED = "disabled", "Desativado"
    ACTIVE = "active", "Ativo"
    REVOKED = "revoked", "Revogado"


class ToolName(models.TextChoices):
    CATALOG_SEARCH = "catalog.search", "Consultar catálogo"
    LEADS_UPSERT = "leads.upsert", "Atualizar lead"
    PROPOSAL_DRAFT = "proposal.draft", "Criar rascunho de proposta"
    HANDOFF_REQUEST = "handoff.request", "Solicitar atendimento humano"
    CONVERSATION_ADD_TAG = "conversation.add_tag", "Adicionar etiqueta"


class ApprovalPolicy(models.TextChoices):
    DENY = "deny", "Negar"
    CONFIGURED = "configured", "Conforme configuração"
    HUMAN = "human", "Aprovação humana"


class RunStatus(models.TextChoices):
    QUEUED = "queued", "Na fila"
    RUNNING = "running", "Em execução"
    WAITING_APPROVAL = "waiting_approval", "Aguardando aprovação"
    SUCCEEDED = "succeeded", "Concluído"
    FAILED = "failed", "Falhou"
    CANCELLED = "cancelled", "Cancelado"
    TIMED_OUT = "timed_out", "Expirou"


class ToolExecutionStatus(models.TextChoices):
    PENDING = "pending", "Pendente"
    SUCCEEDED = "succeeded", "Concluída"
    FAILED = "failed", "Falhou"
    DENIED = "denied", "Negada"


class ApprovalStatus(models.TextChoices):
    PENDING = "pending", "Pendente"
    APPROVED = "approved", "Aprovada"
    REJECTED = "rejected", "Rejeitada"
    EXPIRED = "expired", "Expirada"
    CANCELLED = "cancelled", "Cancelada"



class WorkspaceRelationScopedModel(WorkspaceScopedModel):
    """Reject tenant-crossing foreign keys on every ordinary ORM save."""

    workspace_relation_fields: tuple[str, ...] = ()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        for field_name in self.workspace_relation_fields:
            related = getattr(self, field_name)
            if related is not None and related.workspace_id != self.workspace_id:
                raise ValidationError({field_name: "O registro relacionado precisa pertencer ao mesmo espaço de trabalho."})
        super().save(*args, **kwargs)

class AIProviderConnection(WorkspaceScopedModel):
    """Provider configuration with encrypted credentials and no enabled default."""

    name = models.CharField(max_length=100)

    provider = models.CharField(max_length=20, choices=ProviderKind.choices)
    model = models.CharField(max_length=120)
    credentials = EncryptedJSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=ProviderStatus.choices, default=ProviderStatus.DISABLED)
    approved_auth_method = models.CharField(
        max_length=20,
        choices=ProviderAuthMethod.choices,
        default=ProviderAuthMethod.API_KEY,
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["workspace", "name"], name="ai_provider_ws_name_uniq")]
        indexes = [models.Index(fields=["workspace", "status"], name="ai_provider_ws_status_idx")]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_provider_display()})"



class AIAgent(WorkspaceRelationScopedModel):
    workspace_relation_fields = ("provider_connection",)
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=24, choices=AgentKind.choices, default=AgentKind.GENERAL)
    status = models.CharField(max_length=16, choices=AgentStatus.choices, default=AgentStatus.DRAFT)
    provider_connection = models.ForeignKey(
        AIProviderConnection, null=True, blank=True, on_delete=models.PROTECT, related_name="agents"
    )
    model = models.CharField(max_length=120, blank=True, default="")
    language = models.CharField(max_length=16, default="pt-BR")
    persona = models.CharField(max_length=240, blank=True, default="")
    prompt_template = models.TextField(blank=True, default="")
    business_hours = models.JSONField(default=dict, blank=True)
    limits = models.JSONField(default=dict, blank=True)
    fallback_message = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["workspace", "name"], name="ai_agent_ws_name_uniq")]
        indexes = [models.Index(fields=["workspace", "status"], name="ai_agent_ws_status_idx")]

    def clean(self) -> None:
        super().clean()
        if self.provider_connection_id and self.provider_connection.workspace_id != self.workspace_id:
            raise ValidationError({"provider_connection": "A conexão precisa pertencer ao mesmo espaço de trabalho."})

    def __str__(self) -> str:
        return self.name


class AIAgentVersion(WorkspaceRelationScopedModel):
    workspace_relation_fields = ("agent",)
    agent = models.ForeignKey(AIAgent, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    prompt_template = models.TextField()
    language = models.CharField(max_length=16, default="pt-BR")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    prompt_hash = models.CharField(max_length=64)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["agent", "version"], name="ai_agent_version_uniq")]
        indexes = [models.Index(fields=["workspace", "created_at"], name="ai_agent_ver_ws_created_idx")]

    def clean(self) -> None:
        super().clean()
        if self.agent_id and self.agent.workspace_id != self.workspace_id:
            raise ValidationError({"agent": "O agente precisa pertencer ao mesmo espaço de trabalho."})


class AIToolGrant(WorkspaceRelationScopedModel):
    workspace_relation_fields = ("agent",)
    agent = models.ForeignKey(AIAgent, on_delete=models.CASCADE, related_name="tool_grants")
    tool_name = models.CharField(max_length=40, choices=ToolName.choices)
    scope = models.JSONField(default=dict, blank=True)
    approval_policy = models.CharField(max_length=16, choices=ApprovalPolicy.choices, default=ApprovalPolicy.DENY)
    enabled = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["agent", "tool_name"], name="ai_tool_grant_uniq")]
        indexes = [models.Index(fields=["workspace", "agent", "enabled"], name="ai_tool_grant_ws_enabled_idx")]

    def clean(self) -> None:
        super().clean()
        if self.agent_id and self.agent.workspace_id != self.workspace_id:
            raise ValidationError({"agent": "O agente precisa pertencer ao mesmo espaço de trabalho."})


class AIConversationState(WorkspaceRelationScopedModel):
    workspace_relation_fields = ("conversation", "agent")
    class State(models.TextChoices):
        OFF = "off", "Desativado"
        ACTIVE = "active", "Ativo"
        PAUSED_HUMAN = "paused_human", "Pausado por atendimento humano"
        PAUSED_BUDGET = "paused_budget", "Pausado por orçamento"
        PAUSED_POLICY = "paused_policy", "Pausado por política"

    conversation = models.ForeignKey("messaging.Conversation", on_delete=models.CASCADE, related_name="ai_agent_states")
    agent = models.ForeignKey(AIAgent, on_delete=models.CASCADE, related_name="conversation_states")
    state = models.CharField(max_length=24, choices=State.choices, default=State.OFF)
    last_processed_event = models.CharField(max_length=255, blank=True, default="")
    version = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["conversation", "agent"], name="ai_conversation_agent_uniq")]
        indexes = [models.Index(fields=["workspace", "state"], name="ai_conv_state_ws_state_idx")]

    def clean(self) -> None:
        super().clean()
        if self.agent_id and self.agent.workspace_id != self.workspace_id:
            raise ValidationError({"agent": "O agente precisa pertencer ao mesmo espaço de trabalho."})
        if self.conversation_id and self.conversation.workspace_id != self.workspace_id:
            raise ValidationError({"conversation": "A conversa precisa pertencer ao mesmo espaço de trabalho."})


class AIRun(WorkspaceRelationScopedModel):
    workspace_relation_fields = ("agent", "conversation")
    agent = models.ForeignKey(AIAgent, on_delete=models.PROTECT, related_name="runs")
    conversation = models.ForeignKey("messaging.Conversation", on_delete=models.CASCADE, related_name="ai_runs")
    trigger_event_id = models.CharField(max_length=255)
    status = models.CharField(max_length=24, choices=RunStatus.choices, default=RunStatus.QUEUED)
    provider = models.CharField(max_length=20, choices=ProviderKind.choices)
    model = models.CharField(max_length=120)
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    cost_estimate = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    currency = models.CharField(max_length=3, default="USD")
    error_code = models.CharField(max_length=40, blank=True, default="")
    prompt_version = models.PositiveIntegerField(default=1)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["workspace", "trigger_event_id", "agent"], name="ai_run_event_agent_uniq")]
        indexes = [
            models.Index(fields=["workspace", "status"], name="ai_run_ws_status_idx"),
            models.Index(fields=["workspace", "conversation"], name="ai_run_ws_conv_idx"),
            models.Index(fields=["workspace", "created_at"], name="ai_run_ws_created_idx"),
        ]

    def clean(self) -> None:
        super().clean()
        if self.agent_id and self.agent.workspace_id != self.workspace_id:
            raise ValidationError({"agent": "O agente precisa pertencer ao mesmo espaço de trabalho."})
        if self.conversation_id and self.conversation.workspace_id != self.workspace_id:
            raise ValidationError({"conversation": "A conversa precisa pertencer ao mesmo espaço de trabalho."})


class AIToolExecution(WorkspaceRelationScopedModel):
    workspace_relation_fields = ("run",)
    run = models.ForeignKey(AIRun, on_delete=models.CASCADE, related_name="tool_executions")
    tool_name = models.CharField(max_length=40, choices=ToolName.choices)
    args_redacted = models.JSONField(default=dict, blank=True)
    result_redacted = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=ToolExecutionStatus.choices, default=ToolExecutionStatus.PENDING)
    idempotency_key = models.CharField(max_length=255)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["workspace", "idempotency_key"], name="ai_tool_exec_idem_uniq")]
        indexes = [models.Index(fields=["workspace", "run"], name="ai_tool_exec_ws_run_idx")]

    def clean(self) -> None:
        super().clean()
        if self.run_id and self.run.workspace_id != self.workspace_id:
            raise ValidationError({"run": "A execução precisa pertencer ao mesmo espaço de trabalho."})


class AIApprovalRequest(WorkspaceRelationScopedModel):
    workspace_relation_fields = ("run", "tool_execution")
    run = models.ForeignKey(AIRun, on_delete=models.CASCADE, related_name="approvals")
    tool_execution = models.ForeignKey(AIToolExecution, null=True, blank=True, on_delete=models.CASCADE, related_name="approvals")
    proposed_action = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING)
    expires_at = models.DateTimeField()
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["workspace", "status", "expires_at"], name="ai_approval_ws_status_idx")]

    def clean(self) -> None:
        super().clean()
        if self.run_id and self.run.workspace_id != self.workspace_id:
            raise ValidationError({"run": "A execução precisa pertencer ao mesmo espaço de trabalho."})
        if self.tool_execution_id and self.tool_execution.workspace_id != self.workspace_id:
            raise ValidationError({"tool_execution": "A ferramenta precisa pertencer ao mesmo espaço de trabalho."})


class AIUsageLedger(WorkspaceRelationScopedModel):
    workspace_relation_fields = ("run",)
    run = models.ForeignKey(AIRun, on_delete=models.CASCADE, related_name="usage_entries")
    provider = models.CharField(max_length=20, choices=ProviderKind.choices)
    model = models.CharField(max_length=120)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cost_estimate = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    currency = models.CharField(max_length=3, default="USD")

    class Meta:
        indexes = [models.Index(fields=["workspace", "created_at"], name="ai_usage_ws_created_idx")]

    def clean(self) -> None:
        super().clean()
        if self.run_id and self.run.workspace_id != self.workspace_id:
            raise ValidationError({"run": "A execução precisa pertencer ao mesmo espaço de trabalho."})


class AIServiceCatalogEntry(WorkspaceScopedModel):
    sku = models.CharField(max_length=80)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    currency = models.CharField(max_length=3)
    active = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["workspace", "sku", "version"], name="ai_catalog_sku_ver_uniq")]
        indexes = [models.Index(fields=["workspace", "active"], name="ai_catalog_ws_active_idx")]


class AIProposalDraft(WorkspaceRelationScopedModel):
    workspace_relation_fields = ("contact", "source_run")
    # Customer requirements can be embedded in a draft; erasure must cascade.
    contact = models.ForeignKey("contacts.Contact", on_delete=models.CASCADE, related_name="ai_proposal_drafts")
    items = models.JSONField(default=list)
    total = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    currency = models.CharField(max_length=3)
    catalog_versions = models.JSONField(default=dict)
    approval_status = models.CharField(max_length=16, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING)
    source_run = models.ForeignKey(AIRun, null=True, blank=True, on_delete=models.CASCADE, related_name="proposal_drafts")

    class Meta:
        indexes = [models.Index(fields=["workspace", "created_at"], name="ai_proposal_ws_created_idx")]

    def clean(self) -> None:
        super().clean()
        if self.contact_id and self.contact.workspace_id != self.workspace_id:
            raise ValidationError({"contact": "O contato precisa pertencer ao mesmo espaço de trabalho."})
        if self.source_run_id and self.source_run.workspace_id != self.workspace_id:
            raise ValidationError({"source_run": "A execução precisa pertencer ao mesmo espaço de trabalho."})
