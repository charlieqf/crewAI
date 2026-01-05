"""
GitLabTool - GitLab integration tool for CrewAI agents.

Enables automated code review by fetching commit diffs, reading files, searching code,
listing directories, and posting comments using the python-gitlab library.
"""
import logging
from typing import Literal, Optional, Type, Any

import gitlab
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
    action: Literal[
        "get_diff", 
        "get_mr_changes", 
        "post_comment", 
        "get_file", 
        "search_code", 
        "list_files"
    ] = Field(
        ..., 
        description="The action to perform: 'get_diff', 'get_mr_changes', 'post_comment', 'get_file', 'search_code', 'list_files'"
    )
    project_id: str = Field(
        ..., 
        description="The GitLab project ID or path (e.g., '123' or 'group/project')"
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
    file_path: Optional[str] = Field(
        None,
        description="The full path to the file for get_file action"
    )
    ref: Optional[str] = Field(
        "main",
        description="The branch, tag or commit SHA to use (default: main)"
    )
    query: Optional[str] = Field(
        None,
        description="The search query for search_code action"
    )
    path: Optional[str] = Field(
        None,
        description="The directory path for list_files action"
    )


# --- Tool Implementation ---
class GitLabTool(BaseTool):
    """A tool to interact with GitLab for automated code review."""
    
    name: str = "GitLab Tool"
    description: str = "A tool to fetch commit diffs, read files, search code, and post review comments on GitLab."
    args_schema: Type[BaseModel] = GitLabToolInput
    
    # Configuration
    gitlab_url: str = Field(..., exclude=True, description="GitLab server URL")
    private_token: str = Field(..., exclude=True, description="GitLab Private Access Token")
    
    # python-gitlab client
    _gl: Any = PrivateAttr()
    
    def __init__(self, **data):
        super().__init__(**data)
        try:
            self._gl = gitlab.Gitlab(self.gitlab_url, private_token=self.private_token)
        except Exception as e:
            logger.error(f"Failed to initialize GitLab client: {e}")
            raise GitLabAuthenticationError(f"Failed to initialize GitLab client: {e}")

    def _run(
        self, 
        action: str,
        project_id: str,
        commit_sha: Optional[str] = None,
        mr_iid: Optional[int] = None,
        comment: Optional[str] = None,
        file_path: Optional[str] = None,
        ref: str = "main",
        query: Optional[str] = None,
        path: Optional[str] = None
    ) -> str:
        """Execute the tool logic."""
        try:
            # projects.get can take id or 'namespace/project'
            project = self._gl.projects.get(project_id)
        except gitlab.exceptions.GitlabAuthenticationError as e:
            raise GitLabAuthenticationError(f"Authentication failed: {e}")
        except gitlab.exceptions.GitlabGetError as e:
            raise GitLabAPIError(f"Project not found or access denied: {project_id}. Error: {e}")
        
        if action == "get_diff":
            return self._get_commit_diff(project, commit_sha)
        elif action == "get_mr_changes":
            return self._get_mr_changes(project, mr_iid)
        elif action == "post_comment":
            return self._post_comment(project, commit_sha, comment)
        elif action == "get_file":
            if not file_path:
                raise ValueError("file_path is required for get_file action")
            return self._get_file_content(project, file_path, ref)
        elif action == "search_code":
            if not query:
                raise ValueError("query is required for search_code action")
            return self._search_code(project, query, ref)
        elif action == "list_files":
            return self._list_repository_tree(project, path or "", ref)
        else:
            raise ValueError(f"Unknown action: {action}")

    def _get_commit_diff(self, project: Any, commit_sha: Optional[str]) -> str:
        """Get the diff for a specific commit."""
        if not commit_sha:
            raise GitLabAPIError("commit_sha is required for get_diff action")
        
        try:
            commit = project.commits.get(commit_sha)
            diffs = commit.diff()
            
            # Format the diff for readability
            formatted_diff = [f"Commit: {commit_sha}", f"Message: {commit.message}", "-"*20]
            for diff in diffs:
                formatted_diff.append(f"File: {diff.get('new_path', 'unknown')}")
                # python-gitlab diff dict structure usually mirrors the API response
                diff_content = diff.get('diff', '')
                formatted_diff.append(diff_content)
                formatted_diff.append("---")
            
            logger.info(f"Retrieved diff for commit {commit_sha} in project {project.id}")
            return "\n".join(formatted_diff)
            
        except gitlab.exceptions.GitlabGetError as e:
            raise GitLabAPIError(f"Commit not found: {commit_sha}. Error: {e}")

    def _get_mr_changes(self, project: Any, mr_iid: Optional[int]) -> str:
        """Get the changes in a Merge Request."""
        if not mr_iid:
            raise GitLabAPIError("mr_iid is required for get_mr_changes action")
        
        try:
            mr = project.mergerequests.get(mr_iid)
            changes = mr.changes()
            
            formatted = [f"MR !{mr_iid}: {mr.title}"]
            formatted.append(f"Source: {mr.source_branch} -> {mr.target_branch}")
            formatted.append(f"Files changed: {len(changes.get('changes', []))}")
            formatted.append("---")
            
            for change in changes.get('changes', []):
                formatted.append(f"File: {change.get('new_path', 'unknown')}")
                formatted.append(change.get('diff', '')[:500])  # Truncate long diffs
                formatted.append("---")
            
            logger.info(f"Retrieved changes for MR !{mr_iid} in project {project.id}")
            return "\n".join(formatted)
            
        except gitlab.exceptions.GitlabGetError as e:
            raise GitLabAPIError(f"MR not found: {mr_iid}. Error: {e}")

    def _post_comment(self, project: Any, commit_sha: Optional[str], comment: Optional[str]) -> str:
        """Post a comment on a commit."""
        if not commit_sha:
            raise GitLabAPIError("commit_sha is required for post_comment action")
        if not comment:
            raise GitLabAPIError("comment is required for post_comment action")
        
        try:
            commit = project.commits.get(commit_sha)
            # Use 'note' as per API
            result = commit.comments.create({'note': comment})
            
            # result is a Comment object, we can access attributes
            logger.info(f"Posted comment on commit {commit_sha} in project {project.id}")
            return f"Comment posted successfully. Note ID: {getattr(result, 'id', 'unknown')}"
            
        except gitlab.exceptions.GitlabError as e:
            raise GitLabAPIError(f"Failed to post comment: {e}")

    def _get_file_content(self, project: Any, file_path: str, ref: str) -> str:
        """Get repository file content."""
        try:
            f = project.files.get(file_path=file_path, ref=ref)
            # project.files.get returns a File object with content in base64
            # python-gitlab's decode() returns bytes
            content_bytes = f.decode()
            
            # Handle case where decode() might return string in some versions
            if isinstance(content_bytes, str):
                content = content_bytes
            else:
                try:
                    content = content_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    logger.warning(f"File {file_path} is binary or non-UTF-8")
                    return f"File: {file_path}\n{'='*60}\n[Binary or non-UTF-8 content - size: {len(content_bytes)} bytes]"
            
            return f"File: {file_path}\n{'='*60}\n{content}"
        except gitlab.exceptions.GitlabGetError:
            raise GitLabAPIError(f"File not found: {file_path} at ref {ref}")
        except Exception as e:
            raise GitLabAPIError(f"Error reading file {file_path}: {e}")

    def _search_code(self, project: Any, query: str, ref: str = "main") -> str:
        """Search code in the project.
        
        Args:
            project: GitLab project object
            query: Search query string
            ref: Branch, tag, or commit to search in (default: main)
        """
        try:
            # scope='blobs' searches file content, ref specifies the branch
            results = project.search('blobs', query, ref=ref) 
            
            formatted = [f"Search results for '{query}':"]
            
            # Limit results - iterate lazily instead of loading all
            count = 0
            for item in results:
                if count >= 10:
                    break
                formatted.append(f"\nFile: {item.get('path', 'unknown')}")
                # 'data' usually contains the matching line or snippet
                snippet = item.get('data', '')
                if isinstance(snippet, str):
                    formatted.append(f"Match: {snippet[:200]}")
                else:
                    formatted.append(f"Match: {str(snippet)[:200]}")
                count += 1
            
            return "\n".join(formatted)
        except Exception as e:
            raise GitLabAPIError(f"Search failed: {e}")

    def _list_repository_tree(self, project: Any, path: str, ref: str) -> str:
        """List files in directory."""
        try:
            items = project.repository_tree(path=path, ref=ref, recursive=False)
            
            formatted = [f"Directory: {path or '/'}"]
            for item in items:
                icon = "📁" if item['type'] == 'tree' else "📄"
                formatted.append(f"{icon} {item['name']}")
            
            return "\n".join(formatted)
        except Exception as e:
            raise GitLabAPIError(f"Failed to list directory: {e}")
