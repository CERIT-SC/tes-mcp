# TES MCP

TES (Task Execution Service) as an MCP tool, enabling users to execute scripts in a managed execution environment and persist outputs to S3 storage.

- Run scripts via TES, store generated outputs in S3-compatible storage, and receive a presigned URL.
- List TES tasks associated with a specific session.
- Retrieve detailed information about individual TES tasks, including status and execution metadata.
- Wait for a TES task to reach a terminal state.
- Sleep for up to 300 seconds without blocking the server's event loop.
- Cancel running TES tasks when they are no longer needed.
- Generate presigned URLs for known files in a session.
- Create a `.tar.gz` archive of all session files through TES and generate a presigned URL.

## Persistent environment between tasks

Every task starts in a fresh container; only the session directory
(`OUTPUT_PATH`, `/data` by default) carries over, synced file by file. To
keep installs persistent without slowing staging, every submitted script is
wrapped so the session environment lives in a single tarball,
`$OUTPUT_PATH/mcp-env/env.tar.gz`: unpacked to `/tmp/mcp-env` at task start,
repacked after the task only if it changed.

- `pip install` / `pip3 install` work through shims that install into a
  persistent `PYTHONPATH` directory inside the bundle.
- `bin/` — put scripts or static binaries there (`cp mytool /tmp/mcp-env/bin/`);
  on `PATH` in later tasks.
- `prefix/` — extracted `.deb`s / libraries (`apt-get download pkg && dpkg -x
  pkg.deb /tmp/mcp-env/prefix`), on `PATH` and `LD_LIBRARY_PATH`.
- `R/` — persistent R library (`R_LIBS_USER`).

Files written by scripts must be under `$OUTPUT_PATH` to survive. The session
archive (`get_session_files_presigned_url`) excludes `mcp-env` to stay small.
