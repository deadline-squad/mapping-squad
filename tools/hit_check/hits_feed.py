"""Host-side hit feed: one player's own hits and map markers, as JSON lines.

Runs on the game host as the forced command of an SSH key (one key per
player), follows the Training server's SquadGame.log and prints only the
events whose shooter has the given Steam ID. Nothing is stored; the log stays
where it is. Standard library only, Python 3.

Usage (the key line fixes the arguments; the client can add only `since=`):

    command="/usr/bin/python3 -I /opt/hitfeed/hits_feed.py \\
        --log /home/squad/squad2/SquadGame/Saved/Logs/SquadGame.log \\
        --allow-under /home/squad/squad2 --steam-id 76561190000000001"

    python3 -I hits_feed.py --replay [--log FILE] [--steam-id ID]   # tests, counts

Client request: `SSH_ORIGINAL_COMMAND` is either unset (start at the end of the
log) or exactly `since=YYYY.MM.DD-HH.MM.SS:mmm` (start at the first log line at
or after that stamp, the stamp of the last event the client has). Anything
else is refused with exit code 2 and a short message that does not repeat the
input. `--log` must resolve (symlinks and `..` followed) to a path under
`--allow-under`; this is the only thing that keeps the account away from the
other server's log, because Unix permissions do not.

Protocol: one JSON object per line on standard output, flushed at once.

    {"type":"hello","version":1,"clock":"2026-10-29T17:02:24.014Z"}
    {"type":"hb","clock":"..."}                  every 5 s, the server clock
    {"type":"rotate","clock":"..."}              the log file was replaced or truncated
    {"type":"hit","id":"2026.10.29-17.02.24:014#0#1a2b3c4d","ts":"2026-10-29T17:02:24.014Z",
     "target":"BP_FOBRadio_Woodland_C","damage":7.4,"causer":"BP_40MM_VOG_Proj2_C","health":252.6}
    {"type":"marker","id":"...","ts":"...","marker":"BP_MapMarker_POI","x":85946.0,"y":-57540.0,"z":4675.0}

`id` is `<log stamp>#<chain>#<crc32>`: the stamp of the log line, the number of
events already emitted with that stamp (so two identical shots in one
millisecond differ) and the CRC-32 of the event fields. It is the same for the
same log line on every run, so a client that resends `since=<stamp>` after a
reconnect drops the repeats by `id`. `ts` is the log stamp as UTC (the server
writes UTC). `target` is a Blueprint class name with the instance suffix
`_C_<digits>` cut to `_C`, or "other" when the victim field is not a class
name (in `TraceAndMessageClient` lines it can be a player's name). A hit has no
distance: the log has only damage, so a miss is "no line".

Never emitted: nicknames, Steam or EOS IDs, IP addresses.

Trust model for a log line. Nicknames are player-controlled and can contain
any text, including " health remaining ", "steam: <someone's id>)" or a whole
fake event. The server writes the end of a line (`... EOS: <32 hex> steam:
<17 digits>) health remaining <number>` or the marker's `Location: x, y, z`)
and the start (stamp, function, causer). Only these are trusted:

* the shooter's Steam ID is read from the end of the line, anchored at the end
  of the string, so no text before it can supply or hide it;
* `TakeDamage()` lines are read from the left (the victim is an actor name
  without spaces, so a nickname cannot move the field boundaries);
* `TraceAndMessageClient()` lines can have a nickname as the victim, so the
  fields are cut at the last " damage taken by causer " before the ID tail
  that has the server's layout around it (at most 16 are tried): a victim's
  nickname cannot change anything, and a shooter's own nickname that imitates
  the whole layout can at most distort that shooter's own events;
* the three shapes of the shooter field (`<name> (Online IDs: EOS: .. steam:
  ..)`, `(Online Ids: <name>) EOS: .. steam: ..` and the unattributable
  `(Online Ids: nullptr) INVALID`) are told apart by that end; the last one,
  and every "damage attempt" line, is dropped.

Every parse is linear in the line length; a 1 MB nickname takes a few
milliseconds. A line longer than 64 KB is skipped before it is parsed.
"""

import argparse
import collections
import datetime
import json
import os
import re
import stat
import sys
import time
import zlib

VERSION = 1
MAX_LINE_BYTES = 64 * 1024
HEARTBEAT_SECONDS = 5.0
POLL_SECONDS = 0.05
READ_CHUNK_BYTES = 64 * 1024
TAIL_WINDOW = 400
CHAIN_MEMORY = 1024
MAX_SEPARATOR_CANDIDATES = 16
EXIT_REFUSED = 2

STAMP = r"\d{4}\.\d\d\.\d\d-\d\d\.\d\d\.\d\d:\d{3}"
NUMBER = r"-?\d{1,12}(?:\.\d{1,12})?"
EOS = r"[0-9a-fA-F]{32}"
STEAM = r"\d{17}"

LINE_HEAD = re.compile(rf"\[(?P<stamp>{STAMP})\]\[\s*\d+\]")
TAKE_DAMAGE = "LogSquadTrace: [DedicatedServer]TakeDamage(): "
TRACE_AND_MESSAGE = "LogSquadTrace: [DedicatedServer]TraceAndMessageClient(): "
MARKER_PREFIX = "LogSquad: Player "
DAMAGE_SEPARATOR = " damage taken by causer "

TAKE_DAMAGE_HEAD = re.compile(
    rf"(?P<victim>\S+): (?P<damage>{NUMBER}) damage taken by causer (?P<causer>\S+) instigator "
)
TAKE_DAMAGE_TAIL = re.compile(
    rf"\(Online IDs: EOS: {EOS} steam: (?P<steam>{STEAM})\) health remaining (?P<health>{NUMBER})\Z"
)
MESSAGE_DAMAGE_BEFORE = re.compile(rf": (?P<damage>{NUMBER})\Z")
MESSAGE_DAMAGE_AFTER = re.compile(r"(?P<causer>\S+) instigator \(Online Ids: ")
MESSAGE_TAIL = re.compile(
    rf"\) EOS: {EOS} steam: (?P<steam>{STEAM}) health remaining (?P<health>{NUMBER})\Z"
)
MARKER_TAIL = re.compile(
    rf"\(Team: \d+; ID: EOS: {EOS} steam: (?P<steam>{STEAM})\) placed a new map marker "
    rf"for team \d+ : Type: (?P<marker>BP_MapMarker_[A-Za-z0-9_]+) ; "
    rf"Location: (?P<x>{NUMBER}), (?P<y>{NUMBER}), (?P<z>{NUMBER})\Z"
)
CLASS_NAME = re.compile(r"[A-Za-z0-9_]+_C(?:_\d+)?")
INSTANCE_SUFFIX = re.compile(r"_C_\d+\Z")
CLIENT_REQUEST = re.compile(rf"since=(?P<stamp>{STAMP})\Z")
MAX_CLASS_NAME_LENGTH = 200


class Refused(Exception):
    """The request or the arguments are not allowed; the message is safe to print."""


Parsed = collections.namedtuple("Parsed", "stamp steam fields")


def class_name(text):
    """Return the class name with `_C_<digits>` cut to `_C`, or None if `text` is not one."""
    if len(text) > MAX_CLASS_NAME_LENGTH or CLASS_NAME.fullmatch(text) is None:
        return None
    return INSTANCE_SUFFIX.sub("_C", text)


def _hit_fields(victim, damage, causer, health):
    """Fields of a hit event, or None when the causer is not a class name."""
    causer_class = class_name(causer)
    if causer_class is None:
        return None
    return {
        "type": "hit",
        "target": class_name(victim) or "other",
        "damage": float(damage),
        "causer": causer_class,
        "health": float(health),
    }


def _parse_take_damage(line, start):
    head = TAKE_DAMAGE_HEAD.match(line, start)
    if head is None:
        return None
    tail = TAKE_DAMAGE_TAIL.search(line, max(head.end(), len(line) - TAIL_WINDOW))
    if tail is None:
        return None
    fields = _hit_fields(head["victim"], head["damage"], head["causer"], tail["health"])
    return fields, tail["steam"]


def _message_fields_at(line, start, separator, tail_start):
    """Cut a `TraceAndMessageClient` line at one candidate separator.

    Returns (victim, damage, causer) when the text around the separator has
    the server's layout (`<victim>: <damage>` before it, `<causer> instigator
    (Online Ids: ` after it), else None.
    """
    after = MESSAGE_DAMAGE_AFTER.match(line, separator + len(DAMAGE_SEPARATOR))
    if after is None or after.end() > tail_start:
        return None
    window_start = max(start, separator - 40)
    before = MESSAGE_DAMAGE_BEFORE.search(line[window_start:separator])
    if before is None:
        return None
    victim = line[start : window_start + before.start()]
    return victim, before["damage"], after["causer"]


def _parse_trace_and_message(line, start):
    tail = MESSAGE_TAIL.search(line, max(start, len(line) - TAIL_WINDOW))
    if tail is None:
        return None
    end = tail.start()
    for _ in range(MAX_SEPARATOR_CANDIDATES):
        separator = line.rfind(DAMAGE_SEPARATOR, start, end)
        if separator < 0:
            return None
        cut = _message_fields_at(line, start, separator, tail.start())
        if cut is not None:
            return _hit_fields(cut[0], cut[1], cut[2], tail["health"]), tail["steam"]
        end = separator + len(DAMAGE_SEPARATOR) - 1
    return None


def _parse_marker(line, start):
    tail = MARKER_TAIL.search(line, max(start, len(line) - TAIL_WINDOW))
    if tail is None:
        return None
    fields = {
        "type": "marker",
        "marker": tail["marker"],
        "x": float(tail["x"]),
        "y": float(tail["y"]),
        "z": float(tail["z"]),
    }
    return fields, tail["steam"]


def parse_line(line):
    """Parse one log line (no line terminator) into `Parsed`, or None.

    `Parsed.steam` is the shooter's Steam ID as the server wrote it at the end
    of the line; `Parsed.fields` holds only class names, markers and numbers.
    Lines that are not an attributable hit or marker give None.
    """
    head = LINE_HEAD.match(line)
    if head is None:
        return None
    start = head.end()
    if line.startswith(TAKE_DAMAGE, start):
        parsed = _parse_take_damage(line, start + len(TAKE_DAMAGE))
    elif line.startswith(TRACE_AND_MESSAGE, start):
        parsed = _parse_trace_and_message(line, start + len(TRACE_AND_MESSAGE))
    elif line.startswith(MARKER_PREFIX, start):
        parsed = _parse_marker(line, start + len(MARKER_PREFIX))
    else:
        return None
    if parsed is None or parsed[0] is None:
        return None
    return Parsed(head["stamp"], parsed[1], parsed[0])


def stamp_to_iso(stamp):
    """`2026.10.29-17.02.24:014` as `2026-10-29T17:02:24.014Z`."""
    date, clock = stamp.split("-")
    seconds, millis = clock.split(":")
    return f"{date.replace('.', '-')}T{seconds.replace('.', ':')}.{millis}Z"


def server_clock():
    """The host's UTC time with millisecond precision, in the format of `ts`."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class EventFilter:
    """Turns raw log lines into event dicts for one shooter.

    With `steam_id` set, only that shooter's events pass; with None every
    attributable event passes (replay counts only).
    """

    def __init__(self, steam_id=None):
        self._steam_id = steam_id
        self._chains = collections.OrderedDict()

    def event_for(self, raw_line):
        """Return the event dict for one log line (bytes, no `\\n`), or None."""
        line = raw_line.decode("utf-8", errors="replace")
        if line.endswith("\r"):
            line = line[:-1]
        parsed = parse_line(line)
        if parsed is None:
            return None
        if self._steam_id is not None and parsed.steam != self._steam_id:
            return None
        fields = parsed.fields
        checksum = zlib.crc32(json.dumps(fields, sort_keys=True).encode()) & 0xFFFFFFFF
        chain = self._chains.pop(parsed.stamp, 0)
        self._chains[parsed.stamp] = chain + 1
        if len(self._chains) > CHAIN_MEMORY:
            self._chains.popitem(last=False)
        event = {"type": fields["type"], "id": f"{parsed.stamp}#{chain}#{checksum:08x}"}
        event["ts"] = stamp_to_iso(parsed.stamp)
        event.update((key, value) for key, value in fields.items() if key != "type")
        return event


class LineSplitter:
    """Splits a byte stream into lines, skipping the ones over `MAX_LINE_BYTES`.

    A line without its newline yet is kept until the rest arrives. The buffer
    never holds more than `MAX_LINE_BYTES`: a longer line is dropped as it grows
    and its remainder is discarded up to the next newline.
    """

    def __init__(self):
        self._buffer = bytearray()
        self._skipping = False

    def skip_partial_line(self):
        """Drop the rest of the line the stream starts in the middle of."""
        self._buffer.clear()
        self._skipping = True

    def reset(self):
        """Forget a half-read line (the file was replaced or truncated)."""
        self._buffer.clear()
        self._skipping = False

    def feed(self, data):
        """Return the complete lines (bytes, no `\\n`) found after adding `data`."""
        lines = []
        position = 0
        while position < len(data):
            newline = data.find(b"\n", position)
            if newline < 0:
                if not self._skipping:
                    self._buffer += data[position:]
                    if len(self._buffer) > MAX_LINE_BYTES:
                        self._buffer.clear()
                        self._skipping = True
                break
            piece = data[position:newline]
            position = newline + 1
            if self._skipping:
                self._skipping = False
                continue
            line = bytes(self._buffer) + piece
            self._buffer.clear()
            if len(line) <= MAX_LINE_BYTES:
                lines.append(line)
        return lines


def is_under(path, root):
    """True if `path` resolves, symlinks and `..` included, to `root` or below it."""
    resolved_path = os.path.realpath(path)
    resolved_root = os.path.realpath(root)
    return os.path.commonpath([resolved_path, resolved_root]) == resolved_root


class LogFollower:
    """Follows a log file by path and emits the events of its new lines.

    `step()` does one non-blocking pass so it can be driven by a loop or by a
    test. The file is opened when the follower is created: that open starts at
    the end of the file, or at the first line whose stamp is at or after
    `since`; a file that appears later or replaces the followed one is read
    from its start. A replaced inode or a file
    shorter than what was read gives a `rotate` event; the old file is read to
    its end first. The path is resolved and checked against `allow_under` on
    every open, and a file that is not a regular file is ignored.
    """

    def __init__(self, path, allow_under, event_filter, emit, since=None, clock=time.monotonic):
        self._path = path
        self._allow_under = allow_under
        self._filter = event_filter
        self._emit = emit
        self._since = since.encode() if since else None
        self._since_pending = since is not None
        self._clock = clock
        self._splitter = LineSplitter()
        self._fd = None
        self._identity = None
        self._offset = 0
        self._first_open = True
        self._next_heartbeat = clock() + HEARTBEAT_SECONDS
        self._open_file()

    def run(self, sleep=time.sleep):
        """Follow the log until the process is stopped."""
        while True:
            if not self.step():
                sleep(POLL_SECONDS)

    def step(self):
        """One pass: open, read what is there, notice a rotation, send a heartbeat.

        Returns True if any bytes were read, so the caller can skip its sleep.
        """
        self._send_heartbeat()
        if self._fd is None and not self._open_file():
            return False
        read_any = self._drain()
        if not read_any:
            self._notice_replacement()
        return read_any

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def _send_heartbeat(self):
        now = self._clock()
        if now >= self._next_heartbeat:
            self._next_heartbeat = now + HEARTBEAT_SECONDS
            self._emit({"type": "hb", "clock": server_clock()})

    def _resolve(self):
        resolved = os.path.realpath(self._path)
        return resolved if is_under(resolved, self._allow_under) else None

    def _open_file(self):
        fd = self._open_regular_file()
        if fd is None:
            self._first_open = False
            return False
        info = os.fstat(fd)
        self._fd = fd
        self._identity = (info.st_dev, info.st_ino)
        self._offset = 0
        self._splitter.reset()
        if self._first_open and self._since is None:
            self._start_at_end(info.st_size)
        self._first_open = False
        return True

    def _open_regular_file(self):
        resolved = self._resolve()
        if resolved is None:
            return None
        try:
            fd = os.open(resolved, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
        except OSError:
            return None
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            return None
        return fd

    def _start_at_end(self, size):
        os.lseek(self._fd, size, os.SEEK_SET)
        self._offset = size
        if size > 0 and os.pread(self._fd, 1, size - 1) != b"\n":
            self._splitter.skip_partial_line()

    def _drain(self):
        read_any = False
        while True:
            try:
                data = os.read(self._fd, READ_CHUNK_BYTES)
            except BlockingIOError:
                break
            if not data:
                break
            read_any = True
            self._offset += len(data)
            for line in self._splitter.feed(data):
                self._handle_line(line)
        return read_any

    def _handle_line(self, line):
        if self._since_pending:
            if line[:1] != b"[" or line[24:25] != b"]" or line[1:24] < self._since:
                return
            self._since_pending = False
        event = self._filter.event_for(line)
        if event is not None:
            self._emit(event)

    def _notice_replacement(self):
        if os.fstat(self._fd).st_size < self._offset:
            os.lseek(self._fd, 0, os.SEEK_SET)
            self._offset = 0
            self._rotated()
            return
        resolved = self._resolve()
        if resolved is None:
            return
        try:
            current = os.stat(resolved)
        except OSError:
            return
        if (current.st_dev, current.st_ino) == self._identity:
            return
        self._drain()
        self.close()
        self._rotated()
        self._open_file()

    def _rotated(self):
        self._since_pending = False
        self._splitter.reset()
        self._emit({"type": "rotate", "clock": server_clock()})


def replay(source, event_filter, emit):
    """Read a binary stream to its end and emit the events of its lines."""
    splitter = LineSplitter()
    while True:
        data = source.read(READ_CHUNK_BYTES)
        if not data:
            break
        for line in splitter.feed(data):
            event = event_filter.event_for(line)
            if event is not None:
                emit(event)


def parse_client_request(original_command):
    """Validate `SSH_ORIGINAL_COMMAND`; return the `since` stamp or None if unset.

    Raises `Refused` for anything but exactly `since=YYYY.MM.DD-HH.MM.SS:mmm`
    with a real calendar date and time. The message never repeats the input.
    """
    if original_command is None:
        return None
    match = CLIENT_REQUEST.match(original_command)
    if match is None:
        raise Refused("only since=YYYY.MM.DD-HH.MM.SS:mmm is accepted")
    try:
        datetime.datetime.strptime(match["stamp"][:-4], "%Y.%m.%d-%H.%M.%S")
    except ValueError:
        raise Refused("since is not a valid date") from None
    return match["stamp"]


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused("bad arguments")


def _build_parser():
    parser = _Parser(description="One player's hit and marker events from the game log.", allow_abbrev=False)
    parser.add_argument("--log", help="log file to follow (or to replay with --replay)")
    parser.add_argument("--allow-under", help="directory the resolved --log must be inside")
    parser.add_argument("--steam-id", help="17-digit Steam ID of the shooter whose events are sent")
    parser.add_argument("--replay", action="store_true", help="read --log or standard input to the end and exit")
    return parser


def _validate(args):
    """Check the arguments of a follow run; raises `Refused`."""
    if args.steam_id is None or re.fullmatch(STEAM, args.steam_id) is None:
        raise Refused("--steam-id must be 17 digits")
    if not args.log or not args.allow_under:
        raise Refused("--log and --allow-under are required")
    if not os.path.isabs(args.log) or not os.path.isabs(args.allow_under):
        raise Refused("--log and --allow-under must be absolute paths")
    if not is_under(args.log, args.allow_under):
        raise Refused("--log is outside --allow-under")


def _writer(out):
    def emit(event):
        out.write(json.dumps(event, separators=(",", ":")) + "\n")
        out.flush()

    return emit


def _client_gone():
    """End quietly when the client closed the pipe; also keeps the exit-time flush from failing."""
    os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    return 0


def main(argv=None, environ=None, out=None, stdin=None):
    """Entry point; returns the process exit code (2 when refused)."""
    environ = os.environ if environ is None else environ
    out = sys.stdout if out is None else out
    emit = _writer(out)
    try:
        args = _build_parser().parse_args(argv)
        since = parse_client_request(environ.get("SSH_ORIGINAL_COMMAND"))
        if args.replay:
            if args.steam_id is not None and re.fullmatch(STEAM, args.steam_id) is None:
                raise Refused("--steam-id must be 17 digits")
            event_filter = EventFilter(args.steam_id)
            if args.log:
                with open(args.log, "rb") as source:
                    replay(source, event_filter, emit)
            else:
                replay((sys.stdin if stdin is None else stdin).buffer, event_filter, emit)
            return 0
        _validate(args)
    except Refused as refusal:
        print(f"hits_feed: refused: {refusal}", file=sys.stderr)
        return EXIT_REFUSED
    except BrokenPipeError:
        return _client_gone()
    follower = LogFollower(args.log, args.allow_under, EventFilter(args.steam_id), emit, since)
    try:
        emit({"type": "hello", "version": VERSION, "clock": server_clock()})
        follower.run()
    except BrokenPipeError:
        return _client_gone()
    except KeyboardInterrupt:
        return 0
    finally:
        follower.close()


if __name__ == "__main__":
    sys.exit(main())
