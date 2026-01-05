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
        
        # 2. Define Task
        qa_task = Task(
            description=f"""Analyze the codebase to answer the following question: 
            "{self.query}"
            
            Context provided: {self.context}
            
            Strict Guidelines:
            1. You MUST use search_code to find files matching internal names (tables, fields, etc.).
            2. For every file you intend to mention in your final answer, you MUST first call get_file to read its actual content.
            3. NEVER assume a function or file exists. Only use filenames returned by search_code or list_files.
            4. If a file is not found (404), DO NOT mention it in your final answer unless the user specifically asked about that file.
            5. If the user asks for Python only, ignore Java/SQL results in your logic analysis but you may mention they exist if relevant.
            6. If you cannot find a Python implementation but find Java/SQL, report exactly that. DO NOT invent a Python version or guess where it might be.
            7. Your final answer must ONLY list the files you actually READ successfully and what you found in them.
            
            Target Branch: {self.branch}
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
