"""Small Groq client (OpenAI-compatible API) with a strict JSON helper."""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .config import settings


class LLMError(RuntimeError):
    pass


def chat(prompt: str, *, system: str = "", temperature: float = 0.7, json_mode: bool = False,
         timeout: float = 60.0) -> str:
    if not settings.groq_api_key:
        raise LLMError("GROQ_API_KEY is not set.")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body: dict[str, Any] = {
        "model": settings.groq_model,
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        r = httpx.post(
            f"{settings.groq_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            json=body,
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not reach the AI service: {exc}") from exc
    if r.status_code == 400 and json_mode:
        # Some models don't support JSON mode; the prompt already asks for JSON, so retry without it.
        return chat(prompt, system=system, temperature=temperature, json_mode=False, timeout=timeout)
    if r.status_code == 429:
        raise LLMError("The AI service is busy right now. Try again in a minute.")
    if r.status_code >= 400:
        raise LLMError(f"AI service error {r.status_code}: {r.text[:200]}")
    try:
        return r.json()["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, ValueError) as exc:
        raise LLMError("The AI service sent back an unexpected response.") from exc


def parse_json(text: str) -> Any:
    """Parse JSON from a model reply, tolerating code fences or text around it."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except ValueError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start, end = text.find(open_c), text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                continue
    raise LLMError("The AI reply was not valid JSON.")


def chat_json(prompt: str, *, system: str = "", temperature: float = 0.7, retries: int = 1,
              timeout: float = 60.0) -> Any:
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            return parse_json(chat(prompt, system=system, temperature=temperature, json_mode=True,
                                   timeout=timeout))
        except LLMError as exc:
            last = exc
            if "busy" in str(exc) or "reach" in str(exc):
                break
    raise last or LLMError("Unknown AI error")
