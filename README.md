# TES MCP

TES (Task Execution Service) as an MCP tool, enabling users to execute scripts in a managed execution environment and persist outputs to S3 storage.

- `run_script` - run a script via TES and store its outputs in S3.
- `list_tasks` - list the tasks of the current MCP session.
- `get_task` / `cancel_task` - inspect or cancel a task.
- `get_service_info` - query the remote TES service.