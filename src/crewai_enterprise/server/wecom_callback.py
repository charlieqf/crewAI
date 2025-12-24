"""
WeCom Callback Server.

FastAPI server to receive and process Enterprise WeChat callback messages.
"""
import logging
import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from src.crewai_enterprise.utils.wecom_crypto import WeComCrypto, WeComCryptoError
from src.crewai_enterprise.utils.wecom_message import WeComMessage, WeComMessageParseError, parse_message

logger = logging.getLogger(__name__)


class WeComCallbackConfigError(Exception):
    """Raised when required configuration is missing."""
    pass


def get_required_env(key: str) -> str:
    """Get a required environment variable, fail fast if missing."""
    value = os.getenv(key)
    if not value:
        raise WeComCallbackConfigError(f"Required environment variable '{key}' is not set")
    return value


# Load configuration from environment variables
# These will be set in .env file
def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    
    app = FastAPI(
        title="WeCom Callback Server",
        description="Receives and processes Enterprise WeChat callback messages for CrewAI agents.",
        version="0.1.0"
    )
    
    # Lazy initialization of crypto handler
    _crypto: Optional[WeComCrypto] = None
    
    def get_crypto() -> WeComCrypto:
        nonlocal _crypto
        if _crypto is None:
            token = get_required_env("WECOM_TOKEN")
            encoding_aes_key = get_required_env("WECOM_ENCODING_AES_KEY")
            corp_id = get_required_env("WECOM_CORP_ID")
            _crypto = WeComCrypto(token, encoding_aes_key, corp_id)
        return _crypto
    
    @app.get("/wecom/callback", response_class=PlainTextResponse)
    async def verify_url(
        msg_signature: str = Query(..., description="Message signature"),
        timestamp: str = Query(..., description="Timestamp"),
        nonce: str = Query(..., description="Nonce"),
        echostr: str = Query(..., description="Echo string to return")
    ) -> str:
        """
        URL verification endpoint for WeCom callback configuration.
        
        WeCom will call this endpoint with a GET request when configuring the callback URL.
        We need to verify the signature and return the decrypted echostr.
        """
        crypto = get_crypto()
        
        if not crypto.verify_signature(msg_signature, timestamp, nonce, echostr):
            raise HTTPException(status_code=403, detail="Invalid signature")
        
        # Decrypt and return the echostr
        try:
            decrypted_echostr = crypto.decrypt_message(echostr)
            return decrypted_echostr
        except WeComCryptoError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    
    @app.post("/wecom/callback")
    async def receive_message(
        request: Request,
        msg_signature: str = Query(..., description="Message signature"),
        timestamp: str = Query(..., description="Timestamp"),
        nonce: str = Query(..., description="Nonce")
    ) -> dict:
        """
        Receive and process callback messages from WeCom.
        
        This endpoint receives encrypted messages when users send messages
        in WeCom groups where the bot is present.
        """
        crypto = get_crypto()
        
        # Read the raw XML body
        body = await request.body()
        xml_body = body.decode("utf-8")
        
        # Extract encrypted content for signature verification
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(xml_body)
            encrypt_element = root.find("Encrypt")
            encrypt_content = encrypt_element.text if encrypt_element is not None else ""
        except ET.ParseError:
            raise HTTPException(status_code=400, detail="Invalid XML body")
        
        # Verify signature before processing
        if not crypto.verify_signature(msg_signature, timestamp, nonce, encrypt_content):
            raise HTTPException(status_code=403, detail="Invalid signature")
        
        # Decrypt the message
        try:
            decrypted_xml = crypto.decrypt_callback_body(xml_body)
        except WeComCryptoError as e:
            raise HTTPException(status_code=400, detail=f"Decryption failed: {e}") from e
        
        # Parse the message
        try:
            message: WeComMessage = parse_message(decrypted_xml)
        except WeComMessageParseError as e:
            raise HTTPException(status_code=400, detail=f"Message parse failed: {e}") from e
        
        # Log the received message (in production, route to CrewAI agent)
        logger.info(f"Received message from {message.from_user_name}: {message.content}")
        
        # TODO: Route to CrewAI agent based on message content
        # For now, just acknowledge receipt
        return {
            "status": "received",
            "from": message.from_user_name,
            "type": message.msg_type,
            "content": message.content[:50] if message.content else None
        }
    
    @app.get("/health")

    async def health_check() -> dict:
        """Health check endpoint."""
        return {"status": "healthy", "service": "wecom-callback"}
    
    return app


# Create the app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
