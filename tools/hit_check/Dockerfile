# Throw-away sshd for sandbox_test.sh: Ubuntu 24.04 (OpenSSH 9.6, the version of
# the game host), the accounts and log folders of the host, and the feed script.
# Nothing here is used outside the sandbox test.
FROM ubuntu:24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-server python3 xauth \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sshd \
    && ssh-keygen -A

# Accounts: root, admin and squad exist on the host; ctrl is the unrestricted
# control account that shows each test is able to succeed; hitfeed is the new
# account with the shell /bin/sh (nologin would break the forced command).
RUN useradd -m -s /bin/bash admin \
    && useradd -m -s /bin/sh squad \
    && useradd -m -s /bin/bash ctrl \
    && useradd -m -s /bin/sh hitfeed \
    && for user in admin squad ctrl hitfeed; do usermod -p '*' "$user"; done \
    && mkdir -p /home/squad/squad1/SquadGame/Saved/Logs /home/squad/squad2/SquadGame/Saved/Logs \
    && chown -R squad:squad /home/squad \
    && chmod 755 /home/squad \
    && mkdir -p /home/hitfeed/.ssh /opt/hitfeed

# The base server config of the host, as far as it matters: key login only and
# a list of allowed users. The drop-in under test is added by sandbox_test.sh.
RUN printf '%s\n' \
    'Include /etc/ssh/sshd_config.d/*.conf' \
    'PermitRootLogin prohibit-password' \
    'PasswordAuthentication no' \
    'KbdInteractiveAuthentication no' \
    'UsePAM no' \
    'X11Forwarding yes' \
    'AllowUsers root admin squad ctrl' \
    'Subsystem sftp /usr/lib/openssh/sftp-server' \
    'LogLevel VERBOSE' \
    > /etc/ssh/sshd_config

COPY hits_feed.py /opt/hitfeed/hits_feed.py
RUN chown root:root /opt/hitfeed/hits_feed.py && chmod 755 /opt/hitfeed/hits_feed.py

EXPOSE 22
CMD ["/usr/sbin/sshd", "-D", "-e"]
