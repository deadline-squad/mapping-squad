"""Hits on the Training server, read from its SquadGame.log.

Squad's dedicated server writes one `TakeDamage()` (or, for vehicles and
players, `TraceAndMessageClient()`) line per damage event:
the actor that was hit, the damage, the class of the projectile that caused
it and the health left. The line also names the player who fired; this tool
never reads that part, so no nickname or Steam id leaves it.

Usage (read-only, the log stays on the server):

    ssh root@<host> 'tail -n 20000 <SquadGame.log>' | python3 hits.py
    python3 hits.py SquadGame.log --causer Mortarround --since 17.02

Output: one line per event, `time target damage causer health_left`.
A shot that did not touch a target leaves no line: the log records only
damage, so a miss is "no line", not a distance.
"""

import argparse
import re
import sys

EVENT = re.compile(
    r"^\[(?P<stamp>\d{4}\.\d\d\.\d\d-\d\d\.\d\d\.\d\d):\d+\]\[\s*\d+\]"
    r"LogSquadTrace: \[DedicatedServer\](?:TakeDamage|TraceAndMessageClient)\(\): "
    r"(?P<target>\S+): (?P<damage>[\d.]+) damage taken by causer "
    r"(?P<causer>\S+) instigator "
    r".* health remaining (?P<health>-?[\d.]+)\s*$"
)
INSTANCE_SUFFIX = re.compile(r"_C_\d+$")


def class_name(actor):
    """Blueprint class of an actor name such as `BP_FOBRadio_C_2147396823`."""
    return INSTANCE_SUFFIX.sub("_C", actor)


def parse(lines):
    """Yield (stamp, target, damage, causer, health) for each damage event."""
    for line in lines:
        match = EVENT.match(line)
        if match is None:
            continue
        yield (
            match["stamp"],
            class_name(match["target"]),
            float(match["damage"]),
            class_name(match["causer"]),
            float(match["health"]),
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("log", nargs="?", help="log file; standard input if absent")
    parser.add_argument("--causer", help="keep events whose projectile class contains this")
    parser.add_argument("--target", help="keep events whose hit actor class contains this")
    parser.add_argument("--since", help="keep events from this time, e.g. 17.02 or 2026.10.29-17.02")
    args = parser.parse_args()

    source = open(args.log, encoding="utf-8", errors="replace") if args.log else sys.stdin
    for stamp, target, damage, causer, health in parse(source):
        if args.causer and args.causer not in causer:
            continue
        if args.target and args.target not in target:
            continue
        if args.since and args.since not in stamp and stamp < args.since:
            continue
        print(f"{stamp}\t{target}\t{damage:g}\t{causer}\t{health:g}")


if __name__ == "__main__":
    main()
