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

## Persistent environment between tasks

Every task starts in a fresh container from `EXECUTOR_IMAGE`, so anything
installed outside `/data` (system packages, `pip install` into the system
interpreter) is lost between tasks. To make installs persist, every submitted
script is automatically prepended with a bootstrap that manages a per-session
environment in `/data/mcp-env` (inside the session's S3-backed output
directory, which TES stages before and uploads after every task):

- `py/` — a persistent `pip --target` directory on `PYTHONPATH`. The `pip` /
  `pip3` shims redirect plain `pip install` here, so packages installed in
  one task are importable in all later tasks of the session.
- `prefix/` — extracted binaries/libraries (e.g. `apt-get download pkg && dpkg -x pkg.deb /data/mcp-env/prefix`),
  put on `PATH` and `LD_LIBRARY_PATH`.
- `R/` — persistent R package library (`R_LIBS_USER`).
- `bin/` — the pip/pip3 shims, plus any session-local executables.

Because S3 object storage does not keep POSIX modes, the bootstrap re-adds
execute bits at the start of every task. Files written by scripts must be
under `/data` to survive; TES only syncs that directory. The session archive
(`get_session_files_presigned_url`) excludes `mcp-env` to stay small;
installed packages are reproducible via pip instead.