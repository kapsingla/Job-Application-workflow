from __future__ import annotations

import json
import re
from typing import Optional, Type, TypeVar
from pydantic import BaseModel
from src.config import GEMINI_API_KEY, GEMINI_PRO_MODEL

T = TypeVar("T", bound=BaseModel)


def _extract_json_object(raw_text: str) -> str:
    """Extracts the first valid JSON object from markdown fences or raw text."""
    text = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


async def generate_structured(
    prompt: str,
    schema: Type[T],
    system_instruction: Optional[str] = None,
    model_name: str = GEMINI_PRO_MODEL,
    temperature: float = 0.2,
    thinking_budget: Optional[int] = None,
) -> T:
    """
    Executes a structured-output LLM call powered by Google Antigravity (`google.antigravity.Agent`)
    using your active Antigravity session (no GEMINI_API_KEY required).
    When `thinking_budget` is set (e.g. for `recruiter_critic`), enables maximum deep reasoning.
    Falls back to `google-genai` with `ThinkingConfig(thinking_budget=...)` if `GEMINI_API_KEY` is used.
    """
    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    reasoning_directive = (
        "\nDEEP REASONING MODE ENABLED: Perform exhaustive, step-by-step executive analysis before generating the final JSON verdict.\n"
        if thinking_budget
        else ""
    )
    full_system = (
        f"{system_instruction.strip()}\n\n" if system_instruction else ""
    ) + (
        f"{reasoning_directive}"
        "CRITICAL OUTPUT FORMAT REQUIREMENT:\n"
        "You must respond with ONLY a single valid JSON object matching the exact JSON Schema below. "
        "Do NOT wrap in markdown explanations or add any text outside the JSON object.\n\n"
        f"JSON SCHEMA:\n{schema_json}"
    )

    # Primary Path: Run through Google Antigravity SDK (uses local Antigravity auth/runtime)
    try:
        from google.antigravity import Agent, LocalAgentConfig

        config = LocalAgentConfig(
            system_instructions=full_system,
        )
        async with Agent(config) as agent:
            response = await agent.chat(prompt)
            chunks: list[str] = []
            async for token in response:
                chunks.append(token)
            raw_output = "".join(chunks)
            cleaned_json = _extract_json_object(raw_output)
            return schema.model_validate_json(cleaned_json)
    except ImportError as import_err:
        if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
            raise RuntimeError(
                "google-antigravity SDK is not installed in this Python environment and no GEMINI_API_KEY is set. "
                "Install it with `pip install google-antigravity` or run the harness directly inside Antigravity Chat."
            ) from import_err

    # Fallback Path: google-genai with explicit ThinkingConfig for high-reasoning agents
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    config_kwargs = {
        "response_mime_type": "application/json",
        "response_schema": schema,
        "temperature": temperature,
    }
    if system_instruction:
        config_kwargs["system_instruction"] = system_instruction
    if thinking_budget:
        config_kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_budget=thinking_budget
        )

    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    return schema.model_validate_json(response.text)
