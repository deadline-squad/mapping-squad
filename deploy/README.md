# Deployment on tk104

Copies of the live files; after changing a live file, copy it here and commit.

| File here | Live location |
|---|---|
| `Caddyfile` | `~/apps/squadcalc/Caddyfile` (user unit `squadcalc.service`, port 9910, behind the panel Caddy `calc.<domain>`) |
| `squadcalc.service` | `~/.config/systemd/user/` |
| `squadcalc-live.service` | `~/.config/systemd/user/` (enabled; `systemctl --user status squadcalc-live`) |
| `live_servers.py` | `~/apps/squadcalc/live_servers.py`, run by `squadcalc-live.service`; writes `~/apps/squadcalc/live/servers.json` |

Home servers feed: `live_servers.py` asks the Deadline site (`https://deadline-squad.org/api/v1/server`, served from the
game host) every 20 s and rewrites `live/servers.json`, which the Caddyfile serves as `/live/servers.json` (never cached)
and SquadCalc reads as `HOME_SERVERS_URL`: the Deadline server in the servers list, with the layer it plays, the players
and both factions. The folder is outside `dist`, so a site deploy does not touch it. Nothing runs on the game host and
RCON is not used. SquadCalc drops a feed older than two minutes: when the service or the site is down, the server
leaves the list instead of showing an old layer. Tests: `python3 -m unittest test_live_servers.py` in this folder;
in a browser: `tools/browser_check/home_server_check.mjs`.

Site build: from `dev` of `~/agl/SquadCalc` (remote `deadline`), in a worktree, `cp .env.template .env && npm run build`.
Under `flock /tmp/squadcalc-deploy.lock`, back up `~/apps/squadcalc/dist` to `dist.bak.<date>-<reason>` and
`rsync -a dist/ ~/apps/squadcalc/dist/`, both with `--exclude=/heightmaps --exclude='/heightmaps.bak.*'
--exclude=/maptiles --exclude='/maptiles.*'` (no `--delete`: the previous bundles stay so a cached page can
still load them). Then `tools/browser_check/browser_check.mjs https://calc.<domain> --maps --ballistics <weapons.json>`.

Precise heightmaps (`dist/heightmaps/<map>/`, outside the webpack build): built from the game files
with `tools/heightmaps/heightmaps.sh` (`extract`, `build`, then `deploy`, which backs up the previous
copy); see `tools/heightmaps/README.md`. Each map has a `heightmap.webp` next to its `heightmap.png`; the
PNGs stay for the older bundles. Without them SquadCalc uses its 8-bit heightmaps. The page requests the
heavy files as `?v=<generated of meta.json>` and the Caddyfile caches those URLs for a year, so a rebuilt heightmap
must get a new `generated` (`build` and `webp` write it). To add the WebP to already deployed heightmaps:
`heightmaps.sh webp`, `deploy-webp` (files; nothing changes for a page), deploy the bundle, `switch-webp` (the
`meta.json` files), then `tools/browser_check/heightmap_exact.mjs` and `browser_check.mjs --maps`.

After a change to Squad Ballistics' `weapons.json`, rewrite SquadCalc's generated entries in place with
`tools/direct_fire/gen_squadcalc_weapons.py <weapons.json> --update src/data/weapons.js`, then generate the
weapons SquadCalc lacks with
`tools/direct_fire/gen_squadcalc_weapons.py <weapons.json> <entries.js> <names.json> src/data/weapons.js`,
append them at the end of `WEAPONS`, add the names to every `public/locales/*/weapons.json`, and check both apps agree with
`python3 tools/direct_fire/compare.py ~/dev/Squad-Ballistics ~/agl/SquadCalc` (exit 0). It covers every weapon both apps have, the weapons aimed by elevation included (both arcs, every shell, time of flight, minimum distance and elevation limits), on the grid documented in its docstring.
