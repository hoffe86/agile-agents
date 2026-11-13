import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import { register } from "node:module";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

// Only the host SDK boundary is replaced; copied plugin code, YAML and generators run unchanged.
const sdk = `data:text/javascript,${encodeURIComponent(`
export const createCanvas = options => options;
export class CanvasError extends Error {
    constructor(code, message) { super(message); this.code = code; }
}
export async function joinSession({ canvases }) {
    globalThis.canvasFixture.canvas = canvases[0];
    return globalThis.canvasFixture.session;
}
`)}`;
register(`data:text/javascript,${encodeURIComponent(`
export function resolve(specifier, context, nextResolve) {
    if (specifier === "@github/copilot-sdk/extension")
        return { url: ${JSON.stringify(sdk)}, shortCircuit: true };
    return nextResolve(specifier, context);
}
`)}`, import.meta.url);

const pluginRoot = fileURLToPath(new URL("../../../", import.meta.url));
const valid = `identity: { project_name: consumer, lifecycle_stage: pilot }
documentation: { location: "docs/" }
backlog: { platform: none }
tech_stack: { primary_languages: [python], test_discipline: test-after }
infrastructure: { deploy_verify: "off" }
`;

async function fixture(t) {
    const temporary = await fs.mkdtemp(path.join(os.tmpdir(), "installed-profile-canvas-"));
    const installed = path.join(temporary, "plugin");
    const consumer = path.join(temporary, "consumer");
    const artifacts = path.join(temporary, "artifacts");
    const instances = new Set();
    let canvas;
    t.after(async () => {
        await Promise.all([...instances].map(instanceId => canvas.onClose({ instanceId })));
        await fs.rm(temporary, { recursive: true, force: true });
    });
    await fs.cp(pluginRoot, installed, {
        recursive: true,
        filter: source => !["node_modules", ".git"].includes(path.basename(source)),
    });
    await fs.mkdir(consumer);
    const manifest = JSON.parse(await fs.readFile(path.join(installed, ".github/plugin/plugin.json"), "utf8"));
    const extension = path.join(installed, manifest.extensions[0], "solution-profile");
    await assert.rejects(fs.stat(path.join(extension, "node_modules")), { code: "ENOENT" });
    const host = {
        session: {
            workspacePath: artifacts,
            rpc: { metadata: { snapshot: async () => ({ workingDirectory: consumer }) } },
        },
    };
    globalThis.canvasFixture = host;
    try { await import(pathToFileURL(path.join(extension, "extension.mjs")).href); }
    finally { delete globalThis.canvasFixture; }
    canvas = host.canvas;
    return {
        installed, consumer, artifacts, canvas, session: host.session,
        async open(instanceId, workingDirectory) {
            instances.add(instanceId);
            return canvas.open({ instanceId,
                ...(workingDirectory === undefined ? {} : { session: { workingDirectory } }) });
        },
    };
}

async function request(url, operation, input) {
    const address = new URL(url);
    const response = await fetch(`${address.origin}/api/${operation}`, {
        method: input ? "POST" : "GET",
        headers: {
            authorization: `Bearer ${address.hash.slice(1)}`,
            ...(input ? { "content-type": "application/json" } : {}),
        },
        body: input ? JSON.stringify(input) : undefined,
        signal: AbortSignal.timeout(45_000),
    });
    const result = await response.json();
    assert.equal(response.status, 200, JSON.stringify(result));
    return result;
}

test("installed plugin opens and saves a fresh consumer without npm or writes to the plugin", async t => {
    const { installed, consumer, canvas, open } = await fixture(t);
    const pluginProfile = path.join(installed, ".github/solution-profile.yaml");
    await fs.writeFile(pluginProfile, "# Installed plugin must not be edited.\n");
    const panel = await open("consumer");
    const state = await request(panel.url, "state");
    assert.equal(state.exists, false);
    assert.ok(state.fields.some(field => field.key === "identity.project_name"));
    await assert.rejects(fs.stat(path.join(consumer, ".github")), { code: "ENOENT" });
    const address = new URL(panel.url);
    assert.equal((await fetch(`${address.origin}/app.js`)).status, 200);
    assert.equal((await fetch(`${address.origin}/style.css`)).status, 200);
    const draft = await request(panel.url, "draft", { version: state.version, text: valid });
    const saved = await request(panel.url, "save", { version: draft.version, reviewedHash: draft.hash });
    assert.equal(saved.generation.status, "updated");
    assert.equal(await fs.readFile(path.join(consumer, ".github/solution-profile.yaml"), "utf8"), valid);
    assert.match(await fs.readFile(path.join(consumer, "AGENTS.md"), "utf8"), /# AGENTS.md — consumer/);
    assert.equal(await fs.readFile(pluginProfile, "utf8"), "# Installed plugin must not be edited.\n");
    await assert.rejects(fs.stat(path.join(installed, "AGENTS.md")), { code: "ENOENT" });
    assert.equal((await canvas.actions[0].handler({ instanceId: "consumer" })).dirty, false);
});

test("panels share a workspace draft but never reuse it for another workspace", async t => {
    const { consumer, installed, canvas, open } = await fixture(t);
    const other = path.join(path.dirname(consumer), "other");
    await fs.mkdir(other);
    const first = await open("first", consumer);
    const draft = await request(first.url, "draft", { version: 0, text: valid });
    const peer = await open("peer", consumer);
    assert.equal((await request(peer.url, "state")).text, draft.text);
    const separate = await open("other", other);
    assert.equal((await request(separate.url, "state")).version, 0);
    assert.notEqual((await request(separate.url, "state")).text, draft.text);
    assert.equal((await canvas.actions[0].handler({ instanceId: "first" })).version, 1);
    assert.equal((await canvas.actions[0].handler({ instanceId: "other" })).version, 0);
    await canvas.onClose({ instanceId: "first" });
    await assert.rejects(canvas.actions[0].handler({ instanceId: "first" }), { code: "not_open" });
    await assert.rejects(fs.stat(path.join(installed, ".github/solution-profile.yaml")), { code: "ENOENT" });
});

test("missing or relative session directories fail instead of using the installed plugin or process cwd", async t => {
    const { consumer, session, open } = await fixture(t);
    session.rpc.metadata.snapshot = async () => ({});
    await assert.rejects(open("missing"), { code: "repository_missing" });
    await assert.rejects(open("relative", "relative/path"), { code: "repository_missing" });
    assert.deepEqual(await fs.readdir(consumer), []);
});

test("concurrent opens of one panel share a listener and closing releases it", async t => {
    const { consumer, canvas, open } = await fixture(t);
    const [first, second] = await Promise.all([open("shared", consumer), open("shared", consumer)]);
    assert.equal(first.url, second.url);
    await canvas.onClose({ instanceId: "shared" });
    await assert.rejects(fetch(first.url, { signal: AbortSignal.timeout(1_000) }));
});
