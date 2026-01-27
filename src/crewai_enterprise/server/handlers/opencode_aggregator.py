import time
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

class StatusAggregator:
    """
    Collects and throttles OpenCode SSE events into meaningful WeCom status updates.
    """
    def __init__(self, throttle_seconds: int = 10):
        self.throttle_seconds = throttle_seconds
        self.last_update_time = 0
        self.agent_milestones: Dict[str, str] = {} # Track per agent
        self.events_seen = 0
        self.start_time = time.time()
        
    def process_event(self, event: Dict[str, Any]) -> Optional[str]:
        """
        Process an SSE event. Returns a status string if an update should be sent, else None.
        """
        self.events_seen += 1
        event_type = event.get("type")
        
        # 1. Update milestones based on event type
        metadata = event.get("metadata", {})
        agent = metadata.get("agent", "OpenCode")
        
        new_val = ""
        if event_type == "thought":
            new_val = f"🤔 {agent} 正在思考执行策略..."
        elif event_type == "call":
            # e.g., calling shell or git
            new_val = f"🛠️ {agent} 正在执行操作..."
        elif event_type == "status":
            new_val = f"🔄 {agent}: {event.get('text', '处理中...')}"
        
        if not new_val:
            return None

        # 2. Update agent specific milestone
        if self.agent_milestones.get(agent) != new_val:
            self.agent_milestones[agent] = new_val
            
            # 3. Check if enough time passed
            now = time.time()
            if now - self.last_update_time >= self.throttle_seconds:
                self.last_update_time = now
                return self._format_status()
            
        return None

    def _format_status(self) -> str:
        """Format the current agent milestones into a multi-agent status line."""
        elapsed = int(time.time() - self.start_time)
        
        # Concatenate: "Agent1: thinking... | Agent2: searching..."
        active_statuses = []
        for agent in sorted(self.agent_milestones.keys()):
            status = self.agent_milestones[agent]
            # Strip emojis for compact concatenation if needed, or keep for flavor
            active_statuses.append(status)
            
        status_line = " | ".join(active_statuses)
        
        return (
            f"⏳ **实时进展 ({elapsed}s)**\n"
            f"{status_line}\n"
            f"💡 *任务仍在后台进行中，请稍候...*"
        )
