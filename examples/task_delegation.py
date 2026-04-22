"""Task mode example: planner delegates work to a worker agent.

Demonstrates: request, accept_task, update, complete, commit.
Requires a running MACP runtime on localhost:50051.
"""

from macp_sdk import AuthConfig, MacpClient
from macp_sdk.task import TaskSession

# --- Create client ---
client = MacpClient(
    target="127.0.0.1:50051",
    allow_insecure=True,  # local dev only; production requires TLS (RFC-0006 §3)
    auth=AuthConfig.for_dev_agent("planner"),
)

# --- Start task session ---
session = TaskSession(client, auth=AuthConfig.for_dev_agent("planner"))
session.start(
    intent="analyze Q4 sales data",
    participants=["planner", "worker"],
    ttl_ms=120_000,
)

# --- Planner creates task request ---
session.request_task(
    "t1",
    "Q4 Sales Analysis",
    instructions="Run the sales pipeline and produce a summary report",
    requested_assignee="worker",
)

# --- Worker accepts ---
session.accept_task("t1", sender="worker")

# --- Worker reports progress ---
session.update_task("t1", status="running", progress=0.5, message="50% complete", sender="worker")

# --- Worker completes ---
session.complete_task(
    "t1", output=b"Q4 revenue: $2.3M", summary="Analysis complete", sender="worker"
)

# --- Planner commits the outcome ---
proj = session.task_projection
if proj.is_completed():
    session.commit(
        action="task.completed",
        authority_scope="data-analysis",
        reason="Worker delivered output successfully",
    )
    print("Task completed and committed")

client.close()
