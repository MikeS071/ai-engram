# Copilot Custom Instructions

## Session Initialization

At the start of every new conversation:
1. Call `get_system_prompt` from the AIEngram MCP server to load the memory protocol
2. Call `recall_all` with a query based on the user's first message to load relevant context from memory AND blog content
3. Call `list_memories` with category "decision" to load all workflow decisions
4. Acknowledge any relevant context naturally before proceeding

## Always Follow
- All stored decisions in memory (workflow rules, preferences, rejected topics)
- The Brand Voice Profile when creating blog content
- Karpathy engineering principles when writing code
