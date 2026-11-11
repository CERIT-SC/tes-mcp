# TES MCP

TES (Task Execution Service) as an MCP tool, enabling users to execute scripts in a managed execution environment and persist outputs to S3 storage.

- Run scripts via TES, store generated outputs in S3-compatible storage, and receive a presigned URL.
- List TES tasks associated with a specific session.
- Retrieve detailed information about individual TES tasks, including status and execution metadata.
- Wait for a TES task to reach a terminal state.
- Sleep for a specified number of seconds without blocking the server's event loop.
- Cancel running TES tasks when they are no longer needed.
- Generate presigned URLs for known files in a session.
- Create a `.tar.gz` archive of all session files through TES and generate a presigned URL.