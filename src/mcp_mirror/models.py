"""Core data model (DESIGN.md section 6).

Both the source MCP definition and every framework rendering are mapped into the
same ``ToolRep`` so they can be diffed apples-to-apples. The engine below
``ToolRep`` never imports MCP or any framework: it only operates on these models.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Category = Literal["faithful", "lossy", "additive", "transformative"]


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


class ToolRep(BaseModel):
    """Normalized representation of a tool, from the source or from a framework.

    ``annotations`` are the annotations the model actually receives in the tool spec
    (almost always empty for renderings, since the OpenAI/Anthropic function-tool
    format has no slot for them). ``framework_metadata`` records what the framework
    still *retains* out-of-band but does not surface to the model, e.g. annotations
    kept on the tool object's metadata. Distinguishing the two is what lets J5 tell a
    framework that merely fails to surface a risk hint apart from one that destroys it.
    """

    name: str
    description: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    annotations: dict[str, Any] = Field(default_factory=dict)
    framework_metadata: dict[str, Any] = Field(default_factory=dict)
    origin: str
    raw: dict[str, Any] = Field(default_factory=dict)


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

    Every check is against the *rendered* tool (what the model receives). A job passes
    as long as what it needs survived, even if the framework dropped other things.
    Dropping irrelevant fields is not a failure: change is not degradation.
    """

    tool: str
    params: list[str] = Field(default_factory=list)  # must be present in the rendered params
    required_params: list[str] = Field(default_factory=list)  # must remain in the params' ``required`` set
    constraints: dict[str, list[str]] = Field(default_factory=dict)  # {param: [JSON-Schema keys that must survive]}
    annotations: list[str] = Field(default_factory=list)  # annotation keys that must be SURFACED to the model


class Job(BaseModel):
    id: str
    title: str  # the Jobs-To-Be-Done statement, in its circumstance
    requires: list[JobRequirement] = Field(default_factory=list)


class JobSpec(BaseModel):
    provider: str
    jobs: list[Job] = Field(default_factory=list)


class JobFinding(BaseModel):
    """The verdict for one job under one framework.

    ``fail``     the job cannot be done: a needed tool or param never reached the model.
    ``degraded`` it can probably still be done, but something aiding correctness or
                 safety was weakened (a lost constraint, a risk hint the model cannot see).
    ``pass``     the job's needs survived intact, regardless of what else changed.
    """

    job_id: str
    title: str
    framework: str
    verdict: JobVerdict
    reasons: list[str] = Field(default_factory=list)


class FrameworkRun(BaseModel):
    """Everything one framework produced for one scan."""

    framework: str
    framework_version: str
    adapter_version: str | None = None
    differences: list[Difference] = Field(default_factory=list)


class Report(BaseModel):
    """A full scan result. The scorecard is derived from this, not stored."""

    mcp_server: str
    mcp_spec_version: str
    generated_with: str
    tools: list[str]
    runs: list[FrameworkRun] = Field(default_factory=list)
    job_findings: list[JobFinding] = Field(default_factory=list)
