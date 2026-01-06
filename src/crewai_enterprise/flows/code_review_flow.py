"""
Code Review Flow - A CrewAI Flow for automated multi-agent code review.

This flow orchestrates a team of AI agents to review code changes from GitLab:
1. Architecture & Security Reviewer (Claude)
2. Performance Reviewer (Gemini)
3. Testing Reviewer (GPT-4)
4. Summary Agent (Gemini) - Aggregates findings
"""

from crewai import Crew, Task
from crewai.flow.flow import Flow, start

from ..agents.code_review_agents import (
    create_arch_reviewer_agent,
    create_perf_reviewer_agent,
    create_summary_agent,
)
from ..tools.gitlab.gitlab_tool import GitLabTool

class CodeReviewFlow(Flow):
    """Flow for performing automated code reviews."""

    def __init__(self, gitlab_url: str, private_token: str, project_id: str, commit_sha: str):
        super().__init__()
        self.gitlab_url = gitlab_url
        self.private_token = private_token
        self.project_id = project_id
        self.commit_sha = commit_sha
        
        # Initialize Tool
        self.gitlab_tool = GitLabTool(
            gitlab_url=gitlab_url,
            private_token=private_token
        )

    @start()
    def review_code(self):
        """Execute the code review process with single agent for speed."""
        
        # 1. Create Agent (simplified to single agent for faster response)
        arch_agent = create_arch_reviewer_agent(self.gitlab_tool)
        
        # 2. Define Task
        review_task = Task(
            description=f"""
            Review Project: {self.project_id}, Commit: {self.commit_sha}.
            
            IMPORTANT: Always set ref="{self.commit_sha}" when using tools.
            
            Steps:
            1. Use get_diff to obtain changes.
            2. Use get_file with ref="{self.commit_sha}" to view context if needed.
            3. Identify architecture, security, and performance issues.
            4. Provide specific recommendations.
            5. Categorize by severity (Critical, Major, Minor).
            6. Give final conclusion: Should this be merged?
            
            Respond in Chinese (中文).
            """,
            agent=arch_agent,
            expected_output="Code review report with issues and recommendations (Markdown format)"
        )

        # 3. Create Crew and Kickoff (max_iter=3 to prevent timeout)
        review_crew = Crew(
            agents=[arch_agent],
            tasks=[review_task],
            verbose=True,
            max_iter=3
        )

        result = review_crew.kickoff()
        return str(result)

