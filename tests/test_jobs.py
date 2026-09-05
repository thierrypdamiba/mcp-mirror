"""Unit tests for the Jobs-To-Be-Done checker (jobs.py).

The checker is pure: it takes a Job and a list of rendered ToolReps and returns a
verdict. These tests build ToolReps by hand, so they need no MCP server or framework.
"""

from mcp_mirror.jobs import evaluate_job, list_bundled_providers, load_jobs
from mcp_mirror.models import Job, JobRequirement, ToolRep


def _rep(name, properties, required=None, annotations=None, framework_metadata=None):
    return ToolRep(
        name=name,
        params={"type": "object", "properties": properties, "required": required or []},
        annotations=annotations or {},
        framework_metadata=framework_metadata or {},
        origin="test",
    )


def test_pass_when_needs_survive():
    reps = [_rep("write_file", {"path": {"type": "string"}, "content": {"type": "string"}},
                 ["path", "content"])]
    job = Job(id="w", title="write", requires=[
        JobRequirement(tool="write_file", params=["path", "content"], required_params=["path", "content"])])
    verdict, reasons = evaluate_job(job, reps)
    assert verdict == "pass"
    assert reasons == []


def test_pass_ignores_unrelated_drops():
    # The framework dropped readOnlyHint and any description, but the read job does not need them.
    reps = [_rep("read_file", {"path": {"type": "string"}}, ["path"], annotations={})]
    job = Job(id="r", title="read", requires=[JobRequirement(tool="read_file", params=["path"])])
    assert evaluate_job(job, reps)[0] == "pass"


def test_fail_when_tool_missing():
    job = Job(id="w", title="write", requires=[JobRequirement(tool="write_file", params=["path"])])
    verdict, reasons = evaluate_job(job, [])
    assert verdict == "fail"
    assert any("absent at the capture boundary" in r for r in reasons)


def test_fail_when_param_missing():
    reps = [_rep("write_file", {"path": {"type": "string"}})]
    job = Job(id="w", title="write",
              requires=[JobRequirement(tool="write_file", params=["path", "content"])])
    verdict, reasons = evaluate_job(job, reps)
    assert verdict == "fail"
    assert any("content" in r for r in reasons)


def test_fail_when_annotation_destroyed():
    # write_file is present, but destructiveHint is neither captured nor retained.
    reps = [_rep("write_file", {"path": {"type": "string"}}, ["path"], annotations={})]
    job = Job(id="w", title="write", requires=[
        JobRequirement(tool="write_file", params=["path"], annotations=["destructiveHint"])])
    verdict, reasons = evaluate_job(job, reps)
    assert verdict == "fail"
    assert any("destroyed" in r and "destructiveHint" in r for r in reasons)


def test_degraded_when_annotation_retained_outside_capture_boundary():
    # The framework keeps destructiveHint in metadata for a policy layer, but it is
    # absent from the captured definition. Degraded, not failed.
    reps = [_rep("write_file", {"path": {"type": "string"}}, ["path"],
                 annotations={}, framework_metadata={"annotations": {"destructiveHint": True}})]
    job = Job(id="w", title="write", requires=[
        JobRequirement(tool="write_file", params=["path"], annotations=["destructiveHint"])])
    verdict, reasons = evaluate_job(job, reps)
    assert verdict == "degraded"
    assert any("retained" in r for r in reasons)


def test_degraded_when_constraint_lost():
    reps = [_rep("t", {"mode": {"type": "string"}})]  # no enum survived
    job = Job(id="c", title="c", requires=[
        JobRequirement(tool="t", params=["mode"], constraints={"mode": ["enum"]})])
    verdict, reasons = evaluate_job(job, reps)
    assert verdict == "degraded"
    assert any("enum" in r for r in reasons)


def test_degraded_when_required_relaxed():
    reps = [_rep("t", {"path": {"type": "string"}}, required=[])]  # path no longer required
    job = Job(id="t", title="t", requires=[
        JobRequirement(tool="t", params=["path"], required_params=["path"])])
    assert evaluate_job(job, reps)[0] == "degraded"


def test_namespaced_tool_matches():
    reps = [_rep("server__read_file", {"path": {"type": "string"}}, ["path"])]
    job = Job(id="r", title="read", requires=[JobRequirement(tool="read_file", params=["path"])])
    assert evaluate_job(job, reps)[0] == "pass"


def test_fail_outranks_degrade():
    # Missing param (fail) plus a retained-only annotation (degrade) => overall fail.
    reps = [_rep("write_file", {"path": {"type": "string"}}, ["path"],
                 annotations={}, framework_metadata={"annotations": {"destructiveHint": True}})]
    job = Job(id="w", title="write", requires=[
        JobRequirement(tool="write_file", params=["path", "content"], annotations=["destructiveHint"])])
    assert evaluate_job(job, reps)[0] == "fail"


def test_bundled_filesystem_spec_loads():
    spec = load_jobs("filesystem")
    assert spec.provider == "filesystem"
    assert len(spec.jobs) >= 4
    assert "filesystem" in list_bundled_providers()
    assert "example" not in list_bundled_providers()
