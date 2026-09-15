"""Core data model (DESIGN.md section 6).

Both the source MCP definition and every framework rendering are mapped into the
same ``ToolRep`` so they can be diffed apples-to-apples. The engine below
``ToolRep`` never imports MCP or any framework: it only operates on these models.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["faithful", "lossy", "additive", "transformative"]
CaptureStage = Literal["framework_tool_definition", "provider_format", "provider_request"]
ObservationStage = Literal[
    "source",
    "framework_tool_definition",
    "provider_format",
    "provider_request",
    "tool_call",
    "tool_result",
]
RunStatus = Literal[
    "measured",
    "unsupported",
    "adapter_error",
    "protocol_mismatch",
    "server_variance",
    "unmeasured",
]
Attestation = Literal["local", "local_attested", "service_verified"]


class Dimension:
    """The aspects of a tool a difference can be about.

    ``REQUIRED`` and ``AUTHZ`` extend the section-6 list so that the Jobs-To-Be-Done
    mapping (section 10) is expressible: ``required`` feeds J2, and ``authz``
    (risk/scope language lost from a description) feeds J5 alongside ``annotation``.
    """

    NAME = "name"
    DESCRIPTION = "description"
    PARAM_TYPE = "param_type"
    CONSTRAINT = "constraint"
    STRUCTURE = "structure"
    ANNOTATION = "annotation"
    INJECTION = "injection"
    REQUIRED = "required"
    AUTHZ = "authz"
    ICONS = "icons"
    RESULT = "result"


class ToolRep(BaseModel):
    """Normalized representation of a tool, from the source or from a framework.

    ``annotations`` are annotations present on the tool definition at the renderer's
    declared capture boundary. ``framework_metadata`` records what the framework still
    retains elsewhere, e.g. annotations kept on an adapted tool object's metadata but
    absent from the captured definition. Distinguishing the two lets J5 tell retained
    policy evidence apart from a signal destroyed during adaptation.
    """

    name: str
    description: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    annotations: dict[str, Any] = Field(default_factory=dict)
    icons: list[dict[str, Any]] = Field(default_factory=list)
    framework_metadata: dict[str, Any] = Field(default_factory=dict)
    origin: str
    raw: dict[str, Any] = Field(default_factory=dict)


class ResultRep(BaseModel):
    """Normalized representation of what a ``tools/call`` produced.

    ``ToolRep`` answers what the agent was told a tool *is*; this answers what the agent
    receives when it calls one. They are separate captures because an adapter can be
    faithful about the definition and still flatten the result: the common shape a
    framework hands a model is a single string, which has nowhere to put an image, a
    resource link, a JSON value, or an error flag.

    ``block_kinds`` is the ordered list of content types, kept separately from
    ``blocks`` so a diff can say "the image is gone" without comparing base64 payloads.
    ``is_error`` is ``None`` when the framework exposes no failure channel at all,
    which is different from exposing one that says ``False``.
    """

    tool: str
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    block_kinds: list[str] = Field(default_factory=list)
    structured_content: Any | None = None
    is_error: bool | None = None
    text: str | None = None
    origin: str
    raw: Any = None


class Difference(BaseModel):
    """One categorized delta at one JSON path between source and a rendering."""

    tool: str
    framework: str
    path: str
    category: Category
    dimension: str
    detail: str
    source_value: Any | None = None
    rendered_value: Any | None = None


JobVerdict = Literal["pass", "degraded", "fail"]


class JobRequirement(BaseModel):
    """What one job needs from one tool in order to be doable.

    Every check is against the tool at the renderer's declared capture boundary. A job
    passes as long as what it needs survived to that boundary, even if the framework
    dropped other things. Dropping irrelevant fields is not a failure: change is not
    degradation.
    """

    tool: str
    params: list[str] = Field(default_factory=list)  # must be present in the rendered params
    required_params: list[str] = Field(default_factory=list)  # must remain in the params' ``required`` set
    constraints: dict[str, list[str]] = Field(default_factory=dict)  # {param: [JSON-Schema keys that must survive]}
    annotations: list[str] = Field(default_factory=list)  # keys required at the capture boundary


class Job(BaseModel):
    id: str
    title: str  # the Jobs-To-Be-Done statement, in its circumstance
    requires: list[JobRequirement] = Field(default_factory=list)


class JobSpec(BaseModel):
    provider: str
    jobs: list[Job] = Field(default_factory=list)


class JobFinding(BaseModel):
    """The verdict for one job under one framework.

    ``fail``     the job cannot be done from the captured definition: a needed tool or
                 param did not survive adaptation.
    ``degraded`` it can probably still be done, but something aiding correctness or
                 safety was weakened (a lost constraint, a retained-only risk hint).
    ``pass``     the job's needs survived intact, regardless of what else changed.
    """

    job_id: str
    title: str
    framework: str
    verdict: JobVerdict
    reasons: list[str] = Field(default_factory=list)


class RendererEvidence(BaseModel):
    """What a renderer actually inspected, and what remains unproven.

    A published framework adapter can expose a framework tool object, a
    provider-shaped tool dictionary, or a fully serialized provider request. Those
    are different evidence strengths. ``provider_request_captured`` is deliberately
    explicit so an intermediate object is never silently promoted to a stronger
    claim. The adapter's negotiated MCP version is similarly nullable because most
    current list-tools APIs do not expose it.
    """

    capture_api: str
    capture_object: str
    capture_stage: CaptureStage
    provider_request_captured: bool
    negotiated_mcp_spec_version: str | None = None
    protocol_version_evidence: str
    limitation: str | None = None


class CaptureObservation(BaseModel):
    """One inspectable artifact at one stage of the MCP-to-provider pipeline.

    ``tools`` contains the normalized comparison view. ``artifact_sha256`` hashes
    the canonical artifact represented by that view so a report can cite evidence
    without pretending the normalization is the original wire payload.
    A future provider-request capture may additionally retain the redacted raw body
    in ``artifact``. ``redacted`` is false unless a capture path actually applied a
    redaction policy.
    """

    stage: ObservationStage
    capture_api: str
    capture_object: str
    tools: list[ToolRep] = Field(default_factory=list)
    artifact_sha256: str
    artifact: Any | None = None
    redacted: bool = False
    limitation: str | None = None


class ScanProvenance(BaseModel):
    """Versions and runtime identity needed to reproduce a report."""

    generated_at: str
    scanner_version: str
    scanner_commit: str | None = None
    python_version: str | None = None
    platform: str | None = None
    runner_digest: str | None = None


class ScanConfiguration(BaseModel):
    """Non-secret inputs needed to understand and reproduce a scan."""

    transport: Literal["stdio", "http"]
    frameworks: list[str] = Field(default_factory=list)
    spec_version_assertion: str | None = None
    jobs: list[str] = Field(default_factory=list)
    jtbd: str | None = None
    header_names: list[str] = Field(default_factory=list)
    runner_mode: Literal["local_subprocess", "managed", "container"] = (
        "local_subprocess"
    )


class FrameworkRun(BaseModel):
    """Everything one framework produced for one scan."""

    framework: str
    framework_version: str
    adapter_version: str | None = None
    runner_digest: str | None = None
    status: RunStatus = "measured"
    status_detail: str | None = None
    evidence: RendererEvidence | None = None
    observations: list[CaptureObservation] = Field(default_factory=list)
    differences: list[Difference] = Field(default_factory=list)


class Report(BaseModel):
    """A full scan result. The scorecard is derived from this, not stored.

    ``mcp_spec_version`` is the version negotiated by mcp-mirror's direct source
    connection. A renderer's independently negotiated version belongs in its
    ``RendererEvidence`` and remains ``None`` when the framework does not expose it.
    """

    model_config = ConfigDict(populate_by_name=True)

    report_schema: str = Field(default="mcp-mirror/report@2", alias="schema")
    mcp_server: str
    mcp_spec_version: str
    mcp_spec_version_evidence: str = "direct source connection initialize result"
    generated_with: str
    attestation: Attestation = "local"
    provider_profile: str | None = None
    provenance: ScanProvenance | None = None
    scan: ScanConfiguration | None = None
    source_observation: CaptureObservation | None = None
    tools: list[str]
    runs: list[FrameworkRun] = Field(default_factory=list)
    job_findings: list[JobFinding] = Field(default_factory=list)
