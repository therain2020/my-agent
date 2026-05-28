"""Structured role definitions — what objects a role cares about and how to observe them.

Each role declares:
- focus_objects: which object types it pays attention to
- observation_tools: which tool capabilities to use for observing each type
- manipulation_tools: which tool capabilities to use for changing each type
"""

from dataclasses import dataclass, field

from .objects import ObjectAction, ObjectConstraint


@dataclass
class ObjectFocus:
    """How a role interacts with one type of object."""
    object_type: str                                # "file", "git-repo", "database"
    observation: list[str] = field(default_factory=list)    # capability names for reading
    manipulation: list[str] = field(default_factory=list)   # capability names for writing
    dont_do_operations: list[str] = field(default_factory=list)  # blocked operations

    def as_constraints(self) -> list[ObjectConstraint]:
        """Generate ontology constraints from this focus definition."""
        constraints = []
        for op in self.dont_do_operations:
            constraints.append(ObjectConstraint(
                description=f"禁止操作: {op}",
                severity="blocker",
                source="role",
            ))
        return constraints

    def as_actions(self) -> list[ObjectAction]:
        """Generate ontology actions from this focus definition."""
        actions = []
        for cap in self.observation:
            actions.append(ObjectAction(
                name=cap, preconditions=[], side_effects=[],
            ))
        for cap in self.manipulation:
            actions.append(ObjectAction(
                name=cap,
                preconditions=["目标对象存在且可访问"],
                side_effects=["修改对象状态"],
            ))
        return actions


@dataclass
class Role:
    """Structured agent role — defines what and how to observe."""
    name: str
    description: str = ""
    focus_objects: list[ObjectFocus] = field(default_factory=list)
    behavior_rules: list[str] = field(default_factory=list)

    @property
    def known_object_types(self) -> list[str]:
        return [f.object_type for f in self.focus_objects]

    def get_focus(self, object_type: str) -> ObjectFocus | None:
        for f in self.focus_objects:
            if f.object_type == object_type:
                return f
        return None

    def get_observation_tools(self, object_type: str) -> list[str]:
        focus = self.get_focus(object_type)
        return focus.observation if focus else []

    def get_manipulation_tools(self, object_type: str) -> list[str]:
        focus = self.get_focus(object_type)
        return focus.manipulation if focus else []

    def get_dont_do_operations(self, object_type: str) -> list[str]:
        focus = self.get_focus(object_type)
        return focus.dont_do_operations if focus else []

    def get_constraints(self, object_type: str) -> list[ObjectConstraint]:
        """Get ontology constraints for an object type from this role."""
        focus = self.get_focus(object_type)
        return focus.as_constraints() if focus else []

    def get_actions(self, object_type: str) -> list[ObjectAction]:
        """Get ontology actions for an object type from this role."""
        focus = self.get_focus(object_type)
        return focus.as_actions() if focus else []


# ——— Pre-defined roles ———

DEFAULT_ROLE = Role(
    name="general-assistant",
    description="通用编程助手",
    focus_objects=[
        ObjectFocus(
            object_type="file",
            observation=["read_file", "list_directory", "search_content"],
            manipulation=["write_file", "delete_file", "rename_file"],
            dont_do_operations=["delete_system_file"],
        ),
        ObjectFocus(
            object_type="git-repo",
            observation=["git_status", "git_diff", "git_log"],
            manipulation=["git_commit", "git_branch", "git_checkout"],
            dont_do_operations=["git_push_force", "git_reset_hard"],
        ),
        ObjectFocus(
            object_type="database",
            observation=["db_describe", "db_query_select"],
            manipulation=["db_query_write", "db_migrate"],
            dont_do_operations=["drop_table", "truncate_table"],
        ),
    ],
    behavior_rules=[
        "修改代码前先读文件",
        "数据库写操作前备份",
        "提交前运行测试",
    ],
)
