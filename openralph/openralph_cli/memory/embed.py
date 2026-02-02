from __future__ import annotations
import json
import urllib.request

def ollama_embed(ollama_host: str, model: str, text: str) -> list[float]:
    payload = {"model": model, "prompt": text}
    for endpoint in ("/api/embeddings", "/api/embed"):
        url = f"{ollama_host}{endpoint}"
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
                return [float(x) for x in data["embedding"]]
            if "embeddings" in data and isinstance(data["embeddings"], list) and data["embeddings"]:
                return [float(x) for x in data["embeddings"][0]]
        except Exception:
            continue
    raise RuntimeError("Failed to get embedding from Ollama. Check OLLAMA_HOST and model name.")
