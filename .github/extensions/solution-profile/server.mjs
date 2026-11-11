import { createServer } from "node:http";
import { randomBytes } from "node:crypto";
import * as fs from "node:fs/promises";
import path from "node:path";
import {
    PROFILE, MAX_BYTES, ProfileError, digest, describeFields, diffText,
    editField, loadProfile, saveProfile, validateProfile,
} from "./profile.mjs";
import { regenerate } from "./regenerate.mjs";

const assets = new Map([
    ["/", ["index.html", "text/html; charset=utf-8"]],
    ["/app.js", ["app.js", "text/javascript; charset=utf-8"]],
    ["/style.css", ["style.css", "text/css; charset=utf-8"]],
]);

export async function createStore(root, workspace) {
    if (!workspace) throw new ProfileError("workspace_missing", "Session artifact storage is unavailable; drafts cannot be kept safely.");
    const file = path.join(workspace, `solution-profile-draft-${digest(root).slice(0, 20)}.json`);
    const initial = await loadProfile(root);
    let state = { ...initial, version: 0 };
    try {
        const saved = JSON.parse(await fs.readFile(file, "utf8"));
        if (saved.root !== root || typeof saved.text !== "string" ||
            typeof saved.baseText !== "string" || typeof saved.revision !== "string" ||
            typeof saved.exists !== "boolean" || !Number.isSafeInteger(saved.version) ||
            Buffer.byteLength(saved.text) > MAX_BYTES)
            throw new ProfileError("draft_invalid", `Invalid saved draft. Recover it from ${file} before reopening.`);
        state = { ...state, ...saved };
    } catch (error) {
        if (error.code !== "ENOENT") throw error;
    }
    let queue = Promise.resolve();
    async function persist(next) {
        await fs.mkdir(workspace, { recursive: true, mode: 0o700 });
        const temporary = `${file}.tmp`;
        await fs.writeFile(temporary, JSON.stringify({ ...next, root }), { mode: 0o600 });
        await fs.rename(temporary, file);
        state = next;
    }
    function summarize() {
        const validation = validateProfile(state.text, state.template);
        let fields = [];
        try { fields = describeFields(state.text, state.baseText, state.template, state.exists, state.suggestions); }
        catch (error) { if (!(error instanceof ProfileError)) throw error; }
        return {
            path: PROFILE, text: state.text, version: state.version, hash: digest(state.text),
            revision: state.revision, exists: state.exists, fields, ...validation,
            dirty: !state.exists || state.text !== state.baseText,
            diff: diffText(state.exists ? state.baseText : "", state.text),
            backup: state.backup ?? null,
            generation: state.generation ?? null,
        };
    }
    return {
        snapshot: summarize,
        async disk() {
            const disk = await loadProfile(root);
            return { text: disk.text, exists: disk.exists, revision: disk.revision, conflict: disk.revision !== state.revision };
        },
        mutate(operation, input) {
            const task = queue.then(async () => {
                if (!input || input.version !== state.version)
                    throw new ProfileError("draft_conflict", "Another panel updated this draft. Reload the view before editing.", 409);
                let next = { ...state, version: state.version + 1 };
                if (operation === "edit") next.text = editField(state.text, input.keys, input.value);
                else if (operation === "draft") {
                    if (typeof input.text !== "string" || Buffer.byteLength(input.text) > MAX_BYTES)
                        throw new ProfileError("invalid_draft", "Draft must be text no larger than 1 MiB.");
                    next.text = input.text;
                } else if (operation === "reload") next = { ...await loadProfile(root), version: next.version };
                else if (operation === "save") {
                    if (input.reviewedHash !== digest(state.text))
                        throw new ProfileError("preview_changed", "Review the latest diff before saving.", 409);
                    const saved = await saveProfile(root, state.text, state.revision, state.template);
                    next = { ...next, ...saved, backup: saved.backup ?? state.backup,
                        baseText: state.text, exists: true, generation: { status: "pending" } };
                } else throw new ProfileError("not_found", "Unknown operation.", 404);
                try { await persist(next); }
                catch (error) {
                    if (operation === "save") {
                        state = next;
                        throw new ProfileError("draft_persistence_failed", "Profile saved, but draft storage failed. Reload from disk before further changes.", 500);
                    }
                    throw error;
                }
                if (operation === "save") {
                    let generation;
                    try { generation = await regenerate(root, state.text); }
                    catch (error) {
                        generation = { status: "failed", message: error.message };
                    }
                    next = { ...state, generation };
                    try { await persist(next); }
                    catch (error) {
                        state = next;
                        throw new ProfileError("draft_persistence_failed",
                            `Profile saved; AGENTS.md generation ${generation.status}, but draft storage failed (${error.code ?? "unknown"}). Reload the view.`, 500);
                    }
                    if (generation.status === "failed")
                        throw new ProfileError("generation_failed", `Profile saved, but AGENTS.md was not regenerated: ${generation.message}`, 500);
                }
                return summarize();
            });
            queue = task.then(() => undefined, () => undefined);
            return task;
        },
    };
}

async function body(req) {
    const chunks = [];
    let size = 0;
    for await (const chunk of req) {
        size += chunk.length;
        if (size > MAX_BYTES * 2) throw new ProfileError("request_too_large", "Request too large.", 413);
        chunks.push(chunk);
    }
    try { return JSON.parse(Buffer.concat(chunks).toString("utf8")); }
    catch { throw new ProfileError("invalid_json", "Expected JSON."); }
}

export async function startServer(store) {
    const token = randomBytes(32).toString("hex");
    const cachedAssets = new Map(await Promise.all([...assets].map(async ([route, [file, type]]) =>
        [route, { data: await fs.readFile(new URL(file, import.meta.url)), type }])));
    let origin;
    const server = createServer(async (req, res) => {
        res.setHeader("Cache-Control", "no-store");
        res.setHeader("X-Content-Type-Options", "nosniff");
        res.setHeader("Referrer-Policy", "no-referrer");
        res.setHeader("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'");
        function json(status, data) {
            res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
            res.end(JSON.stringify(data));
        }
        try {
            if (req.headers.host !== new URL(origin).host ||
                (req.headers.origin && req.headers.origin !== origin))
                throw new ProfileError("forbidden", "Origin rejected.", 403);
            const url = new URL(req.url, origin);
            if (req.method === "GET" && cachedAssets.has(url.pathname)) {
                const asset = cachedAssets.get(url.pathname);
                res.writeHead(200, { "Content-Type": asset.type });
                res.end(asset.data);
                return;
            }
            if (req.headers.authorization !== `Bearer ${token}`)
                throw new ProfileError("unauthorized", "Reopen the canvas to obtain access.", 401);
            if (req.method === "GET" && url.pathname === "/api/state") json(200, store.snapshot());
            else if (req.method === "GET" && url.pathname === "/api/disk") json(200, await store.disk());
            else if (req.method === "POST" && /^\/api\/(edit|draft|reload|save)$/.test(url.pathname)) {
                if (req.headers["content-type"] !== "application/json")
                    throw new ProfileError("invalid_content_type", "Expected application/json.", 415);
                json(200, await store.mutate(url.pathname.slice(5), await body(req)));
            } else throw new ProfileError("not_found", "Route not found.", 404);
        } catch (error) {
            json(error.status ?? 500, { error: error.code ?? "io_error",
                state: ["generation_failed", "draft_persistence_failed"].includes(error.code) ? store.snapshot() : undefined,
                message: error instanceof ProfileError ? error.message : `Operation failed (${error.code ?? "unexpected error"}). The draft was not discarded.` });
        }
    });
    server.requestTimeout = 10_000;
    server.headersTimeout = 10_000;
    await new Promise((resolve, reject) => {
        server.once("error", reject);
        server.listen(0, "127.0.0.1", resolve);
    });
    origin = `http://127.0.0.1:${server.address().port}`;
    return {
        url: `${origin}/#${token}`,
        async close() {
            server.closeIdleConnections();
            await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
        },
    };
}
