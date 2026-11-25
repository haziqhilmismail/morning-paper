#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a
export TZ="${PAPER_TZ:-UTC}"
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

# Links from the Telegram bot (bot.py) skip the age filter for 7 days after the share.
touch data/shared.tsv
awk -F"\t" -v c="$(date -d "7 days ago" +%F)" '$1 >= c {print $2}' data/shared.tsv > data/pinned.txt
cat data/pinned.txt >> data/queue.txt

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

# One file and one catalog entry per edition, so KOReader's OPDS sync sees each edition as new.
# KOReader sync expects the newest entry first.
day=$(date +%F)
no=$(cat data/edition.txt)
name="morning-paper-$day-no$no"
mkdir -p www/editions
cp data/read-later.epub "www/editions/.$name.epub"; mv "www/editions/.$name.epub" "www/editions/$name.epub"
cp data/cover.jpg "www/editions/.$name.jpg"; mv "www/editions/.$name.jpg" "www/editions/$name.jpg"
# Keep the 7 newest editions on the server; the reader keeps its own copies.
ls -1 www/editions/*.epub | sort -V -r | tail -n +8 | sed 's/\.epub$//' | while read -r old; do rm -f "$old.epub" "$old.jpg"; done
now=$(date -u +%FT%TZ)
{
  echo '<?xml version="1.0" encoding="UTF-8"?>'
  echo '<feed xmlns="http://www.w3.org/2005/Atom">'
  echo "  <id>urn:morning-paper</id><title>Morning Paper</title><updated>$now</updated>"
  echo '  <author><name>morning-paper</name></author>'
  echo '  <link rel="self" href="/opds.xml" type="application/atom+xml;profile=opds-catalog;kind=acquisition"/>'
  for f in $(ls -1 www/editions/*.epub | sort -V -r); do
    n=$(basename "$f" .epub); d=${n#morning-paper-}; d=${d%-no*}; e=${n##*-no}
    echo "  <entry><title>The Morning Paper $d No. $e</title><id>urn:morning-paper:$n</id><updated>$(date -u -r "$f" +%FT%TZ)</updated>"
    echo "    <author><name>Articles</name></author>"
    echo "    <link rel=\"http://opds-spec.org/image\" href=\"/editions/$n.jpg\" type=\"image/jpeg\"/>"
    echo "    <link rel=\"http://opds-spec.org/acquisition\" href=\"/editions/$n.epub\" type=\"application/epub+zip\"/></entry>"
  done
  echo '</feed>'
} > www/.opds.xml
mv www/.opds.xml www/opds.xml
echo "published $(date -Is)"
