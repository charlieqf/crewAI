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
        qa_agent = create_codebase_qa_agent(self.gitlab_tool)
        
        # 2. Define Task
        qa_task = Task(
            description=f"""
            Answer user question about Project: {self.project_id}.
            
            User Question: {self.query}
            
            Additional Context (e.g., image description): 
            {self.context}
            
            IMPORTANT: Always use ref="{self.branch}" when calling get_file, list_files, or search_code to ensure you're viewing the correct branch.
            
            Action Guide:
            1. Extract keywords from the question (class names, function names, error messages).
            2. Use list_files with ref="{self.branch}" to view root directory structure to infer code organization.
            3. Use search_code to search for keywords.
            4. Use get_file with ref="{self.branch}" to read relevant code.
            5. If it's an error, try to find where the error message is defined or thrown.
            
            Provide a clear, evidence-based answer.
            """,
            agent=qa_agent,
            expected_output="Detailed answer to user's question including code references and potential solutions"
        )

        # 3. Create Crew and Kickoff
        qa_crew = Crew(
            agents=[qa_agent],
            tasks=[qa_task],
            verbose=True
        )

        result = qa_crew.kickoff()
        return str(result)
