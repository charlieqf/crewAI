"""
Unit tests for WeComTool.
"""
import unittest
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from src.crewai_enterprise.tools.wecom.wecom_tool import (
    WeComAuthenticationError,
    WeComSendError,
    WeComTool,
    WeComToolInput,
)


class TestWeComToolInput(unittest.TestCase):
    """Tests for input validation."""

    def test_valid_text_input(self):
        """Test valid text message input."""
        input_data = WeComToolInput(content="Hello", msg_type="text")
        self.assertEqual(input_data.content, "Hello")
        self.assertEqual(input_data.msg_type, "text")

    def test_valid_markdown_input(self):
        """Test valid markdown message input."""
        input_data = WeComToolInput(content="# Title", msg_type="markdown")
        self.assertEqual(input_data.msg_type, "markdown")

    def test_invalid_msg_type(self):
        """Test that invalid message types are rejected by Pydantic."""
        with self.assertRaises(ValidationError):
            WeComToolInput(content="test", msg_type="invalid_type")


class TestWeComTool(unittest.TestCase):
    """Tests for WeComTool functionality."""

    def setUp(self):
        self.corp_id = "corp123"
        self.agent_id = "agent456"
        self.secret = "test_secret"
        self.tool = WeComTool(
            corp_id=self.corp_id,
            agent_id=self.agent_id,
            secret=self.secret
        )

    @patch('src.crewai_enterprise.tools.wecom.wecom_tool.requests.get')
    def test_get_access_token_success(self, mock_get):
        """Test successful token retrieval."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"errcode": 0, "access_token": "new_token"}
        mock_get.return_value = mock_response

        token = self.tool._get_access_token()
        
        self.assertEqual(token, "new_token")
        mock_get.assert_called_once()
        # Verify correct URL with corp_id (not agent_id)
        call_url = mock_get.call_args[0][0]
        self.assertIn(f"corpid={self.corp_id}", call_url)
        self.assertIn(f"corpsecret={self.secret}", call_url)

    @patch('src.crewai_enterprise.tools.wecom.wecom_tool.requests.get')
    def test_get_access_token_auth_error(self, mock_get):
        """Test token retrieval failure raises typed exception."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"errcode": 40014, "errmsg": "invalid secret"}
        mock_get.return_value = mock_response

        with self.assertRaises(WeComAuthenticationError) as context:
            self.tool._get_access_token()
        
        self.assertIn("40014", str(context.exception))

    @patch('src.crewai_enterprise.tools.wecom.wecom_tool.requests.post')
    @patch('src.crewai_enterprise.tools.wecom.wecom_tool.WeComTool._get_access_token')
    def test_send_text_to_all_users(self, mock_get_token, mock_post):
        """Test sending text message to all users (broadcast)."""
        mock_get_token.return_value = "fake_token"
        mock_response = MagicMock()
        mock_response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        mock_post.return_value = mock_response

        result = self.tool._run(content="Hello WeCom", msg_type="text")
        
        self.assertEqual(result, "Message sent successfully")
        # Verify payload uses touser for broadcast
        payload = mock_post.call_args.kwargs.get('json')
        self.assertEqual(payload["touser"], "@all")
        self.assertNotIn("chatid", payload)

    @patch('src.crewai_enterprise.tools.wecom.wecom_tool.requests.post')
    @patch('src.crewai_enterprise.tools.wecom.wecom_tool.WeComTool._get_access_token')
    def test_send_markdown_to_group_chat(self, mock_get_token, mock_post):
        """Test sending markdown message to a specific group chat."""
        mock_get_token.return_value = "fake_token"
        mock_response = MagicMock()
        mock_response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        mock_post.return_value = mock_response

        result = self.tool._run(content="# Report", msg_type="markdown", chat_id="group123")
        
        self.assertEqual(result, "Message sent successfully")
        # Verify payload uses chatid for group chat
        payload = mock_post.call_args.kwargs.get('json')
        self.assertEqual(payload["chatid"], "group123")
        self.assertEqual(payload["msgtype"], "markdown")
        self.assertNotIn("touser", payload)

    def test_token_cache_is_instance_isolated(self):
        """Test that token cache is not shared between instances."""
        tool1 = WeComTool(corp_id="corp1", agent_id="agent1", secret="secret1")
        tool2 = WeComTool(corp_id="corp2", agent_id="agent2", secret="secret2")
        
        # Manually set token cache on tool1
        tool1._token_cache = "token_for_corp1"
        
        # tool2 should NOT have this token
        self.assertIsNone(tool2._token_cache)

    @patch('src.crewai_enterprise.tools.wecom.wecom_tool.requests.post')
    @patch('src.crewai_enterprise.tools.wecom.wecom_tool.WeComTool._get_access_token')
    def test_send_error_raises_exception(self, mock_get_token, mock_post):
        """Test that send failure raises WeComSendError."""
        mock_get_token.return_value = "fake_token"
        mock_response = MagicMock()
        mock_response.json.return_value = {"errcode": 40001, "errmsg": "invalid credential"}
        mock_post.return_value = mock_response

        with self.assertRaises(WeComSendError) as context:
            self.tool._run(content="Hello", msg_type="text")
        
        self.assertIn("40001", str(context.exception))
        self.assertIn("invalid credential", str(context.exception))


if __name__ == '__main__':
    unittest.main()
