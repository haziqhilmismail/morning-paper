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

instructions='You pick articles for my morning e-reader paper. Stdin has three parts: MY PROMPT (my own words, top priority), MY FEEDS (post titles from feeds I follow, which show my taste: find similar articles from other sources, never posts from these feeds), and MY E-READER BOOKS (books I read in the last 30 days, with minutes read: find articles on their subjects and authors). Split the articles by input: 60% MY PROMPT, 30% MY FEEDS, 10% MY E-READER BOOKS. If an input is empty, share its percentage among the others in proportion. Use web search to find about 10 articles from the last 7 days that match. Prefer long-form readable articles. No paywalls (also skip Substack posts for paid subscribers only), videos, PDFs or social media posts. Output only the article URLs, one per line, with no other text.'
# Same cutoff as the build's 7-day filter (max_age_days in the upstream config); older articles are built but then dropped.
cutoff=$(date -d "7 days ago" +%F)
instructions+=" Hard rule: open each article and check its publish date. Give it only if it was published on or after $cutoff. If you cannot find the date, skip the article. Give fewer articles rather than older ones."

# The filters after `claude` keep only https URLs with a hostname (no IPs, no localhost),
# because web pages can inject text into the answer.
{
  echo "MY PROMPT:"; grep -v '^#' my-prompt.txt || true
  echo; echo "MY FEEDS (feed names and recent post titles):"
  grep -oh '<title><!\[CDATA\[[^]]*' www/feeds/*.xml 2>/dev/null | sed 's/.*CDATA\[//' || true
  echo; echo "MY E-READER BOOKS (title | authors | minutes read, last 30 days):"
  # KOReader statistics plugin syncs this file over WebDAV (paper-dav).
  sqlite3 -readonly -separator " | " data/koreader/statistics.sqlite3 \
    "SELECT b.title, replace(b.authors, char(10), ', '), sum(p.duration) / 60 FROM page_stat_data p
     JOIN book b ON b.id = p.id_book WHERE p.start_time > strftime('%s', 'now', '-30 days')
     GROUP BY b.id ORDER BY sum(p.duration) DESC LIMIT 15" 2>/dev/null || true
} | "${claude[@]}" -p "$instructions" --model opus --tools "WebSearch,WebFetch" --allowedTools "WebSearch,WebFetch" \
      --permission-mode default --strict-mcp-config \
  | grep -oE 'https://[^[:space:]<>()"]+' | sed 's/[.,;]$//' \
  | grep -viE '^https://([^/]*@)?([0-9.]+|\[|localhost\.?)([:/]|$)' \
  | awk '!seen[$0]++ && n++ < 12' | tee -a data/queue.txt | grep -q .
