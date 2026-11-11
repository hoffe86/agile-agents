import { fileURLToPath } from "node:url";
import { joinSession, createCanvas, CanvasError } from "@github/copilot-sdk/extension";
import { createStore, startServer } from "./server.mjs";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const servers = new Map();
let store;

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
                    handler: async () => {
                        if (!store) throw new CanvasError("not_open", "Open the canvas first.");
                        const state = store.snapshot();
                        const disk = await store.disk();
                        return { path: state.path, dirty: state.dirty, errors: state.errors,
                            warnings: state.warnings, conflict: disk.conflict, version: state.version,
                            generation: state.generation };
                    },
                },
            ],
            open: async (ctx) => {
                store ??= await createStore(root, session.workspacePath);
                let entry = servers.get(ctx.instanceId);
                if (!entry) {
                    entry = await startServer(store);
                    servers.set(ctx.instanceId, entry);
                }
                return { title: "Solution profile", url: entry.url };
            },
            onClose: async (ctx) => {
                const entry = servers.get(ctx.instanceId);
                if (entry) {
                    servers.delete(ctx.instanceId);
                    await entry.close();
                }
            },
        }),
    ],
});
