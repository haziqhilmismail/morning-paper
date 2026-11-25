// Reading progress: a bar and the last position on articles, read counts on the editions list.
// With a sync key, each device also writes its log to /dav/web/<device>.json for the curation (curate.sh).
(() => {
	const base = new URL(".", document.currentScript.src);
	const STORE = "paper-reading";
	const DAY = 864e5;
	let data = {};
	try { data = JSON.parse(localStorage.getItem(STORE)) || {}; } catch {}
	data.items ||= {};
	data.device ||= crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2);
	const save = () => { try { localStorage.setItem(STORE, JSON.stringify(data)); } catch {} };

	// The sync key comes once in the link (#sync=...) and stays on this device only.
	// A sync code from the bot is "key:device name". A bare key keeps the name that the device had.
	function useCode(code) {
		const [key, ...name] = code.trim().split(":");
		data.key = key || undefined;
		if (name.length) data.name = name.join(":").trim() || data.name;
	}
	const fromLink = new URLSearchParams(location.hash.slice(1)).get("sync");
	if (fromLink) {
		useCode(fromLink);
		history.replaceState(null, "", location.pathname);
	}
	save();

	function push() {
		if (!data.key) return;
		for (const [id, it] of Object.entries(data.items)) if (Date.now() - it.last > 60 * DAY) delete data.items[id];
		fetch(new URL(`/dav/web/${data.device}.json`, location), {
			method: "PUT",
			keepalive: true,
			headers: { Authorization: "Basic " + btoa("sync:" + data.key), "Content-Type": "application/json" },
			body: JSON.stringify({ device: data.device, name: data.name, items: data.items }),
		}).catch(() => {});
	}

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
			for (const e of ["scroll", "pointerdown", "keydown", "touchstart"]) addEventListener(e, () => { used = Date.now(); }, { passive: true });
			addEventListener("scroll", measure, { passive: true });
			setInterval(() => {
				if (document.hidden || Date.now() - used > 60e3) return;
				it.seconds += 5;
				it.last = Date.now();
				save();
			}, 5e3);
			addEventListener("visibilitychange", () => { if (document.hidden) { save(); push(); } });
			addEventListener("pagehide", () => { save(); push(); });
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
			const link = document.createElement("a");
			link.href = "#";
			link.textContent = data.key ? "Sync on" : "Turn on sync";
			link.onclick = (e) => {
				e.preventDefault();
				const key = prompt("Paste the sync code. Send /synckey to the Telegram bot to get it. Without a code, your progress stays on this device only. Leave it empty to turn sync off.", data.key ? `${data.key}:${data.name || ""}` : "");
				if (key === null) return;
				useCode(key);
				save();
				push();
				link.textContent = data.key ? "Sync on" : "Turn on sync";
			};
			document.querySelector(".colophon")?.append(" · ", link);
		}
	}
})();
