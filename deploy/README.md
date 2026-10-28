# Deployment on tk104

Copies of the live files; after changing a live file, copy it here and commit.

| File here | Live location |
|---|---|
| `Caddyfile` | `~/apps/squadcalc/Caddyfile` (user unit `squadcalc.service`, port 9910, behind the panel Caddy `calc.<domain>`) |
| `squadcalc.service`, `squadcalc-relay.service` | `~/.config/systemd/user/` |

Site build: in `~/agl/SquadCalc` (branch `feature/ags17`) `cp .env.template .env && npm run build`,
then back up `~/apps/squadcalc/dist` and `rsync -a dist/ ~/apps/squadcalc/dist/` (no `--delete`: the
previous bundles stay so a cached page can still load them).
