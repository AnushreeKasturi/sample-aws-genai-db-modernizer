"""The Strands Bedrock model every role builds (see ``src/shared/models.py``).

Strands answers a structured-output turn that ended without the output tool by
retrying with a forced ``tool_choice`` and dropping ``thinking`` from the
request. That retry is not valid on every family, so this subclass adjusts it
per :class:`~src.shared.models.ModelProfile`:

* ``accepted``: unchanged (today's 4.x behaviour);
* ``needs_thinking_disabled``: the forced turn sends ``thinking: {type: "disabled"}``;
* ``rejected``: the forced choice goes out as ``auto``, with Strands' own
  "use the tool" instruction still in the conversation.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from strands.models.bedrock import BedrockModel
from strands.types.content import Messages
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolChoice, ToolChoiceAuto, ToolChoiceAutoDict, ToolSpec

from src.shared.models import ModelProfile

logger = logging.getLogger(__name__)

_FORCED_KEYS = ("any", "tool")

# The Sonnet 5 forced-turn fix overrides this private Strands method. If a
# Strands release renames it, the override would silently stop applying, so
# fail at import instead (the AWS Transform image installs Strands without the
# lock file; src/atx_orchestrator/requirements.txt bounds the version too).
_OVERRIDDEN_PRIVATE_METHODS = ("_get_additional_request_fields",)
_missing = [name for name in _OVERRIDDEN_PRIVATE_METHODS if not hasattr(BedrockModel, name)]
if _missing:
    raise ImportError(
        "strands.models.bedrock.BedrockModel no longer has "
        + ", ".join(_missing)
        + "; src/shared/role_bedrock_model.py overrides it to keep Strands' forced "
        "structured-output retry valid per model family. Update the override for this "
        "Strands version."
    )


def is_forced(tool_choice: ToolChoice | None) -> bool:
    """True for ``any`` or a named ``tool`` choice (the forced kinds)."""
    return tool_choice is not None and any(key in tool_choice for key in _FORCED_KEYS)


class RoleBedrockModel(BedrockModel):
    """A ``BedrockModel`` whose forced ``tool_choice`` follows the model family."""

    def __init__(self, *, profile: ModelProfile, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.profile = profile

    def safe_tool_choice(self, tool_choice: ToolChoice | None) -> ToolChoice | None:
        """``auto`` in place of a forced choice when the family rejects it."""
        if self.profile.forced_tool_choice == "rejected" and is_forced(tool_choice):
            logger.info("Forced tool_choice not supported by %s; sending auto", self.profile.family)
            auto: ToolChoiceAutoDict = {"auto": ToolChoiceAuto()}
            return auto
        return tool_choice

    async def stream(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        *,
        tool_choice: ToolChoice | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamEvent, None]:
        async for event in super().stream(
            messages,
            tool_specs,
            system_prompt,
            tool_choice=self.safe_tool_choice(tool_choice),
            **kwargs,
        ):
            yield event

    def _get_additional_request_fields(self, tool_choice: ToolChoice | None) -> dict[str, Any]:
        fields: dict[str, Any] = super()._get_additional_request_fields(tool_choice)
        if self.profile.forced_tool_choice == "needs_thinking_disabled" and is_forced(tool_choice):
            extra = dict(fields.get("additionalModelRequestFields", {}))
            extra["thinking"] = {"type": "disabled"}
            return {"additionalModelRequestFields": extra}
        return fields
