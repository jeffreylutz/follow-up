#!/usr/bin/env bash
# Container entrypoint for the HITL bench demo.
set -euo pipefail

# Persist tunables (from compose `environment:`) where the wrapper can read them,
# because sshd does not pass the daemon environment into ForceCommand sessions.
cat > /etc/hil.env <<EOF
HIL_QUEUE_TIMEOUT=${HIL_QUEUE_TIMEOUT:-120}
HIL_MAX_SESSION=${HIL_MAX_SESSION:-30}
EOF

# Runtime dirs (host /run is a tmpfs, recreated each start).
mkdir -p /run/sshd
mkdir -p /run/hil
chgrp hil /run/hil
chmod 2770 /run/hil          # setgid: files created inside inherit group `hil`

# Generate host keys on first boot.
ssh-keygen -A >/dev/null

echo "HIL bench demo ready."
echo "  Connect:        ssh dev@localhost -p 2222   (password: dev)"
echo "  Queue wait:     ${HIL_QUEUE_TIMEOUT:-120}s"
echo "  Hard session cap: ${HIL_MAX_SESSION:-30}s"

exec /usr/sbin/sshd -D -e
