#!/usr/bin/env python3
"""The home servers feed of SquadCalc (`HOME_SERVERS_URL`, read by its `src/js/serversSource.js`):

    live_servers.py <feed file>

Every PERIOD_S seconds asks the Deadline site for the state of the game server (its public `GET /api/v1/server`, which
the site fills from the game host itself; 60 requests a minute are allowed per address) and rewrites the feed
`{"generated": <UTC time>, "servers": [...]}` with the server in the shape of SquadCalc's API servers: the layer played,
the players and the faction ID of both teams. The site names a faction by its display name ("Armed Forces of Ukraine")
or, where it has none, by its upper-cased ID; the ID is taken from the factions the layer offers that team
(SquadCalc's API, `get/layer`, asked once an hour per layer). The unit of a team is not known to the site, so the feed has
none. A layer the API does not have (404) lists the server without teams.

The feed is rewritten only from answers of the shape read here. While the site, or the layer API for a layer not asked
before, gives none (no answer, a timeout, an error status, a body of another shape), the feed is left as it is and one
line says why: SquadCalc drops a feed older than two minutes, so a state that can no longer be confirmed is not shown
as live. Such an answer is not kept, the next round asks again. After `429 Too Many Requests` the next round waits as
long as the answer's `Retry-After` says (at most MAX_RETRY_AFTER_S), or without one twice as long as the round before
(at most MAX_BACKOFF_S).
"""
import datetime
import email.utils
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SITE_URL = "https://deadline-squad.org/api/v1/server"
LAYER_URL = "https://squadcalc.app/api/get/layer?name="
SERVER_ID = "deadline"
PERIOD_S = 20
TIMEOUT_S = 10
MAX_BODY_BYTES = 4 * 1024 * 1024
MAX_RETRY_AFTER_S = 3600
MAX_BACKOFF_S = 300
# What the layer API said of a layer is asked again after this long (a game patch gives it new layers and factions),
# and, when that request fails, once more after LAYER_RETRY_S while the last answer stands
LAYER_KEPT_S = 3600
LAYER_RETRY_S = 300
USER_AGENT = "squadcalc-live-servers"
TEAMS = ("1", "2")


def field(holder, key, kind):
    """`holder[key]`, None when it is missing or null.

    Raises ValueError when it is of another type than `kind` (a boolean is no number)."""
    value = holder.get(key)
    if value is not None and (not isinstance(value, kind) or isinstance(value, bool)):
        raise ValueError(f"{key!r} is {type(value).__name__}, not {kind.__name__}")
    return value


def site_status(body):
    """What the feed takes from the site's answer `{"data": {...}}`: `name`, `map`, `players`, `max` and `factions`,
    the label the site gives the faction of each team (None for a team without one).

    Raises ValueError when the answer has no `data` object, or a field has another type than the one read here: text
    for `name`, `map` and a faction, a whole number for `players` and `max`, an object for `teams` and for a team."""
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        raise ValueError("no data object")
    teams = field(data, "teams", dict) or {}
    return {
        "name": field(data, "name", str),
        "map": field(data, "map", str),
        "players": field(data, "players", int),
        "max": field(data, "max", int),
        "factions": {team: field(field(teams, team, dict) or {}, "faction", str) for team in TEAMS},
    }


def offered_factions(answer):
    """The factions a layer offers each team, `{"1": [{"factionID", "factionName"}, ...], "2": [...]}`, from the layer
    API's answer (`units.team1Units` and `units.team2Units`, one entry per unit of a faction).

    Raises ValueError when the answer does not list them so."""
    units = answer.get("units") if isinstance(answer, dict) else None
    if not isinstance(units, dict):
        raise ValueError("no units object")
    offered = {}
    for team in TEAMS:
        listed = units.get(f"team{team}Units")
        if not isinstance(listed, list) or not all(isinstance(unit, dict) for unit in listed):
            raise ValueError(f"team{team}Units is not a list of units")
        factions = dict.fromkeys((field(unit, "factionID", str), field(unit, "factionName", str)) for unit in listed)
        if any(None in faction for faction in factions):
            raise ValueError(f"a unit of team{team}Units has no factionID or factionName")
        offered[team] = [{"factionID": faction, "factionName": name} for faction, name in factions]
    return offered


def faction_id(label, factions):
    """The ID of the faction the site calls `label`, among the `factions` a layer offers a team (each with `factionID`
    and `factionName`); None when the layer offers no such faction."""
    wanted = (label or "").casefold()
    for faction in factions:
        if wanted and wanted in (faction["factionName"].casefold(), faction["factionID"].casefold()):
            return faction["factionID"]
    return None


def server_entry(status, offered):
    """The feed's server from the site's state (`site_status`) and the factions its layer offers each team
    (`offered_factions`; None when the API does not have the layer: the server is then listed without teams); None
    while the server plays no layer."""
    if not status["map"] or not status["name"]:
        return None
    entry = {
        "id": SERVER_ID,
        "attributes": {
            "name": status["name"],
            "players": status["players"],
            "maxPlayers": status["max"],
            "details": {"map": status["map"]},
        },
    }
    for team in TEAMS:
        faction = faction_id(status["factions"][team], offered[team]) if offered else None
        if faction:
            entry[f"team{team}"] = faction
    return entry


def get_json(url, etag=None):
    """(parsed body, ETag) of `url`; the body is None when the server answers that `etag` is still current.

    Raises OSError or http.client.HTTPException when there is no answer or an error status, ValueError when the body
    is not JSON, is JSON null (which would read as "still current") or is longer than MAX_BODY_BYTES."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if etag:
        headers["If-None-Match"] = etag
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT_S) as response:
            body = response.read(MAX_BODY_BYTES + 1)
            if len(body) > MAX_BODY_BYTES:
                raise ValueError(f"a body of more than {MAX_BODY_BYTES} bytes")
            parsed = json.loads(body)
            if parsed is None:
                raise ValueError("a body of JSON null")
            return parsed, response.headers.get("ETag")
    except urllib.error.HTTPError as error:
        if error.code == 304:
            return None, etag
        raise


def layer_factions(name, known):
    """The factions the layer `name` offers each team (`offered_factions`), asked from the API and kept in `known`
    for LAYER_KEPT_S; None for a layer the API does not have (kept as long, then asked again). An answer that cannot
    be read is not kept: for a layer not asked before it raises, for a layer whose time has run out the last answer
    stands and the API is asked again LAYER_RETRY_S later."""
    now = time.monotonic()
    if name in known and now < known[name][1]:
        return known[name][0]
    try:
        factions = offered_factions(get_json(LAYER_URL + urllib.parse.quote(name))[0])
    except Exception as error:
        if isinstance(error, urllib.error.HTTPError) and error.code == 404:
            factions = None
        elif name in known:
            known[name] = (known[name][0], now + LAYER_RETRY_S)
            return known[name][0]
        else:
            raise
    known[name] = (factions, now + LAYER_KEPT_S)
    return factions


def write_feed(path, servers):
    """Replaces the feed in one step, so a reader never sees half a file."""
    feed = {"generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "servers": servers}
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(feed, file, ensure_ascii=False)
    os.chmod(temporary, 0o644)
    os.replace(temporary, path)


def retry_after(value):
    """The seconds a `Retry-After` header asks to wait, given as a number of seconds or as an HTTP date; None when the
    header is missing or gives neither. A number with more digits than MAX_RETRY_AFTER_S is read as infinity: Python
    refuses to convert a string of thousands of digits, and the caller caps the pause anyway."""
    if value is None:
        return None
    seconds = value.strip()
    if re.fullmatch(r"[0-9]+", seconds):
        return int(seconds) if len(seconds) <= len(str(MAX_RETRY_AFTER_S)) else float("inf")
    try:
        date = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if date.tzinfo is None:
        date = date.replace(tzinfo=datetime.timezone.utc)
    return (date - datetime.datetime.now(datetime.timezone.utc)).total_seconds()


def pause_after(error, last):
    """The seconds from the start of a failed round to the next one: PERIOD_S, or longer when the server asked for
    fewer requests. An HTTP error status with `Retry-After` waits as long as it says (at most MAX_RETRY_AFTER_S); a
    429 without one waits twice as long as `last`, the pause of the round before (at most MAX_BACKOFF_S)."""
    if not isinstance(error, urllib.error.HTTPError):
        return PERIOD_S
    asked = retry_after(error.headers.get("Retry-After")) if error.headers else None
    if asked is not None:
        return max(PERIOD_S, min(MAX_RETRY_AFTER_S, asked))
    if error.code == 429:
        return min(MAX_BACKOFF_S, 2 * last)
    return PERIOD_S


def main(path):
    status, etag, layers, said, pause = None, None, {}, None, PERIOD_S
    while True:
        started = time.monotonic()
        asked = SITE_URL
        try:
            body, etag = get_json(SITE_URL, etag)
            if body is not None:
                status = site_status(body)
            offered = None
            if status["map"]:
                asked = LAYER_URL + status["map"]
                offered = layer_factions(status["map"], layers)
            entry = server_entry(status, offered)
            asked = path
            write_feed(path, [entry] if entry else [])
            message = f"{status['map']}, teams {entry.get('team1')} / {entry.get('team2')}" if entry else "no layer played"
            pause, note = PERIOD_S, ""
        except Exception as error:
            # The service outlives any answer: the feed is left as it is and the next round asks again
            etag = None
            pause = pause_after(error, pause)
            message = f"feed not updated: {asked}: {error!r}"
            note = "" if pause == PERIOD_S else f"; next request in {pause:.0f} s"
        if message != said:
            print(message + note, file=sys.stderr, flush=True)
            said = message
        time.sleep(max(0.0, pause - (time.monotonic() - started)))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
