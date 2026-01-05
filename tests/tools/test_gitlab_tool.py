"""
Unit tests for GitLabTool.

Tests updated to mock python-gitlab library with proper isolation.
"""
import sys
import unittest
from unittest.mock import MagicMock, patch

# Note: We do NOT import the tool at top-level to avoid "baking in" the mocks
# or failing if dependencies are missing. We import inside the test setup.

class TestGitLabTool(unittest.TestCase):
    """Tests for GitLabTool functionality."""

    @classmethod
    def setUpClass(cls):
        # 1. Prepare global patches
        cls.gitlab_mock = MagicMock()
        cls.gitlab_exceptions_mock = MagicMock()
        
        # Setup exceptions structure
        class MockGitlabError(Exception): pass
        class MockGitlabGetError(MockGitlabError): pass
        class MockGitlabAuthenticationError(MockGitlabError): pass
        
        cls.gitlab_exceptions_mock.GitlabError = MockGitlabError
        cls.gitlab_exceptions_mock.GitlabGetError = MockGitlabGetError
        cls.gitlab_exceptions_mock.GitlabAuthenticationError = MockGitlabAuthenticationError
        
        cls.gitlab_mock.exceptions = cls.gitlab_exceptions_mock
        cls.gitlab_mock.Gitlab.return_value = MagicMock()

        # Patch sys.modules globally for this class's duration
        cls.modules_patcher = patch.dict(sys.modules, {
            'gitlab': cls.gitlab_mock,
            'gitlab.exceptions': cls.gitlab_exceptions_mock
        })
        cls.modules_patcher.start()
        
        # Import SUT once to avoid PyO3 reload issues
        import src.crewai_enterprise.tools.gitlab.gitlab_tool as gitlab_tool_module
        cls.gitlab_tool_module = gitlab_tool_module
        
    @classmethod
    def tearDownClass(cls):
        cls.modules_patcher.stop()

    def setUp(self):
        # Reset mocks between tests
        self.gitlab_mock.reset_mock()
        # Ensure the module has the right references (just in case)
        self.gitlab_tool_module.gitlab = self.gitlab_mock
        self.gitlab_tool_module.gitlab.exceptions = self.gitlab_exceptions_mock
        
        # Helper aliases
        self.GitLabTool = self.gitlab_tool_module.GitLabTool
        self.GitLabToolInput = self.gitlab_tool_module.GitLabToolInput
        self.GitLabAPIError = self.gitlab_tool_module.GitLabAPIError
        self.GitLabAuthenticationError = self.gitlab_tool_module.GitLabAuthenticationError
        self.ValidationError = getattr(sys.modules.get('pydantic', MagicMock()), 'ValidationError', None)
        if not self.ValidationError:
            from pydantic import ValidationError
            self.ValidationError = ValidationError
        
        self.gitlab_url = "http://gitlab.example.com"
        self.private_token = "test_token"
        
        # Capture the Gitlab client mock that the instantiations will return
        self.mock_gl_client = MagicMock()
        self.gitlab_mock.Gitlab.return_value = self.mock_gl_client
        
        # We need to ensure that subsequent calls to Gitlab() return our FRESH mock client
        # because the tool calls Gitlab() in its __init__
        
        self.tool = self.GitLabTool(
            gitlab_url=self.gitlab_url,
            private_token=self.private_token
        )

    def test_valid_get_diff_input(self):
        """Test valid input for getting commit diff."""
        input_data = self.GitLabToolInput(
            action="get_diff",
            project_id="123",
            commit_sha="abc123def"
        )
        self.assertEqual(input_data.action, "get_diff")
        self.assertEqual(input_data.project_id, "123")
        self.assertEqual(input_data.commit_sha, "abc123def")

    def test_valid_get_file_input(self):
        """Test valid input for getting file content."""
        input_data = self.GitLabToolInput(
            action="get_file",
            project_id="123",
            file_path="src/main.py"
        )
        self.assertEqual(input_data.action, "get_file")
        self.assertEqual(input_data.file_path, "src/main.py")

    def test_invalid_action(self):
        """Test that invalid action are rejected."""
        with self.assertRaises(self.ValidationError):
            self.GitLabToolInput(
                action="invalid_action",
                project_id="123"
            )

    def test_init_success(self):
        """Test successful initialization."""
        self.gitlab_mock.Gitlab.assert_called_with(self.gitlab_url, private_token=self.private_token)

    def test_init_failure(self):
        """Test initialization failure."""
        self.gitlab_mock.Gitlab.side_effect = Exception("Connection error")
        with self.assertRaises(self.GitLabAuthenticationError):
            self.GitLabTool(gitlab_url="bad", private_token="bad")
        # Restore side effect
        self.gitlab_mock.Gitlab.side_effect = None

    def test_get_commit_diff_success(self):
        """Test successful commit diff retrieval."""
        mock_project = MagicMock()
        self.mock_gl_client.projects.get.return_value = mock_project
        
        mock_commit = MagicMock()
        mock_commit.message = "Test commit"
        mock_project.commits.get.return_value = mock_commit
        
        # Diff return structure
        mock_commit.diff.return_value = [
            {"new_path": "src/main.py", "diff": "@@ -1 +1 @@\n-old\n+new"},
        ]

        result = self.tool._run(
            action="get_diff",
            project_id="1",
            commit_sha="abc123"
        )
        
        self.assertIn("src/main.py", result)
        self.mock_gl_client.projects.get.assert_called_with("1")
        mock_project.commits.get.assert_called_with("abc123")

    def test_get_file_success(self):
        """Test successful file content retrieval."""
        mock_project = MagicMock()
        self.mock_gl_client.projects.get.return_value = mock_project
        
        mock_file = MagicMock()
        mock_file.decode.return_value = b"file content"
        mock_project.files.get.return_value = mock_file

        result = self.tool._run(
            action="get_file",
            project_id="1",
            file_path="test.py"
        )
        
        self.assertIn("file content", result)
        mock_project.files.get.assert_called_with(file_path="test.py", ref="main")

    def test_get_file_binary(self):
        """Test handling of binary/non-UTF8 files."""
        mock_project = MagicMock()
        self.mock_gl_client.projects.get.return_value = mock_project
        
        mock_file = MagicMock()
        # Invalid utf-8 sequence
        mock_file.decode.return_value = b"\x80abc" 
        mock_project.files.get.return_value = mock_file

        result = self.tool._run(
            action="get_file",
            project_id="1",
            file_path="binary.dat"
        )
        
        self.assertIn("Binary or non-UTF-8", result)

    def test_api_error_handling(self):
        """Test API error handling."""
        # Use classes from our dynamic mock setup
        self.mock_gl_client.projects.get.side_effect = self.gitlab_exceptions_mock.GitlabGetError("Not Found")
        
        with self.assertRaises(self.GitLabAPIError):
            self.tool._run(
                action="get_diff",
                project_id="999",
                commit_sha="abc"
            )

if __name__ == '__main__':
    unittest.main()
