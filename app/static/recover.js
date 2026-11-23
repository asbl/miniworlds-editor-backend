/* One-time export of old tab-local drafts; never exports tokens or free-text answers. */
(() => {
  const host = document.getElementById("legacy-drafts");
  function download(name, data, type) {
    const url = URL.createObjectURL(new Blob([data], {type}));
    const link = document.createElement("a"); link.href = url; link.download = name; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  for (const key of Object.keys(sessionStorage).filter(key => /^miniworlds-draft:\d+$/.test(key))) {
    try {
      const data = JSON.parse(sessionStorage.getItem(key));
      if (typeof data.source !== "string") continue;
      const section = document.createElement("section"), title = document.createElement("h3");
      title.textContent = "Projekt " + key.split(":")[1]; section.append(title);
      const button = document.createElement("button"); button.textContent = "Python-Entwurf herunterladen";
      button.onclick = () => download("main.py", data.source, "text/x-python"); section.append(button);
      if (typeof data.db === "string" && data.db) {
        const db = Uint8Array.from(atob(data.db), c => c.charCodeAt(0));
        const save = document.createElement("button"); save.textContent = "Programmdaten herunterladen";
        save.onclick = () => download("save.db", db, "application/octet-stream"); section.append(save);
      }
      host.append(section);
    } catch (_) { /* damaged drafts stay untouched */ }
  }
  if (!host.children.length) host.textContent = "In diesem Tab wurden keine bisherigen Entwürfe gefunden.";
})();
