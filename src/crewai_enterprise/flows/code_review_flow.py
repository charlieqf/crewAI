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
        """Execute the code review process with multiple agents."""
        
        # 1. Create Agents
        arch_agent = create_arch_reviewer_agent(self.gitlab_tool)
        perf_agent = create_perf_reviewer_agent(self.gitlab_tool)
        # test_agent = create_test_reviewer_agent(self.gitlab_tool) # User requested to disable test agent
        summary_agent = create_summary_agent()
        
        # 2. Define Tasks
        
        # Common description for review tasks
        base_desc = f"""
        Review Project: {self.project_id}, Commit: {self.commit_sha}.
        
        IMPORTANT: When using get_file, list_files, or search_code, always set ref="{self.commit_sha}" to ensure you're viewing the code at this specific commit, NOT the main branch.
        
        1. Use get_diff to obtain changes.
        2. MUST use get_file with ref="{self.commit_sha}" to view full context of modified files.
        3. If necessary, use search_code to find references.
        
        Identify potential issues in your area of expertise and provide specific recommendations.
        """

        arch_task = Task(
            description=f"From architecture and security perspective: {base_desc}",
            agent=arch_agent,
            expected_output="Architecture and security review report including design pattern analysis and security risk warnings",
            async_execution=True  # Run in parallel
        )

        perf_task = Task(
            description=f"From performance perspective: {base_desc}",
            agent=perf_agent,
            expected_output="Performance review report including algorithm complexity and resource usage analysis",
            async_execution=True  # Run in parallel
        )

        # test_task = Task(
        #     description=f"从测试和可维护性角度: {base_desc}",
        #     agent=test_agent,
        #     expected_output="测试与质量审查报告，包含测试覆盖率和代码规范分析",
        #     async_execution=True  # Run in parallel
        # )

        # Summary task depends on the 2 review tasks
        summary_task = Task(
            description=f"""
            Aggregate the review reports from 2 experts (Architecture, Performance) and generate the final code review feedback.
            
            Commit: {self.commit_sha}
            
            Requirements:
            1. Consolidate duplicate opinions.
            2. Resolve conflicting suggestions.
            3. Categorize issues by severity (Critical, Major, Minor).
            4. Provide final conclusion: Should this be merged?
            """,
            agent=summary_agent,
            context=[arch_task, perf_task], # Wait for these tasks
            expected_output="Final aggregated code review report (Markdown format)"
        )

        # 3. Create Crew and Kickoff
        review_crew = Crew(
            agents=[arch_agent, perf_agent, summary_agent],
            tasks=[arch_task, perf_task, summary_task],
            verbose=True
        )

        result = review_crew.kickoff()
        return str(result)
