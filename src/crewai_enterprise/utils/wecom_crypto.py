"""
WeCom Message Encryption/Decryption Utilities.

Handles AES-256-CBC encryption/decryption for Enterprise WeChat callback messages.
"""

import base64
import hashlib
import struct

import defusedxml.ElementTree as ET
from Crypto.Cipher import AES


class WeComCryptoError(Exception):
    """Raised when encryption/decryption fails."""

    pass


class WeComCrypto:
    """Handles WeCom message encryption and decryption."""

    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        """
        Initialize the crypto handler.

        Args:
            token: The token configured in WeCom callback settings.
            encoding_aes_key: The 43-character EncodingAESKey from WeCom.
            corp_id: The enterprise CorpID.
        """
        if not token or not encoding_aes_key or not corp_id:
            raise WeComCryptoError(
                "token, encoding_aes_key, and corp_id are all required"
            )

        if len(encoding_aes_key) != 43:
            raise WeComCryptoError(
                f"EncodingAESKey must be 43 characters, got {len(encoding_aes_key)}"
            )

        self.token = token
        self.corp_id = corp_id
        # Decode the AES key: EncodingAESKey is Base64 encoded, actual key is 32 bytes
        self.aes_key = base64.b64decode(encoding_aes_key + "=")

    def verify_signature(
        self, signature: str, timestamp: str, nonce: str, echostr: str = ""
    ) -> bool:
        """
        Verify the callback signature from WeCom.

        Args:
            signature: The msg_signature from request params.
            timestamp: The timestamp from request params.
            nonce: The nonce from request params.
            echostr: Optional echostr for URL verification.

        Returns:
            True if signature is valid, False otherwise.
        """
        items = sorted([self.token, timestamp, nonce, echostr])
        joined = "".join(items)
        computed = hashlib.sha1(joined.encode()).hexdigest()
        return computed == signature

    def decrypt_message(self, encrypted_msg: str) -> str:
        """
        Decrypt an encrypted message from WeCom.

        Args:
            encrypted_msg: The Base64-encoded encrypted message.

        Returns:
            The decrypted XML message content.
        """
        try:
            # Base64 decode
            cipher_text = base64.b64decode(encrypted_msg)

            # AES-256-CBC decrypt with IV = first 16 bytes of key
            iv = self.aes_key[:16]
            cipher = AES.new(self.aes_key, AES.MODE_CBC, iv)
            decrypted = cipher.decrypt(cipher_text)

            # Remove PKCS#7 padding
            pad_len = decrypted[-1]
            decrypted = decrypted[:-pad_len]

            # Parse the decrypted content:
            # Format: random(16 bytes) + msg_len(4 bytes) + msg + corp_id
            msg_len = struct.unpack(">I", decrypted[16:20])[0]
            msg = decrypted[20 : 20 + msg_len].decode("utf-8")
            received_corp_id = decrypted[20 + msg_len :].decode("utf-8")

            # Verify corp_id matches
            if received_corp_id != self.corp_id:
                raise WeComCryptoError(
                    f"CorpID mismatch: expected {self.corp_id}, got {received_corp_id}"
                )

            return msg
        except Exception as e:
            raise WeComCryptoError(f"Failed to decrypt message: {e}") from e

    def decrypt_callback_body(self, xml_body: str) -> str:
        """
        Decrypt the full callback XML body.

        Args:
            xml_body: The raw XML body from the callback request.

        Returns:
            The decrypted message content.
        """
        try:
            root = ET.fromstring(xml_body)
            encrypt_element = root.find("Encrypt")
            if encrypt_element is None:
                raise WeComCryptoError("No <Encrypt> element found in XML body")

            encrypted_msg = encrypt_element.text
            return self.decrypt_message(encrypted_msg)
        except ET.ParseError as e:
            raise WeComCryptoError(f"Failed to parse XML body: {e}") from e
