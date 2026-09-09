#!/usr/bin/env bash
# Haifa AI Utility MCP Server Pre-flight & Life-cycle Manager
set -euo pipefail

RUN_USER="${1:-$USER}"
MCP_PORT="${2:-20002}"
MCP_REPO_URL="${3:-git@github.com:AarenWang/haifa-ai-deerflow.git}"
MCP_COMMIT="${4:-}"

WORKSPACE_DIR="/home/$RUN_USER/workspace"
DEERFLOW_DIR="$WORKSPACE_DIR/haifa-ai-deerflow"
MCP_DIR="$DEERFLOW_DIR/utility-mcp-server"

# 1. Quick probe: if already healthy on MCP_PORT, exit immediately
if curl --silent --fail --connect-timeout 2 "http://127.0.0.1:$MCP_PORT/actuator/health" >/dev/null 2>&1; then
  echo "[ensure-mcp] Utility MCP Server is already UP on port $MCP_PORT"
  exit 0
fi

echo "[ensure-mcp] Utility MCP Server is not running on port $MCP_PORT. Ensuring deployment..."

# 2. Ensure repository is cloned and optionally pinned
mkdir -p "$WORKSPACE_DIR"
if [[ ! -d "$DEERFLOW_DIR/.git" ]]; then
  echo "[ensure-mcp] Cloning $MCP_REPO_URL into $DEERFLOW_DIR..."
  git clone "$MCP_REPO_URL" "$DEERFLOW_DIR"
else
  echo "[ensure-mcp] Repository $DEERFLOW_DIR already exists."
fi

if [[ -n "$MCP_COMMIT" ]]; then
  echo "[ensure-mcp] Checking out pinned commit $MCP_COMMIT..."
  git -C "$DEERFLOW_DIR" checkout "$MCP_COMMIT"
fi

# 3. Ensure Maven settings has org.springframework.boot pluginGroup
USER_M2_DIR="/home/$RUN_USER/.m2"
mkdir -p "$USER_M2_DIR"
if [[ ! -f "$USER_M2_DIR/settings.xml" ]] || ! grep -q "org.springframework.boot" "$USER_M2_DIR/settings.xml"; then
  cat <<'EOF' > "$USER_M2_DIR/settings.xml"
<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.0.0 https://maven.apache.org/xsd/settings-1.0.0.xsd">
    <pluginGroups>
        <pluginGroup>org.springframework.boot</pluginGroup>
    </pluginGroups>
</settings>
EOF
  chown -R "$RUN_USER:$RUN_USER" "$USER_M2_DIR"
fi

# 4. Ensure mvn binary is globally linked if in .m2/wrapper
if ! command -v mvn >/dev/null 2>&1; then
  WRAPPER_MVN="$(find "/home/$RUN_USER/.m2/wrapper/dists" -name mvn 2>/dev/null | head -n 1 || true)"
  if [[ -n "$WRAPPER_MVN" && -x "$WRAPPER_MVN" ]]; then
    sudo ln -sf "$WRAPPER_MVN" /usr/local/bin/mvn
  fi
fi

# 5. Pre-compile / ensure dependencies are resolved
if [[ ! -f "$MCP_DIR/target/classes/org/wrj/haifa/ai/utilitymcp/UtilityMcpServerApplication.class" ]]; then
  echo "[ensure-mcp] Pre-compiling utility-mcp-server..."
  mvn -f "$DEERFLOW_DIR/pom.xml" -pl utility-mcp-server -am compile -DskipTests
fi

# 6. Ensure systemd service unit exists bound strictly to localhost (127.0.0.1)
SERVICE_FILE="/etc/systemd/system/haifa-utility-mcp.service"
eval_java="$(readlink -f "$(command -v java)")"
eval_java_home="$(dirname "$(dirname "$eval_java")")"

cat <<EOF | sudo tee "$SERVICE_FILE" >/dev/null
[Unit]
Description=Haifa AI Utility MCP Server (Localhost Only)
After=network.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$MCP_DIR
Environment="SERVER_ADDRESS=127.0.0.1"
Environment="UTILITY_MCP_PORT=$MCP_PORT"
Environment="JAVA_HOME=$eval_java_home"
Environment="PATH=/usr/local/bin:/usr/bin:/bin:$eval_java_home/bin"
ExecStart=/usr/local/bin/mvn spring-boot:run -Dspring-boot.run.jvmArguments="-Dserver.address=127.0.0.1 -Dserver.port=$MCP_PORT"
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable haifa-utility-mcp
sudo systemctl restart haifa-utility-mcp

# 7. Wait for health check UP
echo "[ensure-mcp] Waiting for Utility MCP Server to be healthy on port $MCP_PORT..."
for i in $(seq 1 30); do
  if curl --silent --fail --connect-timeout 2 "http://127.0.0.1:$MCP_PORT/actuator/health" | grep -q '"status":"UP"'; then
    echo "[ensure-mcp] SUCCESS: Utility MCP Server is UP on port $MCP_PORT (checked in ${i}s)"
    exit 0
  fi
  sleep 1
done

echo "[ensure-mcp] ERROR: Timed out waiting for Utility MCP Server on port $MCP_PORT"
sudo systemctl status haifa-utility-mcp --no-pager || true
sudo journalctl -u haifa-utility-mcp -n 30 --no-pager || true
exit 1
