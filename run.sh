#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a
export TZ="${PAPER_TZ:-UTC}"
: "${PAPER_URL:?set PAPER_URL in .env}"
exec 9>data/.lock
flock -n 9 || { echo "already running"; exit 0; }

# The EPUB build comes from jstriblet/kobo-morning-paper (MIT), at the commit this was tested with.
if [ ! -d upstream ]; then
  rm -rf upstream.tmp
  git clone -q https://github.com/jstriblet/kobo-morning-paper upstream.tmp
  mv upstream.tmp upstream
fi
git -C upstream checkout -q eef60f736a827b4a49245299928b862e92552513

docker build -q -t morning-paper . >/dev/null

py() {
  docker run --rm --memory 1g --user "$(id -u):$(id -g)" \
    -v "$PWD/upstream:/app:ro" -v "$PWD/data:/data" -v "$PWD/config.json:/config.json:ro" \
    -e KOBO_PAPER_CONFIG=/config.json -e TZ morning-paper python "$1"
}

python3 feeds.py || echo "some feeds failed"
./curate.sh || echo "curation failed; building from the existing queue"

rc=0; py scripts/kobo-digest-build.py || rc=$?
# Upstream clears the queue only when Calibre is on. Every URL is now stored or logged as failed.
: > data/queue.txt
[ "$rc" -eq 0 ] || exit "$rc"
# Paywall previews and stubs extract to a few hundred words. Rebuild without them under the same edition number.
pruned=$(python3 prune_short.py data/articles)
if [ -n "$pruned" ]; then
  echo "$pruned"
  echo $(( $(cat data/edition.txt) - 1 )) > data/edition.txt
  py scripts/kobo-digest-build.py
fi

# One file per edition, so News Downloader sees each edition as new.
day=$(date +%F)
no=$(cat data/edition.txt)
name="morning-paper-$day-no$no"
mkdir -p www/editions
cp data/read-later.epub "www/editions/.$name.epub"; mv "www/editions/.$name.epub" "www/editions/$name.epub"
cp data/cover.jpg "www/editions/.$name.jpg"; mv "www/editions/.$name.jpg" "www/editions/$name.jpg"
# Keep the 7 newest editions on the server; the reader keeps its own copies.
ls -1 www/editions/*.epub | sort -V -r | tail -n +8 | sed 's/\.epub$//' | while read -r old; do rm -f "$old.epub" "$old.jpg"; done
# News Downloader saves a feed link that returns an EPUB as a book, and it needs full URLs.
{
  echo '<?xml version="1.0" encoding="UTF-8"?>'
  echo "<rss version=\"2.0\"><channel><title>Morning Paper</title><link>$PAPER_URL/read/</link><description>Morning Paper editions</description>"
  for f in $(ls -1 www/editions/*.epub | sort -V -r); do
    n=$(basename "$f" .epub); d=${n#morning-paper-}; d=${d%-no*}; e=${n##*-no}
    echo "<item><title>Morning Paper $d No. $e</title><link>$PAPER_URL/editions/$n.epub</link><guid>$n</guid><pubDate>$(date -u -R -r "$f")</pubDate></item>"
  done
  echo '</channel></rss>'
} > www/feeds/.paper.xml
mv www/feeds/.paper.xml www/feeds/paper.xml
python3 reader.py
echo "published $(date -Is)"
