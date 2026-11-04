# Release bundle

`build_release.sh` assembles the directory that is uploaded with the thesis: the source of the three repositories at one
commit each, the built SquadCalc page, the documents, a secret scan and a manifest that ties them together. Russian
version: [`README.ru.md`](README.ru.md).

```sh
tools/release/build_release.sh                       # -> ~/work/release/<today>/ from the dev branches
tools/release/build_release.sh --out /tmp/rel --date 2026-11-04 --no-dist
tools/release/build_release.sh --scan-only <dir>     # only the secret scan, exit 0 clean / 2 findings
tools/release/test_scan.sh                           # the scan against planted fake secrets
```

| option | meaning |
|---|---|
| `--out DIR` | where bundles go (default `~/work/release`); the bundle is `DIR/<date>/` |
| `--date YYYY-MM-DD` | bundle name (default today) |
| `--ref BRANCH` | branch or commit-ish archived in all three repositories (default `dev`) |
| `--no-dist` | skip the webpack build (the manifest then has no dist) |
| `--deny-list FILE` | fixed strings (one per line, case-insensitive) that must not appear: player nicknames, host names. Keep the file outside the repositories |
| `--force` | replace an existing bundle of the same date |
| `SQUADCALC_REPO`, `SB_REPO`, `AGL_REPO` | checkout paths (defaults `~/agl/SquadCalc`, `~/dev/Squad-Ballistics`, the repository of the script) |

## What the bundle holds

| file | content |
|---|---|
| `SquadCalc-<commit>.tar.gz`, `Squad-Ballistics-<commit>.tar.gz`, `agl-<commit>.tar.gz` | `git archive` of the branch HEAD (committed files only; uncommitted work is not included); the 12-character commit is in the name |
| `SquadCalc-dist-<commit>.tar.gz` | `npm run build` of the archived SquadCalc sources, without any `heightmaps/` or `maptiles/` directory (those data are served separately and are not part of the thesis upload) |
| `docs/` | READMEs, `CHANGELOG.md`, `RELEASE_NOTES.md` (RU + EN in one file), `tools/volumetric/docs/*.md`, `docs/*.md` of the tools repository (the methods and results report), and the evaluation tables (`engine/tests/last-run-precision.txt`, `engine/wgsl/test/last-run*.txt`, `tools/volumetric/data/*.json`) |
| `MANIFEST.json` | per repository: branch, full commit hash, commit date and subject, version (SquadCalc `package.json`; Squad Ballistics `config.py` `APP_VERSION`, which must equal the first heading of `RELEASE_NOTES.md` or the build stops); the dist note; the scan status; size and SHA-256 of every file |
| `SHA256SUMS` | the same hashes (and the manifest's) for `sha256sum -c` |

The archives and the dist are reproducible byte for byte for the same commits: `git archive` plus `gzip -n`, the dist
tarball sorted, owner 0, time of the commit.

The dist is built in a scratch copy of the archived sources, so the checkout is not touched. Two things come from the
local checkout because git does not hold them: `node_modules` (run `npm ci` in SquadCalc first) and `public/engine`
(the wasm build of the Rust engine, `npm run build:engine`; without it the volume layer is missing from the dist and the
manifest says so). `API_URL` is the placeholder `https://example.invalid/api`: the real address is never read from a
`.env`.

## The secret scan

Runs over the extracted archives, the built page and the `docs/` copies, before anything is moved into place. A finding
prints `SECRET-SCAN FAIL rule=<name> at=<file>:<line>` (never the matching text), the partial bundle is deleted and the
exit status is 2. Rules (`SECRET_RULES` in the script): PEM private keys; AES keys (a `0x` + 64 hex literal, or 64 hex /
43 base64 characters next to "aes key" or "encryption key"); GitHub, Slack, Telegram, Google, AWS and `sk-` tokens; JWTs;
`password`, `passwd`, `rcon_password`, `secret`, `token`, `api_key`, `authorization` assigned a quoted literal of 8 or
more characters; a `Password=` line (Squad `Rcon.cfg`); Steam IDs (`7656119` + 10 digits); file names `.env`, `*.pem`,
`id_rsa*`, `id_ed25519*`, `*.key`, `*.p12`, `*.pfx`, `*.ppk`, `.netrc`, `*.kdbx`.

Limits, stated so that nobody over-trusts it:

* A Steam ID with six zeros in a row among its digits (`76561198000000000`) is accepted as synthetic; the test fixtures
  of `tools/hit_check` use such IDs. A real ID essentially never has that.
* Player nicknames and host names are not patterns. Use `--deny-list`.
* Only the committed HEAD is scanned, not the git history, and binary files are skipped. A secret removed from HEAD but
  still in an old commit is not in the archives, but is in the repositories: do not publish the repositories themselves.
* Placeholders in angle brackets, shell variables (`$X`) and braces are not flagged by the password rule.

`test_scan.sh` plants one fake secret per rule in a temporary tree (assembled at run time, so the test file contains
none), requires exit 2 with the right rule, and requires exit 0 on a clean tree, on the synthetic Steam ID and on a
placeholder.

## Before uploading

1. Merge the work into `dev` in all three repositories; the bundle is built from `dev` HEAD.
2. Run the test suites of the repositories (SquadCalc `npm test`, Squad Ballistics `pytest`); the bundle does not run them.
3. Run the build, read the last lines (`SECRET-SCAN OK`, `SHA256SUMS verified`) and copy `MANIFEST.json` into the
   submission text. The repositories are private and public release is allowed only from 2027.
