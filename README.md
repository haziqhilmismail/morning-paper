<p align="center"><img src="logo.svg" width="96" alt="Morning Paper logo"></p>

# Morning Paper

Morning Paper makes one EPUB newspaper each morning from articles that Claude picks for you. Your e-reader gets the paper through KOReader, with no cable and no cloud account.

![The front page of a sample edition](docs/front-page.jpg)

Based on [jstriblet/kobo-morning-paper](https://github.com/jstriblet/kobo-morning-paper) (MIT). That project makes the EPUB. This project adds the curation, the OPDS catalog for KOReader, the feed slots and the Telegram bot.

## How a daily run works

`run.sh` runs once a day at 05:15 server time from `morning-paper.timer`. The `/now` command of the Telegram bot also starts it.

```mermaid
flowchart TD
	timer["morning-paper.timer<br/>05:15 server time"] --> run
	bot["bot.py (Telegram)"] -- "/now" --> run
	bot -- "links you send" --> shared["www/feeds/shared.xml<br/>the Shared feed"]

	subgraph run["run.sh"]
		direction TB
		feedspy["feeds.py<br/>feeds.txt to www/feeds/1.xml ... 6.xml"]
		curate["curate.sh<br/>Claude CLI with web search"]
		queue["data/queue.txt<br/>about 10 URLs"]
		build["Upstream build in Docker<br/>upstream/ mounted read-only"]
		prune["prune_short.py<br/>drops articles under 400 words"]
		publish["www/editions/*.epub, www/opds.xml<br/>reader.py: www/read/"]
		feedspy --> curate --> queue --> build --> prune --> publish
	end

	prompt["my-prompt.txt<br/>your topics: 60%"] --> curate
	stats["data/koreader/statistics.sqlite3<br/>posts and books you read: 40%"] --> curate
	shared --> web

	publish --> web["paper-web (Caddy)<br/>password"]
	web --> koreader["KOReader<br/>OPDS sync and News Downloader"]
	web --> phone["Phone browser<br/>/read/"]
	koreader -- "reading statistics over WebDAV, /dav" --> web
	web --> dav["paper-dav (rclone WebDAV)"] --> stats
```

Each run does these steps:

1. `feeds.py` downloads the feeds in `feeds.txt` to `www/feeds/1.xml` to `www/feeds/6.xml`. It removes Substack posts that are only previews for paid subscribers.
2. `curate.sh` sends two inputs to the Claude CLI: your topics in `my-prompt.txt` (60%), and the posts and books that you read in KOReader in the last 30 days (40%). Feed posts that you do not read have no effect. Claude uses web search and returns about 10 article URLs from the last 7 days.
3. Claude returns the URLs to `data/queue.txt`.
4. The upstream build fetches each URL, extracts the text, and makes an EPUB with a front page. Articles that are older than 7 days are not included.
5. `prune_short.py` removes articles with fewer than 400 words, because those are usually paywall previews. If it removes one, the build runs again.
6. `run.sh` copies the EPUB to `www/editions/` and writes `www/opds.xml`. The catalog lists the 7 newest editions, newest first.
7. `reader.py` turns each edition into web pages in `www/read/`, for a phone browser.

The `paper-web` container serves `www/` behind a password. KOReader reads the OPDS catalog and downloads each new edition.

### What is this project and what is upstream

`run.sh` clones [jstriblet/kobo-morning-paper](https://github.com/jstriblet/kobo-morning-paper) into `upstream/` at a fixed commit. The upstream code does not change here. It runs in a Docker container that has `upstream/` as a read-only folder.

```mermaid
flowchart LR
	subgraph here["This repository"]
		scripts["run.sh, curate.sh, feeds.py<br/>prune_short.py, reader.py, bot.py"]
		docker["Dockerfile: the Python image<br/>compose.yml: paper-web, paper-dav"]
	end
	subgraph up["upstream/ (MIT)"]
		builder["scripts/kobo-digest-build.py<br/>fetch, extract, EPUB, cover"]
	end
	scripts -- "docker run, /app read-only" --> builder
	builder -- "data/read-later.epub, data/cover.jpg" --> scripts
```

## What you need

- A Linux server with Docker, Docker Compose, `git`, `python3` and `flock`. `sqlite3` is optional. It reads your KOReader reading statistics.
- An e-reader with [KOReader](https://koreader.rocks): a Kindle, a Kobo or another reader that KOReader supports.
- The [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) and a Claude subscription, for the curation. Without it, the paper is empty.
- A way for the reader to reach the server, for example a reverse proxy with HTTPS or a Tailscale network. `paper-web` listens only on `127.0.0.1:8092`.
- Optional: a Telegram bot, to send article links from your phone to the e-reader.

## Set up the server

1. Clone the repository to `~/morning-paper`. The systemd units use this path.

	```sh
	git clone https://github.com/haziqhilmismail/morning-paper ~/morning-paper
	cd ~/morning-paper
	```

2. Make your own copies of the settings files.

	```sh
	for f in .env feeds.txt my-prompt.txt config.json Caddyfile; do cp "$f.example" "$f"; done
	chmod 600 .env
	```

3. Edit `.env`. Set `PAPER_TZ` to your time zone. Set `CLAUDE_CODE_OAUTH_TOKEN` to a token from `claude setup-token`.
4. Write your topics in `my-prompt.txt`. Put up to 6 feeds in `feeds.txt`.
5. Make a password hash for the web server, and paste it into `Caddyfile` in place of `<paste-the-hash-here>`.

	```sh
	docker run --rm caddy:2.11.6-alpine caddy hash-password --plaintext 'your-password'
	```

6. Optional: download the fonts for the masthead. Without them, the build uses a plain font.

	```sh
	mkdir -p data/fonts && cd data/fonts
	curl -LO https://github.com/google/fonts/raw/main/ofl/unifrakturmaguntia/UnifrakturMaguntia-Book.ttf
	curl -LO https://github.com/google/fonts/raw/main/ofl/ptserif/PT_Serif-Web-Bold.ttf
	curl -LO https://github.com/google/fonts/raw/main/ofl/ptserif/PT_Serif-Web-Regular.ttf
	cd ../..
	```

7. Start the web server and the WebDAV server.

	```sh
	docker compose up -d
	```

8. Make the first paper. The first run clones the upstream build into `upstream/` and builds the `morning-paper` Docker image. It takes about 5 to 10 minutes.

	```sh
	./run.sh
	```

	The last line is `published <date and time>`.

9. Install the daily timer.

	```sh
	mkdir -p ~/.config/systemd/user
	cp morning-paper.service morning-paper.timer ~/.config/systemd/user/
	systemctl --user daemon-reload
	systemctl --user enable --now morning-paper.timer
	sudo loginctl enable-linger "$USER"
	```

	`enable-linger` keeps the timer active when you are not logged in. The timer runs at 05:15 server time. If your server uses another time zone than `PAPER_TZ`, add the `PAPER_TZ` value to the `OnCalendar` line, for example `*-*-* 05:15:00 Asia/Kuala_Lumpur`.

## Set up KOReader

Do these steps on the e-reader. Use the user name and the password from your `Caddyfile`. In the examples, `https://paper.example.com` is the address where your reader reaches `paper-web`.

1. Add the catalog. Open the top menu, then the search icon, then **OPDS catalog**. Tap **+**, and enter `https://paper.example.com/opds.xml` with your user name and password.
2. Turn on sync. Long-press the catalog, tap **Edit**, and tick **Sync catalog**. Set a sync folder, for example `Morning Paper`. If you do not see **Sync catalog**, update KOReader. OPDS sync came in 2025.
3. Each morning, open the catalog menu and tap **Sync**. KOReader downloads each edition that it does not have yet.

### Optional: read your feeds with News Downloader

1. Copy `koreader/feed_config.lua.example` to `koreader/feed_config.lua`. Replace the address, the user name and the password.
2. Put the file in the News Downloader download folder on the reader. The default folder is `koreader/news/`. You can use a USB cable, or KOReader **Cloud storage** (step 1 of the next section). KOReader shows only book files, so give the file a `.txt` name on the server, download it, and rename it to `feed_config.lua`. To see the renamed file, turn on **Show unsupported files** in the file browser settings.
3. Open ☰, then **News downloader**, then **Sync news feeds**.

The file lists 6 fixed slot URLs, the Shared feed and the Morning Paper feed, so you do not copy it again when you change `feeds.txt`. The Morning Paper feed (`www/feeds/paper.xml`) links each edition's EPUB, so one **Sync news feeds** also gets the paper, and you do not need OPDS sync. `run.sh` writes this feed only when `PAPER_URL` is set in `.env`. Each feed gets a folder with the feed's own title.

### Optional: send your reading statistics

The curation uses the posts and books that you read as 40% of the picks. Without these statistics, it uses only `my-prompt.txt`.

1. Open ☰, then **Cloud storage**, then **Add new cloud storage**, then **WebDAV**. Enter `https://paper.example.com/dav` with your user name and password.
2. Open **Tools**, then **Reading statistics**, then **Settings**, then **Cloud sync**. Select the WebDAV storage and its top folder.
3. Tap **Synchronize now**. The server stores the file at `data/koreader/statistics.sqlite3`.

## Read the paper on your phone

Open `https://paper.example.com/read/` in the phone browser. The reader has no password, because an iPhone home-screen app asks for it again on each start. Anyone with the address can read it, but search engines get a `noindex` header. The EPUB files, the catalog, the feeds and WebDAV still need the password. To keep the reader private, remove the `@private` matcher from `basic_auth` in the `Caddyfile`. The page lists the editions, newest first. Tap an edition to open its front page, and tap a story to read it.

A banner asks you to install the reader as an app. On an iPhone, it tells you to tap **Share** and then **Add to Home Screen**, because Safari has no install prompt for websites. In Chrome and Edge, it shows an **Install** button. If you close the banner, it stays hidden for 7 days. Pages that you opened once also open without a connection.

## Check that it works

1. Run `systemctl --user list-timers morning-paper.timer`. The **NEXT** column shows the next run.
2. Run `curl -u reader:your-password http://127.0.0.1:8092/opds.xml`. The output lists one `<entry>` for each edition.
3. Read `data/build.log`. Each article has a `stored:` line. An article that is too old has an `excluded stale` line.
4. If a run fails, read its output with `journalctl --user -u morning-paper.service`.

## Use the Telegram bot

The bot adds the links that you send it to the Shared feed, `www/feeds/shared.xml`. The feed holds the 20 newest links. The bot fetches each article on the server and puts its text in the feed. Entry 7 of `feed_config.lua` reads it, and News Downloader saves each article in a `Shared` folder. The e-reader opens no other site. The links do not go into the paper. The command `/now` starts a new build of the paper.

1. Make a bot with [@BotFather](https://t.me/BotFather), and put its token in `PAPER_BOT_TOKEN` in `.env`.
2. Put your own chat id in `PAPER_BOT_CHAT_ID`. The bot ignores messages from other chats.
3. Install and start the service.

	```sh
	cp paper-bot.service ~/.config/systemd/user/
	systemctl --user daemon-reload
	systemctl --user enable --now paper-bot.service
	```

## Configuration reference

### Variables in `.env`

| Variable | Used by | Meaning |
|---|---|---|
| `PAPER_URL` | `run.sh` | Optional. The address where the e-reader reaches `paper-web`, for example `https://paper.example.com`. If it is set, `run.sh` writes the Morning Paper feed for News Downloader. |
| `PAPER_TZ` | `run.sh`, `curate.sh` | IANA time zone for the masthead date, the 7-day window and the curation cutoff. The default is `UTC`. |
| `READING_SINCE` | `curate.sh` | Optional. The curation counts KOReader reading only from this date (`YYYY-MM-DD`). Use it when the reader had an earlier owner. |
| `CLAUDE_CODE_OAUTH_TOKEN` | `curate.sh` | The token for the Claude CLI. |
| `CLAUDE_CONTAINER` | `curate.sh` | The name of a running container that has the Claude CLI. If it is empty, `curate.sh` runs `claude` on the host. |
| `PAPER_BOT_TOKEN` | `bot.py` | The Telegram bot token. |
| `PAPER_BOT_CHAT_ID` | `bot.py` | The only chat that the bot answers. |

### Files

| File | Tracked | Meaning |
|---|---|---|
| `my-prompt.txt` | No, copy the `.example` | Your topics in your own words. Lines that start with `#` are ignored. Write a number of articles after a topic to set its share. |
| `feeds.txt` | No, copy the `.example` | Up to 6 feeds, one `name url` line each. Line N goes to `www/feeds/N.xml`. |
| `config.json` | No, copy the `.example` | Settings for the upstream build. See the [upstream README](https://github.com/jstriblet/kobo-morning-paper#readme). |
| `Caddyfile` | No, copy the `.example` | The web server: the password hash, the WebDAV route and the static files. |
| `koreader/feed_config.lua` | No, copy the `.example` | The News Downloader feed list for the reader. |
| `compose.yml` | Yes | The `paper-web` (Caddy) and `paper-dav` (rclone WebDAV) containers. `paper-dav` runs as user `1000:1000`. Change it if your user has another id. |
| `morning-paper.timer` | Yes | The daily run at 05:15 server time. To use another time zone, add it to `OnCalendar`. |

### Folders that the scripts make

| Folder | Content |
|---|---|
| `upstream/` | A clone of `jstriblet/kobo-morning-paper` at the tested commit. `run.sh` clones it when it is missing. |
| `data/` | The queue, the stored articles, `build.log`, the edition number, and the KOReader statistics in `data/koreader/`. |
| `www/` | The files that `paper-web` serves: `opds.xml`, `editions/`, `feeds/` and the phone reader in `read/`. |

## License

MIT. See [LICENSE](LICENSE). The EPUB build comes from [jstriblet/kobo-morning-paper](https://github.com/jstriblet/kobo-morning-paper), also under the MIT license.
