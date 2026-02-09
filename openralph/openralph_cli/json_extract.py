from __future__ import annotations

import json
import logging
import re

log = logging.getLogger(__name__)

_FENCED_JSON_RE = re.compile(r"```json\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


def extract_json_object(text: str) -> dict | None:
    value = _extract_json_value(text, "{", "}")
    if isinstance(value, dict):
        return value
    return None


def extract_json_array(text: str) -> list | None:
    value = _extract_json_value(text, "[", "]")
    if isinstance(value, list):
        return value
    return None


def _extract_json_value(text: str, open_char: str, close_char: str):
    raw = (text or "").strip()
    if not raw:
        log.debug("JSON extraction failed: empty text")
        return None

    # 1) Full payload parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 2) Parse fenced json blocks
    for block in _FENCED_JSON_RE.findall(raw):
        try:
            return json.loads(block.strip())
        except json.JSONDecodeError:
            continue

    # 3) Bracket slicing fallback
    start = raw.find(open_char)
    end = raw.rfind(close_char)
    if start != -1 and end != -1 and end > start:
        candidate = raw[start:end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    log.debug("JSON extraction failed: no parseable payload found")
    return None
