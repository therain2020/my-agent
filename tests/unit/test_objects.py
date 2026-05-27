"""Tests for Phase 2: object model and role definitions."""

from agent.objects import (
    AgentObject,
    ObjectState,
    extract_state_properties,
    resolve_object_type,
)
from agent.role import DEFAULT_ROLE, ObjectFocus, Role


class TestAgentObject:
    def test_state_changed_with_both_states(self):
        obj = AgentObject(
            uri="file://test.py", type="file",
            state_before=ObjectState(observed_at="t1", properties={"size": 100}),
            state_after=ObjectState(observed_at="t2", properties={"size": 200}),
        )
        assert obj.state_changed is True

    def test_state_not_changed_when_same(self):
        obj = AgentObject(
            uri="file://test.py", type="file",
            state_before=ObjectState(observed_at="t1", properties={"size": 100}),
            state_after=ObjectState(observed_at="t2", properties={"size": 100}),
        )
        assert obj.state_changed is False

    def test_state_not_changed_without_after(self):
        obj = AgentObject(
            uri="file://test.py", type="file",
            state_before=ObjectState(observed_at="t1", properties={"size": 100}),
        )
        assert obj.state_changed is False

    def test_diff_computes_changes(self):
        obj = AgentObject(
            uri="file://test.py", type="file",
            state_before=ObjectState(observed_at="t1", properties={"size": 100, "exists": True}),
            state_after=ObjectState(observed_at="t2", properties={"size": 200, "exists": True}),
        )
        diff = obj.diff
        assert "size" in diff
        assert diff["size"] == {"before": 100, "after": 200}
        assert "exists" not in diff

    def test_diff_empty_without_states(self):
        obj = AgentObject(uri="file://test.py", type="file")
        assert obj.diff == {}

    def test_display_name_defaults_to_uri(self):
        obj = AgentObject(uri="file://main.py", type="file")
        assert obj.display_name == "file://main.py"

    def test_display_name_explicit(self):
        obj = AgentObject(uri="file://main.py", type="file", display_name="Main Script")
        assert obj.display_name == "Main Script"


class TestExtractStateProperties:
    def test_from_dict(self):
        assert extract_state_properties({"a": 1}) == {"a": 1}

    def test_from_json_string(self):
        result = extract_state_properties('{"key": "value"}')
        assert result == {"key": "value"}

    def test_from_plain_string(self):
        result = extract_state_properties("hello world")
        assert result == {"raw_output": "hello world"}

    def test_truncates_long_string(self):
        long_str = "x" * 1000
        result = extract_state_properties(long_str)
        assert len(result["raw_output"]) == 500


class TestResolveObjectType:
    def test_from_uri_scheme(self):
        assert resolve_object_type("file://path/to/file", []) == "file"

    def test_from_tool_objects(self):
        assert resolve_object_type("no-scheme", ["database"]) == "database"

    def test_unknown(self):
        assert resolve_object_type("no-scheme", []) == "unknown"


class TestRole:
    def test_known_object_types(self):
        assert "file" in DEFAULT_ROLE.known_object_types
        assert "database" in DEFAULT_ROLE.known_object_types

    def test_get_focus(self):
        focus = DEFAULT_ROLE.get_focus("file")
        assert focus is not None
        assert focus.object_type == "file"

    def test_get_focus_missing(self):
        assert DEFAULT_ROLE.get_focus("nonexistent") is None

    def test_get_observation_tools(self):
        tools = DEFAULT_ROLE.get_observation_tools("file")
        assert "read_file" in tools

    def test_get_manipulation_tools(self):
        tools = DEFAULT_ROLE.get_manipulation_tools("file")
        assert "write_file" in tools

    def test_get_dont_do_operations(self):
        ops = DEFAULT_ROLE.get_dont_do_operations("database")
        assert "drop_table" in ops

    def test_get_observation_tools_missing_type(self):
        assert DEFAULT_ROLE.get_observation_tools("nonexistent") == []

    def test_custom_role(self):
        role = Role(
            name="test-role",
            focus_objects=[ObjectFocus(object_type="file", observation=["read"])],
        )
        assert role.get_observation_tools("file") == ["read"]
        assert role.get_manipulation_tools("file") == []
