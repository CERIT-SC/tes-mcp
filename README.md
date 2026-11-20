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
interpreter) is lost between tasks. The session directory is also staged
object-by-object, so thousands of small files (e.g. a pip-installed numpy
stack) can make staging minutes slow. To fix both, every submitted script is
wrapped by a bootstrap that keeps the per-session environment in a single
tarball, `/data/mcp-env/env.tar.gz`: it is unpacked to `/tmp/mcp-env` at task
start and repacked only when the task changed it.

- `pip install` / `pip3 install` (shims) install into a persistent
  `PYTHONPATH` directory inside the bundle — importable in all later tasks
  of the session.
- `prefix/` inside the bundle holds extracted binaries/libraries
  (e.g. `mkdir -p /tmp/apt-lists/partial /tmp/apt-cache/archives/partial &&
  apt-get -o Dir::State::Lists=/tmp/apt-lists -o Dir::Cache=/tmp/apt-cache download pkg
  && dpkg -x pkg.deb /tmp/mcp-env/prefix` — the `-o` flags and `partial`
  directories are needed because tasks run unprivileged),
  on `PATH` and `LD_LIBRARY_PATH`.
- `R/` inside the bundle is `R_LIBS_USER` (persistent R library).
- `bin/` inside the bundle holds the pip/pip3 shims and session executables:
  copy scripts or static binaries there (`cp mytool /tmp/mcp-env/bin/`) and
  they are on `PATH` in later tasks.

Sessions created before the bundle existed are migrated on their first task
(loose `py/`/`venv/` trees are folded into the bundle and deleted). Because
S3 object storage does not keep POSIX modes, loose files saved directly in
the session directory get their exec bits repaired at task start. Files
written by scripts must still be under `/data` to survive; TES only syncs
that directory, and the session archive (`get_session_files_presigned_url`)
excludes `mcp-env` to stay small.