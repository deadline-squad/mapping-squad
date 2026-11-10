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

SquadCalc has one entry per distinct firing solution. Squad Ballistics has an entry per view of a weapon (each zoom
level of a gunner's sight, the normal view next to an optic); a name whose generated entry equals another weapon's,
name apart, gets no entry: `--update` and the append list it in that weapon's `ballisticsViews`, and
`window.squadBallistics.selectWeapon` takes it and reports it back. The data decides, so a view with another launch
point or shell gets an entry. `compare.py` solves every view name against its entry and fails (`MISSING`) for an overlay
weapon that is neither an entry nor a view, so a `weapons.json` that SquadCalc was not synced to fails without a browser.
What the generator cannot do, by hand:

- a weapon Squad Ballistics renamed (its `RENAMED_WEAPONS`) goes into the generator's `RENAMED`, old name first, and its
  rows of `GAME_MOA` and `GAME_EXPLOSION` under the new name: `--update` then keeps the entry's place and `DF_` identifier and
  lists the old names as `legacyBallistics`; change its display name in `public/locales/*/weapons.json`. When the new name
  is a view of an entry, `--update` writes the pair into that entry's `legacyBallisticsViews` (old name -> view) and
  `selectWeapon` reports the view; `tools/browser_check/sb_bridge_races.mjs` tries every name of `RENAMED_WEAPONS` in a browser;
- a new name needs its row in `GAME_MOA` (the generator stops without it) and, for a round that explodes, in
  `GAME_EXPLOSION`, from the first Blueprint of the weapon's `sources.classes` in Squad Ballistics'
  `tests/data/game_weapons.json`; `gen_squadcalc_weapons.py --verify <resolved.json>` checks the explosions;
- SquadCalc's own "AGS-17" (the optic emplacement, which the generator skips) follows `weapons.json` by hand:
  `compare.py` reports its hold times and limits under "AGS-17 · emplacement · optic (RMB ×2.5)";
- a renamed or split weapon gets its group in `TARGETS` of `tools/game_ballistics/gamecheck.py` under the new name (a group
  is named after Squad Ballistics' entry of its first class); the ammunition labels of SquadCalc's
  `src/data/structureDamage.js` come from those names (`tools/volumetric/docs/structure-damage.md`, section 7).

Then rewrite the provenance tables, which list every weapon of both apps:
`python3 tools/game_ballistics/provenance.py --resolved ~/data/squad-weapons/resolved.json --dump ~/data/squad-weapons/dump --sb ~/dev/Squad-Ballistics --sc ~/agl/SquadCalc --write tools/volumetric/docs`;
the same command with `--check` exits 1 while a weapon is missing from them or a value differs from the game unexplained.

After a game patch (a new build of the dedicated server in `~/data/squad-server`), recheck what the calculator keeps by
hand against the new files with `tools/game_audit/game_audit.sh`: the four `extract-*` commands and `derive`, then
`git diff tools/game_audit/data` (what the patch changed: mount pitch ranges, sight offsets, landscapes, minimap
corners, FOB radius and protection zones per layer), `check` (which value of `maps.js` or `weapons.js` no longer equals
the game's, exit 1) and `api` (the layers the upstream API serves against the game's). The steps are in
`tools/game_audit/README.md`, "After a game patch"; the weapon checks above (`gamecheck.py`, `provenance.py`,
`compare.py`) follow, and the heightmaps are rebuilt with `tools/heightmaps/heightmaps.sh`.
