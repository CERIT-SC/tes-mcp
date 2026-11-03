# TES MCP

TES (Task Execution Service) as an MCP tool, enabling users to execute scripts in a managed execution environment and persist outputs to S3 storage.

- Run scripts via TES and store generated outputs in S3-compatible storage.
- List TES tasks associated with a specific session.
- Retrieve detailed information about individual TES tasks, including status and execution metadata.
- Cancel running TES tasks when they are no longer needed.

## Output URLs

`run_script` automatically stores the script's standard output and error as
`output.txt` under the configured S3 prefix and session ID. Its response
includes `output_url`, a temporary presigned GET URL for that file. The URL is
valid for the configured `PRESIGNED_URL_EXPIRATION` period.

The `get_presigned_url` tool remains available when a script creates another
known object and the user needs a URL for that specific file.