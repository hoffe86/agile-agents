import * as fs from "node:fs/promises";
import path from "node:path";
import { joinSession, createCanvas, CanvasError } from "@github/copilot-sdk/extension";
import { createStore, startServer } from "./server.mjs";

const stores = new Map();
const servers = new Map();

async function openServer(ctx) {
    const directory = ctx.session?.workingDirectory ??
        (await session.rpc.metadata.snapshot()).workingDirectory;
    if (typeof directory !== "string" || !path.isAbsolute(directory))
        throw new CanvasError("repository_missing", "The active session's working directory is unavailable.");
    const root = await fs.realpath(directory);
    if (!stores.has(root)) {
        const pending = createStore(root, session.workspacePath);
        stores.set(root, pending);
        pending.catch(() => {
            if (stores.get(root) === pending) stores.delete(root);
        });
    }
    const store = await stores.get(root);
    return { ...await startServer(store), store };
}

const session = await joinSession({
    canvases: [
        createCanvas({
            id: "solution-profile",
            displayName: "Solution profile",
            description: "Edit this repository's solution profile with validation, diff preview and explicit Save.",
            inputSchema: { type: "object", properties: {}, additionalProperties: false },
            actions: [
                {
                    name: "status",
                    description: "Read validation and draft/disk status without saving or executing profile commands.",
                    inputSchema: { type: "object", properties: {}, additionalProperties: false },
                    handler: async (ctx) => {
                        const entry = await servers.get(ctx.instanceId);
                        if (!entry) throw new CanvasError("not_open", "Open the canvas first.");
                        const state = entry.store.snapshot();
                        const disk = await entry.store.disk();
                        return { path: state.path, dirty: state.dirty, errors: state.errors,
                            warnings: state.warnings, conflict: disk.conflict, version: state.version,
                            generation: state.generation };
                    },
                },
            ],
            open: async (ctx) => {
                if (!servers.has(ctx.instanceId)) {
                    const pending = openServer(ctx);
                    servers.set(ctx.instanceId, pending);
                    pending.catch(() => {
                        if (servers.get(ctx.instanceId) === pending) servers.delete(ctx.instanceId);
                    });
                }
                const entry = await servers.get(ctx.instanceId);
                return { title: "Solution profile", url: entry.url };
            },
            onClose: async (ctx) => {
                const pending = servers.get(ctx.instanceId);
                if (pending) {
                    servers.delete(ctx.instanceId);
                    await (await pending).close();
                }
            },
        }),
    ],
});
