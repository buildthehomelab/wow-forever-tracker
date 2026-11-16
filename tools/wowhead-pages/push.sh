#!/bin/sh
# Sends the Wowhead crawler's batch files (WHC.autoSave(), whc-batch-*.jsonl) to the tracker, then moves each sent file
# to a sent/ folder beside them. For a browser that cannot link a crawl to the tracker (docs/WOWHEAD-PAGES.md,
# "Batches from a computer"). The tracker must have a push key ([wowhead] push_token, FT_WOWHEAD_PUSH_TOKEN in Docker).
#
#   WHC_TRACKER=http://tracker.example:8090 WHC_PUSH_TOKEN=... sh tools/wowhead-pages/push.sh [folder] [--watch seconds]
#
# folder: where the browser saves downloads (default ~/Downloads). --watch: keep sending every so many seconds.
set -u
folder="${1:-$HOME/Downloads}"
every=0
[ "${2:-}" = "--watch" ] && every="${3:-300}"
: "${WHC_TRACKER:?set WHC_TRACKER to the tracker's address, for example http://tracker.example:8090}"
: "${WHC_PUSH_TOKEN:?set WHC_PUSH_TOKEN to the tracker's [wowhead] push_token}"
sent_dir="$folder/whc-sent"
mkdir -p "$sent_dir"

send_all() {
    for file in "$folder"/whc-batch-*.jsonl; do
        [ -f "$file" ] || continue
        answer=$(curl -sS -m 600 -X POST -H "X-Push-Token: $WHC_PUSH_TOKEN" -H 'Content-Type: application/x-ndjson' \
            --data-binary @"$file" "$WHC_TRACKER/api/wowhead-push") || { echo "$(date '+%H:%M:%S') $(basename "$file"): no answer, kept for the next run"; continue; }
        case "$answer" in
            *'"ok":true'*) mv "$file" "$sent_dir/" && echo "$(date '+%H:%M:%S') $(basename "$file"): $answer" ;;
            *) echo "$(date '+%H:%M:%S') $(basename "$file"): refused, kept: $answer" ;;
        esac
    done
}

send_all
while [ "$every" -gt 0 ]; do sleep "$every"; send_all; done
