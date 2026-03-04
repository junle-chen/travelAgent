from __future__ import annotations

try:
    from langchain_core.prompts import ChatPromptTemplate
except ImportError:  # pragma: no cover - optional dependency during local bootstrap
    ChatPromptTemplate = None


def render_chat_prompts(system_prompt: str, user_prompt: str) -> tuple[str, str]:
    if ChatPromptTemplate is None:
        return system_prompt, user_prompt

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "{system_prompt}"),
            ("human", "{user_prompt}"),
        ]
    )
    messages = prompt.format_messages(system_prompt=system_prompt, user_prompt=user_prompt)
    system_value = str(messages[0].content) if messages else system_prompt
    user_value = str(messages[1].content) if len(messages) > 1 else user_prompt
    return system_value, user_value
