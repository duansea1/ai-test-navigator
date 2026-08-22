from __future__ import annotations

import os
from pathlib import Path


class DshAgentClient:
    """Optional semantic layer. It never starts DSH when no key is configured."""

    def __init__(self, workspace: Path, session_root: Path):
        self.workspace = workspace
        self.session_root = session_root

    def available(self) -> bool:
        return bool(os.getenv("DEEPSEEK_API_KEY", "").strip())

    def run(self, prompt: str) -> str:
        if not self.available():
            return "[fallback] 未配置 DEEPSEEK_API_KEY，跳过 DSH 语义分析。"
        try:
            from deepseek_harness import DeepSeekHarness
            with DeepSeekHarness(cwd=str(self.workspace), session_root=str(self.session_root)) as harness:
                result = harness.run(prompt)
            if result.finish_reason == "error":
                return "[fallback] DSH 回合失败，保留规则分析结果。"
            return result.final_response or "[fallback] DSH 未返回文本。"
        except Exception as exc:  # optional integration must not break offline MVP
            return f"[fallback] DSH 不可用：{type(exc).__name__}"
