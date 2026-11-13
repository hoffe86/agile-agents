import { execFile } from "node:child_process";
import * as fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { PROFILE, MAX_BYTES, ProfileError, digest, parseProfile, safeFile, saveFile } from "./profile.mjs";

const execute = promisify(execFile);
const scripts = fileURLToPath(new URL("../../skills/solution-profile-interview/scripts/", import.meta.url));
const marker = "<!-- GENERATED-BY: scripts/generate-agents-md.ps1 -->";

export async function regenerate(root, text) {
    const current = await safeFile(root, "AGENTS.md", true);
    if (current !== null && current.split(/\r?\n/, 1)[0] !== marker)
        throw new ProfileError("unmanaged_agents", "AGENTS.md is hand-maintained or belongs to another generator; it was not overwritten.");
    const temporary = await fs.mkdtemp(path.join(os.tmpdir(), "profile-generation-"));
    try {
        // JSON is a lossless snapshot for the generators, including flow YAML and quoted '#' values.
        const snapshot = path.join(temporary, "profile.json");
        await fs.writeFile(snapshot, JSON.stringify(parseProfile(text).toJSON()), { mode: 0o600 });
        const windows = process.platform === "win32";
        const command = windows ? "pwsh" : "bash";
        const args = windows
            ? ["-NoProfile", "-File", path.join(scripts, "generate-agents-md.ps1"),
                "-RepoRoot", root, "-ProfilePath", snapshot, "-DryRun"]
            : [path.join(scripts, "generate-agents-md.sh"), "--repo-root", root, "--profile", snapshot, "--dry-run"];
        let output;
        try {
            ({ stdout: output } = await execute(command, args, {
                cwd: root, timeout: 30_000, maxBuffer: MAX_BYTES, windowsHide: true,
                env: { ...process.env, BASH_ENV: "", ENV: "" },
            }));
        } catch (error) {
            throw new ProfileError("generator_failed",
                `Bundled generator failed (${error.code ?? error.signal ?? "unknown"}): ${error.stderr?.trim() || error.message}`);
        }
        output = output.replaceAll("\r\n", "\n").trimEnd() + "\n";
        if (!output.startsWith(`${marker}\n`) || Buffer.byteLength(output) > MAX_BYTES)
            throw new ProfileError("invalid_generation", "Generator returned invalid or oversized output; AGENTS.md was not changed.");
        if (await safeFile(root, PROFILE) !== text)
            throw new ProfileError("generation_conflict", "Profile changed during generation; AGENTS.md was not changed.");
        const saved = await saveFile(root, "AGENTS.md", output, current === null ? "missing" : digest(current));
        return { status: "updated", backup: saved.backup };
    } finally {
        await fs.rm(temporary, { recursive: true, force: true });
    }
}
