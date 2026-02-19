from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Protocol

import httpx
from ollama import Client, ResponseError


LOG = logging.getLogger(__name__)


class JsonChatModel(Protocol):
    def chat_json(
        self,
        prompt_name: str,
        system_prompt: str,
        user_prompt: str,
        *,
        required_keys: tuple[str, ...] = (),
    ) -> dict:
        ...


class JsonResponseError(RuntimeError):
    pass


CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
JSON_REPAIR_PROMPT_VARIANTS: tuple[tuple[str, str], ...] = (
    (
        "rewrite",
        "Rewrite the user's response into one valid JSON object. "
        "Return JSON only with no markdown and no commentary.",
    ),
    (
        "repair",
        "Repair the user's malformed JSON into one valid JSON object. "
        "Return JSON only with no markdown and no commentary. "
        "Do not leave strings unterminated, and escape inner quotes, backslashes, and newlines correctly. "
        "Preserve the original content when possible, but prioritize valid JSON if the source is broken.",
    ),
)
JSON_STRING_CLOSERS = {",", "}", "]", ":"}


def _candidate_json_payloads(content: str) -> list[str]:
    stripped = (content or "").strip()
    if not stripped:
        return []

    candidates: list[str] = [stripped]
    fenced = CODE_FENCE_RE.match(stripped)
    if fenced:
        candidates.append(fenced.group(1).strip())

    object_start = stripped.find("{")
    if object_start >= 0:
        candidates.append(stripped[object_start:])

    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def _sanitize_json_string_issues(candidate: str) -> str:
    sanitized: list[str] = []
    in_string = False
    escaped = False

    for index, char in enumerate(candidate):
        if not in_string:
            sanitized.append(char)
            if char == '"':
                in_string = True
            continue

        if escaped:
            sanitized.append(char)
            escaped = False
            continue

        if char == "\\":
            sanitized.append(char)
            escaped = True
            continue

        if char == '"':
            lookahead = index + 1
            while lookahead < len(candidate) and candidate[lookahead].isspace():
                lookahead += 1
            if lookahead == len(candidate) or candidate[lookahead] in JSON_STRING_CLOSERS:
                in_string = False
                sanitized.append(char)
            else:
                sanitized.append('\\"')
            continue

        if char == "\n":
            sanitized.append("\\n")
            continue
        if char == "\r":
            sanitized.append("\\r")
            continue
        if char == "\t":
            sanitized.append("\\t")
            continue

        sanitized.append(char)

    if in_string:
        sanitized.append('"')

    return "".join(sanitized)


def _parse_json_object(content: str) -> dict:
    decoder = json.JSONDecoder()
    last_error: Exception | None = None

    for candidate in _candidate_json_payloads(content):
        parse_variants = [candidate]
        sanitized = _sanitize_json_string_issues(candidate)
        if sanitized != candidate:
            parse_variants.append(sanitized)

        for parse_candidate in parse_variants:
            try:
                parsed = json.loads(parse_candidate)
            except json.JSONDecodeError as exc:
                last_error = exc
            else:
                if isinstance(parsed, dict):
                    return parsed
                last_error = JsonResponseError(f"Expected JSON object, got {type(parsed).__name__}")
                continue

            try:
                parsed, _ = decoder.raw_decode(parse_candidate)
            except json.JSONDecodeError as exc:
                last_error = exc
                continue
            if isinstance(parsed, dict):
                return parsed
            last_error = JsonResponseError(f"Expected JSON object, got {type(parsed).__name__}")

    raise JsonResponseError("Failed to parse JSON object") from last_error


def _validate_required_keys(payload: dict, required_keys: tuple[str, ...]) -> None:
    missing = [key for key in required_keys if key not in payload]
    if missing:
        raise JsonResponseError(f"Missing required keys: {missing}")


def _ollama_chat(
    *,
    model: str,
    messages: list[dict[str, str]],
    format: str,
    timeout: float,
    think: bool | None = False,
    options: dict[str, object] | None = None,
):
    client = Client(timeout=timeout)
    return client.chat(model=model, messages=messages, format=format, think=think, options=options)


@dataclass
class OllamaJsonClient:
    model: str = "gemma4:26b"
    max_retries: int = 3
    fallback_model: str | None = None
    fallback_retries: int = 2
    request_timeout_seconds: float = 120.0
    transport_retries: int = 1
    think: bool | None = False
    request_options: dict[str, object] | None = None

    def _effective_request_options(self, prompt_name: str | None = None) -> dict[str, object]:
        options: dict[str, object] = {
            "temperature": 0,
            "num_predict": 128,
        }
        if prompt_name == "candidate-window":
            options["num_predict"] = 256
        elif prompt_name == "candidate-window-batch":
            options["num_predict"] = 512
        if self.request_options:
            options.update(self.request_options)
        return options

    def _model_attempt_plan(self) -> list[tuple[str, int]]:
        plan: list[tuple[str, int]] = [(self.model, self.max_retries)]
        if self.fallback_model and self.fallback_model != self.model and self.fallback_retries > 0:
            plan.append((self.fallback_model, self.fallback_retries))
        return plan

    def _json_keys_instruction(self, required_keys: tuple[str, ...]) -> str:
        if not required_keys:
            return ""
        keys_hint = ", ".join(required_keys)
        return f" Use exactly these top-level keys: {keys_hint}."

    def _json_repair_attempt_plan(self, preferred_model_name: str) -> list[tuple[str, str]]:
        models = [preferred_model_name]
        models.extend(model_name for model_name, _ in self._model_attempt_plan() if model_name != preferred_model_name)
        return [
            (model_name, prompt_variant)
            for prompt_variant, _prompt_text in JSON_REPAIR_PROMPT_VARIANTS
            for model_name in models
        ]

    def _chat_response(self, *, prompt_name: str, model_name: str, messages: list[dict[str, str]]):
        transport_attempts = max(1, self.transport_retries + 1)
        for transport_attempt in range(1, transport_attempts + 1):
            try:
                return _ollama_chat(
                    model=model_name,
                    messages=messages,
                    format="json",
                    timeout=self.request_timeout_seconds,
                    think=self.think,
                    options=self._effective_request_options(prompt_name),
                )
            except httpx.TimeoutException as exc:
                if transport_attempt < transport_attempts:
                    LOG.warning(
                        "LLM transport timeout prompt=%s model=%s transport_attempt=%s/%s timeout=%ss; retrying",
                        prompt_name,
                        model_name,
                        transport_attempt,
                        transport_attempts,
                        self.request_timeout_seconds,
                    )
                    continue
                raise JsonResponseError(f"LLM request timed out after {self.request_timeout_seconds:g}s") from exc
            except httpx.TransportError as exc:
                if transport_attempt < transport_attempts:
                    LOG.warning(
                        "LLM transport error prompt=%s model=%s transport_attempt=%s/%s error=%s; retrying",
                        prompt_name,
                        model_name,
                        transport_attempt,
                        transport_attempts,
                        exc,
                    )
                    continue
                raise JsonResponseError(f"LLM request failed: {exc}") from exc
            except (httpx.HTTPError, ResponseError) as exc:
                raise JsonResponseError(f"LLM request failed: {exc}") from exc

    def _rewrite_json_object(
        self,
        *,
        preferred_model_name: str,
        prompt_name: str,
        broken_content: str,
        required_keys: tuple[str, ...],
    ) -> dict:
        last_error: Exception | None = None
        keys_instruction = self._json_keys_instruction(required_keys)

        for model_name, prompt_variant in self._json_repair_attempt_plan(preferred_model_name):
            prompt_text = dict(JSON_REPAIR_PROMPT_VARIANTS)[prompt_variant]
            LOG.warning(
                "Repairing invalid JSON prompt=%s model=%s variant=%s required_keys=%s",
                prompt_name,
                model_name,
                prompt_variant,
                required_keys,
            )
            try:
                response = self._chat_response(
                    prompt_name=prompt_name,
                    model_name=model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": f"{prompt_text}{keys_instruction}",
                        },
                        {
                            "role": "user",
                            "content": f"Original response:\n{broken_content}",
                        },
                    ],
                )
            except JsonResponseError as exc:
                last_error = exc
                LOG.warning(
                    "LLM JSON repair request failed prompt=%s model=%s variant=%s error=%s",
                    prompt_name,
                    model_name,
                    prompt_variant,
                    exc,
                )
                continue

            repaired_content = response.message.content if response.message else ""
            LOG.info(
                "LLM JSON repair response prompt=%s model=%s variant=%s\n%s",
                prompt_name,
                model_name,
                prompt_variant,
                repaired_content,
            )
            try:
                repaired = _parse_json_object(repaired_content)
                _validate_required_keys(repaired, required_keys)
            except JsonResponseError as exc:
                last_error = exc
                LOG.warning(
                    "LLM JSON repair validation failed prompt=%s model=%s variant=%s error=%s",
                    prompt_name,
                    model_name,
                    prompt_variant,
                    exc,
                )
                continue
            return repaired

        raise JsonResponseError("Failed to repair JSON object") from last_error

    def chat_json(
        self,
        prompt_name: str,
        system_prompt: str,
        user_prompt: str,
        *,
        required_keys: tuple[str, ...] = (),
    ) -> dict:
        last_error: Exception | None = None
        attempt_plan = self._model_attempt_plan()
        for model_name, attempts in attempt_plan:
            content = ""
            if model_name != self.model:
                LOG.warning(
                    "Escalating prompt=%s from model=%s to fallback model=%s",
                    prompt_name,
                    self.model,
                    model_name,
                )
            for attempt in range(1, attempts + 1):
                LOG.info(
                    "LLM request prompt=%s attempt=%s model=%s\nSYSTEM:\n%s\nUSER:\n%s",
                    prompt_name,
                    attempt,
                    model_name,
                    system_prompt,
                    user_prompt,
                )
                try:
                    response = self._chat_response(
                        prompt_name=prompt_name,
                        model_name=model_name,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                    )
                except JsonResponseError as exc:
                    last_error = exc
                    LOG.warning(
                        "LLM request failed prompt=%s attempt=%s model=%s error=%s",
                        prompt_name,
                        attempt,
                        model_name,
                        exc,
                    )
                    continue
                content = response.message.content if response.message else ""
                LOG.info("LLM response prompt=%s attempt=%s model=%s\n%s", prompt_name, attempt, model_name, content)
                try:
                    parsed = _parse_json_object(content)
                    _validate_required_keys(parsed, required_keys)
                except JsonResponseError as exc:
                    last_error = exc
                    LOG.warning(
                        "LLM JSON validation failed prompt=%s attempt=%s model=%s error=%s",
                        prompt_name,
                        attempt,
                        model_name,
                        exc,
                    )
                    continue
                return parsed
            if model_name == attempt_plan[-1][0] and content:
                try:
                    return self._rewrite_json_object(
                        preferred_model_name=model_name,
                        prompt_name=prompt_name,
                        broken_content=content,
                        required_keys=required_keys,
                    )
                except JsonResponseError as exc:
                    last_error = exc
                    LOG.warning(
                        "LLM JSON rewrite failed prompt=%s model=%s error=%s",
                        prompt_name,
                        model_name,
                        exc,
                    )

        raise JsonResponseError(f"Failed to get valid JSON for prompt {prompt_name}") from last_error
