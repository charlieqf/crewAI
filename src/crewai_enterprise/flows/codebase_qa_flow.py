"""
Codebase QA Flow - A CrewAI Flow for general codebase questions.

This flow utilizes the Codebase QA Agent to answer questions about:
- Feature location
- Error diagnosis
- Script usage
- General code logic
"""

from crewai import Crew, Task
from crewai.flow.flow import Flow, start

from ..agents.codebase_qa_agents import create_codebase_qa_agent
from ..tools.gitlab.gitlab_tool import GitLabTool

class CodebaseQAFlow(Flow):
    """Flow for answering codebase questions."""

    def __init__(self, gitlab_url: str, private_token: str, project_id: str, query: str, context: str = "", branch: str = "main"):
        super().__init__()
        self.gitlab_url = gitlab_url
        self.private_token = private_token
        self.project_id = project_id
        self.query = query
        self.context = context # For passing image descriptions or previous conversation context
        self.branch = branch # Target branch for file operations
        
        # Initialize Tool
        self.gitlab_tool = GitLabTool(
            gitlab_url=gitlab_url,
            private_token=private_token
        )

    @start()
    def ask_question(self):
        """Execute the QA process."""
        
        # 1. Create Agent
        # Lock the tool to the specific project and branch to prevent agent hallucinations
        self.gitlab_tool.fixed_branch = self.branch
        self.gitlab_tool.fixed_project_id = self.project_id
        qa_agent = create_codebase_qa_agent(self.gitlab_tool)
        
        # 2. Define Task (simplified to reduce iterations)
        qa_task = Task(
            description=f"""Answer this question about the codebase: 
            "{self.query}"
            
            Context: {self.context}
            Branch: {self.branch}
            
            Quick Guidelines:
            1. Use search_code to find files matching the query keywords.
            2. Report the search results directly - list file paths and relevant snippets.
            3. Only use get_file if you need to see more context from a specific file.
            4. Keep your answer concise and focused on the user's question.
            5. Always respond in Chinese (中文).
            """,
            agent=qa_agent,
            expected_output="Concise answer with file paths and code snippets"
        )

        # 3. Create Crew and Kickoff (max_iter=3 to prevent timeout)
        qa_crew = Crew(
            agents=[qa_agent],
            tasks=[qa_task],
            verbose=True,
            max_iter=3  # Limit iterations to prevent WeCom timeout
        )

        result = qa_crew.kickoff()
        return str(result)
