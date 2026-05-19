"""Shared Anthropic client for agent modules."""

from __future__ import annotations

import os
import time

from anthropic import APIConnectionError, APITimeoutError, Anthropic
from dotenv import load_dotenv

load_dotenv()


class LLMClient:
    """Small wrapper so agents can share one Claude client interface."""

    def __init__(self) -> None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        # 여러 Agent가 같은 Claude 클라이언트를 재사용하도록 공통 래퍼를 둡니다.
        # 네트워크가 잠깐 흔들려도 바로 실패하지 않게 timeout을 조금 넉넉하게 둡니다.
        self.client = Anthropic(api_key=api_key, timeout=90.0)

    def ask(self, prompt: str, model: str = "claude-sonnet-4-6", max_tokens: int = 500) -> str:
        # Claude 요청은 최대 3번까지 재시도합니다.
        # 연결/타임아웃 계열 오류만 재시도하고, 그 외 오류는 즉시 올립니다.
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self.client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text
            except (APITimeoutError, APIConnectionError) as error:
                last_error = error
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("Claude response was not returned.")
