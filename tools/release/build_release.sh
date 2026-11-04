#!/usr/bin/env bash
# Builds the release bundle of the ballistics work: source archives of SquadCalc, Squad Ballistics and the agl tools
# at the HEAD of one branch, the built SquadCalc page, the documents, a secret scan and MANIFEST.json.
#
#   build_release.sh [--out DIR] [--date YYYY-MM-DD] [--ref BRANCH] [--no-dist] [--deny-list FILE] [--force]
#   build_release.sh --scan-only DIR [--deny-list FILE]
#
# The bundle lands in DIR/<date>/ (default DIR ~/work/release). It is assembled in DIR/<date>.partial and renamed
# only when the secret scan found nothing; on a finding the partial directory is removed and the exit status is 2.
# Repositories (override with the environment): SQUADCALC_REPO (~/agl/SquadCalc), SB_REPO (~/dev/Squad-Ballistics),
# AGL_REPO (the repository this script is in). Details: tools/release/README.md.
set -euo pipefail

SQUADCALC_REPO=${SQUADCALC_REPO:-$HOME/agl/SquadCalc}
SB_REPO=${SB_REPO:-$HOME/dev/Squad-Ballistics}
AGL_REPO=${AGL_REPO:-$(git -C "$(dirname "$(readlink -f "$0")")" rev-parse --show-toplevel)}
OUT_ROOT=$HOME/work/release
DATE=$(date +%F)
REF=dev
BUILD_DIST=1
FORCE=0
SCAN_ONLY=""
DENY_LIST=""

# Secret rules: "name|PCRE". The scan prints rule name, file and line, never the matching text.
# A Steam ID is accepted only when it is plainly synthetic (six zeros in a row inside its digits), which is what the
# test fixtures of tools/hit_check use. Player nicknames and host names cannot be found by a pattern: pass them in a
# deny list (one fixed string per line, kept outside the repositories).
SECRET_RULES=(
    'private_key|-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----'
    'aes_key_hex_literal|0x[0-9A-Fa-f]{64}\b'
    'aes_key_hex_context|(?i)(aes|encryption)[_ -]?key[^\n]{0,40}?\b[0-9A-Fa-f]{64}\b'
    'aes_key_base64_context|(?i)aes[_ -]?key[^\n]{0,40}?[A-Za-z0-9+/]{43}='
    'github_token|\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})'
    'slack_token|\bxox[baprs]-[A-Za-z0-9-]{10,}'
    'aws_access_key|\bAKIA[0-9A-Z]{16}\b'
    'google_api_key|\bAIza[0-9A-Za-z_-]{35}\b'
    'telegram_bot_token|\b[0-9]{8,10}:AA[A-Za-z0-9_-]{33}\b'
    'jwt|\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.'
    'openai_style_key|\bsk-[A-Za-z0-9_-]{32,}'
    'password_assignment|(?i)(password|passwd|rcon_?pass(word)?|secret|token|api_?key|authorization)["'"'"']?\s*[:=]\s*["'"'"'][^"'"'"'\s$<{}]{8,}["'"'"']'
    'rcon_cfg_password|(?m)^\s*Password\s*=\s*\S{3,}'
    'steam_id|(?<![0-9])7656119(?![0-9]{0,9}0{6})[0-9]{10}(?![0-9])'
)
SECRET_FILE_NAMES=('.env' '*.pem' 'id_rsa*' 'id_ed25519*' '*.key' '*.p12' '*.pfx' '*.ppk' '.netrc' '*.kdbx')

die() { echo "build_release: $*" >&2; exit 1; }

# scan_tree DIR...: prints one line per finding and returns 1 when there is any.
scan_tree() {
    local findings=0 rule name pattern hit dir
    for dir in "$@"; do
        for rule in "${SECRET_RULES[@]}"; do
            name=${rule%%|*}
            pattern=${rule#*|}
            while IFS= read -r hit; do
                echo "SECRET-SCAN FAIL rule=$name at=${hit}"
                findings=$((findings + 1))
            done < <(grep -rInP --exclude-dir=node_modules --exclude-dir=.git -e "$pattern" "$dir" 2>/dev/null | cut -d: -f1,2 || true)
        done
        local name_args=() first=1 pat
        for pat in "${SECRET_FILE_NAMES[@]}"; do
            [ "$first" = 1 ] || name_args+=(-o)
            name_args+=(-name "$pat")
            first=0
        done
        while IFS= read -r hit; do
            echo "SECRET-SCAN FAIL rule=secret_file_name at=${hit}"
            findings=$((findings + 1))
        done < <(find "$dir" \( -name node_modules -o -name .git \) -prune -o -type f \( "${name_args[@]}" \) -print)
        if [ -n "$DENY_LIST" ]; then
            while IFS= read -r hit; do
                echo "SECRET-SCAN FAIL rule=deny_list at=${hit}"
                findings=$((findings + 1))
            done < <(grep -rInFi --exclude-dir=node_modules --exclude-dir=.git -f "$DENY_LIST" "$dir" 2>/dev/null | cut -d: -f1,2 || true)
        fi
    done
    [ "$findings" -eq 0 ] || { echo "SECRET-SCAN FAILED: $findings finding(s)"; return 1; }
    echo "SECRET-SCAN OK: ${#SECRET_RULES[@]} content rules, ${#SECRET_FILE_NAMES[@]} file name patterns${DENY_LIST:+, deny list} over $*"
}

while [ $# -gt 0 ]; do
    case $1 in
        --out) OUT_ROOT=$2; shift 2 ;;
        --date) DATE=$2; shift 2 ;;
        --ref) REF=$2; shift 2 ;;
        --no-dist) BUILD_DIST=0; shift ;;
        --deny-list) DENY_LIST=$(readlink -f "$2"); shift 2 ;;
        --scan-only) SCAN_ONLY=$2; shift 2 ;;
        --force) FORCE=1; shift ;;
        -h|--help) sed -n 2,12p "$0"; exit 0 ;;
        *) die "unknown argument $1" ;;
    esac
done

if [ -n "$SCAN_ONLY" ]; then
    [ -d "$SCAN_ONLY" ] || die "$SCAN_ONLY is not a directory"
    scan_tree "$SCAN_ONLY" && exit 0 || exit 2
fi

[ -z "$DENY_LIST" ] || [ -f "$DENY_LIST" ] || die "deny list $DENY_LIST not found"
for repo in "$SQUADCALC_REPO" "$SB_REPO" "$AGL_REPO"; do
    git -C "$repo" rev-parse --verify --quiet "$REF^{commit}" >/dev/null || die "$repo has no branch $REF"
done

BUNDLE=$OUT_ROOT/$DATE
PARTIAL=$BUNDLE.partial
if [ -e "$BUNDLE" ] && [ "$FORCE" != 1 ]; then die "$BUNDLE exists (use --force)"; fi
rm -rf "$PARTIAL"
mkdir -p "$PARTIAL/docs"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/src"

# 1. Source archives of the three repositories at the HEAD of $REF.
REPOS=("SquadCalc:$SQUADCALC_REPO" "Squad-Ballistics:$SB_REPO" "agl:$AGL_REPO")
for entry in "${REPOS[@]}"; do
    name=${entry%%:*}
    repo=${entry#*:}
    commit=$(git -C "$repo" rev-parse "$REF^{commit}")
    archive=$name-${commit:0:12}.tar.gz
    git -C "$repo" archive --format=tar --prefix="$name/" "$commit" | gzip -n -9 > "$PARTIAL/$archive"
    tar -xzf "$PARTIAL/$archive" -C "$WORK/src"
    echo "archived $name at ${commit:0:12} -> $archive"
done

# 2. The built SquadCalc page, from the archived sources (the working tree is not touched). node_modules and the
# wasm engine (public/engine, ignored by git) come from the local checkout; .env gets a placeholder API address.
DIST_NOTE="not built (--no-dist)"
if [ "$BUILD_DIST" = 1 ]; then
    [ -d "$SQUADCALC_REPO/node_modules" ] || die "$SQUADCALC_REPO/node_modules missing: run npm ci there first"
    mkdir -p "$WORK/build"
    cp -a "$WORK/src/SquadCalc" "$WORK/build/SquadCalc"
    cd "$WORK/build/SquadCalc"
    ln -s "$SQUADCALC_REPO/node_modules" node_modules
    printf 'API_URL=https://example.invalid/api\n' > .env
    DIST_NOTE="public/engine (wasm) taken from the local checkout; API_URL is the placeholder https://example.invalid/api"
    if [ -d "$SQUADCALC_REPO/public/engine" ]; then
        mkdir -p public && cp -a "$SQUADCALC_REPO/public/engine" public/engine
    else
        DIST_NOTE="public/engine (wasm) absent in the local checkout: the volume layer is not in this dist; API_URL is the placeholder https://example.invalid/api"
    fi
    nice -n 19 npm run build >"$WORK/build.log" 2>&1 || { tail -30 "$WORK/build.log" >&2; die "npm run build failed"; }
    find dist -type d \( -name heightmaps -o -name maptiles \) -prune -exec rm -rf {} +
    commit=$(git -C "$SQUADCALC_REPO" rev-parse "$REF^{commit}")
    stamp=$(git -C "$SQUADCALC_REPO" show -s --format=%ct "$commit")
    tar --sort=name --mtime="@$stamp" --owner=0 --group=0 --numeric-owner -cf - dist | gzip -n -9 > "$PARTIAL/SquadCalc-dist-${commit:0:12}.tar.gz"
    echo "built SquadCalc dist"
    cd "$OLDPWD"
fi

# 3. Documents: the READMEs, change logs, release notes, volumetric docs and evaluation tables, as plain files.
DOCS=(
    "SquadCalc:README.md" "SquadCalc:CHANGELOG.md" "SquadCalc:engine/README.md" "SquadCalc:engine/README.ru.md"
    "SquadCalc:engine/tests/last-run-precision.txt" "SquadCalc:engine/wgsl/test/last-run.txt"
    "SquadCalc:engine/wgsl/test/last-run-voxel.txt"
    "Squad-Ballistics:README.md" "Squad-Ballistics:RELEASE_NOTES.md" "Squad-Ballistics:RELEASING.md"
    "agl:tools/release/README.md" "agl:tools/release/README.ru.md"
    "agl:tools/volumetric/README.md" "agl:tools/heightmaps/README.md" "agl:tools/game_ballistics/README.md"
    "agl:tools/browser_check/README.md" "agl:tools/volumetric/data/primitives.json"
    "agl:tools/volumetric/data/structure_damage.json"
)
for doc in "${DOCS[@]}"; do
    name=${doc%%:*}
    path=${doc#*:}
    [ -f "$WORK/src/$name/$path" ] || { echo "note: $name/$path not in this commit, skipped"; continue; }
    mkdir -p "$PARTIAL/docs/$name/$(dirname "$path")"
    cp "$WORK/src/$name/$path" "$PARTIAL/docs/$name/$path"
done
for pattern in "Squad-Ballistics:docs/*.md" "agl:tools/volumetric/docs/*.md" "agl:docs/*.md"; do
    name=${pattern%%:*}
    for file in $WORK/src/$name/${pattern#*:}; do
        [ -f "$file" ] || continue
        relative=${file#"$WORK/src/$name/"}
        mkdir -p "$PARTIAL/docs/$name/$(dirname "$relative")"
        cp "$file" "$PARTIAL/docs/$name/$relative"
    done
done

# 4. Secret scan of everything that goes into the bundle: the archived sources, the built page, the document copies.
scan_dirs=("$WORK/src" "$PARTIAL/docs")
[ "$BUILD_DIST" = 1 ] && scan_dirs+=("$WORK/build/SquadCalc/dist")
if ! scan_tree "${scan_dirs[@]}" | sed "s#$WORK/##g; s#$PARTIAL/#bundle/#g"; then
    rm -rf "$PARTIAL"
    echo "build_release: bundle not written" >&2
    exit 2
fi

# 5. MANIFEST.json and SHA256SUMS.
export WORK PARTIAL REF DATE DIST_NOTE
export SQUADCALC_REPO SB_REPO AGL_REPO
export SCAN_RULE_COUNT=${#SECRET_RULES[@]}
python3 -I - <<'PY'
import hashlib, json, os, re, subprocess, sys
from datetime import datetime, timezone

work, partial, ref = os.environ["WORK"], os.environ["PARTIAL"], os.environ["REF"]


def git(repo, *args):
    return subprocess.check_output(["git", "-C", repo, *args], text=True).strip()


def read(name, path):
    with open(os.path.join(work, "src", name, path), encoding="utf-8") as handle:
        return handle.read()


def squadcalc_version():
    return json.loads(read("SquadCalc", "package.json"))["version"], "package.json"


def ballistics_version():
    code = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', read("Squad-Ballistics", "config.py")).group(1)
    notes = re.search(r"^## Squad Ballistics (\S+)", read("Squad-Ballistics", "RELEASE_NOTES.md"), re.M).group(1)
    if code != notes:
        sys.exit(f"Squad Ballistics: config.py says {code}, RELEASE_NOTES.md says {notes}")
    return code, "config.py APP_VERSION, RELEASE_NOTES.md"


repos = []
for name, env, version in (("SquadCalc", "SQUADCALC_REPO", squadcalc_version),
                           ("Squad-Ballistics", "SB_REPO", ballistics_version),
                           ("agl", "AGL_REPO", lambda: (None, "none: the tools repository is not versioned"))):
    repo = os.environ[env]
    commit = git(repo, "rev-parse", f"{ref}^{{commit}}")
    number, source = version()
    archive = next(f for f in os.listdir(partial) if f.startswith(f"{name}-{commit[:12]}.tar"))
    repos.append({
        "name": name, "branch": ref, "commit": commit,
        "commit_date": git(repo, "show", "-s", "--format=%cI", commit),
        "commit_subject": git(repo, "show", "-s", "--format=%s", commit),
        "version": number, "version_source": source, "archive": archive,
    })

artifacts = []
for folder, _, files in os.walk(partial):
    for filename in files:
        path = os.path.join(folder, filename)
        relative = os.path.relpath(path, partial)
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        artifacts.append({"path": relative, "bytes": os.path.getsize(path), "sha256": digest.hexdigest()})
artifacts.sort(key=lambda item: item["path"])

dist = next((f for f in os.listdir(partial) if f.startswith("SquadCalc-dist-")), None)
manifest = {
    "format": 1,
    "bundle_date": os.environ["DATE"],
    "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "repositories": repos,
    "dist": {"archive": dist, "built_from": "SquadCalc archive above", "note": os.environ["DIST_NOTE"],
             "data_excluded": ["heightmaps/", "maptiles/"]},
    "secret_scan": {"status": "passed", "content_rules": int(os.environ["SCAN_RULE_COUNT"]),
                    "scanned": ["source archives (extracted)", "docs/", "dist" if dist else None]},
    "artifacts": artifacts,
}
manifest["secret_scan"]["scanned"] = [item for item in manifest["secret_scan"]["scanned"] if item]
with open(os.path.join(partial, "MANIFEST.json"), "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, indent=2, ensure_ascii=False)
    handle.write("\n")
with open(os.path.join(partial, "SHA256SUMS"), "w", encoding="utf-8") as handle:
    for item in artifacts:
        handle.write(f"{item['sha256']}  {item['path']}\n")
    with open(os.path.join(partial, "MANIFEST.json"), "rb") as manifest_file:
        handle.write(f"{hashlib.sha256(manifest_file.read()).hexdigest()}  MANIFEST.json\n")
PY

rm -rf "$BUNDLE"
mv "$PARTIAL" "$BUNDLE"
echo "bundle written: $BUNDLE"
(cd "$BUNDLE" && sha256sum -c --quiet SHA256SUMS && echo "SHA256SUMS verified")
