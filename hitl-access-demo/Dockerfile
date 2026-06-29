# Tier 1 HITL bench-access demo (see ../HITL_APPROACH.md).
# An SSH server where every login in the `hil` group is forced through a wrapper
# that (a) takes a blocking flock (mutual exclusion + queue/wait) and (b) runs the
# session under a hard wall-clock cap.
FROM debian:12-slim

# openssh-server: the SSH chokepoint.  util-linux: flock(1).  coreutils: timeout(1).
# psmisc: fuser(1) for the admin "who holds the bench" / break-lock demo.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      openssh-server util-linux coreutils psmisc \
 && rm -rf /var/lib/apt/lists/*

# Bench-access group + a demo user.  Password auth (dev/dev) keeps the tutorial
# friction-free; PRODUCTION should use SSH keys and real users added to `hil`.
RUN groupadd hil \
 && useradd -m -s /bin/bash -G hil dev \
 && echo 'dev:dev' | chpasswd

# sshd drop-in: force every hil-group login through the wrapper.
COPY hil.conf /etc/ssh/sshd_config.d/hil.conf
# The wrapper itself and the container entrypoint.
COPY hil-session /usr/local/sbin/hil-session
COPY entrypoint.sh /usr/local/sbin/entrypoint.sh
RUN chmod 0755 /usr/local/sbin/hil-session /usr/local/sbin/entrypoint.sh

EXPOSE 22
ENTRYPOINT ["/usr/local/sbin/entrypoint.sh"]
