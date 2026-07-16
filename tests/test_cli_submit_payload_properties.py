"""
Property-Based Tests for build_commit_payload (Properties 5–8)
===============================================================
# Feature: cli-submit-flow-fix, Properties 5, 6, 7, 8

Testing framework: Hypothesis
"""
from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings, strategies as st

from agenthub.http_client import build_commit_payload
from agenthub.models import (
    BountyDetail,
    LLMOutput,
    ToolCall,
    ToolResult,
    TraceCommit,
    TraceEntry,
)


# ─────────────────────────────────────────────────────────────────────────────
# Generators
# ─────────────────────────────────────────────────────────────────────────────

_tool_names = st.sampled_from(["read_file", "run_tests", "search", "write_file", "list_dir"])

_args_strategy = st.fixed_dictionaries({
    "path": st.text(min_size=1, max_size=80),
    "content": st.text(max_size=200),
})

_other_args_strategy = st.dictionaries(
    st.text(min_size=1, max_size=20),
    st.text(max_size=50),
    max_size=3,
)


def _make_tool_call(name: str, args: dict[str, Any]) -> ToolCall:
    return ToolCall(id="tc-1", name=name, args=args)


def _make_trace_entry(name: str, args: dict[str, Any]) -> TraceEntry:
    tc = _make_tool_call(name, args)
    tr = ToolResult(tool_call_id="tc-1", output="ok", allowed=True)
    return TraceEntry(tool_call=tc, result=tr, timestamp="2025-01-01T00:00:00Z")


@st.composite
def write_file_entry(draw) -> TraceEntry:
    path = draw(st.text(min_size=1, max_size=80, alphabet=st.characters(whitelist_categories=("Ll",), whitelist_characters="_-")))
    content = draw(st.text(min_size=1, max_size=200))
    return _make_trace_entry("write_file", {"path": path, "content": content})


@st.composite
def non_write_file_entry(draw) -> TraceEntry:
    name = draw(st.sampled_from(["read_file", "run_tests", "search", "list_dir"]))
    args = draw(_other_args_strategy)
    return _make_trace_entry(name, args)


@st.composite
def mixed_trace(draw) -> tuple[TraceCommit, list[TraceEntry], list[TraceEntry]]:
    """Returns (trace, write_file_entries, other_entries)."""
    wf_entries = draw(st.lists(write_file_entry(), min_size=0, max_size=5))
    other_entries = draw(st.lists(non_write_file_entry(), min_size=0, max_size=5))
    all_entries = draw(st.permutations(wf_entries + other_entries))
    trace = TraceCommit(bounty_id="b-1", role="contributor", entries=all_entries)
    return trace, wf_entries, other_entries


def _make_bounty(title: str = "Fix bug", bounty_id: str = "b-1") -> BountyDetail:
    return BountyDetail(
        id=bounty_id,
        role="contributor",
        title=title,
        description="desc",
        files_to_read=[],
        token_budget=8192,
        status="open",
        repo_name="test-repo",
    )


def _make_output(raw_text: str = "output") -> LLMOutput:
    return LLMOutput(status="submitted", content={}, raw_text=raw_text)


def _make_trace(entries: list[TraceEntry] | None = None) -> TraceCommit:
    return TraceCommit(bounty_id="b-1", role="contributor", entries=entries or [])


# ─────────────────────────────────────────────────────────────────────────────
# Property 5: files dict contains exactly the write_file entries
# Feature: cli-submit-flow-fix, Property 5
# Validates: Requirements 3.1, 4.1, 4.2
# ─────────────────────────────────────────────────────────────────────────────

@given(mixed_trace())
@settings(max_examples=100)
def test_property5_files_dict_contains_exactly_write_file_entries(
    trace_data: tuple[TraceCommit, list[TraceEntry], list[TraceEntry]],
) -> None:
    """
    Property 5: files dict contains exactly the write_file entries.

    For any TraceCommit with a mix of tool call entries, build_commit_payload
    SHALL produce a files dict that contains one entry per write_file tool call
    and no entries from non-write_file tool calls.

    **Validates: Requirements 3.1, 4.1, 4.2**
    """
    trace, wf_entries, _ = trace_data
    bounty = _make_bounty()
    output = _make_output()

    payload = build_commit_payload(bounty, output, trace, "agent-1", "claude-3")

    files = payload["files"]
    assert isinstance(files, dict)

    # Build expected files by replaying ALL trace entries in order
    # because build_commit_payload iterates trace.entries in order
    expected: dict[str, str] = {}
    for entry in trace.entries:
        if entry.tool_call.name == "write_file":
            path = entry.tool_call.args.get("path")
            content = entry.tool_call.args.get("content")
            if path is not None and content is not None:
                expected[path] = content  # last write wins

    assert files == expected

    # No keys from non-write_file entries should appear
    # (they don't have "path"/"content" in the same way, but verify no extras)
    write_file_paths = {
        e.tool_call.args["path"]
        for e in wf_entries
        if "path" in e.tool_call.args and "content" in e.tool_call.args
    }
    for key in files:
        assert key in write_file_paths


# ─────────────────────────────────────────────────────────────────────────────
# Property 6: reasoning_trace has one formatted string per entry
# Feature: cli-submit-flow-fix, Property 6
# Validates: Requirements 3.3, 5.1, 5.2
# ─────────────────────────────────────────────────────────────────────────────

@given(st.lists(
    st.builds(
        lambda name, args: _make_trace_entry(name, args),
        name=_tool_names,
        args=_other_args_strategy,
    ),
    min_size=0,
    max_size=20,
))
@settings(max_examples=100)
def test_property6_reasoning_trace_length_and_format(entries: list[TraceEntry]) -> None:
    """
    Property 6: reasoning_trace has one formatted string per entry.

    For any TraceCommit with N entries, build_commit_payload SHALL produce a
    reasoning_trace list of exactly N strings, where each string is
    "{tool_call.name}({tool_call.args!r})".

    **Validates: Requirements 3.3, 5.1, 5.2**
    """
    trace = _make_trace(entries)
    bounty = _make_bounty()
    output = _make_output()

    payload = build_commit_payload(bounty, output, trace, "agent-1", "claude-3")

    rt = payload["reasoning_trace"]
    assert isinstance(rt, list)
    assert len(rt) == len(entries)

    for i, entry in enumerate(entries):
        expected_str = f"{entry.tool_call.name}({entry.tool_call.args!r})"
        assert rt[i] == expected_str


# ─────────────────────────────────────────────────────────────────────────────
# Property 7: diff_summary is always ≤ 500 characters
# Feature: cli-submit-flow-fix, Property 7
# Validates: Requirements 3.2
# ─────────────────────────────────────────────────────────────────────────────

@given(raw_text=st.text(min_size=0, max_size=2000))
@settings(max_examples=100)
def test_property7_diff_summary_length_cap(raw_text: str) -> None:
    """
    Property 7: diff_summary is always ≤ 500 characters.

    For any LLMOutput with raw_text of arbitrary length, build_commit_payload
    SHALL produce a diff_summary equal to raw_text[:500], which is always at
    most 500 characters.

    **Validates: Requirements 3.2**
    """
    output = _make_output(raw_text)
    bounty = _make_bounty()
    trace = _make_trace()

    payload = build_commit_payload(bounty, output, trace, "agent-1", "claude-3")

    diff_summary = payload["diff_summary"]
    assert isinstance(diff_summary, str)
    assert len(diff_summary) <= 500
    assert diff_summary == raw_text[:500]


# ─────────────────────────────────────────────────────────────────────────────
# Property 8: Payload field mapping preserves source values
# Feature: cli-submit-flow-fix, Property 8
# Validates: Requirements 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10
# ─────────────────────────────────────────────────────────────────────────────

@given(
    title=st.text(min_size=1, max_size=100),
    bounty_id=st.text(min_size=1, max_size=50),
    agent_id=st.text(min_size=1, max_size=50),
    model_name=st.text(min_size=1, max_size=50),
)
@settings(max_examples=100)
def test_property8_payload_field_mapping_preserves_source_values(
    title: str,
    bounty_id: str,
    agent_id: str,
    model_name: str,
) -> None:
    """
    Property 8: Payload field mapping preserves source values.

    For any BountyDetail, agent_id, and model_name, build_commit_payload SHALL
    produce a dict where all static and mapped fields match their sources exactly.

    **Validates: Requirements 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10**
    """
    bounty = _make_bounty(title=title, bounty_id=bounty_id)
    output = _make_output()
    trace = _make_trace()

    payload = build_commit_payload(bounty, output, trace, agent_id, model_name)

    assert payload["intent_description"] == bounty.title
    assert payload["bounty_id"] == bounty.id
    assert payload["agent_id"] == agent_id
    assert payload["model_name"] == model_name
    assert payload["intent_category"] == "fix"
    assert payload["intent_vector"] == [0.0]
    assert payload["rejected_alternatives"] == []
