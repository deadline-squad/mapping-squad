#!/usr/bin/env bash
# Restriction test for the hit-feed SSH key: builds a local docker sshd (never a
# real host), installs the key line and the server drop-in from
# deadline-squad/squad-ballistics#6 ("Research 5 of 6") and attempts a matrix of
# things a stolen key must not be able to do. Prints one PASS or FAIL line per
# attempt and exits 1 if any FAIL. Lines starting with "control:" show that the
# same attempt succeeds for an unrestricted account, so a refusal is meaningful.
# Removes the container, the image and the temporary keys on exit.
#
# Usage: ./sandbox_test.sh        (needs docker, ssh, scp, sftp, ssh-keygen, ssh-agent, python3)
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tag="hitfeed-sandbox-$$"
image="$tag:test"
work="$(mktemp -d)"
failures=0
agent_pid=""

OWNER_ID=76561190000000001
OTHER_ID=76561190000000002
OWNER_EOS=a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1
OTHER_EOS=b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2
LOG2=/home/squad/squad2/SquadGame/Saved/Logs/SquadGame.log
LOG1=/home/squad/squad1/SquadGame/Saved/Logs/SquadGame.log

cleanup() {
    [ -n "$agent_pid" ] && kill "$agent_pid" 2>/dev/null
    jobs -p | xargs -r kill 2>/dev/null
    docker rm -f "$tag" >/dev/null 2>&1
    docker rmi -f "$image" >/dev/null 2>&1
    rm -rf "$work"
}
trap cleanup EXIT

pass() { echo "PASS $1"; }
fail() { echo "FAIL $1 -- $2"; failures=$((failures + 1)); }
denied() { [ "$1" != 0 ] && echo "$2" | grep -qi 'permission denied'; }

# ---------------------------------------------------------------- build and start
docker build -q -t "$image" -f "$here/Dockerfile" "$here" >/dev/null || { echo "FAIL build the image"; exit 1; }
docker run -d --name "$tag" -p 127.0.0.1::22 "$image" >/dev/null || { echo "FAIL start the container"; exit 1; }
port="$(docker port "$tag" 22/tcp | head -n1 | sed 's/.*://')"

for name in owner other expired probe_restrict probe_bare ctrl; do
    ssh-keygen -q -t ed25519 -N '' -C "$name" -f "$work/$name"
done
pub() { cut -d' ' -f1,2 "$work/$1.pub"; }

# ---------------------------------------------------------------- server side setup
feed_command="/usr/bin/python3 -I /opt/hitfeed/hits_feed.py --log $LOG2 --allow-under /home/squad/squad2 --steam-id $OWNER_ID"
{
    echo "restrict,expiry-time=\"20271231\",command=\"$feed_command\" $(pub owner) owner"
    echo "restrict,expiry-time=\"20200101\",command=\"$feed_command\" $(pub expired) expired"
    # Sandbox-only probes: print the environment instead of running the feed,
    # with and without `restrict`, to see what the server options alone allow.
    echo "restrict,command=\"/usr/bin/env\" $(pub probe_restrict) probe_restrict"
    echo "command=\"/usr/bin/env\" $(pub probe_bare) probe_bare"
} > "$work/hitfeed_keys"

{
    echo "$(pub ctrl) ctrl"
    echo "$(pub other) other"
    echo "command=\"/usr/bin/env\" $(pub probe_bare) probe_bare"
} > "$work/ctrl_keys"

cat > "$work/hitfeed.conf" <<'CONF'
AllowUsers hitfeed
Match User hitfeed
    AuthenticationMethods publickey
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    DisableForwarding yes
    AllowTcpForwarding no
    AllowAgentForwarding no
    X11Forwarding no
    PermitTunnel no
    PermitTTY no
    PermitUserRC no
    PermitOpen none
    PermitListen none
    GatewayPorts no
    MaxSessions 1
    ClientAliveInterval 15
    ClientAliveCountMax 3
CONF

docker cp "$work/hitfeed_keys" "$tag:/home/hitfeed/.ssh/authorized_keys"
docker cp "$work/hitfeed.conf" "$tag:/etc/ssh/sshd_config.d/hitfeed.conf"
docker cp "$work/ctrl_keys" "$tag:/tmp/ctrl_keys"
docker cp "$work/ctrl.pub" "$tag:/tmp/ctrl.pub"
docker exec "$tag" sh -c '
    chown root:root /home/hitfeed/.ssh /home/hitfeed/.ssh/authorized_keys /etc/ssh/sshd_config.d/hitfeed.conf
    chmod 755 /home/hitfeed/.ssh && chmod 644 /home/hitfeed/.ssh/authorized_keys /etc/ssh/sshd_config.d/hitfeed.conf
    for user in ctrl admin squad; do
        mkdir -p /home/$user/.ssh
        cp /tmp/ctrl_keys /home/$user/.ssh/authorized_keys
        chown -R $user:$user /home/$user/.ssh && chmod 700 /home/$user/.ssh && chmod 600 /home/$user/.ssh/authorized_keys
    done
    mkdir -p /root/.ssh && cp /tmp/ctrl.pub /root/.ssh/authorized_keys && chmod 700 /root/.ssh
    /usr/sbin/sshd -t' || { echo "FAIL the server rejects its own configuration"; exit 1; }
docker exec "$tag" sh -c 'kill -HUP 1'

# Fake logs: squad2 (the feed's) and squad1 (must never be readable through it).
stamp_seed=2026.10.29-17.02.24:014
take_line() {
    printf '[%s][205]LogSquadTrace: [DedicatedServer]TakeDamage(): BP_FOBRadio_Woodland_C_2147396823: 7.40 damage taken by causer BP_40MM_VOG_Proj2_C_2147387038 instigator %s (Online IDs: EOS: %s steam: %s) health remaining 252.60\r\n' "$1" "$2" "$3" "$4"
}
marker_line() {
    printf '[%s][205]LogSquad: Player %s (Team: 1; ID: EOS: %s steam: %s) placed a new map marker for team 1 : Type: BP_MapMarker_POI ; Location: 85946.00000, -57540.00000, 4675.00000\r\n' "$1" "$2" "$3" "$4"
}
{
    take_line "$stamp_seed" FakeAlpha "$OWNER_EOS" "$OWNER_ID"
    take_line "$stamp_seed" FakeBravo "$OTHER_EOS" "$OTHER_ID"
} | docker exec -i "$tag" sh -c "cat > $LOG2; chown squad:squad $LOG2; chmod 644 $LOG2"
printf 'SQUAD1-SECRET-LINE FakeCharlie\r\n' | docker exec -i "$tag" sh -c "cat > $LOG1; chown squad:squad $LOG1; chmod 644 $LOG1"

for _ in $(seq 1 50); do
    ssh-keyscan -p "$port" 127.0.0.1 >/dev/null 2>&1 && break
    sleep 0.2
done

# ---------------------------------------------------------------- client helpers
BASE_OPTIONS=(-F /dev/null -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=no
              -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=5 -o IdentityAgent=none)
SSH=(ssh "${BASE_OPTIONS[@]}" -p "$port")
SCP=(scp "${BASE_OPTIONS[@]}" -P "$port")
SFTP=(sftp "${BASE_OPTIONS[@]}" -P "$port")
as() { # as <user> <key> [remote command...]
    local user="$1" key="$2"; shift 2
    if [ $# -eq 0 ]; then "${SSH[@]}" -i "$work/$key" "$user@127.0.0.1"; else "${SSH[@]}" -i "$work/$key" "$user@127.0.0.1" -- "$@"; fi
}
container_has() { docker exec "$tag" sh -c "$1" >/dev/null 2>&1; }
banner_from() { # first bytes a TCP client gets from a local port ("" if nothing)
    python3 - "$1" <<'PY'
import socket, sys
try:
    with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=2) as s:
        s.settimeout(2)
        print(s.recv(8).decode("ascii", "replace"))
except OSError:
    print("")
PY
}
socks_banner_from() { # SOCKS5 CONNECT to 127.0.0.1:22 through a local port, then the first bytes
    python3 - "$1" <<'PY'
import socket, struct, sys
try:
    with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=2) as s:
        s.settimeout(2)
        s.sendall(b"\x05\x01\x00")
        if s.recv(2) != b"\x05\x00":
            print(""); sys.exit()
        s.sendall(b"\x05\x01\x00\x01" + socket.inet_aton("127.0.0.1") + struct.pack(">H", 22))
        reply = s.recv(10)
        if len(reply) < 2 or reply[1] != 0:
            print(""); sys.exit()
        print(s.recv(8).decode("ascii", "replace"))
except OSError:
    print("")
PY
}
free_port() { python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])'; }

# ---------------------------------------------------------------- 1. the feed itself works
feed_out="$work/feed.out"
"${SSH[@]}" -i "$work/owner" hitfeed@127.0.0.1 > "$feed_out" 2> "$work/feed.err" &
feed_pid=$!
for _ in $(seq 1 30); do grep -q '"type":"hello"' "$feed_out" 2>/dev/null && break; sleep 0.2; done
now_stamp="$(date -u +%Y.%m.%d-%H.%M.%S):500"
{
    take_line "$now_stamp" FakeBravo "$OTHER_EOS" "$OTHER_ID"
    take_line "$now_stamp" FakeAlpha "$OWNER_EOS" "$OWNER_ID"
    marker_line "$now_stamp" FakeBravo "$OTHER_EOS" "$OTHER_ID"
    marker_line "$now_stamp" FakeAlpha "$OWNER_EOS" "$OWNER_ID"
} | docker exec -i "$tag" sh -c "cat >> $LOG2"
for _ in $(seq 1 30); do grep -q '"type":"marker"' "$feed_out" 2>/dev/null && break; sleep 0.2; done
if grep -q '"type":"hello"' "$feed_out"; then pass "owner key: the feed starts and says hello"; else fail "owner key: the feed starts and says hello" "no hello: $(head -c 200 "$work/feed.err")"; fi
hits="$(grep -c '"type":"hit"' "$feed_out")"; markers="$(grep -c '"type":"marker"' "$feed_out")"
if [ "$hits" = 1 ] && [ "$markers" = 1 ]; then
    pass "owner key: only the owner's new hit and marker arrive; the other player's are dropped"
else
    fail "owner key: only the owner's new hit and marker arrive" "hits=$hits markers=$markers"
fi
if grep -Eq "Fake|$OWNER_ID|$OTHER_ID|$OWNER_EOS|$OTHER_EOS" "$feed_out"; then fail "owner key: no name or ID in the output" "found one"; else pass "owner key: no name or ID in the output"; fi

kill -9 "$feed_pid" 2>/dev/null; wait "$feed_pid" 2>/dev/null
gone=no
for _ in $(seq 1 40); do
    container_has 'pgrep -f "[h]its_feed.py"' || { gone=yes; break; }
    sleep 0.2
done
if [ "$gone" = yes ]; then pass "kill -9 of the client: the feed process on the server ends within 8 s"; else fail "kill -9 of the client: the feed process on the server ends within 8 s" "still running"; fi

since_out="$(timeout 8 "${SSH[@]}" -i "$work/owner" "hitfeed@127.0.0.1" "since=$stamp_seed" 2>&1 | head -n 2)"
if echo "$since_out" | grep -q '"type":"hello"' && echo "$since_out" | grep -q '"type":"hit"'; then
    pass "owner key: since=<stamp> replays from that line"
else
    fail "owner key: since=<stamp> replays from that line" "$since_out"
fi

# ---------------------------------------------------------------- 2. a shell and other commands
refused() { # refused <name> <output> <exit code> <regex that must not appear in the output>
    if [ "$3" = 2 ] && ! echo "$2" | grep -Eq "$4"; then pass "$1"; else fail "$1" "rc=$3 out=$(echo "$2" | head -c 120)"; fi
}
for command in 'id' '/bin/sh -c id' 'cat /etc/passwd' "tail -n 5 $LOG1" "cat $LOG1" 'bash' 'python3 -c "print(1)"' 'ls /' 'echo hello'; do
    out="$(as hitfeed owner "$command" 2>&1)"; rc=$?
    refused "other command refused: $command" "$out" "$rc" 'uid=|root:|SQUAD1-SECRET|FakeCharlie|^hello$|^1$|^bin$'
done
out="$(timeout 3 "${SSH[@]}" -i "$work/owner" hitfeed@127.0.0.1 </dev/null 2>&1 | head -c 300 | tr '\n' ' ')"
if echo "$out" | grep -q '"type":"hello"' && ! echo "$out" | grep -q 'uid='; then pass "no command: the feed runs, not a shell"; else fail "no command: the feed runs, not a shell" "$out"; fi

# ---------------------------------------------------------------- 3. bad arguments
long_arg="since=$(head -c 5000 /dev/zero | tr '\0' 'a')"
newline_arg=$'since=2026.10.29-17.02.24:014\nid'
for request in '--log /etc/passwd' "--log $LOG1" "--allow-under / --log /etc/passwd" 'since=../../etc/passwd' 'since=..;id' 'since=$(id)' \
               'since=x;touch /tmp/pwned_by_args' "$newline_arg" "$long_arg"; do
    label="$(printf '%s' "$request" | head -c 40 | tr '\n' '|')"
    out="$(as hitfeed owner "$request" 2>&1)"; rc=$?
    refused "bad argument refused: $label" "$out" "$rc" 'uid=|root:|SQUAD1-SECRET'
done
if container_has 'test -e /tmp/pwned_by_args'; then fail "bad arguments did not run a command" "/tmp/pwned_by_args exists"; else pass "bad arguments did not run a command"; fi

# ---------------------------------------------------------------- 4. scp and sftp
printf 'payload\n' > "$work/payload.txt"
for mode in "-O" "-s"; do
    label="scp $mode"
    rm -f "$work/downloaded.log"
    "${SCP[@]}" -i "$work/owner" $mode "$work/payload.txt" hitfeed@127.0.0.1:/tmp/uploaded.txt >/dev/null 2>&1; rc=$?
    if [ "$rc" != 0 ] && ! container_has 'test -e /tmp/uploaded.txt'; then pass "$label upload refused"; else fail "$label upload refused" "rc=$rc"; fi
    "${SCP[@]}" -i "$work/owner" $mode "hitfeed@127.0.0.1:$LOG2" "$work/downloaded.log" >/dev/null 2>&1
    if [ ! -s "$work/downloaded.log" ]; then pass "$label download of the log refused"; else fail "$label download of the log refused" "got data"; fi
done
if "${SCP[@]}" -i "$work/ctrl" -O "$work/payload.txt" ctrl@127.0.0.1:/tmp/control_upload.txt >/dev/null 2>&1; then
    pass "control: scp works for the unrestricted account"
else
    fail "control: scp works for the unrestricted account" "scp failed"
fi
sftp_out="$(printf 'ls /\n' | "${SFTP[@]}" -i "$work/owner" -b - hitfeed@127.0.0.1 2>&1)"
if echo "$sftp_out" | grep -Eq 'home|etc|bin'; then fail "sftp refused" "a listing came back"; else pass "sftp refused"; fi
sftp_ctrl="$(printf 'ls /\n' | "${SFTP[@]}" -i "$work/ctrl" -b - ctrl@127.0.0.1 2>&1)"
if echo "$sftp_ctrl" | grep -Eq 'home|etc|bin'; then pass "control: sftp works for the unrestricted account"; else fail "control: sftp works for the unrestricted account" "$(echo "$sftp_ctrl" | head -c 100)"; fi

# ---------------------------------------------------------------- 5. port forwarding
forwarded_banner() { # forwarded_banner <local|dynamic> <user> <key>: what a client reads through the tunnel
    local kind="$1" user="$2" key="$3" lport pid
    lport="$(free_port)"
    if [ "$kind" = local ]; then
        "${SSH[@]}" -i "$work/$key" -N -o ExitOnForwardFailure=yes -L "$lport:127.0.0.1:22" "$user@127.0.0.1" >/dev/null 2>&1 &
    else
        "${SSH[@]}" -i "$work/$key" -N -o ExitOnForwardFailure=yes -D "$lport" "$user@127.0.0.1" >/dev/null 2>&1 &
    fi
    pid=$!
    for _ in $(seq 1 25); do (echo > "/dev/tcp/127.0.0.1/$lport") 2>/dev/null && break; sleep 0.2; done
    if [ "$kind" = local ]; then banner_from "$lport"; else socks_banner_from "$lport"; fi
    kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
}
for kind in local dynamic; do
    banner="$(forwarded_banner "$kind" hitfeed owner)"
    case "$banner" in SSH-2.0*) fail "$kind port forwarding refused" "reached sshd through the tunnel";; *) pass "$kind port forwarding refused";; esac
    banner="$(forwarded_banner "$kind" ctrl ctrl)"
    case "$banner" in SSH-2.0*) pass "control: $kind forwarding works for the unrestricted account";; *) fail "control: $kind forwarding works for the unrestricted account" "banner='$banner'";; esac
done
timeout 6 "${SSH[@]}" -i "$work/owner" -N -R 0:127.0.0.1:22 -o ExitOnForwardFailure=yes hitfeed@127.0.0.1 >/dev/null 2>&1; rc=$?
if [ "$rc" = 255 ]; then pass "remote forwarding (-R) refused"; else fail "remote forwarding (-R) refused" "rc=$rc"; fi
timeout 6 "${SSH[@]}" -i "$work/ctrl" -N -R 0:127.0.0.1:22 -o ExitOnForwardFailure=yes ctrl@127.0.0.1 >/dev/null 2>&1; rc=$?
if [ "$rc" = 124 ]; then pass "control: remote forwarding works for the unrestricted account"; else fail "control: remote forwarding works for the unrestricted account" "rc=$rc"; fi
stdio="$(timeout 6 "${SSH[@]}" -i "$work/owner" -W 127.0.0.1:22 hitfeed@127.0.0.1 < <(sleep 3) 2>/dev/null | head -c 8)"
case "$stdio" in SSH-2.0*) fail "stdio forwarding (-W) refused" "reached sshd";; *) pass "stdio forwarding (-W) refused";; esac
stdio="$(timeout 6 "${SSH[@]}" -i "$work/ctrl" -W 127.0.0.1:22 ctrl@127.0.0.1 < <(sleep 3) 2>/dev/null | head -c 8)"
case "$stdio" in SSH-2.0*) pass "control: stdio forwarding works for the unrestricted account";; *) fail "control: stdio forwarding works for the unrestricted account" "got '$stdio'";; esac

# ---------------------------------------------------------------- 6. a TTY
tty_err="$(timeout 4 "${SSH[@]}" -tt -i "$work/owner" hitfeed@127.0.0.1 2>&1 >/dev/null </dev/null | head -c 300)"
if echo "$tty_err" | grep -qi 'PTY allocation request failed'; then pass "forced TTY (-tt) refused"; else fail "forced TTY (-tt) refused" "$tty_err"; fi
tty_err="$(timeout 4 "${SSH[@]}" -o RequestTTY=force -i "$work/owner" hitfeed@127.0.0.1 2>&1 >/dev/null </dev/null | head -c 300)"
if echo "$tty_err" | grep -qi 'PTY allocation request failed'; then pass "forced TTY (RequestTTY=force) refused"; else fail "forced TTY (RequestTTY=force) refused" "$tty_err"; fi
tty_ctrl="$(timeout 4 "${SSH[@]}" -tt -i "$work/ctrl" ctrl@127.0.0.1 true 2>&1 </dev/null | head -c 300)"
if echo "$tty_ctrl" | grep -qi 'PTY allocation request failed'; then fail "control: a TTY is granted to the unrestricted account" "$tty_ctrl"; else pass "control: a TTY is granted to the unrestricted account"; fi

# ---------------------------------------------------------------- 7. agent, X11, environment
eval "$(ssh-agent -s)" >/dev/null
agent_pid="$SSH_AGENT_PID"
ssh-add -q "$work/owner" 2>/dev/null
env_run() { # env_run <user> <key>: the remote `env` of a probe key, asking for everything
    local user="$1" key="$2"
    DISPLAY=:77 ssh -F /dev/null -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=5 -p "$port" -i "$work/$key" \
        -A -X -Y -o SetEnv=LD_PRELOAD=/tmp/evil.so "$user@127.0.0.1" 2>&1 </dev/null
}
for probe in probe_restrict probe_bare; do
    out="$(env_run hitfeed "$probe")"
    if echo "$out" | grep -q '^PATH=' && ! echo "$out" | grep -Eq '^(SSH_AUTH_SOCK|DISPLAY|LD_PRELOAD|SSH_ORIGINAL_COMMAND)='; then
        pass "agent/X11/env ($probe key, -A -X -Y, LD_PRELOAD sent): the command sees no SSH_AUTH_SOCK, DISPLAY or LD_PRELOAD"
    else
        fail "agent/X11/env ($probe key)" "$(echo "$out" | tr '\n' ' ' | head -c 1200)"
    fi
done
out="$(env_run ctrl probe_bare)"
if echo "$out" | grep -q '^SSH_AUTH_SOCK=' && echo "$out" | grep -q '^DISPLAY='; then
    pass "control: the same request gives the unrestricted account an agent socket and a DISPLAY"
else
    fail "control: the same request gives the unrestricted account an agent socket and a DISPLAY" "$(echo "$out" | tr '\n' ' ' | head -c 1200)"
fi

# ---------------------------------------------------------------- 8. other accounts and keys
for account in admin root squad; do
    out="$(as "$account" owner true 2>&1)"; rc=$?
    if denied "$rc" "$out"; then pass "the feed key does not log in as $account"; else fail "the feed key does not log in as $account" "rc=$rc $out"; fi
    out="$(as "$account" ctrl true 2>&1)"; rc=$?
    if [ "$rc" = 0 ]; then pass "control: a key that belongs to $account logs in as $account"; else fail "control: a key that belongs to $account logs in as $account" "rc=$rc $out"; fi
done
out="$(as hitfeed ctrl true 2>&1)"; rc=$?
if denied "$rc" "$out"; then pass "another account's key does not log in as hitfeed"; else fail "another account's key does not log in as hitfeed" "rc=$rc $out"; fi
out="$(as hitfeed other true 2>&1)"; rc=$?
if denied "$rc" "$out"; then pass "an unknown key does not log in as hitfeed"; else fail "an unknown key does not log in as hitfeed" "rc=$rc $out"; fi
out="$(as ctrl other true 2>&1)"; rc=$?
if [ "$rc" = 0 ]; then pass "control: that unknown key is valid for another account"; else fail "control: that unknown key is valid for another account" "rc=$rc $out"; fi
out="$(as hitfeed expired true 2>&1)"; rc=$?
if denied "$rc" "$out"; then pass "an expired key (expiry-time in the past) does not log in"; else fail "an expired key does not log in" "rc=$rc $out"; fi
out="$(ssh "${BASE_OPTIONS[@]}" -p "$port" -o PreferredAuthentications=password -o PubkeyAuthentication=no hitfeed@127.0.0.1 true 2>&1)"; rc=$?
if [ "$rc" != 0 ] && echo "$out" | grep -qi 'permission denied (publickey)'; then pass "password authentication is not offered"; else fail "password authentication is not offered" "rc=$rc $out"; fi
out="$(ssh "${BASE_OPTIONS[@]}" -p "$port" -o PreferredAuthentications=keyboard-interactive -o PubkeyAuthentication=no hitfeed@127.0.0.1 true 2>&1)"; rc=$?
if [ "$rc" != 0 ] && echo "$out" | grep -qi 'permission denied (publickey)'; then pass "keyboard-interactive authentication is not offered"; else fail "keyboard-interactive authentication is not offered" "rc=$rc $out"; fi
if container_has 'getent passwd hitfeed | grep -q ":/bin/sh$"'; then pass "the hitfeed account has the login shell /bin/sh (nologin would break the forced command)"; else fail "the hitfeed login shell" "not /bin/sh"; fi
if docker exec -u hitfeed "$tag" cat "$LOG1" >/dev/null 2>&1; then
    pass "setup check: the hitfeed account itself can read squad1's log (as on the host), so only the forced command stops it"
else
    fail "setup check: hitfeed can read squad1's log" "the sandbox does not model the host"
fi

echo
if [ "$failures" = 0 ]; then echo "ALL PASS"; else echo "$failures FAILED"; fi
exit "$([ "$failures" = 0 ] && echo 0 || echo 1)"
