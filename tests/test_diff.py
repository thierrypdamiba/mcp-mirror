"""Unit tests for the differ, categorizer, scorecard and baseline compare.

These run with no MCP server and no framework installed: they build ``ToolRep``
objects by hand and assert the expected category per dimension (DESIGN.md section 14).
"""

from __future__ import annotations

from mcp_mirror.diff import diff_reps, diff_tool
from mcp_mirror.models import (
    Difference,
    Dimension,
    FrameworkRun,
    RendererEvidence,
    Report,
    ToolRep,
)
from mcp_mirror.report import compare_baseline
from mcp_mirror.scorecard import build_scorecard


def src(name="tool", description="A tool.", params=None, annotations=None) -> ToolRep:
    return ToolRep(
        name=name,
        description=description,
        params=params if params is not None else {"type": "object", "properties": {}},
        annotations=annotations or {},
        origin="source",
    )


def rendered(name="tool", description="A tool.", params=None, annotations=None, framework_metadata=None) -> ToolRep:
    return ToolRep(
        name=name,
        description=description,
        params=params if params is not None else {"type": "object", "properties": {}},
        annotations=annotations or {},
        framework_metadata=framework_metadata or {},
        origin="fw",
    )


def categories_at(diffs, path):
    return [(d.category, d.dimension) for d in diffs if d.path == path]


def find(diffs, *, dimension=None, category=None):
    return [
        d
        for d in diffs
        if (dimension is None or d.dimension == dimension)
        and (category is None or d.category == category)
    ]


def test_identical_tools_are_faithful():
    s = src()
    r = rendered()
    assert diff_tool(s, r) == []


def test_missing_tool_is_lossy():
    diffs = diff_tool(src(name="gone"), None)
    assert len(diffs) == 1
    assert diffs[0].category == "lossy"
    assert diffs[0].dimension == Dimension.NAME


def test_name_namespacing_is_transformative():
    diffs = diff_tool(src(name="search"), rendered(name="server__search"))
    name_diffs = find(diffs, dimension=Dimension.NAME)
    assert len(name_diffs) == 1
    assert name_diffs[0].category == "transformative"


def test_description_truncated_is_lossy():
    s = src(description="A long, detailed description of the tool's behavior.")
    r = rendered(description="A long, detailed")
    diffs = find(diff_tool(s, r), dimension=Dimension.DESCRIPTION)
    assert diffs and diffs[0].category == "lossy"


def test_description_dropped_is_lossy():
    diffs = find(diff_tool(src(description="Has docs"), rendered(description=None)), dimension=Dimension.DESCRIPTION)
    assert diffs and diffs[0].category == "lossy"


def test_description_injected_when_source_had_none():
    diffs = diff_tool(src(description=None), rendered(description="Injected guidance"))
    inj = find(diffs, dimension=Dimension.INJECTION)
    assert inj and inj[0].category == "additive"


def test_description_appended_is_additive_injection():
    s = src(description="Do the thing.")
    r = rendered(description="Do the thing. Always respond using the provided schema.")
    inj = find(diff_tool(s, r), dimension=Dimension.INJECTION)
    assert inj and inj[0].category == "additive"


def test_description_reworded_is_transformative():
    s = src(description="Fetch the user profile.")
    r = rendered(description="Return the user profile!")
    desc = find(diff_tool(s, r), dimension=Dimension.DESCRIPTION)
    assert desc and desc[0].category == "transformative"


def test_enum_lost_is_lossy_constraint():
    s = src(params={
        "type": "object",
        "properties": {"x": {"type": "string", "enum": ["a", "b"]}},
    })
    r = rendered(params={"type": "object", "properties": {"x": {"type": "string"}}})
    diffs = categories_at(diff_tool(s, r), "params.properties.x.enum")
    assert ("lossy", Dimension.CONSTRAINT) in diffs


def test_format_lost_is_lossy_constraint():
    s = src(params={
        "type": "object",
        "properties": {"email": {"type": "string", "format": "email"}},
    })
    r = rendered(params={"type": "object", "properties": {"email": {"type": "string"}}})
    diffs = categories_at(diff_tool(s, r), "params.properties.email.format")
    assert ("lossy", Dimension.CONSTRAINT) in diffs


def test_constraint_value_change_is_transformative():
    s = src(params={
        "type": "object",
        "properties": {"limit": {"type": "integer", "default": 20}},
    })
    r = rendered(params={
        "type": "object",
        "properties": {"limit": {"type": "integer", "default": None}},
    })
    diffs = categories_at(diff_tool(s, r), "params.properties.limit.default")
    assert ("transformative", Dimension.CONSTRAINT) in diffs


def test_type_changed_is_transformative():
    s = src(params={"type": "object", "properties": {"x": {"type": "string"}}})
    r = rendered(params={"type": "object", "properties": {"x": {"type": "object"}}})
    diffs = categories_at(diff_tool(s, r), "params.properties.x.type")
    assert ("transformative", Dimension.PARAM_TYPE) in diffs


def test_required_shrink_is_lossy():
    s = src(params={"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a", "b"]})
    r = rendered(params={"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a"]})
    diffs = categories_at(diff_tool(s, r), "params.required")
    assert ("lossy", Dimension.REQUIRED) in diffs


def test_anyof_collapse_is_transformative_structure():
    s = src(params={
        "type": "object",
        "properties": {"dest": {"anyOf": [{"type": "string"}, {"type": "object"}]}},
    })
    r = rendered(params={"type": "object", "properties": {"dest": {"type": "string"}}})
    structure = find(diff_tool(s, r), dimension=Dimension.STRUCTURE)
    assert any("anyOf" in d.path and d.category == "transformative" for d in structure)


def test_optional_anyof_wrapper_preserves_constraints_but_reports_null_widening():
    # A framework serializing `Optional[str-with-enum]` as anyOf:[{enum}, {null}] keeps
    # the enum one level down, but accepting null is still a semantic addition.
    s = src(params={"type": "object", "properties": {"status": {"type": "string", "enum": ["a", "b"]}}})
    r = rendered(params={
        "type": "object",
        "properties": {
            "status": {"anyOf": [{"type": "string", "enum": ["a", "b"]}, {"type": "null"}], "default": None}
        },
    })
    diffs = diff_tool(s, r)
    assert not find(diffs, dimension=Dimension.CONSTRAINT)
    assert categories_at(diffs, "params.properties.status.null") == [
        ("additive", Dimension.PARAM_TYPE)
    ]


def test_anyof_branches_are_compared_by_semantic_shape():
    source_branch = {
        "description": "Destination.",
        "anyOf": [
            {
                "type": "string",
                "format": "uri",
                "description": "Webhook URL.",
            },
            {
                "type": "object",
                "description": "Object store.",
                "properties": {"bucket": {"type": "string"}},
                "required": ["bucket"],
            },
        ],
    }
    rendered_branch = {
        "description": "Destination.",
        "anyOf": [
            {"type": "string"},
            {
                "type": "object",
                "properties": {"bucket": {"type": "string"}},
                "required": ["bucket"],
            },
        ],
    }
    diffs = diff_tool(
        src(params={"type": "object", "properties": {"destination": source_branch}}),
        rendered(params={"type": "object", "properties": {"destination": rendered_branch}}),
    )

    assert ("lossy", Dimension.CONSTRAINT) in categories_at(
        diffs,
        "params.properties.destination.anyOf[0].format",
    )
    assert ("lossy", Dimension.CONSTRAINT) in categories_at(
        diffs,
        "params.properties.destination.anyOf[0].description",
    )
    assert ("lossy", Dimension.CONSTRAINT) in categories_at(
        diffs,
        "params.properties.destination.anyOf[1].description",
    )


def test_same_type_union_branches_can_reorder_without_false_diffs():
    source_union = {
        "anyOf": [
            {"type": "string", "format": "uri"},
            {"type": "string", "format": "email"},
        ]
    }
    rendered_union = {
        "anyOf": [
            {"type": "string", "format": "email"},
            {"type": "string", "format": "uri"},
        ]
    }
    diffs = diff_tool(
        src(params={"type": "object", "properties": {"value": source_union}}),
        rendered(params={"type": "object", "properties": {"value": rendered_union}}),
    )
    assert diffs == []


def test_additional_properties_restriction_is_transformative():
    s = src(params={
        "type": "object",
        "properties": {"value": {"type": "string"}},
    })
    r = rendered(params={
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "additionalProperties": False,
    })
    diffs = categories_at(diff_tool(s, r), "params.additionalProperties")
    assert ("transformative", Dimension.CONSTRAINT) in diffs


def test_ref_nested_object_is_resolved_not_flattened():
    # A framework nesting an object via $defs/$ref preserves it; resolve the ref rather
    # than reporting the structure as flattened or the enum as lost.
    nested = {"type": "object", "properties": {"fmt": {"type": "string", "enum": ["pdf", "html"]}}, "required": ["fmt"]}
    s = src(params={"type": "object", "properties": {"config": nested}})
    r = rendered(params={
        "type": "object",
        "$defs": {"Config": nested},
        "properties": {"config": {"$ref": "#/$defs/Config"}},
    })
    diffs = diff_tool(s, r)
    assert not find(diffs, dimension=Dimension.STRUCTURE)
    assert not find(diffs, dimension=Dimension.CONSTRAINT)


def test_nested_property_description_lost_is_lossy_constraint():
    s = src(params={
        "type": "object",
        "properties": {
            "cfg": {
                "type": "object",
                "properties": {"fmt": {"type": "string", "description": "Output format."}},
            }
        },
    })
    r = rendered(params={
        "type": "object",
        "properties": {"cfg": {"type": "object", "properties": {"fmt": {"type": "string"}}}},
    })
    diffs = categories_at(diff_tool(s, r), "params.properties.cfg.properties.fmt.description")
    assert ("lossy", Dimension.CONSTRAINT) in diffs


def test_property_dropped_is_lossy_structure():
    s = src(params={"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}}})
    r = rendered(params={"type": "object", "properties": {"a": {"type": "string"}}})
    diffs = categories_at(diff_tool(s, r), "params.properties.b")
    assert ("lossy", Dimension.STRUCTURE) in diffs


def test_property_injected_is_additive():
    s = src(params={"type": "object", "properties": {"a": {"type": "string"}}})
    r = rendered(params={"type": "object", "properties": {"a": {"type": "string"}, "z": {"type": "string"}}})
    diffs = categories_at(diff_tool(s, r), "params.properties.z")
    assert ("additive", Dimension.INJECTION) in diffs


def test_annotation_destroyed_is_lossy():
    # No trace of the annotation anywhere: the dangerous case.
    s = src(annotations={"destructiveHint": True})
    r = rendered(annotations={})
    diffs = categories_at(diff_tool(s, r), "annotations.destructiveHint")
    assert ("lossy", Dimension.ANNOTATION) in diffs


def test_annotation_retained_outside_capture_boundary_is_transformative():
    # The framework keeps the hint outside the declared capture object.
    s = src(annotations={"destructiveHint": True})
    r = rendered(annotations={}, framework_metadata={"annotations": {"destructiveHint": True}})
    diffs = categories_at(diff_tool(s, r), "annotations.destructiveHint")
    assert ("transformative", Dimension.ANNOTATION) in diffs
    detail = next(d for d in diff_tool(s, r) if d.path == "annotations.destructiveHint").detail
    assert "absent from the captured tool definition" in detail


def test_annotation_present_at_capture_boundary_is_faithful():
    # The captured tool definition preserves the hint unchanged.
    s = src(annotations={"destructiveHint": True})
    r = rendered(annotations={"destructiveHint": True})
    assert not find(diff_tool(s, r), dimension=Dimension.ANNOTATION)


def test_risk_language_lost_feeds_authz():
    s = src(description="Delete the account. This is destructive and irreversible.")
    r = rendered(description="Delete the account.")
    authz = find(diff_tool(s, r), dimension=Dimension.AUTHZ)
    assert authz and authz[0].category == "lossy"


def test_diff_reps_matches_namespaced_names():
    sources = [src(name="search"), src(name="delete_account", annotations={"destructiveHint": True})]
    renders = [
        rendered(name="srv__search"),
        rendered(name="srv__delete_account", annotations={}),
    ]
    diffs = diff_reps(sources, renders)
    # delete_account's annotation must be flagged even though the name is namespaced.
    assert any(d.tool == "delete_account" and d.dimension == Dimension.ANNOTATION for d in diffs)


def _report_with(diffs: list[Difference]) -> Report:
    return Report(
        mcp_server="x",
        mcp_spec_version="2026-07-28",
        generated_with="mcp-mirror/test",
        tools=["t"],
        runs=[FrameworkRun(framework="fw", framework_version="1.0", differences=diffs)],
    )


def _diff(category, dimension, path="p", tool="t") -> Difference:
    return Difference(
        tool=tool, framework="fw", path=path, category=category, dimension=dimension, detail="d"
    )


def test_scorecard_picks_per_job_category_and_counts_without_overall_verdict():
    diffs = [
        _diff("lossy", Dimension.DESCRIPTION, "params.description"),
        _diff("lossy", Dimension.CONSTRAINT, "params.properties.a.enum"),
        _diff("lossy", Dimension.CONSTRAINT, "params.properties.a.format"),
        _diff("transformative", Dimension.PARAM_TYPE, "params.properties.a.type"),
        _diff("transformative", Dimension.STRUCTURE, "params.properties.b.anyOf"),
        _diff("additive", Dimension.INJECTION, "params.properties.z"),
        _diff("lossy", Dimension.ANNOTATION, "annotations.destructiveHint"),
    ]
    card = build_scorecard(_report_with(diffs))
    jobs = card["frameworks"]["fw"]["jobs"]
    assert jobs["J1"]["verdict"] == "lossy"
    assert jobs["J2"]["verdict"] == "lossy" and jobs["J2"]["count"] == 3
    assert jobs["J3"]["verdict"] == "transformative"
    assert jobs["J4"]["verdict"] == "additive"
    assert jobs["J5"]["verdict"] == "lossy"
    assert card["frameworks"]["fw"]["authz_flags"]
    assert "worst" not in card["frameworks"]["fw"]


def test_scorecard_faithful_when_no_diffs():
    card = build_scorecard(_report_with([]))
    jobs = card["frameworks"]["fw"]["jobs"]
    assert all(cell["verdict"] == "faithful" and cell["count"] == 0 for cell in jobs.values())


def test_baseline_no_drift_when_equal():
    report = _report_with([_diff("lossy", Dimension.CONSTRAINT, "params.properties.a.enum")])
    drift, _ = compare_baseline(report, report)
    assert drift is False


def test_baseline_drift_on_new_difference():
    baseline = _report_with([])
    current = _report_with([_diff("lossy", Dimension.CONSTRAINT, "params.properties.a.enum")])
    drift, messages = compare_baseline(current, baseline)
    assert drift is True
    assert any(m.startswith("NEW") for m in messages)


def test_baseline_drift_on_worse_category():
    baseline = _report_with([_diff("transformative", Dimension.STRUCTURE, "params.properties.b")])
    current = _report_with([_diff("lossy", Dimension.STRUCTURE, "params.properties.b")])
    drift, messages = compare_baseline(current, baseline)
    assert drift is True
    assert any(m.startswith("WORSE") for m in messages)


def test_baseline_spec_version_mismatch_is_drift():
    baseline = _report_with([])
    current = _report_with([])
    current.mcp_spec_version = "2025-06-18"
    drift, messages = compare_baseline(current, baseline)
    assert drift is True
    assert any("spec version mismatch" in m for m in messages)


def test_baseline_renderer_spec_version_mismatch_is_drift():
    baseline = _report_with([])
    current = _report_with([])
    for report, version in (
        (baseline, "2025-11-25"),
        (current, "2026-07-28"),
    ):
        report.runs[0].evidence = RendererEvidence(
            capture_api="adapter.list_tools",
            capture_object="Tool",
            capture_stage="framework_tool_definition",
            provider_request_captured=False,
            negotiated_mcp_spec_version=version,
            protocol_version_evidence="initialize result",
        )

    drift, messages = compare_baseline(current, baseline)

    assert drift is True
    assert "renderer MCP spec mismatch" in messages[0]
