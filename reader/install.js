// Safari on iPhone has no install prompt for websites, so it gets the Share steps instead.
(() => {
	const base = new URL(".", document.currentScript.src);
	if ("serviceWorker" in navigator) navigator.serviceWorker.register(new URL("sw.js", base), { scope: base.pathname });

	const installed = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
	const KEY = "paper-install-dismissed";
	let dismissed = false;
	try { dismissed = Date.now() - Number(localStorage.getItem(KEY) || 0) < 7 * 864e5; } catch {}
	if (installed || dismissed) return;

	function banner(text, action) {
		const box = document.createElement("div");
		box.className = "install";
		box.setAttribute("role", "dialog");
		box.setAttribute("aria-label", "Install Morning Paper");
		const icon = document.createElement("img");
		icon.src = new URL("icon-192.png", base).href;
		icon.alt = "";
		const msg = document.createElement("p");
		msg.textContent = text;
		const close = document.createElement("button");
		close.type = "button";
		close.className = "install-close";
		close.setAttribute("aria-label", "Not now");
		close.textContent = "×";
		close.onclick = () => {
			try { localStorage.setItem(KEY, String(Date.now())); } catch {}
			box.remove();
		};
		box.append(icon, msg);
		if (action) box.append(action);
		box.append(close);
		document.body.append(box);
		return box;
	}

	const ios = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
	if (ios) {
		banner("Install Morning Paper: tap Share, then Add to Home Screen.");
		return;
	}
	addEventListener("beforeinstallprompt", (e) => {
		e.preventDefault();
		const btn = document.createElement("button");
		btn.type = "button";
		btn.className = "install-go";
		btn.textContent = "Install";
		const box = banner("Install Morning Paper as an app.", btn);
		btn.onclick = async () => {
			e.prompt();
			await e.userChoice;
			box.remove();
		};
	});
})();
