#!/usr/bin/env bash
# Mock FlexLM lmstat. Prints the same lines real lmstat does so the parser works
# unchanged. Control the reported usage with env vars:
#   MOCK_LMSTAT_ISSUED  (default 1)   total seats
#   MOCK_LMSTAT_INUSE   (default 0)   seats currently in use
issued="${MOCK_LMSTAT_ISSUED:-1}"
inuse="${MOCK_LMSTAT_INUSE:-0}"
echo "Users of Vivado_System_Edition:  (Total of ${issued} license(s) issued;  Total of ${inuse} license(s) in use)"
