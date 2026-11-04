#!/usr/bin/env bash
# Tests the secret scan of build_release.sh: a clean tree passes, every planted fake secret fails with its own rule,
# synthetic Steam IDs and a deny-list string behave as documented. The fake secrets are assembled at run time so that
# this file does not contain them. Usage: test_scan.sh
set -uo pipefail

SCRIPT=$(dirname "$(readlink -f "$0")")/build_release.sh
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
failures=0

expect() { # expect <description> <expected exit> <rule or ""> <args for --scan-only...>
    local description=$1 want=$2 rule=$3
    shift 3
    local output status
    output=$("$SCRIPT" "$@" 2>&1)
    status=$?
    if [ "$status" -ne "$want" ] || { [ -n "$rule" ] && ! grep -q "rule=$rule " <<<"$output"; }; then
        echo "FAIL  $description (exit $status, wanted $want)"
        echo "$output" | sed 's/^/        /'
        failures=$((failures + 1))
    else
        echo "ok    $description"
    fi
}

plant() { # plant <name> <content>: a fresh copy of the clean tree with one file added
    rm -rf "$TMP/tree" && mkdir -p "$TMP/tree/src"
    printf 'def add(a, b):\n    return a + b\n' > "$TMP/tree/src/clean.py"
    printf '%s\n' "$2" > "$TMP/tree/src/$1"
}

hex64=$(printf 'ab%.0s' {1..32})
plant clean.txt "plain text, version 1.2.3, sha256 of nothing"
expect "clean tree passes" 0 "" --scan-only "$TMP/tree"

plant k.pem "-----BEGIN RSA ""PRIVATE KEY-----"
expect "private key block" 2 private_key --scan-only "$TMP/tree"
plant a.js "const pakKey = '0x${hex64}';"
expect "AES key as 0x hex literal" 2 aes_key_hex_literal --scan-only "$TMP/tree"
plant a.json "{\"aes_key\": \"${hex64}\"}"
expect "AES key in hex next to the name" 2 aes_key_hex_context --scan-only "$TMP/tree"
plant a.cfg "AesKey = $(printf 'Zx%.0s' {1..21})Z="
expect "AES key in base64 next to the name" 2 aes_key_base64_context --scan-only "$TMP/tree"
plant t.sh "export X=gh""p_$(printf 'a%.0s' {1..36})"
expect "GitHub token" 2 github_token --scan-only "$TMP/tree"
plant t.sh "TOKEN=xo""xb-1234567890-abcdefghij"
expect "Slack token" 2 slack_token --scan-only "$TMP/tree"
plant t.sh "key AK""IA$(printf 'A%.0s' {1..16})"
expect "AWS access key" 2 aws_access_key --scan-only "$TMP/tree"
plant t.sh "bot 1234567890:A""A$(printf 'b%.0s' {1..33})"
expect "Telegram bot token" 2 telegram_bot_token --scan-only "$TMP/tree"
plant t.sh "sk""-$(printf 'q%.0s' {1..40})"
expect "sk- style API key" 2 openai_style_key --scan-only "$TMP/tree"
plant t.py "rcon_pass"'word = "hunter2hunter2"'
expect "password assignment" 2 password_assignment --scan-only "$TMP/tree"
plant Rcon.cfg 'Password=hunter2'
expect "Squad Rcon.cfg password line" 2 rcon_cfg_password --scan-only "$TMP/tree"
plant t.py "steam_id = 7656119""8123456789"
expect "real-looking Steam ID" 2 steam_id --scan-only "$TMP/tree"
plant t.py "steam_id = 7656119""8000000000"
expect "synthetic Steam ID (six zeros) is accepted" 0 "" --scan-only "$TMP/tree"
plant .env 'API_URL=https://example.invalid'
expect "a .env file" 2 secret_file_name --scan-only "$TMP/tree"
plant notes.md 'played with SomeNickname yesterday'
printf 'somenickname\n' > "$TMP/deny.txt"
expect "deny-list string (case-insensitive)" 2 deny_list --scan-only "$TMP/tree" --deny-list "$TMP/deny.txt"
expect "same file without the deny list" 0 "" --scan-only "$TMP/tree"
plant t.py 'password = "<your password here>"'
expect "placeholder password in angle brackets is accepted" 0 "" --scan-only "$TMP/tree"

echo "$failures failure(s)"
[ "$failures" -eq 0 ]
