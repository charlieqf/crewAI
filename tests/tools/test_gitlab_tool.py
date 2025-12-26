"""
Unit tests for GitLabTool.

Following TDD approach - tests written before implementation.
"""
import unittest
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from src.crewai_enterprise.tools.gitlab.gitlab_tool import (
    GitLabAPIError,
    GitLabAuthenticationError,
    GitLabTool,
    GitLabToolInput,
)


class TestGitLabToolInput(unittest.TestCase):
    """Tests for input validation."""

    def test_valid_get_diff_input(self):
        """Test valid input for getting commit diff."""
        input_data = GitLabToolInput(
            action="get_diff",
            project_id="123",
            commit_sha="abc123def"
        )
        self.assertEqual(input_data.action, "get_diff")
        self.assertEqual(input_data.project_id, "123")
        self.assertEqual(input_data.commit_sha, "abc123def")

    def test_valid_post_comment_input(self):
        """Test valid input for posting comment."""
        input_data = GitLabToolInput(
            action="post_comment",
            project_id="123",
            commit_sha="abc123def",
            comment="Great code!"
        )
        self.assertEqual(input_data.action, "post_comment")
        self.assertEqual(input_data.comment, "Great code!")

    def test_invalid_action(self):
        """Test that invalid actions are rejected."""
        with self.assertRaises(ValidationError):
            GitLabToolInput(
                action="invalid_action",
                project_id="123"
            )


class TestGitLabTool(unittest.TestCase):
    """Tests for GitLabTool functionality."""

    def setUp(self):
        self.gitlab_url = "http://gitlab.example.com"
        self.private_token = "test_token"
        self.tool = GitLabTool(
            gitlab_url=self.gitlab_url,
            private_token=self.private_token
        )

    @patch('src.crewai_enterprise.tools.gitlab.gitlab_tool.requests.get')
    def test_get_commit_diff_success(self, mock_get):
        """Test successful commit diff retrieval."""
        mock_response = MagicMock()
        # GitLab diff API returns a list of file diffs
        mock_response.json.return_value = [
            {"new_path": "src/main.py", "diff": "@@ -1 +1 @@\n-old\n+new"},
            {"new_path": "README.md", "diff": "@@ -1 +1 @@\n-v1\n+v2"}
        ]
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = self.tool._run(
            action="get_diff",
            project_id="1",
            commit_sha="abc123"
        )
        
        self.assertIn("src/main.py", result)
        mock_get.assert_called_once()
        # Verify correct URL construction
        call_url = mock_get.call_args[0][0]
        self.assertIn(self.gitlab_url, call_url)
        self.assertIn("projects/1", call_url)

    @patch('src.crewai_enterprise.tools.gitlab.gitlab_tool.requests.get')
    def test_get_commit_diff_with_url_encoded_project(self, mock_get):
        """Test that project paths are URL encoded."""
        mock_response = MagicMock()
        mock_response.json.return_value = [{"new_path": "file.py", "diff": "+code"}]
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        self.tool._run(
            action="get_diff",
            project_id="group/project",
            commit_sha="abc123"
        )
        
        call_url = mock_get.call_args[0][0]
        # Slash should be URL encoded as %2F
        self.assertIn("group%2Fproject", call_url)

    @patch('src.crewai_enterprise.tools.gitlab.gitlab_tool.requests.post')
    def test_post_comment_success(self, mock_post):
        """Test successful comment posting."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": 1, "note": "Great code!"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = self.tool._run(
            action="post_comment",
            project_id="1",
            commit_sha="abc123",
            comment="Great code!"
        )
        
        self.assertIn("Comment posted", result)
        mock_post.assert_called_once()

    @patch('src.crewai_enterprise.tools.gitlab.gitlab_tool.requests.get')
    def test_authentication_error(self, mock_get):
        """Test authentication failure raises typed exception."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response

        with self.assertRaises(GitLabAuthenticationError):
            self.tool._run(
                action="get_diff",
                project_id="1",
                commit_sha="abc123"
            )

    @patch('src.crewai_enterprise.tools.gitlab.gitlab_tool.requests.get')
    def test_api_error(self, mock_get):
        """Test API error raises typed exception."""
        import requests as req
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = req.exceptions.HTTPError("404 Not Found")
        mock_get.return_value = mock_response

        with self.assertRaises(GitLabAPIError):
            self.tool._run(
                action="get_diff",
                project_id="999",
                commit_sha="nonexistent"
            )


if __name__ == '__main__':
    unittest.main()
