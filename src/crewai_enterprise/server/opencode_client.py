import json
import requests
import logging
from typing import List, Dict, Any, Optional
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class OpenCodeClient:
    def __init__(self, base_url: str, api_key: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.retry_session = requests.Session()  # Session WITH retries

        # Setup retries for prompt_async (15s timeout, 3 retries: 2s, 5s, 10s)
        retry_strategy = Retry(
            total=3,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.retry_session.mount("http://", adapter)
        self.retry_session.mount("https://", adapter)

        if api_key:
            self.session.headers.update({"Authorization": f"Bearer {api_key}"})
            self.retry_session.headers.update({"Authorization": f"Bearer {api_key}"})

    def prompt_async(
        self,
        session_id: str,
        parts: List[Dict[str, Any]],
        message_id: str,
        directory: Optional[str] = None,
    ):
        """Silent sync (noReply=true) with 15s timeout and retries."""
        url = f"{self.base_url}/session/{session_id}/prompt_async"
        body = {
            "messageID": message_id,
            "noReply": True,
            "parts": parts,
            "agent": "sisyphus",
        }
        params = {"directory": directory} if directory else None

        try:
            response = self.retry_session.post(
                url, json=body, params=params, timeout=15
            )
            response.raise_for_status()
            return response
        except Exception as e:
            logger.error(f"OpenCode async sync failed: {e}")
            raise

    def prompt_interactive(
        self,
        session_id: str,
        parts: List[Dict[str, Any]],
        message_id: str,
        directory: Optional[str] = None,
    ):
        """Standard POST with retry support."""
        url = f"{self.base_url}/session/{session_id}/message"
        body = {
            "messageID": message_id,
            "noReply": False,
            "parts": parts,
            "agent": "sisyphus",
        }
        params = {"directory": directory} if directory else None

        response = self.retry_session.post(url, json=body, params=params, timeout=60)
        response.raise_for_status()
        return response

    def stream_interactive(
        self,
        session_id: str,
        parts: List[Dict[str, Any]],
        message_id: str,
        directory: Optional[str] = None,
    ):
        """Streaming POST with safe initial-retry (no retry after bytes received)."""
        url = f"{self.base_url}/session/{session_id}/message"
        body = {
            "messageID": message_id,
            "noReply": False,
            "parts": parts,
            "agent": "sisyphus",
            "stream": True,
        }
        params = {"directory": directory} if directory else None

        max_attempts = 2  # initial try + one safe retry before any bytes are received
        last_error: Exception | None = None
        for attempt in range(max_attempts):
            response = None
            buffer = ""
            received_any = False
            try:
                response = self.session.post(
                    url, json=body, params=params, timeout=300, stream=True
                )
                response.raise_for_status()

                for line in response.iter_lines():
                    received_any = True
                    if not line:
                        # An empty line signals the end of an event in SSE
                        if buffer:
                            try:
                                yield json.loads(buffer)
                            except json.JSONDecodeError:
                                logger.warning(f"Failed to parse SSE buffer: {buffer}")
                        buffer = ""
                        continue

                    line_str = line.decode("utf-8")
                    if line_str.startswith("data: "):
                        # Strip prefix per line to allow concatenation of multi-line frames
                        content = line_str[6:].strip()
                        if content == "[DONE]":
                            buffer = ""  # Clear buffer on done
                            break

                        if buffer:
                            buffer += "\n" + content
                        else:
                            buffer = content
                    elif line_str.startswith("event: "):
                        pass

                # Flush any remaining buffer on stream close (EOF without trailing blank line)
                if buffer:
                    try:
                        yield json.loads(buffer)
                    except json.JSONDecodeError:
                        pass

                return
            except Exception as e:
                last_error = e
                if received_any or attempt == max_attempts - 1:
                    logger.error(f"OpenCode streaming failed: {e}")
                    raise
                logger.warning(
                    f"OpenCode stream initial POST failed, retrying once: {e}"
                )
            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass

        if last_error:
            raise last_error

    def create_session(self, directory: Optional[str] = None) -> str:
        url = f"{self.base_url}/session"
        params = {"directory": directory} if directory else None
        response = self.retry_session.post(url, json={}, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        session_id = data.get("id")
        if not session_id:
            raise ValueError("OpenCode session create did not return id")
        return session_id

    def send_command(
        self,
        session_id: str,
        command: str,
        arguments: str,
        message_id: str,
        directory: Optional[str] = None,
    ):
        """Send OMO command with 60s timeout."""
        url = f"{self.base_url}/session/{session_id}/command"
        body = {
            "messageID": message_id,
            "command": command,
            "arguments": arguments,
            "agent": "sisyphus",
        }
        params = {"directory": directory} if directory else None

        try:
            response = self.session.post(url, json=body, params=params, timeout=60)
            response.raise_for_status()
            return response
        except Exception as e:
            logger.error(f"OpenCode command failed: {e}")
            raise
