"""Claude as an arena contestant or judge (anthropic:<model>, e.g. anthropic:claude-sonnet-5).

Uses the official Anthropic SDK (anthropic, pinned in requirements.txt). Credentials come from the SDK's own
resolution: ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile; nothing is written by GaaR.
The model is hosted, so the arena's egress rule applies: it sees constructed cases only, never real evidence.
Sonnet 5 rejects sampling parameters, so none are sent; it thinks adaptively by default.
"""
from __future__ import annotations

from .contestants import Contestant


class Claude(Contestant):
    local = False
    family = "claude"

    def __init__(self, model: str):
        self.model, self.name = model, f"anthropic:{model}"

    def raw(self, prompt: str) -> str:
        import anthropic
        message = anthropic.Anthropic().messages.create(
            model=self.model, max_tokens=16000, output_config={"effort": "medium"},
            messages=[{"role": "user", "content": prompt}])
        if message.stop_reason == "refusal":
            raise RuntimeError(f"the model declined the case ({getattr(message.stop_details, 'category', None)})")
        return "".join(block.text for block in message.content if block.type == "text")
