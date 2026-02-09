from __future__ import annotations
import json
import urllib.request
import urllib.error

from ..logging import get_logger


def ollama_embed(ollama_host: str, model: str, text: str) -> list[float]:
    log = get_logger("memory.embed")
    payload = {"model": model, "prompt": text}
    errors: list[str] = []

    for endpoint in ("/api/embeddings", "/api/embed"):
        url = f"{ollama_host}{endpoint}"
        log.debug("Trying embedding endpoint: %s", url)
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if "embedding" in data and isinstance(data["embedding"], list):
                log.debug("Got embedding from %s: %d dimensions", endpoint, len(data["embedding"]))
                return [float(x) for x in data["embedding"]]
            if "embeddings" in data and isinstance(data["embeddings"], list) and data["embeddings"]:
                log.debug("Got embedding from %s: %d dimensions", endpoint, len(data["embeddings"][0]))
                return [float(x) for x in data["embeddings"][0]]
            log.debug("Unexpected response format from %s: %s", endpoint, list(data.keys()))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError) as e:
            errors.append(f"{endpoint}: {e}")
            log.debug("Endpoint %s failed: %s", endpoint, e)
            continue

    log.error("All embedding endpoints failed: %s", "; ".join(errors))
    raise RuntimeError("Failed to get embedding from Ollama. Check OLLAMA_HOST and model name.")
