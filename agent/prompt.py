"""Prompt assembler. 类比: ELF loader + linker script + DMA."""

from dataclasses import dataclass, field

import structlog

from .output_format import OutputFormatManager

logger = structlog.get_logger()


@dataclass
class PromptInputs:
    """Inputs for prompt assembly."""
    role: str = ""
    behavior_rules: list[str] = field(default_factory=list)
    dont_do_rules: str = ""
    output_format_rules: str = ""
    tool_summaries: str = ""
    memory_context: str = ""
    task: str = ""
    conversation_summary: str = ""
    recent_messages: str = ""
    tool_result: str = ""


class PromptAssembler:
    """Assemble structured prompts in ELF XML format."""

    # System tags that must NEVER appear after user input
    SYSTEM_TAGS = {"<system>", "<constraints>", "<role>", "<function_call>",
                   "<format_rules>"}

    def __init__(self, output_format: OutputFormatManager | None = None):
        self.output_format = output_format or OutputFormatManager()

    def assemble(self, inputs: PromptInputs, reserve_tokens: int = 30000) -> str:
        """Build the full prompt.

        Layout:
          <system>
          <format_rules>
          <constraints>
          <context>
          <tools>
          <task>
          <conversation>
        """
        parts = []

        # TEXT — system prompt (always first)
        parts.append(f"<system>\n{inputs.role}\n</system>")

        # FORMAT_RULES — mandatory output format (immutable system-level)
        format_prompt = inputs.output_format_rules or self.output_format.get_format_prompt()
        if format_prompt:
            parts.append(
                f"<format_rules immutable=\"true\">\n{format_prompt}\n</format_rules>"
            )

        # Behavior rules
        if inputs.behavior_rules:
            rules_text = "\n".join(f"- {r}" for r in inputs.behavior_rules)
            parts.append(f"<behavior_rules>\n{rules_text}\n</behavior_rules>")

        # CONSTRAINTS — dont-do rules
        if inputs.dont_do_rules:
            parts.append(f"<constraints>\n{inputs.dont_do_rules}\n</constraints>")

        # CONTEXT — memory
        if inputs.memory_context:
            parts.append(f"<context>\n{inputs.memory_context}\n</context>")

        # TOOLS — available tools
        if inputs.tool_summaries:
            parts.append(f"<tools>\n{inputs.tool_summaries}\n</tools>")

        # TASK — what to do
        parts.append(f"<task>\n{inputs.task}\n</task>")

        # CONVERSATION — history + latest messages
        conv_parts = []
        if inputs.conversation_summary:
            conv_parts.append(f"<summary>\n{inputs.conversation_summary}\n</summary>")
        if inputs.recent_messages:
            conv_parts.append(inputs.recent_messages)
        if inputs.tool_result:
            conv_parts.append(f"<tool_result>\n{inputs.tool_result}\n</tool_result>")
        if conv_parts:
            parts.append(f"<conversation>\n{''.join(conv_parts)}\n</conversation>")

        return "\n\n".join(parts)

    def sanitize_user_input(self, text: str) -> str:
        """Escape system tags in user input. 类比: copy_from_user()."""
        for tag in self.SYSTEM_TAGS:
            text = text.replace(tag, f"&lt;{tag[1:]}")
            # Also escape closing tags: </system> → &lt;/system>
            close_tag = f"</{tag[1:]}"
            text = text.replace(close_tag, f"&lt;/{tag[1:]}")
        return text

    def wrap_user_input(self, text: str) -> str:
        """Wrap user input in trusted boundary. Always at prompt end."""
        safe = self.sanitize_user_input(text)
        return f"<user_input trusted=\"false\">\n{safe}\n</user_input>"


def format_tool_summary(tools: list) -> str:
    """Format tool list as concise summary for prompt."""
    lines = []
    for t in tools:
        caps = ", ".join(c.name for c in t.capabilities)
        source_hint = f" [来源: {t.source}]" if t.source != "builtin" else ""
        lines.append(f"- {t.name}: {t.description} ({caps}){source_hint}")
    return "\n".join(lines) if lines else "(no tools available)"


class ToolResultManager:
    """DMA-style large result handler. 类比: DMA controller.

    Large tool results (>5000 tokens) are stored in a side channel.
    Only a summary + reference goes into the prompt.
    """

    MAX_PROMPT_TOKENS = 5000

    def __init__(self):
        self._side_channel: dict[str, str] = {}
        self._counter = 0

    def process(self, result: str, token_estimate: int | None = None) -> str:
        """Process a tool result. Large results → side channel."""
        if token_estimate is None:
            token_estimate = len(result) // 4

        if token_estimate <= self.MAX_PROMPT_TOKENS:
            return result

        ref_id = f"result_{self._counter}"
        self._counter += 1
        self._side_channel[ref_id] = result

        lines = result.split("\n")
        preview = "\n".join(lines[:50])
        return (
            f"<large_result id=\"{ref_id}\" size=\"{len(result)} chars\">\n"
            f"<summary>结果较大，显示前 50 行</summary>\n"
            f"<preview>\n{preview}\n</preview>\n"
            f"<hint>用 read_slice(\"{ref_id}\", offset=50) 查看更多</hint>\n"
            f"</large_result>"
        )

    def read_slice(self, ref_id: str, offset: int = 0, limit: int = 100) -> str:
        """Read a slice of a large result."""
        content = self._side_channel.get(ref_id)
        if not content:
            return f"[结果 {ref_id} 已过期或不存在]"
        lines = content.split("\n")[offset:offset + limit]
        return "\n".join(lines)
