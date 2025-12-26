"""
GitLabTool - GitLab integration tool for CrewAI agents.

Enables automated code review by fetching commit diffs and posting comments.
"""
import json
import logging
from typing import Literal, Optional, Type
from urllib.parse import quote

import requests
from pydantic import BaseModel, Field, PrivateAttr

from crewai.tools import BaseTool

logger = logging.getLogger(__name__)


# --- Custom Exceptions ---
class GitLabAuthenticationError(Exception):
    """Raised when GitLab authentication fails."""
    pass


class GitLabAPIError(Exception):
    """Raised when GitLab API returns an error."""
    pass


# --- Input Schema ---
class GitLabToolInput(BaseModel):
    """Input schema for GitLabTool."""
    action: Literal["get_diff", "get_mr_changes", "post_comment"] = Field(
        ..., 
        description="The action to perform: 'get_diff' (get commit diff), 'get_mr_changes' (get MR changes), 'post_comment' (post comment on commit)"
    )
    project_id: str = Field(
        ..., 
        description="The GitLab project ID or URL-encoded path (e.g., '123' or 'group/project')"
    )
    commit_sha: Optional[str] = Field(
        None, 
        description="The commit SHA for get_diff or post_comment actions"
    )
    mr_iid: Optional[int] = Field(
        None, 
        description="The Merge Request IID for get_mr_changes action"
    )
    comment: Optional[str] = Field(
        None, 
        description="The comment text for post_comment action"
    )


# --- Tool Implementation ---
class GitLabTool(BaseTool):
    """A tool to interact with GitLab for automated code review."""
    
    name: str = "GitLab Tool"
    description: str = "A tool to fetch commit diffs and post review comments on GitLab."
    args_schema: Type[BaseModel] = GitLabToolInput
    
    # Configuration
    gitlab_url: str = Field(..., exclude=True, description="GitLab server URL (e.g., http://gitlab.example.com)")
    private_token: str = Field(..., exclude=True, description="GitLab Private Access Token")
    
    def _get_headers(self) -> dict:
        """Get request headers with authentication."""
        return {
            "PRIVATE-TOKEN": self.private_token,
            "Content-Type": "application/json"
        }
    
    def _encode_project_id(self, project_id: str) -> str:
        """URL encode project path if it contains slashes."""
        if "/" in project_id:
            return quote(project_id, safe="")
        return project_id

    def _run(
        self, 
        action: str,
        project_id: str,
        commit_sha: Optional[str] = None,
        mr_iid: Optional[int] = None,
        comment: Optional[str] = None
    ) -> str:
        """Execute the tool logic."""
        
        if action == "get_diff":
            return self._get_commit_diff(project_id, commit_sha)
        elif action == "get_mr_changes":
            return self._get_mr_changes(project_id, mr_iid)
        elif action == "post_comment":
            return self._post_comment(project_id, commit_sha, comment)
        else:
            raise ValueError(f"Unknown action: {action}")

    def _get_commit_diff(self, project_id: str, commit_sha: str) -> str:
        """Get the diff for a specific commit."""
        if not commit_sha:
            raise GitLabAPIError("commit_sha is required for get_diff action")
        
        encoded_project = self._encode_project_id(project_id)
        url = f"{self.gitlab_url}/api/v4/projects/{encoded_project}/repository/commits/{commit_sha}/diff"
        
        try:
            response = requests.get(url, headers=self._get_headers(), timeout=30)
            
            if response.status_code == 401:
                raise GitLabAuthenticationError("Invalid GitLab token or insufficient permissions")
            
            response.raise_for_status()
            diff_data = response.json()
            
            # Format the diff for readability
            formatted_diff = []
            for file_diff in diff_data:
                formatted_diff.append(f"File: {file_diff.get('new_path', 'unknown')}")
                formatted_diff.append(file_diff.get('diff', ''))
                formatted_diff.append("---")
            
            logger.info(f"Retrieved diff for commit {commit_sha} in project {project_id}")
            return "\n".join(formatted_diff)
            
        except requests.exceptions.RequestException as e:
            if "401" in str(e):
                raise GitLabAuthenticationError(f"Authentication failed: {e}") from e
            raise GitLabAPIError(f"Failed to get commit diff: {e}") from e

    def _get_mr_changes(self, project_id: str, mr_iid: int) -> str:
        """Get the changes in a Merge Request."""
        if not mr_iid:
            raise GitLabAPIError("mr_iid is required for get_mr_changes action")
        
        encoded_project = self._encode_project_id(project_id)
        url = f"{self.gitlab_url}/api/v4/projects/{encoded_project}/merge_requests/{mr_iid}/changes"
        
        try:
            response = requests.get(url, headers=self._get_headers(), timeout=30)
            
            if response.status_code == 401:
                raise GitLabAuthenticationError("Invalid GitLab token or insufficient permissions")
            
            response.raise_for_status()
            mr_data = response.json()
            
            # Format the MR changes
            changes = mr_data.get("changes", [])
            formatted = [f"MR !{mr_iid}: {mr_data.get('title', 'No title')}"]
            formatted.append(f"Source: {mr_data.get('source_branch', '')} -> {mr_data.get('target_branch', '')}")
            formatted.append(f"Files changed: {len(changes)}")
            formatted.append("---")
            
            for change in changes:
                formatted.append(f"File: {change.get('new_path', 'unknown')}")
                formatted.append(change.get('diff', '')[:500])  # Truncate long diffs
                formatted.append("---")
            
            logger.info(f"Retrieved changes for MR !{mr_iid} in project {project_id}")
            return "\n".join(formatted)
            
        except requests.exceptions.RequestException as e:
            if "401" in str(e):
                raise GitLabAuthenticationError(f"Authentication failed: {e}") from e
            raise GitLabAPIError(f"Failed to get MR changes: {e}") from e

    def _post_comment(self, project_id: str, commit_sha: str, comment: str) -> str:
        """Post a comment on a commit."""
        if not commit_sha:
            raise GitLabAPIError("commit_sha is required for post_comment action")
        if not comment:
            raise GitLabAPIError("comment is required for post_comment action")
        
        encoded_project = self._encode_project_id(project_id)
        url = f"{self.gitlab_url}/api/v4/projects/{encoded_project}/repository/commits/{commit_sha}/comments"
        
        payload = {"note": comment}
        
        try:
            response = requests.post(url, headers=self._get_headers(), json=payload, timeout=30)
            
            if response.status_code == 401:
                raise GitLabAuthenticationError("Invalid GitLab token or insufficient permissions")
            
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"Posted comment on commit {commit_sha} in project {project_id}")
            return f"Comment posted successfully. Comment ID: {result.get('id', 'unknown')}"
            
        except requests.exceptions.RequestException as e:
            if "401" in str(e):
                raise GitLabAuthenticationError(f"Authentication failed: {e}") from e
            raise GitLabAPIError(f"Failed to post comment: {e}") from e
