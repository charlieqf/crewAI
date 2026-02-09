import json
import logging
import os
import time
import requests
from typing import List, Dict, Any, Optional, Generator
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class OpenCodeClient:
    def __init__(self, base_url: str, api_key: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.retry_session = requests.Session()  # Session WITH retries
        self.default_agent = self._normalize_agent(
            os.getenv("OPENCODE_AGENT", "sisyphus")
        )
        self.default_model = self._parse_model(
            os.getenv("OPENCODE_MODEL") or "",
            os.getenv("OPENCODE_MODEL_PROVIDER") or "",
            os.getenv("OPENCODE_MODEL_ID") or "",
        )

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

    @staticmethod
    def _normalize_agent(agent: Optional[str]) -> Optional[str]:
        if agent is None:
            return None
        raw = agent.strip()
        if not raw:
            return None
        if raw.lower() in {"none", "null", "off", "disabled"}:
            return None
        return raw

    @staticmethod
    def _parse_model(
        raw_model: Optional[str],
        raw_provider: Optional[str],
        raw_model_id: Optional[str],
    ) -> Optional[Dict[str, str]]:
        if raw_provider and raw_model_id:
            provider = raw_provider.strip()
            model_id = raw_model_id.strip()
            if provider and model_id:
                return {"providerID": provider, "modelID": model_id}
            return None
        if raw_model is None:
            return None
        raw = raw_model.strip()
        if not raw:
            return None
        if raw.lower() in {"none", "null", "off", "disabled"}:
            return None
        if ":" in raw:
            provider, model_id = raw.split(":", 1)
        else:
            provider, model_id = "opencode", raw
        provider = provider.strip()
        model_id = model_id.strip()
        if not provider or not model_id:
            return None
        return {"providerID": provider, "modelID": model_id}

    def _resolve_agent(self, agent: Optional[str]) -> Optional[str]:
        if agent is None:
            return self.default_agent
        return self._normalize_agent(agent)

    def _resolve_model(self, agent: Optional[str]) -> Optional[Dict[str, str]]:
        resolved_agent = self._resolve_agent(agent)
        if resolved_agent:
            return None
        return self.default_model

    @staticmethod
    def _attach_agent(body: Dict[str, Any], agent: Optional[str]) -> None:
        if agent:
            body["agent"] = agent

    @staticmethod
    def _attach_model(body: Dict[str, Any], model: Optional[Dict[str, str]]) -> None:
        if model:
            body["model"] = model

    @staticmethod
    def _summarize_messages(messages: List[Dict[str, Any]], limit: int = 6) -> str:
        summary = []
        for msg in messages[-limit:]:
            info = msg.get("info", {}) if isinstance(msg, dict) else {}
            role = info.get("role")
            mid = info.get("id")
            parent = info.get("parentID") or info.get("parentId")
            part_types = []
            for part in msg.get("parts", []) if isinstance(msg, dict) else []:
                if isinstance(part, dict):
                    part_types.append(part.get("type"))
            summary.append(f"{role} id={mid} parent={parent} parts={part_types}")
        return " | ".join(summary)

    def prompt_async(
        self,
        session_id: str,
        parts: List[Dict[str, Any]],
        message_id: Optional[str],
        directory: Optional[str] = None,
        agent: Optional[str] = None,
        parent_id: Optional[str] = None,
    ):
        """Silent sync (noReply=true) with 15s timeout and retries."""
        url = f"{self.base_url}/session/{session_id}/prompt_async"
        body = {
            "noReply": True,
            "parts": parts,
        }
        if message_id:
            body["messageID"] = message_id
        if parent_id:
            body["parentID"] = parent_id
        self._attach_agent(body, self._resolve_agent(agent))
        self._attach_model(body, self._resolve_model(agent))
        params = {"directory": directory} if directory else None
        logger.info(
            "[OPENCODE_CLIENT] prompt_interactive agent=%s model=%s",
            body.get("agent"),
            body.get("model"),
        )

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
        message_id: Optional[str],
        directory: Optional[str] = None,
        agent: Optional[str] = None,
        parent_id: Optional[str] = None,
    ):
        """Standard POST with retry support."""
        url = f"{self.base_url}/session/{session_id}/message"
        body = {
            "noReply": False,
            "parts": parts,
        }
        if message_id:
            body["messageID"] = message_id
        if parent_id:
            body["parentID"] = parent_id
        self._attach_agent(body, self._resolve_agent(agent))
        self._attach_model(body, self._resolve_model(agent))
        params = {"directory": directory} if directory else None

        response = self.retry_session.post(url, json=body, params=params, timeout=60)
        response.raise_for_status()
        return response

    def stream_interactive(
        self,
        session_id: str,
        parts: List[Dict[str, Any]],
        message_id: Optional[str],
        directory: Optional[str] = None,
        agent: Optional[str] = None,
        parent_id: Optional[str] = None,
    ):
        """Streaming POST with safe initial-retry (no retry after bytes received)."""
        url = f"{self.base_url}/session/{session_id}/message"
        body = {
            "noReply": False,
            "parts": parts,
            "stream": True,
        }
        if message_id:
            body["messageID"] = message_id
        if parent_id:
            body["parentID"] = parent_id
        self._attach_agent(body, self._resolve_agent(agent))
        self._attach_model(body, self._resolve_model(agent))
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
        agent: Optional[str] = None,
    ):
        """Send OMO command with 60s timeout."""
        url = f"{self.base_url}/session/{session_id}/command"
        body = {
            "messageID": message_id,
            "command": command,
            "arguments": arguments,
        }
        self._attach_agent(body, self._resolve_agent(agent))
        self._attach_model(body, self._resolve_model(agent))
        params = {"directory": directory} if directory else None

        try:
            response = self.session.post(url, json=body, params=params, timeout=60)
            response.raise_for_status()
            return response
        except Exception as e:
            logger.error(f"OpenCode command failed: {e}")
            raise

    def get_session_messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Get messages from a session."""
        url = f"{self.base_url}/session/{session_id}/message"
        params = {"limit": limit} if limit else None
        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        text = response.text
        if not text or not text.strip():
            logger.warning(
                "[OPENCODE_CLIENT] Empty session messages response "
                f"status={response.status_code} len=0 session={session_id}"
            )
            return []
        try:
            return response.json()
        except ValueError:
            preview = text.strip().replace("\n", " ")[:200]
            logger.warning(
                "[OPENCODE_CLIENT] Non-JSON session messages response "
                f"status={response.status_code} len={len(text)} session={session_id} "
                f"preview={preview!r}"
            )
            return []

    def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """Get the status of a session (busy/idle)."""
        url = f"{self.base_url}/session/status"
        response = self.session.get(url, timeout=15)
        response.raise_for_status()
        statuses = response.json()
        return statuses.get(session_id, {})

    def abort_session(self, session_id: str) -> None:
        """Abort a running session to stop loops and token burn."""
        url = f"{self.base_url}/session/abort"
        body = {"sessionID": session_id}
        try:
            response = self.session.post(url, json=body, timeout=15)
            response.raise_for_status()
            logger.info(f"[OPENCODE_CLIENT] Aborted session {session_id}")
        except Exception as e:
            logger.warning(
                f"[OPENCODE_CLIENT] Failed to abort session {session_id}: {e}"
            )

    def get_config(self) -> Dict[str, Any]:
        url = f"{self.base_url}/config"
        response = self.session.get(url, timeout=15)
        response.raise_for_status()
        return response.json()

    def prompt_interactive_with_polling(
        self,
        session_id: str,
        parts: List[Dict[str, Any]],
        message_id: Optional[str],
        directory: Optional[str] = None,
        poll_interval: float = 2.0,
        max_wait: float = 280.0,
        agent: Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Send a message and poll for responses.

        OpenCode's /message endpoint waits for the entire agent loop to complete,
        which can take minutes for complex tasks. This method:
        1. Sends the message (fire-and-forget style with short timeout)
        2. Polls the session messages to get incremental responses
        3. Yields new assistant message parts as they appear

        Yields:
            Dict with 'type' (text/tool_call/etc) and content
        """
        url = f"{self.base_url}/session/{session_id}/message"
        body = {
            "noReply": False,
            "parts": parts,
        }
        if message_id:
            body["messageID"] = message_id
        if parent_id:
            body["parentID"] = parent_id
        self._attach_agent(body, self._resolve_agent(agent))
        self._attach_model(body, self._resolve_model(agent))
        params = {"directory": directory} if directory else None
        logger.info(
            "[OPENCODE_CLIENT] prompt_interactive_with_polling agent=%s model=%s",
            body.get("agent"),
            body.get("model"),
        )

        # Get initial message count - we need to track what messages existed BEFORE our request
        try:
            initial_messages = self.get_session_messages(session_id)
            # Track all existing message IDs so we only return truly NEW responses
            seen_message_ids = {m["info"]["id"] for m in initial_messages}
            logger.info(
                f"[OPENCODE_CLIENT] Session has {len(initial_messages)} existing messages"
            )
        except Exception as e:
            logger.warning(f"Failed to get initial messages: {e}")
            initial_messages = []
            seen_message_ids = set()

        # Send the message - use a moderate timeout
        # The request will be processed in the background even if we timeout
        try:
            logger.info(f"[OPENCODE_CLIENT] Sending POST to {url}")
            response = self.session.post(url, json=body, params=params, timeout=15)
            response.raise_for_status()
            # If we get here quickly, check if there's already a response
            text = response.text.strip()
            logger.info(
                f"[OPENCODE_CLIENT] POST returned status={response.status_code}, len={len(text) if text else 0}"
            )
            if text:
                try:
                    data = response.json()
                    logger.info(
                        f"[OPENCODE_CLIENT] Response data keys: {list(data.keys()) if isinstance(data, dict) else type(data)}"
                    )
                    # Don't return immediately if the response looks like an old message.
                    if data and isinstance(data, dict):
                        info = (
                            data.get("info", {})
                            if isinstance(data.get("info"), dict)
                            else {}
                        )
                        resp_id = info.get("id")
                        resp_role = info.get("role")
                        resp_parent = info.get("parentID") or info.get("parentId")
                        if info.get("error"):
                            err = info.get("error", {})
                            err_msg = ""
                            if isinstance(err, dict):
                                data = err.get("data", {})
                                err_msg = (
                                    data.get("message") or err.get("message") or ""
                                )
                            if not err_msg:
                                err_msg = "OpenCode returned an error."
                            yield {"type": "error", "message": err_msg}
                            return
                        parts = data.get("parts", [])
                        if (
                            message_id
                            and resp_parent
                            and resp_parent != message_id
                            and resp_role == "assistant"
                        ):
                            logger.info(
                                "[OPENCODE_CLIENT] Response parent mismatch, will poll "
                                f"resp_id={resp_id} resp_parent={resp_parent} expected_parent={message_id}"
                            )
                        elif (
                            parts
                            and resp_id not in seen_message_ids
                            and resp_role == "assistant"
                        ):
                            logger.info(
                                f"[OPENCODE_CLIENT] Response has {len(parts)} parts, yielding complete"
                            )
                            yield {"type": "complete", "data": data}
                            return
                        logger.info(
                            "[OPENCODE_CLIENT] Response not accepted (duplicate or non-assistant), will poll"
                        )
                    else:
                        logger.info(
                            "[OPENCODE_CLIENT] Response has no usable data, will poll instead"
                        )
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse OpenCode response: {text[:200]}")
        except requests.exceptions.Timeout:
            logger.info(
                f"OpenCode message request timed out (expected), polling for response"
            )
        except requests.exceptions.HTTPError as e:
            # If it's not a timeout, re-raise
            logger.error(f"OpenCode HTTP error: {e}")
            raise
        except Exception as e:
            logger.warning(f"OpenCode message send error: {e}, will try polling")

        # Poll for new messages
        start_time = time.time()
        last_text = ""
        last_activity_time = start_time
        # Track if we've seen our own user message come back. Some OpenCode servers
        # do not echo the exact message_id, so we also accept the first new user message.
        our_message_seen = False
        sync_user_message_id: str | None = None
        first_response_time = None  # Track when we first got a response
        response_stable_timeout = 20.0  # If response unchanged for this long, return it
        min_stable_text_len = 50  # Avoid returning very short intermediate fragments
        min_complete_len = 120
        incomplete_idle_grace = 45.0
        short_idle_grace = 8.0
        leadin_keywords = (
            "我来",
            "让我",
            "接下来",
            "需要",
            "下面",
            "先",
            "会",
            "将",
            "正在",
            "这是个",
            "这是一个",
        )

        def _looks_incomplete(text: str) -> bool:
            stripped = text.strip()
            if not stripped:
                return True
            if stripped.startswith("Using skill:"):
                return True
            # Very short, unstructured replies are often intermediate fragments.
            if len(stripped) < min_stable_text_len:
                return True
            if len(stripped) >= min_complete_len:
                return False
            has_structure = (
                ("\n" in stripped)
                or ("##" in stripped)
                or ("- " in stripped)
                or ("1." in stripped)
            )
            if has_structure:
                return False
            if any(key in stripped for key in leadin_keywords):
                return True
            # Short, single-paragraph answers without structure are usually incomplete.
            return True

        while time.time() - start_time < max_wait:
            time.sleep(poll_interval)

            try:
                messages = self.get_session_messages(session_id)
            except Exception as e:
                logger.warning(f"Error polling messages: {e}")
                continue

            # Find new assistant messages that came AFTER our user message.
            # We rely on seen_message_ids to avoid replaying history.
            for msg in messages:
                msg_id = msg["info"]["id"]
                role = msg["info"]["role"]

                if msg_id in seen_message_ids:
                    continue

                # Check if this is our user message
                if message_id and msg_id == message_id:
                    our_message_seen = True
                    sync_user_message_id = message_id
                    seen_message_ids.add(msg_id)
                    logger.info(
                        f"[OPENCODE_CLIENT] Our user message {message_id} is now in session"
                    )
                    continue

                # Some servers don't preserve our message_id; accept the first new user message
                # as the synchronization point for this turn.
                if role == "user" and not our_message_seen:
                    our_message_seen = True
                    sync_user_message_id = msg_id
                    seen_message_ids.add(msg_id)
                    last_activity_time = time.time()
                    logger.info(
                        f"[OPENCODE_CLIENT] Saw a new user message {msg_id}, proceeding"
                    )
                    continue

                # Only process assistant messages that appear AFTER our user message
                if role == "assistant" and our_message_seen:
                    info = msg.get("info", {})
                    parent_id = info.get("parentID") or info.get("parentId")
                    if (
                        sync_user_message_id
                        and parent_id
                        and parent_id != sync_user_message_id
                    ):
                        # Ignore assistant messages that belong to earlier turns
                        continue
                    if info.get("error"):
                        err = info.get("error", {})
                        err_msg = ""
                        if isinstance(err, dict):
                            data = err.get("data", {})
                            err_msg = data.get("message") or err.get("message") or ""
                        if not err_msg:
                            err_msg = "OpenCode returned an error."
                        yield {"type": "error", "message": err_msg}
                        return
                    # Extract text from parts
                    for part in msg.get("parts", []):
                        part_type = part.get("type", "")
                        if part_type == "text":
                            text = part.get("text", "")
                            if text and text != last_text:
                                logger.info(
                                    f"[OPENCODE_CLIENT] Got new assistant text: {text[:50]}..."
                                )
                                yield {"type": "text", "text": text}
                                last_text = text
                                first_response_time = (
                                    time.time()
                                )  # Reset timer on new text
                        elif part_type == "tool-invocation":
                            yield {
                                "type": "tool_call",
                                "name": part.get("toolName", ""),
                                "input": part.get("input", {}),
                            }
                        elif part_type == "tool-result":
                            yield {
                                "type": "tool_result",
                                "name": part.get("toolName", ""),
                                "output": part.get("output", ""),
                            }

                    seen_message_ids.add(msg_id)
                    last_activity_time = time.time()

            # Check if session is idle (agent finished)
            # If we got a new message and session is not busy, we're done
            try:
                status = self.get_session_status(session_id)
                # Empty status dict means not in status list (idle)
                # status.type == "busy" means still processing
                is_busy = status.get("type") == "busy"
                is_idle = not status or not is_busy
                logger.debug(
                    f"[OPENCODE_CLIENT] Session status: {status}, is_idle={is_idle}, last_text={bool(last_text)}"
                )
                if is_idle and last_text:
                    grace = (
                        short_idle_grace
                        if len(last_text.strip()) < min_stable_text_len
                        else incomplete_idle_grace
                    )
                    if _looks_incomplete(last_text):
                        if time.time() - last_activity_time < grace:
                            logger.info(
                                "[OPENCODE_CLIENT] Session idle but response looks incomplete; continue polling briefly"
                            )
                            continue
                    logger.info(
                        f"[OPENCODE_CLIENT] Session is idle and we have response, breaking"
                    )
                    break

                # If we have text and it's been stable for response_stable_timeout, return it
                # This handles cases where session stays "busy" but we already have the answer
                if last_text and first_response_time:
                    stable_duration = time.time() - first_response_time
                    text_len = len(last_text.strip())
                    ends_with_colon = last_text.strip().endswith(
                        ":"
                    ) or last_text.strip().endswith("：")
                    if stable_duration > response_stable_timeout:
                        if (
                            text_len < min_stable_text_len
                            or ends_with_colon
                            or _looks_incomplete(last_text)
                        ):
                            logger.info(
                                "[OPENCODE_CLIENT] Stable but too short/looks incomplete; continue polling "
                                f"len={text_len} ends_with_colon={ends_with_colon}"
                            )
                        else:
                            logger.info(
                                f"[OPENCODE_CLIENT] Response stable for {stable_duration:.1f}s (>{response_stable_timeout}s), breaking"
                            )
                            break
            except Exception as e:
                logger.debug(f"Error checking session status: {e}")
                # If we got text and can't check status, assume done
                if last_text:
                    break

        # Final yield with any remaining text
        if last_text:
            # If we broke early, ensure we return the best/longest assistant text for this turn.
            try:
                messages = self.get_session_messages(session_id)
                if sync_user_message_id:
                    best_text = last_text
                    for msg in messages:
                        info = msg.get("info", {})
                        if info.get("role") != "assistant":
                            continue
                        parent_id = info.get("parentID") or info.get("parentId")
                        if parent_id != sync_user_message_id:
                            continue
                        for part in msg.get("parts", []):
                            if part.get("type") == "text":
                                text = part.get("text", "")
                                if isinstance(text, str) and len(text) > len(best_text):
                                    best_text = text
                    if best_text != last_text:
                        logger.info(
                            "[OPENCODE_CLIENT] Found longer assistant text after polling; returning longest"
                        )
                        last_text = best_text
            except Exception as e:
                logger.debug(f"[OPENCODE_CLIENT] Failed to scan for longest text: {e}")
            # Ensure session is not left busy if we're about to return.
            try:
                status = self.get_session_status(session_id)
                if status.get("type") == "busy":
                    logger.warning(
                        f"[OPENCODE_CLIENT] Session {session_id} still busy on return; aborting to avoid blocking next turn"
                    )
                    self.abort_session(session_id)
            except Exception:
                pass
            yield {"type": "final", "text": last_text}
            return

        # No response after max_wait: emit a clear error so caller can respond.
        try:
            messages = self.get_session_messages(session_id)
            summary = self._summarize_messages(messages)
            logger.warning(
                "[OPENCODE_CLIENT] No assistant text after polling. "
                f"session={session_id} message_id={message_id} "
                f"sync_user_message_id={sync_user_message_id} "
                f"our_message_seen={our_message_seen} "
                f"last_text_len={len(last_text)} "
                f"messages_tail={summary}"
            )
        except Exception as e:
            logger.warning(
                "[OPENCODE_CLIENT] Failed to summarize messages after polling "
                f"session={session_id} message_id={message_id}: {e}"
            )
        yield {
            "type": "error",
            "message": (
                "OpenCode did not return a response within the timeout. "
                "This often indicates an upstream provider error or insufficient balance. "
                "Please check the OpenCode server logs and billing."
            ),
        }
