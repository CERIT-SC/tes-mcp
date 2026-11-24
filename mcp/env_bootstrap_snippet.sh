MCP_ENV_PERSIST=@ENV_PERSIST_DIR@
MCP_ENV=@ENV_LIVE_DIR@
MCP_ENV_BUNDLE="$MCP_ENV_PERSIST/@ENV_BUNDLE_NAME@"
mkdir -p "$MCP_ENV/bin" "$MCP_ENV/py" "$MCP_ENV/prefix" "$MCP_ENV/R" "$MCP_ENV_PERSIST" 2>/dev/null || true
MCP_NEEDS_MIGRATION=0
[ -d "$MCP_ENV_PERSIST/py" ] && MCP_NEEDS_MIGRATION=1
[ -d "$MCP_ENV_PERSIST/venv" ] && MCP_NEEDS_MIGRATION=1
if [ ! -f "$MCP_ENV_BUNDLE" ] && [ "$MCP_NEEDS_MIGRATION" = 1 ]; then
    for d in "$MCP_ENV_PERSIST/bin" "$MCP_ENV_PERSIST/py/bin" "$MCP_ENV_PERSIST/venv/bin" "$MCP_ENV_PERSIST/prefix/bin" "$MCP_ENV_PERSIST/prefix/usr/bin" "$MCP_ENV_PERSIST/prefix/usr/local/bin"; do
        if [ -d "$d" ]; then
            find "$d" -maxdepth 1 -type f -exec chmod u+x {} + 2>/dev/null || true
        fi
    done
    tar -C "$MCP_ENV_PERSIST" --ignore-failed-read -cf "$MCP_ENV_BUNDLE.new" py venv prefix R bin home 2>/dev/null &&
        gzip -1 -c "$MCP_ENV_BUNDLE.new" > "$MCP_ENV_BUNDLE.new.gz" 2>/dev/null &&
        mv -f "$MCP_ENV_BUNDLE.new.gz" "$MCP_ENV_BUNDLE"
    rm -f "$MCP_ENV_BUNDLE.new" "$MCP_ENV_BUNDLE.new.gz"
    if [ -f "$MCP_ENV_BUNDLE" ]; then
        rm -rf "$MCP_ENV_PERSIST/py" "$MCP_ENV_PERSIST/venv" "$MCP_ENV_PERSIST/prefix" "$MCP_ENV_PERSIST/R" "$MCP_ENV_PERSIST/bin" "$MCP_ENV_PERSIST/home"
    fi
fi
if [ -f "$MCP_ENV_BUNDLE" ]; then
    tar -xzf "$MCP_ENV_BUNDLE" -C "$MCP_ENV" 2>/dev/null || true
fi
mkdir -p "$MCP_ENV/home" 2>/dev/null || true
export HOME="$MCP_ENV/home"
export R_LIBS_USER="$MCP_ENV/R"
export PYTHONPATH="$MCP_ENV/py${PYTHONPATH:+:$PYTHONPATH}"
export PATH="$MCP_ENV/bin:$MCP_ENV/py/bin:$MCP_ENV/prefix/usr/bin:$MCP_ENV/prefix/bin${PATH:+:$PATH}"
export LD_LIBRARY_PATH="$MCP_ENV/prefix/usr/lib/x86_64-linux-gnu:$MCP_ENV/prefix/usr/lib:$MCP_ENV/prefix/lib/x86_64-linux-gnu:$MCP_ENV/prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
cat > "$MCP_ENV/bin/pip" <<'MCP_SHIM_PIP'
#!/bin/sh
MCP_ENV=${MCP_ENV:-@ENV_LIVE_DIR@}
if [ "$1" = "install" ]; then
    shift
    exec python3 -m pip --no-cache-dir install --target "$MCP_ENV/py" --upgrade "$@"
fi
exec python3 -m pip --no-cache-dir "$@"
MCP_SHIM_PIP
cat > "$MCP_ENV/bin/pip3" <<'MCP_SHIM_PIP3'
#!/bin/sh
exec "${MCP_ENV:-@ENV_LIVE_DIR@}/bin/pip" "$@"
MCP_SHIM_PIP3
chmod +x "$MCP_ENV/bin/pip" "$MCP_ENV/bin/pip3" 2>/dev/null || true
touch "$MCP_ENV/.stamp"
MCP_STATUS=0
(
