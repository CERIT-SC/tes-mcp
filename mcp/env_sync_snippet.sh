)
MCP_STATUS=$?
MCP_NEEDS_SYNC=0
if [ -n "$(find "$MCP_ENV" -newer "$MCP_ENV/.stamp" -print -quit 2>/dev/null)" ]; then
    MCP_NEEDS_SYNC=1
fi
if [ "$MCP_NEEDS_SYNC" = "1" ]; then
    if tar -C "$MCP_ENV" --exclude='./.stamp' --ignore-failed-read -cf "$MCP_ENV_BUNDLE.new" . &&
        gzip -1 -c "$MCP_ENV_BUNDLE.new" > "$MCP_ENV_BUNDLE.new.gz" &&
        mv -f "$MCP_ENV_BUNDLE.new.gz" "$MCP_ENV_BUNDLE"; then
        :
    else
        echo "mcp-env: failed to persist environment changes to $MCP_ENV_BUNDLE" >&2
        if [ "$MCP_STATUS" -eq 0 ]; then
            MCP_STATUS=125
        fi
    fi
    rm -f "$MCP_ENV_BUNDLE.new" "$MCP_ENV_BUNDLE.new.gz"
fi
exit "$MCP_STATUS"
