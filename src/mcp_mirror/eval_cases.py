"""Golden behavioral eval cases for the bundled reference tools.

These cases are written to probe exactly the schema features that frameworks
mangle in Layer 1: the `priority` enum on send_message and the numeric
`confidence_threshold` on search_records. If a framework drops an enum's
allowed values, the model may fail to set `priority="urgent"` correctly — and
that failure shows up here, in behavior, not just in the structural diff.

For real Arcade tools, cases would be generated per the design doc's prompt
tiers; this hand-written golden set anchors the methodology against the
bundled fixtures.
"""

from __future__ import annotations

from arcade_evals import BinaryCritic, SimilarityCritic

from mcp_mirror.llm_eval import EvalCase, SafeNumericCritic


def golden_cases() -> list[EvalCase]:
    return [
        EvalCase(
            name="send urgent message by user id",
            user_message=(
                "Send an urgent message to the user with id U12345 that says "
                "'The deploy is finished, please verify.'"
            ),
            expected_tool="send_message",
            expected_args={
                "recipient": {"user_id": "U12345"},
                "body": "The deploy is finished, please verify.",
                "priority": "urgent",
            },
            critics=[
                BinaryCritic(critic_field="priority", weight=0.5),
                SimilarityCritic(critic_field="body", weight=0.3),
                BinaryCritic(critic_field="recipient", weight=0.2),
            ],
        ),
        EvalCase(
            name="send normal message by email",
            user_message=(
                "Email a quick note to jordan@example.com letting them know the "
                "weekly report is ready. Nothing urgent."
            ),
            expected_tool="send_message",
            expected_args={
                "recipient": {"email": "jordan@example.com"},
                "body": "The weekly report is ready.",
                "priority": "normal",
            },
            critics=[
                BinaryCritic(critic_field="priority", weight=0.5),
                SimilarityCritic(critic_field="body", weight=0.3),
                BinaryCritic(critic_field="recipient", weight=0.2),
            ],
        ),
        EvalCase(
            name="search with high confidence threshold",
            user_message=(
                "Search the records for 'quarterly revenue projections', but only "
                "give me high-confidence matches — at least 0.9 confidence."
            ),
            expected_tool="search_records",
            expected_args={
                "query": "quarterly revenue projections",
                "confidence_threshold": 0.9,
            },
            critics=[
                SimilarityCritic(critic_field="query", weight=0.5),
                SafeNumericCritic(
                    critic_field="confidence_threshold",
                    weight=0.5,
                    value_range=(0.85, 0.95),
                ),
            ],
        ),
        EvalCase(
            name="search with explicit limit",
            user_message=(
                "Find the top 25 records matching 'security incident postmortem'."
            ),
            expected_tool="search_records",
            expected_args={
                "query": "security incident postmortem",
                "limit": 25,
            },
            critics=[
                SimilarityCritic(critic_field="query", weight=0.5),
                SafeNumericCritic(
                    critic_field="limit",
                    weight=0.5,
                    value_range=(20, 30),
                ),
            ],
        ),
    ]
