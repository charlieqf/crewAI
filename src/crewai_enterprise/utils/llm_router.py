"""
LLM Router - Route requests to different LLM providers.

Supports OpenAI, Gemini, and xAI Grok with unified interface.
"""

from __future__ import annotations

import logging
import os
import json
from dataclasses import dataclass

import requests
import time
import base64


logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Response from LLM."""

    content: str
    model: str
    provider: str
    usage: dict | None = None


class LLMError(Exception):
    """Raised when LLM call fails."""

    pass


class LLMRouter:
    """Route requests to different LLM providers."""

    # Provider configurations
    PROVIDERS = {
        "openai": {
            "base_url": "https://api.openai.com/v1/chat/completions",
            "default_model": "gpt-4o",
            "env_key": "OPENAI_API_KEY",
        },
        "gemini": {
            "base_url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            "default_model": "gemini-3-flash-preview",
            "env_key": "GEMINI_API_KEY",
        },
        "xai": {
            "base_url": "https://api.x.ai/v1/chat/completions",
            "default_model": "grok-4-fast-non-reasoning",
            "env_key": "XAI_API_KEY",
        },
    }

    def __init__(
        self,
        openai_key: str | None = None,
        gemini_key: str | None = None,
        xai_key: str | None = None,
    ):
        """Initialize with API keys (from params or environment)."""
        self.keys = {
            "openai": openai_key or os.getenv("OPENAI_API_KEY"),
            "gemini": gemini_key or os.getenv("GEMINI_API_KEY"),
            "xai": xai_key or os.getenv("XAI_API_KEY"),
        }

    def chat(
        self,
        provider: str,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Send chat completion request to specified provider.

        Args:
            provider: One of 'openai', 'gemini', 'xai'
            messages: List of message dicts with 'role' and 'content'
            model: Model name (uses default if not specified)
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature

        Returns:
            LLMResponse with content and metadata
        """
        if provider not in self.PROVIDERS:
            raise LLMError(f"Unknown provider: {provider}")

        api_key = self.keys.get(provider)
        if not api_key:
            raise LLMError(f"API key not configured for {provider}")

        config = self.PROVIDERS[provider]
        model = model or config["default_model"]

        if provider == "gemini":
            return self._call_gemini(api_key, messages, model, max_tokens, temperature)
        else:
            # OpenAI-compatible API (OpenAI and xAI)
            return self._call_openai_compatible(
                provider,
                api_key,
                config["base_url"],
                messages,
                model,
                max_tokens,
                temperature,
            )

    def _call_openai_compatible(
        self,
        provider: str,
        api_key: str,
        base_url: str,
        messages: list[dict],
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        """Call OpenAI-compatible API (OpenAI, xAI)."""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            response = requests.post(
                base_url, headers=headers, json=payload, timeout=60
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            raise LLMError(f"{provider} API error: {e}") from e

        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage")

        logger.info(f"{provider} response: {len(content)} chars, model={model}")

        return LLMResponse(
            content=content,
            model=model,
            provider=provider,
            usage=usage,
        )

    def _call_gemini(
        self,
        api_key: str,
        messages: list[dict],
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        """Call Google Gemini API."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        # Convert OpenAI-style messages to Gemini format
        # Gemini doesn't support 'system' role - merge into first user message
        system_content = ""
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_content += msg["content"] + "\n"
            else:
                user_messages.append(msg)

        # If we have system content, prepend to first user message
        if system_content and user_messages:
            first_msg = user_messages[0]
            if first_msg["role"] == "user":
                user_messages[0] = {
                    "role": "user",
                    "content": system_content + first_msg["content"],
                }

        # Build Gemini contents, merging consecutive same-role messages
        contents: list[dict] = []
        for msg in user_messages:
            role = "user" if msg["role"] == "user" else "model"
            # Merge consecutive messages with same role (Gemini requirement)
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"][0]["text"] += "\n" + msg["content"]
            else:
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }

        try:
            response = requests.post(url, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            raise LLMError(f"Gemini API error: {e}") from e

        content = data["candidates"][0]["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata")

        logger.info(f"Gemini response: {len(content)} chars, model={model}")

        return LLMResponse(
            content=content,
            model=model,
            provider="gemini",
            usage=usage,
        )

    def quick_chat(
        self, provider: str, user_message: str, system_prompt: str | None = None
    ) -> str:
        """
        Quick single-message chat.

        Args:
            provider: 'openai', 'gemini', or 'xai'
            user_message: The user's message
            system_prompt: Optional system prompt

        Returns:
            The assistant's response text
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})

        response = self.chat(provider, messages)
        return response.content

    def chat_with_image(
        self,
        provider: str,
        text: str,
        image_base64: str,
        image_mime_type: str = "image/jpeg",
        system_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        history: list[dict] | None = None,
    ) -> LLMResponse:
        """
        Chat with an image (multimodal).

        Args:
            provider: 'openai', 'gemini', or 'xai'
            text: Text prompt to accompany the image
            image_base64: Base64-encoded image data
            image_mime_type: MIME type of image (default: image/jpeg)
            system_prompt: Optional system prompt
            model: Model name (uses default if not specified)
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            history: Optional conversation history
        """
        if provider not in self.PROVIDERS:
            raise LLMError(f"Unknown provider: {provider}")

        api_key = self.keys.get(provider)
        if not api_key:
            raise LLMError(f"API key not configured for {provider}")

        config = self.PROVIDERS[provider]
        model = model or config["default_model"]

        if provider == "gemini":
            return self._call_gemini_vision(
                api_key, text, image_base64, image_mime_type,
                system_prompt, model, max_tokens, temperature,
                history=history
            )
        else:
            # OpenAI-compatible vision API
            return self._call_openai_vision(
                provider, api_key, config["base_url"],
                text, image_base64, image_mime_type,
                system_prompt, model, max_tokens, temperature,
                history=history
            )

    def _call_openai_vision(
        self,
        provider: str,
        api_key: str,
        base_url: str,
        text: str,
        image_base64: str,
        image_mime_type: str,
        system_prompt: str | None,
        model: str,
        max_tokens: int,
        temperature: float,
        history: list[dict] | None = None,
    ) -> LLMResponse:
        """Call OpenAI-compatible vision API with history."""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if history:
            messages.extend(history)

        # OpenAI vision format: content is array of objects
        user_content = [
            {"type": "text", "text": text},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{image_mime_type};base64,{image_base64}"
                }
            }
        ]
        
        # Add current user message
        messages.append({"role": "user", "content": user_content})

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            response = requests.post(base_url, headers=headers, json=payload, timeout=90)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            raise LLMError(f"{provider} Vision API error: {e}") from e

        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage")

        logger.info(f"{provider} vision response: {len(content)} chars, model={model}")

        return LLMResponse(
            content=content,
            model=model,
            provider=provider,
            usage=usage,
        )

    def _call_gemini_vision(
        self,
        api_key: str,
        text: str,
        image_base64: str,
        image_mime_type: str,
        system_prompt: str | None,
        model: str,
        max_tokens: int,
        temperature: float,
        history: list[dict] | None = None,
    ) -> LLMResponse:
        """Call Google Gemini Vision API with history."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        # Build contents from history and current prompt
        contents = []
        
        # 1. Process system prompt and history
        system_content = system_prompt + "\n" if system_prompt else ""
        raw_history = history or []
        
        final_history = []
        for msg in raw_history:
            if msg["role"] == "system":
                system_content += msg["content"] + "\n"
            else:
                final_history.append(msg)

        # 2. Convert history to Gemini contents
        for msg in final_history:
            role = "user" if msg["role"] == "user" else "model"
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"][0]["text"] += "\n" + msg["content"]
            else:
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        # 3. Handle system prompt - prepend to first user message
        if system_content:
            first_user = None
            for c in contents:
                if c["role"] == "user":
                    first_user = c
                    break
            
            if first_user:
                first_user["parts"][0]["text"] = system_content + "\n" + first_user["parts"][0]["text"]
            else:
                # Will prepend to current prompt later
                pass

        # 4. Build current user part with text and image
        user_text = text
        if system_content and not any(c["role"] == "user" for c in contents):
            user_text = system_content + "\n" + text

        parts = [
            {"text": user_text},
            {
                "inline_data": {
                    "mime_type": image_mime_type,
                    "data": image_base64
                }
            }
        ]

        if contents and contents[-1]["role"] == "user":
            contents[-1]["parts"].extend(parts)
        else:
            contents.append({"role": "user", "parts": parts})

        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }

        try:
            response = requests.post(url, json=payload, timeout=90)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response:
                logger.error(f"Gemini Vision API Error Response: {e.response.text}")
            raise LLMError(f"Gemini Vision API error: {e}") from e

        content = data["candidates"][0]["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata")

        logger.info(f"Gemini vision response: {len(content)} chars, model={model}")

        return LLMResponse(
            content=content,
            model=model,
            provider="gemini",
            usage=usage,
        )


    def upload_file(
        self,
        provider: str,
        file_data: bytes,
        mime_type: str,
        filename: str = "uploaded_file"
    ) -> str:
        """Upload file to provider and return URI/ID."""
        if provider not in self.PROVIDERS:
            raise LLMError(f"Unknown provider: {provider}")

        api_key = self.keys.get(provider)
        if not api_key:
            raise LLMError(f"API key not configured for {provider}")

        if provider == "gemini":
            return self._upload_gemini_file(api_key, file_data, mime_type, filename)
        else:
            raise NotImplementedError(f"File upload not supported for {provider}")

    def chat_with_file(
        self,
        provider: str,
        text: str,
        file_data: bytes | None,
        file_mime_type: str,
        filename: str = "uploaded_file",
        file_uri: str | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        history: list[dict] | None = None,
    ) -> LLMResponse:
        """
        Chat with a file (document/PDF/etc).

        Args:
            provider: 'gemini'
            text: Prompt
            file_data: Raw bytes (optional if file_uri provided)
            file_mime_type: MIME type
            filename: Name
            file_uri: Pre-uploaded file URI (optional)
            ...
            history: Optional conversation history
        """
        if provider not in self.PROVIDERS:
            raise LLMError(f"Unknown provider: {provider}")

        api_key = self.keys.get(provider)
        if not api_key:
            raise LLMError(f"API key not configured for {provider}")

        config = self.PROVIDERS[provider]
        model = model or config["default_model"]

        if provider == "gemini":
            # Pass data to helper, let it decide between URI or Inline
            return self._call_gemini_file(
                api_key, text, file_uri, file_mime_type,
                system_prompt, model, max_tokens, temperature,
                file_data=file_data,
                history=history
            )
        elif file_mime_type.startswith("image/"):
            # If it's an image, we can use chat_with_image for any provider
            img_b64 = None
            if file_data:
                img_b64 = base64.b64encode(file_data).decode("utf-8")
            elif file_uri and file_uri.startswith("base64:"):
                img_b64 = file_uri[7:]
            
            if img_b64:
                return self.chat_with_image(
                    provider=provider,
                    text=text,
                    image_base64=img_b64,
                    image_mime_type=file_mime_type,
                    system_prompt=system_prompt,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            else:
                raise LLMError(f"Image data or base64 URI required for {provider} vision.")
        elif file_mime_type == "application/pdf":
            # PDF Fallback for non-Gemini (Extract Text)
            logger.info(f"[LLM_ROUTER] Attempting PDF text extraction fallback for {provider}")
            if not file_data and file_uri and file_uri.startswith("base64:"):
                file_data = base64.b64decode(file_uri[7:])
            
            if file_data:
                extracted_text = self._extract_text_from_pdf(file_data)
                
                # Combine history into context if available
                history_text = ""
                if history:
                    history_text = "对话历史:\n" + "\n".join([f"{'用户' if m['role']=='user' else '模型'}: {m['content']}" for m in history]) + "\n\n"

                full_prompt = (
                    f"{history_text}(注意：用户上传了 PDF 文件 {filename}，已为您提取文本内容如下，请基于此回答):\n"
                    f"```\n{extracted_text[:10000]}\n```\n\n用户提问: {text}"
                )
                return self.chat(
                    provider=provider,
                    messages=[{"role": "user", "content": full_prompt}],
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            else:
                raise LLMError(f"PDF data required for {provider} text extraction fallback.")
        else:
            return LLMResponse(
                content=f"抱歉，目前机器人的“大文件原生分析”能力仅在 Gemini 机器人上可用。{provider} 机器人目前仅额外支持分析图片和 PDF 文本。",
                model=model,
                provider=provider,
                usage={}
            )

    def _extract_text_from_pdf(self, file_data: bytes) -> str:
        """Extract text from PDF bytes using pypdf."""
        try:
            import io
            from pypdf import PdfReader
            
            reader = PdfReader(io.BytesIO(file_data))
            text_parts = []
            for page in reader.pages:
                parsed = page.extract_text()
                if parsed:
                    text_parts.append(parsed)
            
            combined = "\n".join(text_parts).strip()
            if not combined:
                return "<PDF appears to be empty or contains only images/non-text content>"
            return combined
        except ImportError:
            logger.error("pypdf not installed, cannot extract PDF text")
            return "<Error: pypdf library is required for PDF text extraction on this bot type.>"
        except Exception as e:
            logger.error(f"PDF text extraction failed: {e}")
            return f"<Error extracting text from PDF: {str(e)}>"

    def _upload_gemini_file(
        self,
        api_key: str,
        file_data: bytes,
        mime_type: str,
        display_name: str
    ) -> str:
        """Upload file to Gemini File API and return URI."""
        # Ref: https://ai.google.dev/api/files#method:-files.create
        url = f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={api_key}"
        
        # Simple metadata + content upload
        headers = {
            "X-Goog-Upload-Protocol": "multipart",
            "X-Goog-Upload-Header-Content-Length": str(len(file_data)),
            "X-Goog-Upload-Header-Content-Type": mime_type
        }
        
        metadata = {
            "file": {
                "displayName": display_name
            }
        }
        
        files = {
            'metadata': ('metadata', json.dumps(metadata), 'application/json'),
            'file': (display_name, file_data, mime_type)
        }
        
        try:
            logger.info(f"Uploading file '{display_name}' ({len(file_data)} bytes) to Gemini...")
            response = requests.post(url, headers=headers, files=files, timeout=300)
            response.raise_for_status()
            result = response.json()
            file_info = result.get("file", {})
            file_uri = file_info.get("uri")
            file_name_id = file_info.get("name") # e.g. files/abc-123

            if not file_uri:
                raise LLMError(f"Upload successful but no URI returned: {result}")

            logger.info(f"File uploaded. Name: {file_name_id} URI: {file_uri}. Waiting for processing...")

            # POLL for ACTIVE state (for up to 30 seconds)
            # Ref: https://ai.google.dev/gemini-api/docs/files#get_file
            check_url = f"https://generativelanguage.googleapis.com/v1beta/{file_name_id}?key={api_key}"
            start_wait = time.time()
            
            while time.time() - start_wait < 30:
                check_res = requests.get(check_url, timeout=30)
                check_res.raise_for_status()
                state = check_res.json().get("state")
                
                if state == "ACTIVE":
                    logger.info(f"File {file_name_id} is ACTIVE. Ready to use.")
                    return file_uri
                elif state == "FAILED":
                    raise LLMError(f"Gemini File Processing FAILED for {file_name_id}")
                
                time.sleep(1) # Wait 1s between checks
            
            # If timeout, warn but return URI (maybe it works?) OR raise error
            logger.warning(f"Timeout waiting for file {file_name_id} to be ACTIVE. State: {state}. Trying to proceed anyway.")
            return file_uri
            
        except requests.exceptions.RequestException as e:
            raise LLMError(f"Gemini File Upload error: {e}") from e

    def _call_gemini_file(
        self,
        api_key: str,
        text: str,
        file_uri: str | None,
        mime_type: str,
        system_prompt: str | None,
        model: str,
        max_tokens: int,
        temperature: float,
        file_data: bytes | None = None,
        history: list[dict] | None = None,
    ) -> LLMResponse:
        """Call Gemini with file URI or Inline Data, including history."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        # If file_uri is an external URL (not Gemini URI), we must download it or use inline data
        is_external_url = file_uri and (file_uri.startswith("http://") or file_uri.startswith("https://")) and "generativelanguage.googleapis.com" not in file_uri
        
        if is_external_url and not file_data:
            try:
                logger.info(f"[LLM_ROUTER] Downloading external file for Gemini: {file_uri}")
                resp = requests.get(file_uri, timeout=30)
                resp.raise_for_status()
                file_data = resp.content
                file_uri = None # Use inline data instead
            except Exception as e:
                logger.error(f"[LLM_ROUTER] Failed to download external file: {e}")

        # Build contents from history and current prompt
        contents = []
        
        # 1. Process system prompt and history
        # Gemini v1beta merge pattern
        system_content = system_prompt + "\n" if system_prompt else ""
        raw_history = history or []
        
        # Pull out system messages from history if any
        final_history = []
        for msg in raw_history:
            if msg["role"] == "system":
                system_content += msg["content"] + "\n"
            else:
                final_history.append(msg)

        # 2. Convert history to Gemini contents
        for msg in final_history:
            role = "user" if msg["role"] == "user" else "model"
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"][0]["text"] += "\n" + msg["content"]
            else:
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        # 3. Handle system prompt - prepend to first user message
        if system_content:
            # Find first user message in contents
            first_user = None
            for c in contents:
                if c["role"] == "user":
                    first_user = c
                    break
            
            if first_user:
                # Prepend to existing first user message
                first_user["parts"][0]["text"] = system_content + "\n" + first_user["parts"][0]["text"]
            else:
                # No user message in history, or history empty
                # We'll prepend it to the current message later if needed
                pass

        # 4. Process current prompt with file
        user_text = text
        # If system content wasn't prepended to history (because no user msg in history), prepend to current
        if system_content and not any(c["role"] == "user" for c in contents):
            user_text = system_content + "\n" + text

        parts = []
        if file_uri:
            parts.append({"file_data": {"mime_type": mime_type, "file_uri": file_uri}})
        elif file_data:
            b64_data = base64.b64encode(file_data).decode('utf-8')
            parts.append({"inline_data": {"mime_type": mime_type, "data": b64_data}})
        
        parts.append({"text": user_text})

        # Add current user message
        if contents and contents[-1]["role"] == "user":
            contents[-1]["parts"].extend(parts)
        else:
            contents.append({"role": "user", "parts": parts})

        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }

        try:
            response = requests.post(url, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            # Log full response on error for debugging
            if hasattr(e, 'response') and e.response:
                logger.error(f"Gemini API Error Response: {e.response.text}")
            raise LLMError(f"Gemini File Analysis API error: {e}") from e

        content = data["candidates"][0]["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata")

        logger.info(f"Gemini file analysis response: {len(content)} chars, model={model}")

        return LLMResponse(
            content=content,
            model=model,
            provider="gemini",
            usage=usage,
        )


# Global singleton with thread-safe access
_router: LLMRouter | None = None
_router_lock = __import__("threading").Lock()


def get_router() -> LLMRouter:
    """Get or create global LLM router (thread-safe)."""
    global _router
    if _router is None:
        with _router_lock:
            # Double-check locking pattern
            if _router is None:
                _router = LLMRouter()
    return _router


def quick_chat(provider: str, message: str, system_prompt: str | None = None) -> str:
    """Convenience function for quick chat."""
    return get_router().quick_chat(provider, message, system_prompt)
