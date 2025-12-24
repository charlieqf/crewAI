"""
Unit tests for WeCom Callback Service.
"""
import hashlib
import unittest
from unittest.mock import MagicMock, patch

from src.crewai_enterprise.utils.wecom_crypto import WeComCrypto, WeComCryptoError
from src.crewai_enterprise.utils.wecom_message import WeComMessage, WeComMessageParseError, parse_message


class TestWeComCrypto(unittest.TestCase):
    """Tests for WeCom crypto utilities."""

    def test_init_requires_all_params(self):
        """Test that initialization fails without required params."""
        with self.assertRaises(WeComCryptoError):
            WeComCrypto("", "x" * 43, "corp123")
        
        with self.assertRaises(WeComCryptoError):
            WeComCrypto("token", "", "corp123")
        
        with self.assertRaises(WeComCryptoError):
            WeComCrypto("token", "x" * 43, "")

    def test_encoding_aes_key_length_validation(self):
        """Test that EncodingAESKey must be exactly 43 characters."""
        with self.assertRaises(WeComCryptoError) as context:
            WeComCrypto("token", "tooshort", "corp123")
        
        self.assertIn("43 characters", str(context.exception))

    def test_valid_initialization(self):
        """Test successful initialization with valid params."""
        # Valid 43-char key (will be base64 decoded to 32 bytes)
        valid_key = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
        crypto = WeComCrypto("token", valid_key, "corp123")
        
        self.assertEqual(crypto.token, "token")
        self.assertEqual(crypto.corp_id, "corp123")
        self.assertEqual(len(crypto.aes_key), 32)

    def test_signature_verification(self):
        """Test signature verification logic."""
        valid_key = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
        crypto = WeComCrypto("test_token", valid_key, "corp123")
        
        # Compute expected signature manually
        items = sorted(["test_token", "1234567890", "nonce123", "echostr"])
        expected_sig = hashlib.sha1("".join(items).encode()).hexdigest()

        
        # Should pass with correct signature
        self.assertTrue(crypto.verify_signature(expected_sig, "1234567890", "nonce123", "echostr"))
        
        # Should fail with wrong signature
        self.assertFalse(crypto.verify_signature("wrong_sig", "1234567890", "nonce123", "echostr"))


class TestWeComMessage(unittest.TestCase):
    """Tests for WeCom message parsing."""

    def test_parse_text_message(self):
        """Test parsing a text message."""
        xml = """
        <xml>
            <ToUserName><![CDATA[toUser]]></ToUserName>
            <FromUserName><![CDATA[fromUser]]></FromUserName>
            <CreateTime>1348831860</CreateTime>
            <MsgType><![CDATA[text]]></MsgType>
            <Content><![CDATA[Hello World!]]></Content>
            <MsgId>1234567890123456</MsgId>
            <AgentID>1</AgentID>
        </xml>
        """
        msg = parse_message(xml)
        
        self.assertEqual(msg.to_user_name, "toUser")
        self.assertEqual(msg.from_user_name, "fromUser")
        self.assertEqual(msg.create_time, 1348831860)
        self.assertEqual(msg.msg_type, "text")
        self.assertEqual(msg.content, "Hello World!")
        self.assertEqual(msg.msg_id, "1234567890123456")
        self.assertEqual(msg.agent_id, "1")
        self.assertTrue(msg.is_text)
        self.assertFalse(msg.is_event)

    def test_parse_event_message(self):
        """Test parsing an event message."""
        xml = """
        <xml>
            <ToUserName><![CDATA[toUser]]></ToUserName>
            <FromUserName><![CDATA[fromUser]]></FromUserName>
            <CreateTime>1348831860</CreateTime>
            <MsgType><![CDATA[event]]></MsgType>
        </xml>
        """
        msg = parse_message(xml)
        
        self.assertEqual(msg.msg_type, "event")
        self.assertTrue(msg.is_event)
        self.assertFalse(msg.is_text)

    def test_parse_missing_required_fields(self):
        """Test that parsing fails with missing required fields."""
        xml = """
        <xml>
            <ToUserName><![CDATA[toUser]]></ToUserName>
        </xml>
        """
        with self.assertRaises(WeComMessageParseError):
            parse_message(xml)

    def test_parse_invalid_xml(self):
        """Test that parsing fails with invalid XML."""
        with self.assertRaises(WeComMessageParseError):
            parse_message("not valid xml")


class TestFastAPIEndpoints(unittest.TestCase):
    """Integration tests for FastAPI callback endpoints."""

    def test_health_endpoint(self):
        """Test health check endpoint."""
        from fastapi.testclient import TestClient
        from src.crewai_enterprise.server.wecom_callback import app
        
        # Health endpoint should work without credentials
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/health")
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")


if __name__ == '__main__':
    unittest.main()
