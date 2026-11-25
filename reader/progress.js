// Reading progress: a bar and the last position on articles, read counts on the editions list.
// Each reading session also goes to the server log (/read/log) for the curation (curate.sh).
(() => {
	const base = new URL(".", document.currentScript.src);
	const STORE = "paper-reading";
	const DAY = 864e5;
	let data = {};
	try { data = JSON.parse(localStorage.getItem(STORE)) || {}; } catch {}
	data.items ||= {};
	delete data.key; // from the sync key, which the session log replaced
	data.device ||= crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2);
	const save = () => { try { localStorage.setItem(STORE, JSON.stringify(data)); } catch {} };
	for (const [id, it] of Object.entries(data.items)) if (Date.now() - (it.last || 0) > 60 * DAY) delete data.items[id];

	save();

	// One request per session: the server logs its address with the time, the device address and the browser.
	function send(it, page, seconds) {
		const q = new URLSearchParams({ e: page[1], a: page[2], t: it.title, s: seconds, p: it.progress, d: data.device });
		navigator.sendBeacon(new URL(`log?${q}`, base));
	}

	// The next page can take a moment to load, so mark the link that was tapped at once.
	addEventListener("click", (e) => {
		const a = e.target.closest?.("a[href]");
		if (a && a.origin === location.origin && !a.hash) a.classList.add("tapped");
	});
	// Going back restores the old page from memory, mark and all.
	addEventListener("pageshow", () => document.querySelectorAll(".tapped").forEach((a) => a.classList.remove("tapped")));

	// The article pages are XHTML, which ignores defer, so wait for the body.
	if (document.readyState === "loading") addEventListener("DOMContentLoaded", start);
	else start();

	function start() {
		const page = location.pathname.slice(base.pathname.length).match(/^([^/]+)\/(art_\d+)\.xhtml$/);
		if (page) {
			const it = (data.items[`${page[1]}/${page[2]}`] ||= {
				title: document.title.replace(/\s*\(\d+ min\)$/, ""), edition: page[1], seconds: 0, progress: 0, pos: 0,
			});
			const bar = document.createElement("div");
			bar.className = "progress";
			document.body.append(bar);

			const measure = () => {
				const end = document.documentElement.scrollHeight - innerHeight;
				const now = end > 0 ? Math.min(100, Math.round((scrollY / end) * 100)) : 100;
				bar.style.transform = `scaleX(${now / 100})`;
				it.progress = Math.max(it.progress, now);
				it.pos = end > 0 ? scrollY / end : 0;
				it.last = Date.now();
			};
			// Reopen at the last position, unless the article was read to the end.
			addEventListener("load", () => {
				if (it.pos > 0.02 && it.progress < 95) scrollTo(0, it.pos * (document.documentElement.scrollHeight - innerHeight));
				measure();
			});

			// Count only time when the page is visible and was used in the last minute, so an open tab does not count.
			let used = Date.now();
			let session = 0;
			let sent = -1;
			for (const e of ["scroll", "pointerdown", "keydown", "touchstart"]) addEventListener(e, () => { used = Date.now(); }, { passive: true });
			addEventListener("scroll", measure, { passive: true });
			setInterval(() => {
				if (document.hidden || Date.now() - used > 60e3) return;
				it.seconds += 5;
				session += 5;
				it.last = Date.now();
				save();
			}, 5e3);
			// Leaving the page or the app ends the session. A new session starts when the page shows again.
			const end = () => {
				save();
				if (session || it.progress !== sent) send(it, page, session);
				session = 0;
				sent = it.progress;
			};
			addEventListener("visibilitychange", () => { if (document.hidden) end(); });
			addEventListener("pagehide", end);
			return;
		}

		if (document.body.classList.contains("home")) {
			for (const li of document.querySelectorAll(".editions li[data-edition]")) {
				const done = Object.values(data.items).filter((it) => it.edition === li.dataset.edition && it.progress >= 90).length;
				const note = document.createElement("small");
				note.className = "read-count";
				note.textContent = `${done} of ${li.dataset.total} read`;
				li.querySelector("span").append(note);
			}
		}
	}
})();
