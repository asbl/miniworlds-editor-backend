/* Authenticated data stays on the backend. Only snapshot files go to the editor. */
(() => {
  "use strict";
  const frame = document.getElementById("editor-preview"), status = document.getElementById("preview-status");
  const origin = new URL(frame.src).origin;
  let loading = false;
  async function payload() {
    const response = await fetch(frame.dataset.endpoint, {credentials:"same-origin", cache:"no-store", redirect:"error"});
    if (!response.ok) throw new Error("Die Vorschau ist nicht verfügbar. Bitte erneut im Lehrerbereich anmelden.");
    const data = await response.json(), snapshot = data.snapshot || data, save = snapshot.save || {};
    const files = Object.create(null);
    for (const [name, content] of Object.entries(save.files || {})) files[name] = {base64:content};
    if (!("main.py" in files)) files["main.py"] = save.source || "";
    if (save.db && !("save.db" in files)) files["save.db"] = {base64:save.db};
    for (const asset of snapshot.media || []) {
      const name = asset.filename || asset.orig_name;
      if (name in files) continue;
      if (asset.content) files[name] = {base64:asset.content};
      else {
        const media = await fetch(`/api/public/${encodeURIComponent(snapshot.slug)}/media/${asset.asset_id}`, {credentials:"omit", cache:"no-store"});
        if (!media.ok) throw new Error("Eine Mediendatei fehlt.");
        const bytes = new Uint8Array(await media.arrayBuffer()); let binary = "";
        for (let i=0;i<bytes.length;i+=32768) binary += String.fromCharCode(...bytes.subarray(i,i+32768));
        files[name] = {base64:btoa(binary)};
      }
    }
    const task = snapshot.task;
    const section = document.getElementById("preview-task"); section.replaceChildren();
    if (task) {
      const heading = document.createElement("h3"); heading.textContent = task.title; section.append(heading);
      const description = document.createElement("p"); description.textContent = task.description; section.append(description);
      for (const item of task.items || []) {
        const label = document.createElement("p"); label.textContent = `${data.answers?.[item.id]?.checked ? "☑" : "☐"} ${item.prompt}`; section.append(label);
      }
    }
    return files;
  }
  window.addEventListener("message", async event => {
    if (event.source !== frame.contentWindow || event.origin !== origin || event.data?.app !== "miniworlds-editor") return;
    if (event.data.type === "loaded") { status.textContent = "Schreibgeschützte Vorschau · Änderungen am Original sind ausgeschlossen."; return; }
    if (event.data.type === "error") { status.textContent = "Die Vorschau konnte nicht geladen werden."; return; }
    if (event.data.type !== "ready" || loading) return;
    loading = true;
    if (event.data.apiVersion !== 1 || !event.data.capabilities?.includes("read-only-preview")) {
      status.textContent = "Der Editor muss aktualisiert werden, bevor diese Vorschau geöffnet werden kann.";
      return;
    }
    try {
      const files = await payload();
      frame.contentWindow.postMessage({app:"miniworlds-editor", type:"load", id:"preview", files, readOnly:true, mode:"miniworlds"}, origin);
    } catch (error) { status.textContent = error.message; }
  });
  setTimeout(() => { if (!loading) status.textContent = "Der Editor antwortet nicht. Bitte die Einbettungsfreigabe und die kompatible Editor-Version prüfen."; }, 20000);
})();
