# An Efficient Interactive Travel Planning Agent 
## Brief project description (1 paragraph)
This project develops an interactive travel planning agent that guides users from coarse, underspecified requests to executable and personalized travel plans through intent clarification, dynamic model routing, long-horizon memory management, and structured tool integration. Instead of immediately performing large-scale search or serial tool calls, the agent strategically interacts with users to elicit critical constraints, reduce uncertainty, and compress the effective search space before committing to expensive planning actions. This design directly addresses inefficiencies in standard ReAct-style pipelines, which often suffer from excessive token consumption, long end-to-end latency, and cumulative reasoning errors in real-world planning tasks.

## Project Details (>=1 paragraph)
The system is designed as an interactive travel planning agent that incrementally constructs executable itineraries through user-guided clarification, dynamic model routing, and structured tool integration. Given an initial user request, the agent first identifies missing or ambiguous constraints and selectively asks clarification questions before initiating any external search or tool calls.

Planning is decomposed into modular subtasks, which are handled through dynamic routing between small and large language models. Routine operations such as schedule lookup, distance estimation, and weather interpretation are delegated to smaller models for efficiency, while complex reasoning—such as constraint conflicts or cascading plan revisions—is escalated to a larger model.

The agent accesses real-world information via an MCP-based tool layer, integrating mapping and routing services, weather forecasts, transportation schedules, and user-generated local content (e.g., Xiaohongshu). These tools provide both hard constraints and soft experiential signals to support feasible and context-aware planning.

To support long-horizon planning, the agent maintains a compact memory state that summarizes completed decisions (e.g., confirmed bookings, fixed time anchors, accumulated costs), enabling consistent planning without unbounded context growth.

## Goals (bullet points)
- Design an interactive travel planning agent that prioritizes clarification over premature search 
- Reduce token usage and end-to-end latency through dynamic routing between small and large models 
- Mitigate error accumulation in long-horizon planning via state summarization and memory compression 
- Support real-world tool integration with robustness to noisy or incomplete information, by incorporating diverse MCP-based tools(e.g., Xiaohongshu, Amap). 

```bash
cd /Users/junle/Code/Github/travelAgent/backend
uv sync
uv run uvicorn app.main:app --reload

```bash
cd /Users/junle/Code/Github/travelAgent
pnpm install
pnpm dev:web

```      