from __future__ import annotations

import json
import os
import random
import re
import signal
import socket
import string
import sys
import threading
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProxyConfig:
    listen_port: int = 18889
    target_host: str = "127.0.0.1"
    target_port: int = 30000
    target_model: str = "openai/gpt-oss-120b"


def _generate_call_id() -> str:
    return "call_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=9))


def _extract_reasoning(content: str) -> tuple[str | None, str]:
    pattern = r"<\|channel\|>analysis<\|message\|>([\s\S]*?)<\|end\|>"
    match = re.search(pattern, content, re.IGNORECASE)
    if match:
        reasoning = match.group(1).strip()
        cleaned = re.sub(pattern, "", content, flags=re.IGNORECASE).strip()
        return reasoning, cleaned
    return None, content


def _clean_sglang_tags(content: str) -> str:
    content = re.sub(r"<\|start\|>assistant<\|channel\|>", "", content)
    # Strip multi-word tag sequences like <|channel|>analysis or <|end|><|call|>
    content = re.sub(r"(<\|[^|>]+\|>)+", "", content)
    return content.strip()


def _extract_tool_calls(content: str) -> tuple[list[dict], str | None]:
    tool_calls: list[dict] = []

    # Primary pattern: handles optional prefix words before to=functions.name
    # Also tolerates residual SGLang tags between function name and JSON brace
    tool_patterns = [
        re.compile(
            r"(?:commentary|analysis|assistantcommentary|analysiscommentary|assistant|final)?\s*"
            r"to=(?:functions\.)?(\w+)\s*(?:json|code)?\s*(?:<\|[^|>]+\|>)*\s*\{",
            re.IGNORECASE,
        ),
        # Fallback: bare to=name { without any prefix
        re.compile(
            r"to=(?:functions\.)?(\w+)\s*(?:<\|[^|>]+\|>)*\s*\{",
            re.IGNORECASE,
        ),
    ]

    first_tool_idx = -1
    text_content = ""

    for pattern in tool_patterns:
        pos = 0
        while True:
            match = pattern.search(content, pos)
            if not match:
                break

            if first_tool_idx == -1:
                first_tool_idx = match.start()
                text_content = content[:first_tool_idx].strip()

            function_name = match.group(1)
            start_brace = content.find("{", match.start())

            if start_brace == -1:
                pos = match.end()
                continue

            brace_count = 0
            json_end = -1
            for i in range(start_brace, len(content)):
                if content[i] == "{":
                    brace_count += 1
                elif content[i] == "}":
                    brace_count -= 1
                if brace_count == 0:
                    json_end = i
                    break

            if json_end == -1:
                pos = match.end()
                continue

            args_str = content[start_brace : json_end + 1]
            tool_calls.append(
                {
                    "index": len(tool_calls),
                    "id": _generate_call_id(),
                    "type": "function",
                    "function": {"name": function_name, "arguments": args_str},
                }
            )
            pos = json_end + 1

        # If the first pattern found results, don't try the fallback
        if tool_calls:
            break

    if tool_calls:
        cleaned_text = re.sub(
            r"^(commentary|analysis|assistantcommentary|analysiscommentary|assistant|final)[:\s\.]*",
            "",
            text_content,
            flags=re.IGNORECASE,
        ).strip()
        return tool_calls, cleaned_text if cleaned_text else None

    return [], None


def _clean_message_prefix(content: str) -> str:
    return re.sub(
        r"^(commentary|analysis|assistantcommentary|analysiscommentary|assistant|final)[:\s]*",
        "",
        content,
        flags=re.IGNORECASE | re.MULTILINE,
    ).strip()


def _transform_request(body: str, config: ProxyConfig) -> tuple[str, str, bool]:
    original_model = ""
    client_wants_stream = False

    try:
        data = json.loads(body)
        if "model" in data:
            original_model = data["model"]
            data["model"] = config.target_model
        if data.get("stream"):
            client_wants_stream = True
            data["stream"] = False
        return json.dumps(data), original_model, client_wants_stream
    except json.JSONDecodeError:
        return body, "", False


def _transform_response(
    body: str, original_model: str, client_wants_stream: bool
) -> tuple[str | list[str], bool]:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return body, False

    if original_model:
        data["model"] = original_model
    data.pop("metadata", None)

    if "choices" in data and data["choices"]:
        choice = data["choices"][0]
        choice.pop("matched_stop", None)

        if "message" in choice:
            content = choice["message"].get("content") or ""

            reasoning, content = _extract_reasoning(content)
            if reasoning:
                choice["message"]["reasoning_content"] = reasoning

            content = _clean_sglang_tags(content)
            tool_calls, text_content = _extract_tool_calls(content)

            if tool_calls:
                choice["message"]["tool_calls"] = tool_calls
                choice["message"]["content"] = text_content
                choice["finish_reason"] = "tool_calls"
            else:
                choice["message"]["content"] = _clean_message_prefix(content)

            if not choice.get("finish_reason") or choice["finish_reason"] in ("null", "stop"):
                choice["finish_reason"] = "tool_calls" if choice["message"].get("tool_calls") else "stop"

    if client_wants_stream:
        chunks: list[str] = []
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})

        first_chunk = {
            "id": data.get("id"),
            "object": "chat.completion.chunk",
            "created": data.get("created"),
            "model": data.get("model"),
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": message.get("content") or ""},
                    "finish_reason": None if message.get("tool_calls") else choice.get("finish_reason"),
                }
            ],
        }
        chunks.append(f"data: {json.dumps(first_chunk)}\n\n")

        if message.get("tool_calls"):
            tool_chunk = {
                "id": data.get("id"),
                "object": "chat.completion.chunk",
                "created": data.get("created"),
                "model": data.get("model"),
                "choices": [
                    {
                        "index": 0,
                        "delta": {"tool_calls": message["tool_calls"]},
                        "finish_reason": choice.get("finish_reason"),
                    }
                ],
            }
            chunks.append(f"data: {json.dumps(tool_chunk)}\n\n")

        chunks.append("data: [DONE]\n\n")
        return chunks, True

    return json.dumps(data), False


class ProxyHandler(BaseHTTPRequestHandler):
    config: ProxyConfig

    def log_message(self, format: str, *args: Any) -> None:
        msg = f"[OpenRalph-Proxy] {format % args}"
        print(msg, file=sys.stderr)

    def do_GET(self) -> None:
        self._proxy_request()

    def do_POST(self) -> None:
        self._proxy_request()

    def do_PUT(self) -> None:
        self._proxy_request()

    def do_DELETE(self) -> None:
        self._proxy_request()

    def do_OPTIONS(self) -> None:
        self._proxy_request()

    def _proxy_request(self) -> None:
        config = self.config
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else ""

        self.log_message("Incoming: %s %s", self.command, self.path)

        clean_body = body
        original_model = ""
        client_wants_stream = False

        if self.command == "POST" and body:
            clean_body, original_model, client_wants_stream = _transform_request(body, config)

        target_url = f"http://{config.target_host}:{config.target_port}{self.path}"
        headers = dict(self.headers)
        headers["Host"] = f"{config.target_host}:{config.target_port}"
        headers["Content-Length"] = str(len(clean_body.encode("utf-8")))

        try:
            req = urllib.request.Request(
                target_url,
                data=clean_body.encode("utf-8") if clean_body else None,
                headers=headers,
                method=self.command,
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                response_body = resp.read().decode("utf-8")
                response_headers = dict(resp.headers)
                status_code = resp.status
        except urllib.error.HTTPError as e:
            response_body = e.read().decode("utf-8") if e.fp else ""
            response_headers = dict(e.headers) if e.headers else {}
            status_code = e.code
        except urllib.error.URLError as e:
            self.send_error(502, f"Proxy Error: {e.reason}")
            return
        except Exception as e:
            self.send_error(502, f"Proxy Error: {e}")
            return

        content_type = response_headers.get("Content-Type", "")
        is_json_ct = "application/json" in content_type
        if not is_json_ct and response_body.lstrip().startswith("{"):
            is_json_ct = True
        if is_json_ct:
            result, is_stream = _transform_response(response_body, original_model, client_wants_stream)

            if is_stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                for chunk in result:  # type: ignore[union-attr]
                    self.wfile.write(chunk.encode("utf-8"))
            else:
                final_body = result.encode("utf-8") if isinstance(result, str) else b"".join(c.encode() for c in result)
                self.send_response(status_code)
                for k, v in response_headers.items():
                    if k.lower() not in ("content-length", "transfer-encoding"):
                        self.send_header(k, v)
                self.send_header("Content-Length", str(len(final_body)))
                self.end_headers()
                self.wfile.write(final_body)
        else:
            self.send_response(status_code)
            for k, v in response_headers.items():
                if k.lower() != "transfer-encoding":
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(response_body.encode("utf-8"))


class ProxyServer:
    def __init__(self, config: ProxyConfig):
        self.config = config
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self, daemon: bool = True) -> None:
        handler = ProxyHandler
        handler.config = self.config

        self._server = HTTPServer(("0.0.0.0", self.config.listen_port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=daemon)
        self._thread.start()
        print(f"[OpenRalph-Proxy] Listening on port {self.config.listen_port}", file=sys.stderr)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def serve_forever(self) -> None:
        handler = ProxyHandler
        handler.config = self.config

        self._server = HTTPServer(("0.0.0.0", self.config.listen_port), handler)
        print(f"[OpenRalph-Proxy] Listening on port {self.config.listen_port}", file=sys.stderr)
        self._server.serve_forever()


def start_proxy_background(config: ProxyConfig, pid_file: Path, log_file: Path | None = None) -> int:
    if sys.platform.startswith("win"):
        return _start_proxy_background_windows(config, pid_file, log_file)
    return _start_proxy_background_unix(config, pid_file, log_file)


def _start_proxy_background_unix(config: ProxyConfig, pid_file: Path, log_file: Path | None = None) -> int:
    pid = os.fork()
    if pid > 0:
        time.sleep(0.5)
        if pid_file.exists():
            return int(pid_file.read_text().strip())
        return pid

    os.setsid()
    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)

    os.chdir("/")
    sys.stdin.close()

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_fd = open(log_file, "a", encoding="utf-8")
        os.dup2(log_fd.fileno(), sys.stdout.fileno())
        os.dup2(log_fd.fileno(), sys.stderr.fileno())
    else:
        devnull = open(os.devnull, "w")
        os.dup2(devnull.fileno(), sys.stdout.fileno())
        os.dup2(devnull.fileno(), sys.stderr.fileno())

    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()), encoding="utf-8")

    def cleanup(signum: int, frame: Any) -> None:
        if pid_file.exists():
            pid_file.unlink()
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    server = ProxyServer(config)
    try:
        server.serve_forever()
    except Exception:
        pass
    finally:
        if pid_file.exists():
            pid_file.unlink()
    os._exit(0)


def _start_proxy_background_windows(config: ProxyConfig, pid_file: Path, log_file: Path | None = None) -> int:
    import subprocess

    script = f'''
import sys
sys.path.insert(0, {repr(str(Path(__file__).parent.parent.parent))})
from openralph.openralph_cli.proxy import ProxyServer, ProxyConfig
config = ProxyConfig(
    listen_port={config.listen_port},
    target_host={repr(config.target_host)},
    target_port={config.target_port},
    target_model={repr(config.target_model)},
)
server = ProxyServer(config)
server.serve_forever()
'''

    pid_file.parent.mkdir(parents=True, exist_ok=True)

    kwargs: dict[str, Any] = {
        "creationflags": subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
    }
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_fd = open(log_file, "a", encoding="utf-8")
        kwargs["stdout"] = log_fd
        kwargs["stderr"] = log_fd
    else:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL

    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.DEVNULL,
        **kwargs,
    )
    pid_file.write_text(str(proc.pid), encoding="utf-8")
    return proc.pid


def stop_proxy(pid_file: Path) -> bool:
    if not pid_file.exists():
        return False

    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        pid_file.unlink()
        return False

    try:
        if sys.platform.startswith("win"):
            os.kill(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
        time.sleep(0.5)
    except ProcessLookupError:
        pass
    except PermissionError:
        return False

    if pid_file.exists():
        pid_file.unlink()
    return True


def proxy_status(pid_file: Path, listen_port: int) -> tuple[bool, int | None]:
    if not pid_file.exists():
        return False, None

    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        return False, None

    try:
        if sys.platform.startswith("win"):
            os.kill(pid, 0)
        else:
            os.kill(pid, 0)
    except ProcessLookupError:
        if pid_file.exists():
            pid_file.unlink()
        return False, None
    except PermissionError:
        pass

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("127.0.0.1", listen_port))
        sock.close()
        if result == 0:
            return True, pid
    except Exception:
        pass

    return False, pid


def proxy_is_listening(port: int) -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("127.0.0.1", port))
        sock.close()
        return result == 0
    except Exception:
        return False
