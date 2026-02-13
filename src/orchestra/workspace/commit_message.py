from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)

COMMIT_MESSAGE_PROMPT = """\
Generate a conventional commit message for the following git diff.

Agent intent: {intent}

Staged diff:
```
{diff}
```

Rules:
- First line: imperative summary under 72 characters (e.g. "feat: add login endpoint")
- Blank line after summary
- Brief description (1-3 lines) of what changed and why
- Use conventional commit prefixes: feat, fix, refactor, chore, docs, test, style
- Do NOT include any markdown formatting or code blocks
- Output ONLY the commit message, nothing else
"""


class CommitMessageGenerator(Protocol):
    def generate(self, diff: str, intent: str) -> str: ...


class LLMCommitMessageGenerator:
    def __init__(self, chat_model: Any) -> None:
        self._chat_model = chat_model

    def generate(self, diff: str, intent: str) -> str:
        try:
            from langchain_core.messages import HumanMessage

            truncated_diff = diff[:4000] if len(diff) > 4000 else diff
            prompt = COMMIT_MESSAGE_PROMPT.format(intent=intent, diff=truncated_diff)
            response = self._chat_model.invoke([HumanMessage(content=prompt)])
            message = response.content.strip()
            if not message:
                return DeterministicCommitMessageGenerator().generate(diff, intent)
            return message
        except Exception:
            logger.warning("LLM commit message generation failed, using fallback")
            return DeterministicCommitMessageGenerator().generate(diff, intent)


class DeterministicCommitMessageGenerator:
    def generate(self, diff: str, intent: str) -> str:
        lines = diff.strip().split("\n") if diff.strip() else []
        file_set: list[str] = []
        for line in lines:
            if line.startswith("diff --git"):
                parts = line.split(" b/")
                if len(parts) > 1:
                    file_set.append(parts[-1])
        file_list = ", ".join(file_set) if file_set else "agent changes"
        return f"chore: auto-commit agent changes\n\nFiles: {file_list}"


def build_commit_message_generator(config: Any) -> CommitMessageGenerator:
    from orchestra.config.providers import get_provider_settings, resolve_model, resolve_provider

    provider_name = resolve_provider("", config.providers)
    model_name = resolve_model("cheap", provider_name, config.providers)

    if model_name == "cheap" and not provider_name:
        from orchestra.workspace.session_branch import WorkspaceError

        raise WorkspaceError(
            "No 'cheap' model alias configured. Add a 'cheap' model alias "
            "to your providers config in orchestra.yaml for commit message generation."
        )

    settings = get_provider_settings(provider_name, config.providers)

    if provider_name == "anthropic":
        from langchain_anthropic import ChatAnthropic

        chat_model = ChatAnthropic(
            model=model_name,
            max_tokens=256,
            **{k: v for k, v in settings.items() if k in ("max_tokens",)},
        )
    elif provider_name == "openai":
        from langchain_openai import ChatOpenAI

        chat_model = ChatOpenAI(
            model=model_name,
            **{k: v for k, v in settings.items() if k in ("max_tokens",)},
        )
    else:
        from langchain_openai import ChatOpenAI

        api_base = settings.get("api_base", "")
        kwargs: dict[str, Any] = {"model": model_name}
        if api_base:
            kwargs["base_url"] = api_base
        chat_model = ChatOpenAI(**kwargs)

    return LLMCommitMessageGenerator(chat_model)
