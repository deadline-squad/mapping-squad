# hit_check

Tools that read hits and map markers out of the Training server's `SquadGame.log`.

| File | What it is |
|---|---|
| `hits.py`, `test_hits.py` | Simple extractor for a log on stdin or in a file: hit lines without the shooter, as TSV. |
| `hits_feed.py`, `test_hits_feed.py` | Host-side feed for one player: that player's own hits and markers as JSON lines. Built for the plan in [squad-ballistics#6](https://github.com/deadline-squad/squad-ballistics/issues/6) ("Research 5 of 6"). Not installed anywhere. |
| `mutation_check.py` | Breaks `hits_feed.py` in six places and checks that the tests fail each time. |
| `Dockerfile`, `sandbox_test.sh` | Local docker sshd that reproduces the key line and the server drop-in and attempts what a stolen key must not be able to do. |

## hits_feed.py

Python 3, standard library only. It is the forced command of one SSH key per player:

```
restrict,expiry-time="20271231",command="/usr/bin/python3 -I /opt/hitfeed/hits_feed.py --log /home/squad/squad2/SquadGame/Saved/Logs/SquadGame.log --allow-under /home/squad/squad2 --steam-id 76561190000000001" ssh-ed25519 AAAA... player-label
```

* The client may send only `since=YYYY.MM.DD-HH.MM.SS:mmm` (it arrives in `SSH_ORIGINAL_COMMAND`). Anything else, a bad date included, is refused with exit code 2 and a short message that does not repeat the input.
* `--log` must resolve (symlinks and `..` followed) to a path under `--allow-under`. The check is repeated on every (re)open of the file. Unix permissions cannot do this: `/home/squad` and squad1's log are world-readable.
* With no `since` the feed starts at the end of the log; with `since` at the first line whose stamp is at or after it (the client sends the stamp of its last event and drops repeats by `id`).
* The log is followed by path. A new inode, or a file shorter than what was read, gives a `rotate` event; the old file is read to its end first and the new one from its start. A missing file is waited for. A partial line waits for its newline. A line over 64 KB is skipped. Events during a disconnect are recovered only back to the start of the current log file.
* A heartbeat goes out every 5 s; output is flushed per line; the process ends when the client goes away (at the next write, 5 s at most).

### Protocol

One JSON object per line:

```
{"type":"hello","version":1,"clock":"2026-10-29T17:02:24.014Z"}
{"type":"hb","clock":"..."}
{"type":"rotate","clock":"..."}
{"type":"hit","id":"2026.10.29-17.02.24:014#0#1a2b3c4d","ts":"2026-10-29T17:02:24.014Z","target":"BP_FOBRadio_Woodland_C","damage":7.4,"causer":"BP_40MM_VOG_Proj2_C","health":252.6}
{"type":"marker","id":"...","ts":"...","marker":"BP_MapMarker_POI","x":85946.0,"y":-57540.0,"z":4675.0}
```

* `id` is `<log stamp>#<chain>#<crc32>`: the chain is the count of events already sent with that stamp (two identical shots in one millisecond differ), the CRC-32 is over the event fields. The same log line gets the same `id` on every run.
* `ts` is the log stamp read as UTC. Marker coordinates are the numbers in the log (Unreal units, presumably cm: not verified).
* `target` is a class name with `_C_<digits>` cut to `_C`, or `"other"` when the victim field is not a class name (it can be a player's name). A `causer` that is not a class name drops the event.
* Never emitted: nicknames, Steam or EOS IDs, IP addresses.

### What is trusted in a log line

Nicknames can contain anything, for example `" health remaining "`, `"steam: <someone's id>)"` or a whole fake event. Only what the server writes is trusted:

* The shooter's Steam ID comes from the end of the line, anchored at the end of the string: `(Online IDs: EOS: .. steam: ..) health remaining N` (`TakeDamage`), `) EOS: .. steam: .. health remaining N` (`TraceAndMessageClient`), or `(Team: N; ID: EOS: .. steam: ..) placed a new map marker ... Location: x, y, z` (marker). The unattributable `(Online Ids: nullptr) INVALID` and the "damage attempt" lines match none of them and are dropped.
* `TakeDamage` lines are read from the left (the victim is an actor name without spaces). `TraceAndMessageClient` lines are cut at the last ` damage taken by causer ` that has the server's layout around it, so a victim's nickname cannot change an event.
* Parsing is linear: a 1 MB nickname or 40 000 repeated tokens take a few milliseconds (limit 50 ms, tested).

Residual limits, by design: a nickname that imitates the server's whole layout can distort the events of its own owner only; a player who names themselves like a Blueprint class (`Foo_C`) shows up as that string when they are a victim; the feed depends on the current log format, so a game update that changes a line shape drops events (it cannot leak them) and `--replay` over a real log shows it.

### Replay

```
python3 -I hits_feed.py --replay [--log FILE] [--steam-id ID]
ssh root@HOST 'cat /home/squad/squad2/SquadGame/Saved/Logs/SquadGame.log' | python3 -I hits_feed.py --replay
```

Reads the file or standard input to the end and exits. Without `--steam-id` every attributable event is printed (for counts and format checks; the output still holds no names or IDs). `--replay` has no hello, heartbeat or rotate events.

## Tests

```
cd tools/hit_check && python3 -m unittest          # both test files
python3 mutation_check.py                           # six deliberate breaks, each must be KILLED
./sandbox_test.sh                                   # needs docker; prints one PASS/FAIL line per attempt
```

`sandbox_test.sh` builds an Ubuntu 24.04 container (OpenSSH 9.6, as on the host), installs the key line and the `Match User hitfeed` drop-in from the issue, and attempts a shell and other commands, bad arguments, scp (both modes), sftp, local, dynamic, remote and stdio forwarding, a forced TTY, agent and X11 forwarding, the environment, another account's key, the feed key as other accounts, an expired key and password login. Lines starting with `control:` show that the same attempt works for an unrestricted account, so a refusal means something. It removes the container and the image on exit. Not covered: the `nproc` cap in the limits file (needs PAM) and a burst of fire.
