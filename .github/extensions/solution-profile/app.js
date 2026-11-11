const $ = id => document.getElementById(id);
// The capability stays in memory/session storage, never in requests or referrers as a URL.
const token = location.hash.slice(1) || sessionStorage.getItem("profile-token");
if (location.hash) {
    sessionStorage.setItem("profile-token", token);
    history.replaceState(null, "", "/");
}
let state;
let busy = false;
let yamlChanged = false;
let reviewedHash = null;
const openGroups = new Set();

function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
}

async function request(route, data) {
    const response = await fetch(`/api/${route}`, {
        method: data ? "POST" : "GET",
        headers: { Authorization: `Bearer ${token}`, ...(data ? { "Content-Type": "application/json" } : {}) },
        body: data ? JSON.stringify(data) : undefined,
        signal: AbortSignal.timeout(route === "save" ? 45000 : 15000),
    });
    const result = await response.json();
    if (!response.ok) throw Object.assign(new Error(result.message || "Request failed."), { state: result.state });
    return result;
}

function error(message) {
    $("error").textContent = message;
    $("error").hidden = false;
}

function saveState() {
    const needsGeneration = ["failed", "pending"].includes(state?.generation?.status);
    const canSave = state && (state.dirty || needsGeneration) && !state.errors.length && !busy && !yamlChanged &&
        reviewedHash === state.hash;
    $("save").disabled = !canSave;
    $("save-hint").textContent = yamlChanged ? "Apply your YAML edits to the draft first."
        : state?.errors.length ? "Resolve configuration errors before saving."
        : !state?.dirty && !needsGeneration ? "Profile matches the saved snapshot."
        : reviewedHash !== state.hash ? "Review the exact diff and approve it to enable Save."
        : "Save writes the profile and regenerates AGENTS.md using the bundled generator.";
}

async function act(operation, data = {}) {
    if (busy) return;
    if (yamlChanged && operation === "edit") {
        error("Apply your YAML edits to the draft before changing structured fields.");
        return false;
    }
    busy = true;
    if (operation !== "save") { reviewedHash = null; $("reviewed").checked = false; }
    $("error").hidden = true;
    document.querySelectorAll("button, input, textarea, select").forEach(n => n.disabled = true);
    saveState();
    try {
        const next = await request(operation, { version: state.version, ...data });
        if (next.hash !== state.hash) reviewedHash = null;
        state = next;
        yamlChanged = false;
        render();
        $("message").textContent = operation === "save"
            ? `Profile saved and AGENTS.md regenerated.${state.backup ? ` Previous profile retained at ${state.backup}.` : ""}${state.generation?.backup ? ` Previous AGENTS.md retained at ${state.generation.backup}.` : ""}`
            : operation === "reload" ? "Draft discarded; loaded current disk content."
            : "Session draft updated. Profile file is unchanged.";
        return true;
    } catch (e) {
        if (e.state) { state = e.state; yamlChanged = false; render(); }
        $("message").textContent = "";
        error(e.message);
        return false;
    }
    finally {
        busy = false;
        document.querySelectorAll("button, input, textarea, select").forEach(n => n.disabled = n.dataset.missing === "true");
        saveState();
    }
}

function switchView(view) {
    for (const name of ["form", "yaml", "changes"]) $(`${name}-view`).hidden = name !== view;
    document.querySelectorAll("[data-view]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.view === view)));
}

function fieldControl(field) {
    const id = `field-${encodeURIComponent(field.key)}`;
    const wrapper = element("div", undefined, "field");
    const problems = state.errors.filter(e => e.path === field.key);
    if (problems.length) wrapper.classList.add("invalid");
    const label = element("label", field.key.split(".").at(-1).replaceAll("_", " ") + (field.required ? " *" : ""));
    label.htmlFor = id;
    wrapper.append(label, element("span", field.key, "path"), element("span", field.origin, "badge"));
    let control;
    if (field.choices || field.kind === "boolean") {
        control = document.createElement("select");
        const choices = field.choices ? ["", ...field.choices] : ["true", "false"];
        for (const value of choices) {
            const option = element("option", value || "Choose a value");
            option.value = value;
            control.append(option);
        }
        control.value = String(field.value ?? "");
    } else if (field.kind === "yaml" || (typeof field.value === "string" && field.value.includes("\n"))) {
        control = document.createElement("textarea");
        control.rows = Math.min(10, Math.max(3, field.value.split("\n").length));
        control.spellcheck = false;
        control.value = field.value;
    } else {
        control = document.createElement("input");
        control.type = field.kind === "number" ? "number" : "text";
        control.value = field.kind === "nullable" ? JSON.stringify(field.value) : field.value ?? "";
    }
    control.id = id;
    control.disabled = field.kind === "missing";
    control.dataset.missing = String(field.kind === "missing");
    control.setAttribute("aria-describedby", `${id}-hint`);
    if (problems.length) control.setAttribute("aria-invalid", "true");
    control.addEventListener("change", async () => {
        try {
            const value = field.kind === "boolean" ? control.value === "true"
                : field.kind === "number" ? (control.value.trim() ? Number(control.value) : null)
                : field.kind === "nullable" ? JSON.parse(control.value) : control.value;
            await act("edit", { keys: field.keys, value });
        } catch { error("Enter null, a quoted string, a number or a boolean."); }
    });
    const hint = element("p", field.hint + (field.kind === "yaml" ? "\nYAML fragment: keep comments you want to retain."
        : field.kind === "nullable" ? "\nUse null or a JSON scalar (quote text)." : ""), "hint");
    hint.id = `${id}-hint`;
    wrapper.append(control, hint);
    for (const problem of problems) wrapper.append(element("p", problem.message, "field-error"));
    if (field.suggestion && (field.origin === "Unknown" || field.kind === "missing")) {
        wrapper.append(element("p", `Discovered (confirm): ${JSON.stringify(field.suggestion.value)} from ${field.suggestion.source}. Use the YAML editor to accept or correct it.`, "hint"));
    }
    return wrapper;
}

function renderFields() {
    const query = $("search").value.trim().toLowerCase();
    const fields = state.fields.filter(f => `${f.key} ${f.hint}`.toLowerCase().includes(query));
    const required = fields.filter(f => f.required);
    const verification = fields.filter(f => !f.required && (f.key.startsWith("quality_gates.") || f.key.startsWith("testing.")));
    const other = fields.filter(f => !required.includes(f) && !verification.includes(f));
    const container = $("fields");
    container.replaceChildren();
    for (const [title, list] of [["Required basics", required], ["Verification commands and testing", verification]]) {
        if (!list.length) continue;
        const group = element("section", undefined, "group");
        group.append(element("h2", title), ...list.map(fieldControl));
        container.append(group);
    }
    const sections = [...new Set(other.map(f => f.key.split(".")[0]))];
    for (const name of sections) {
        const details = element("details", undefined, "group");
        details.open = !!query || openGroups.has(name);
        details.append(element("summary", name.replaceAll("_", " ")), ...other.filter(f => f.key.startsWith(`${name}.`)).map(fieldControl));
        details.addEventListener("toggle", () => details.open ? openGroups.add(name) : openGroups.delete(name));
        container.append(details);
    }
    if (!fields.length) container.append(element("p", "No editable fields. Check the YAML view and validation messages.", "muted"));
}

function render() {
    $("summary").replaceChildren(
        element("span", state.exists ? "Existing profile" : "New from template", "badge"),
        element("span", state.dirty ? "Unsaved draft" : "Saved snapshot", "badge"),
        element("span", `${state.errors.length} errors`, "badge"),
    );
    $("yaml").value = state.text;
    $("diff").textContent = state.diff;
    $("reviewed").checked = reviewedHash === state.hash;
    $("issues").replaceChildren(...[
        ...state.errors.map(i => element("li", `Error: ${i.path || "YAML"} — ${i.message}`, "danger")),
        ...(["failed", "pending"].includes(state.generation?.status)
            ? [element("li", `AGENTS.md regeneration ${state.generation.status}: ${state.generation.message || "not confirmed"}. Review and Save again to retry.`, "danger")]
            : []),
        ...state.warnings.map(i => element("li", `${i.path} — ${i.message}`)),
    ]);
    renderFields();
    saveState();
}

document.querySelectorAll("[data-view]").forEach(b => b.addEventListener("click", () => switchView(b.dataset.view)));
$("search").addEventListener("input", renderFields);
$("yaml").addEventListener("input", () => { yamlChanged = $("yaml").value !== state.text; reviewedHash = null; $("reviewed").checked = false; saveState(); });
$("apply-yaml").addEventListener("click", () => act("draft", { text: $("yaml").value }));
$("reviewed").addEventListener("change", e => { reviewedHash = e.target.checked ? state.hash : null; saveState(); });
$("save").addEventListener("click", () => act("save", { reviewedHash }));
$("compare").addEventListener("click", async () => {
    try {
        const disk = await request("disk");
        $("disk").textContent = disk.exists ? disk.text : "(Profile does not exist on disk.)";
        $("message").textContent = disk.conflict ? "Disk changed since this draft began. Save will refuse to overwrite it." : "Disk still matches the draft's base.";
    } catch (e) { error(e.message); }
});
$("discard").addEventListener("click", () => {
    if (confirm("Discard the session draft and any unapplied YAML edits, then load the current file?")) {
        reviewedHash = null;
        act("reload");
    }
});
$("reload-view").addEventListener("click", async () => {
    if (yamlChanged && !confirm("Discard unapplied YAML edits and reload the shared session draft?")) return;
    try { state = await request("state"); yamlChanged = false; reviewedHash = null; render(); $("error").hidden = true; }
    catch (e) { error(e.message); }
});
window.addEventListener("beforeunload", e => { if (yamlChanged) { e.preventDefault(); e.returnValue = ""; } });
try { state = await request("state"); render(); }
catch (e) { error(e.message); $("summary").textContent = "Could not load profile."; }
