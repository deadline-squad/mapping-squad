#!/usr/bin/env python3
"""The home servers feed of SquadCalc (`HOME_SERVERS_URL`, read by its `src/js/serversSource.js`):

    live_servers.py <feed file>

Every PERIOD_S seconds asks the Deadline site for the state of the game server (its public `GET /api/v1/server`, which
the site fills from the game host itself; 60 requests a minute are allowed per address) and rewrites the feed
`{"generated": <UTC time>, "servers": [...]}` with the server in the shape of SquadCalc's API servers: the layer played,
the players and the faction ID of both teams. The site names a faction by its display name ("Armed Forces of Ukraine")
or, where it has none, by its upper-cased ID; the ID is taken from the factions the layer offers that team
(SquadCalc's API, `get/layer`). The unit of a team is not known to the site, so the feed has none.

While the site does not answer, the feed is left as it is: SquadCalc drops a feed older than two minutes, so a state
that can no longer be confirmed is not shown as live.
"""
import datetime
import json
import os
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
USER_AGENT = "squadcalc-live-servers"


def faction_id(label, units):
    """The ID of the faction the site calls `label`, among the `units` a layer offers a team (each with `factionID`
    and `factionName`); None when the layer offers no such faction."""
    wanted = (label or "").casefold()
    for unit in units:
        if wanted and wanted in (unit["factionName"].casefold(), unit["factionID"].casefold()):
            return unit["factionID"]
    return None


def server_entry(status, layer):
    """The feed's server from the site's `data` block and the layer's API answer (None when the layer is not known to
    the API: the server is then listed without teams); None while the server plays no layer."""
    if not status.get("map") or not status.get("name"):
        return None
    entry = {
        "id": SERVER_ID,
        "attributes": {
            "name": status["name"],
            "players": status.get("players"),
            "maxPlayers": status.get("max"),
            "details": {"map": status["map"]},
        },
    }
    for team in ("1", "2"):
        label = (status.get("teams") or {}).get(team, {}).get("faction")
        faction = faction_id(label, layer["units"][f"team{team}Units"]) if layer else None
        if faction:
            entry[f"team{team}"] = faction
    return entry


def get_json(url, etag=None):
    """(parsed body, ETag) of `url`; the body is None when the server answers that `etag` is still current."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if etag:
        headers["If-None-Match"] = etag
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT_S) as response:
            return json.load(response), response.headers.get("ETag")
    except urllib.error.HTTPError as error:
        if error.code == 304:
            return None, etag
        raise


def layer_info(name, known):
    """The API's description of the layer `name`, kept in `known`; None for a layer the API does not have."""
    if name not in known:
        try:
            known[name] = get_json(LAYER_URL + urllib.parse.quote(name))[0]
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            known[name] = None
    return known[name]


def write_feed(path, servers):
    """Replaces the feed in one step, so a reader never sees half a file."""
    feed = {"generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "servers": servers}
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(feed, file, ensure_ascii=False)
    os.chmod(temporary, 0o644)
    os.replace(temporary, path)


def main(path):
    status, etag, layers, said = None, None, {}, None
    while True:
        started = time.monotonic()
        try:
            body, etag = get_json(SITE_URL, etag)
            if body is not None:
                status = body.get("data") or {}
            layer = None
            if status.get("map"):
                try:
                    layer = layer_info(status["map"], layers)
                except (OSError, ValueError) as error:
                    print(f"layer {status['map']}: {error}; the server is listed without teams", file=sys.stderr, flush=True)
            entry = server_entry(status, layer)
            write_feed(path, [entry] if entry else [])
            message = f"{status.get('map')}, teams {entry.get('team1')} / {entry.get('team2')}" if entry else "no layer played"
        except (OSError, ValueError, KeyError) as error:
            etag, message = None, f"feed not updated: {error!r}"
        if message != said:
            print(message, file=sys.stderr, flush=True)
            said = message
        time.sleep(max(0.0, PERIOD_S - (time.monotonic() - started)))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
