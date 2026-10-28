# Deployment on tk104

Copies of the live files; after changing a live file, copy it here and commit.

| File here | Live location |
|---|---|
| `Caddyfile` | `~/apps/squadcalc/Caddyfile` (user unit `squadcalc.service`, port 9910, behind the panel Caddy `calc.<domain>`) |
| `squadcalc.service`, `squadcalc-relay.service` | `~/.config/systemd/user/` |

Site build: in `~/agl/SquadCalc` (branch `feature/direct-fire`, on top of `feature/ags17`) `cp .env.template .env && npm run build`,
then back up `~/apps/squadcalc/dist` and `rsync -a dist/ ~/apps/squadcalc/dist/` (no `--delete`: the
previous bundles stay so a cached page can still load them).

After a change to Squad Ballistics' `weapons.json`, regenerate the direct-fire weapons with
`tools/direct_fire/gen_squadcalc_weapons.py` and check both apps agree with
`python3 tools/direct_fire/compare.py ~/dev/Squad-Ballistics ~/agl/SquadCalc` (exit 0).
