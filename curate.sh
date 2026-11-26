#!/bin/bash
# run.sh calls this script with .env and TZ already loaded.
set -euo pipefail
cd "$(dirname "$0")"
# An empty token would override a `claude login` session on the host.
[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] || unset CLAUDE_CODE_OAUTH_TOKEN
# systemd's PATH has no ~/.local/bin, where the Claude installer puts `claude`.
export PATH="$HOME/.local/bin:$PATH"
# timeout runs inside the container, so a hung claude is killed there and not only the docker CLI.
claude=(timeout 20m claude)
if [ -n "${CLAUDE_CONTAINER:-}" ]; then claude=(docker exec -i -e CLAUDE_CODE_OAUTH_TOKEN "$CLAUDE_CONTAINER" timeout 20m claude); fi

instructions='You pick articles for my morning e-reader paper. Stdin has two parts: MY PROMPT (my own words, top priority) and MY READING (posts and books I read on my e-reader in the last 30 days, with minutes read, which show my taste: find similar articles from other sources on the same subjects, never the same posts). Split the articles by input: 60% MY PROMPT, 40% MY READING. If MY READING is empty, use MY PROMPT for all articles. Use web search to find about 10 articles from the last 7 days that match. Prefer long-form readable articles. No paywalls (also skip Substack posts for paid subscribers only), videos, PDFs or social media posts. Output one line per article and no other text: the URL, a space, and the section name. The section name is one or two words for the MY PROMPT topic line that the article matches, for example Data, Ideas, Malaysia or Urbanism (use the same name for a topic each day), or Your reading for a MY READING article.'
# Same cutoff as the build's 7-day filter (max_age_days in the upstream config); older articles are built but then dropped.
cutoff=$(date -d "7 days ago" +%F)
instructions+=" Hard rule: open each article and check its publish date. Give it only if it was published on or after $cutoff. If you cannot find the date, skip the article. Give fewer articles rather than older ones."

# The filters after `claude` keep only https URLs with a hostname (no IPs, no localhost),
# because web pages can inject text into the answer.
{
  echo "MY PROMPT:"; grep -v '^#' my-prompt.txt || true
  echo; echo "MY READING (title | authors | minutes read, last 30 days):"
  # KOReader statistics plugin syncs this file over WebDAV (paper-dav). The paper itself is left out, so it does not pick articles like its own.
  since=${READING_SINCE:-1970-01-01}
  [[ $since =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || since=1970-01-01
  sqlite3 -readonly -separator " | " data/koreader/statistics.sqlite3 \
    "SELECT b.title, replace(b.authors, char(10), ', '), sum(p.duration) / 60 FROM page_stat_data p
     JOIN book b ON b.id = p.id_book WHERE p.start_time > max(strftime('%s', 'now', '-30 days'), strftime('%s', '$since', 'utc'))
       AND b.title NOT IN ('KOReader Quickstart Guide', 'feed_config', 'Morning Paper', 'Read Later')
     GROUP BY b.id HAVING sum(p.duration) >= 60 ORDER BY sum(p.duration) DESC LIMIT 15" 2>/dev/null || true
  # Morning Paper articles read in the phone reader: progress.js logs each session to data/logs/reading.log*.
  python3 - "$since" data/logs/reading*.log <<'PY' 2>/dev/null || true
import json, sys, time
from datetime import datetime
from urllib.parse import parse_qs, urlsplit
cutoff = max(time.time() - 30 * 86400, datetime.fromisoformat(sys.argv[1]).timestamp())
seen = {}
for path in sys.argv[2:]:
    try:
        lines = open(path).readlines()
    except OSError:
        continue  # no log yet (the glob stays unexpanded)
    for line in lines:
        try:
            entry = json.loads(line)
            q = {k: v[0] for k, v in parse_qs(urlsplit(entry["request"]["uri"]).query).items()}
            if entry["ts"] < cutoff:
                continue
            key = (q["e"], q["a"])
            title = " ".join(q.get("t", "")[:200].split())
            old = seen.get(key, (title, 0, 0))
            seen[key] = (title, old[1] + int(q.get("s", 0)), max(old[2], int(q.get("p", 0))))
        except (ValueError, KeyError, TypeError):
            continue
for title, sec, prog in sorted(seen.values(), key=lambda v: -v[1])[:15]:
    if sec >= 60 and prog > 10:  # a minute of reading and past the first screens
        print(f"{title} | Morning Paper web reader, {prog}% read | {sec // 60}")
PY
} | "${claude[@]}" -p "$instructions" --model opus --tools "WebSearch,WebFetch" --allowedTools "WebSearch,WebFetch" \
      --permission-mode default --strict-mcp-config \
  | tee data/curation.txt \
  | grep -oE 'https://[^[:space:]<>()"]+' | sed 's/[.,;]$//' \
  | grep -viE '^https://([^/]*@)?([0-9.]+|\[|localhost\.?)([:/]|$)' \
  | awk '!seen[$0]++ && n++ < 12' | tee -a data/queue.txt | grep -q .
# Each answer line is "URL Section". frontpage.py groups the front page by these sections.
awk 'match($0, /https:\/\/[^[:space:]<>()"]+/) {
  u = substr($0, RSTART, RLENGTH); t = substr($0, RSTART + RLENGTH); sub(/[.,;]$/, "", u)
  gsub(/^[[:space:]|:-]+|[[:space:]]+$/, "", t); if (t != "") print u "\t" t
}' data/curation.txt >> data/topics.tsv
