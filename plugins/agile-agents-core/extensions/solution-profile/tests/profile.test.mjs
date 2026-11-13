import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {
    PROFILE, TEMPLATE, describeFields, digest, editField, loadProfile, parseProfile,
    saveProfile, validateProfile,
} from "../profile.mjs";
import { createStore, startServer } from "../server.mjs";

const template = await fs.readFile(TEMPLATE, "utf8");
const valid = `# owned comment
identity:
  project_name: "example" # retain this
  lifecycle_stage: pilot
documentation: { location: "docs/" }
backlog: { platform: none }
tech_stack:
  primary_languages:
    - { name: python } # language note
  test_discipline: test-after
infrastructure:
  deploy_verify: "off"
custom: { future_key: 42 }
`;

async function fixture(t, text = valid) {
    const root = await fs.mkdtemp(path.join(os.tmpdir(), "profile-canvas-"));
    t.after(() => fs.rm(root, { recursive: true, force: true }));
    await fs.mkdir(path.join(root, ".github"), { recursive: true });
    if (text !== null) await fs.writeFile(path.join(root, PROFILE), text);
    const workspace = path.join(root, "session");
    return { root, workspace };
}

test("editing a scalar preserves untouched bytes, comments, unknown keys and quoted off", () => {
    const result = editField(valid, ["identity", "project_name"], "updated");
    assert.equal(result, valid.replace('"example"', '"updated"'));
    assert.equal(parseProfile(result).getIn(["infrastructure", "deploy_verify"]), "off");
});

test("sequence editing round trips unchanged fragments and preserves nested comments", () => {
    const field = describeFields(valid, valid, template, true).find(f => f.key === "tech_stack.primary_languages");
    assert.equal(editField(valid, field.keys, field.value), valid);
    const result = editField(valid, field.keys, field.value.replace("python", "typescript"));
    assert.equal(result, valid.replace("name: python", "name: typescript"));
});

test("CRLF scalar edits do not reflow untouched lines", () => {
    const text = valid.replaceAll("\n", "\r\n");
    assert.equal(editField(text, ["identity", "project_name"], "updated"), text.replace('"example"', '"updated"'));
});

test("implicit null fields can be set without breaking trailing comments", () => {
    const text = `${valid}optional:                  # keep\n`;
    assert.equal(parseProfile(editField(text, ["optional"], 2)).get("optional"), 2);
    assert.match(editField(text, ["optional"], 2), /# keep/);
});

test("invalid YAML, duplicate keys, aliases and tagged input are rejected explicitly", () => {
    assert.throws(() => parseProfile("identity: ["), { code: "invalid_yaml" });
    assert.throws(() => parseProfile("a: 1\na: 2"), /unique/);
    assert.throws(() => parseProfile("a: &x 1\nb: *x"), /Anchors/);
    assert.throws(() => parseProfile("a: !unknown text"), /Unresolved tag/);
    assert.throws(() => parseProfile("%YAML 1.1\n---\na: off"), /YAML 1.2/);
});

test("validation blocks missing basics, incorrect types and empty enabled commands", () => {
    const text = valid.replace('project_name: "example"', 'project_name: ""') +
        "quality_gates:\n  test_bar:\n    enabled: true\n    lint: { enabled: true, command: '' }\n";
    const result = validateProfile(text, template);
    assert.ok(result.errors.some(e => e.path === "identity.project_name"));
    assert.ok(result.errors.some(e => e.path === "quality_gates.test_bar.lint.command"));
    assert.ok(validateProfile(valid.replace("deploy_verify: \"off\"", "deploy_verify: false"), template)
        .errors.some(e => e.path === "infrastructure.deploy_verify"));
});

test("disabled checks remain visible skips and missing startup remains unverified", () => {
    const text = valid + "quality_gates:\n  test_bar:\n    lint: { enabled: false, command: '' }\n";
    const result = validateProfile(text, template);
    assert.equal(result.errors.length, 0);
    assert.ok(result.warnings.some(w => w.path === "quality_gates.test_bar.lint"));
    assert.ok(result.warnings.some(w => w.path === "testing.smoke"));
});

test("command strings and argv lists follow the same profile contract", () => {
    const text = valid + "quality_gates:\n  test_bar:\n    lint: { enabled: true, command: [python, check.py] }\n" +
        "testing:\n  smoke: { command: 'python app.py', url: 'http://localhost:9000' }\n";
    assert.deepEqual(validateProfile(text, template).errors, []);
});

test("invalid section structures and unquoted off cannot evade validation", () => {
    assert.ok(validateProfile(valid + "quality_gates: false\n", template).errors.some(e => e.path === "quality_gates"));
    assert.ok(validateProfile(valid.replace('"off"', "off"), template).errors.some(e => e.path === "infrastructure.deploy_verify"));
});

test("e2e requires all five fields and correctly typed worker settings", () => {
    const result = validateProfile(valid + "testing:\n  e2e: { framework: none, parallelism: 0 }\n", template);
    assert.ok(result.errors.some(e => e.path === "testing.e2e.headless"));
    assert.ok(result.errors.some(e => e.path === "testing.e2e.flake_retries"));
    assert.ok(result.errors.some(e => e.path === "testing.e2e.parallelism"));
});

test("missing profile starts from the template without writing or inventing confirmed facts", async t => {
    const { root } = await fixture(t, null);
    const state = await loadProfile(root);
    assert.equal(state.text, template);
    assert.equal(state.revision, "missing");
    await assert.rejects(fs.stat(path.join(root, PROFILE)), { code: "ENOENT" });
    const fields = describeFields(state.text, state.text, template, false);
    assert.equal(fields.find(f => f.key === "identity.project_name").origin, "Unknown");
    assert.equal(fields.find(f => f.key === "identity.default_branch").origin, "Template default");
});

test("session drafts survive provider reload, share a document identity and never write profile implicitly", async t => {
    const { root, workspace } = await fixture(t);
    const store = await createStore(root, workspace);
    const snapshot = await store.mutate("edit", { version: 0, keys: ["identity", "project_name"], value: "draft" });
    assert.equal(snapshot.dirty, true);
    assert.equal(await fs.readFile(path.join(root, PROFILE), "utf8"), valid);
    await assert.rejects(fs.stat(path.join(root, "AGENTS.md")), { code: "ENOENT" });
    const reopened = await createStore(root, workspace);
    assert.equal(reopened.snapshot().text, snapshot.text);
    await assert.rejects(store.mutate("edit", { version: 0, keys: ["identity", "project_name"], value: "stale" }),
        { code: "draft_conflict" });
});

test("explicit save requires exact preview and retains the prior file for recovery", async t => {
    const { root, workspace } = await fixture(t);
    const store = await createStore(root, workspace);
    const draft = await store.mutate("edit", { version: 0, keys: ["identity", "project_name"], value: "saved" });
    await assert.rejects(store.mutate("save", { version: draft.version, reviewedHash: "stale" }), { code: "preview_changed" });
    const result = await store.mutate("save", { version: draft.version, reviewedHash: draft.hash });
    assert.equal(await fs.readFile(path.join(root, PROFILE), "utf8"), draft.text);
    assert.equal(await fs.readFile(path.join(root, result.backup), "utf8"), valid);
    assert.equal(result.dirty, false);
    assert.equal(result.generation.status, "updated");
    const agents = await fs.readFile(path.join(root, "AGENTS.md"), "utf8");
    assert.match(agents, /# AGENTS.md — saved/);
    assert.match(agents, /Documentation.*docs\//);
});

test("generation failure preserves hand-maintained instructions and supports retry after ownership resolution", async t => {
    const { root, workspace } = await fixture(t);
    const owned = "# Team instructions\nKeep this file.\n";
    await fs.writeFile(path.join(root, "AGENTS.md"), owned);
    const store = await createStore(root, workspace);
    const draft = await store.mutate("edit", { version: 0, keys: ["identity", "project_name"], value: "after-save" });
    await assert.rejects(store.mutate("save", { version: draft.version, reviewedHash: draft.hash }),
        { code: "generation_failed" });
    assert.equal(await fs.readFile(path.join(root, PROFILE), "utf8"), draft.text);
    assert.equal(await fs.readFile(path.join(root, "AGENTS.md"), "utf8"), owned);
    const reopened = await createStore(root, workspace);
    const failed = reopened.snapshot();
    assert.equal(failed.dirty, false);
    assert.equal(failed.generation.status, "failed");
    await fs.rename(path.join(root, "AGENTS.md"), path.join(root, "TEAM.md"));
    const result = await reopened.mutate("save", { version: failed.version, reviewedHash: failed.hash });
    assert.equal(result.generation.status, "updated");
    assert.match(await fs.readFile(path.join(root, "AGENTS.md"), "utf8"), /# AGENTS.md — after-save/);
    assert.equal(await fs.readFile(path.join(root, "TEAM.md"), "utf8"), owned);
});

test("regeneration replaces only generated files and retains their prior content", async t => {
    const { root, workspace } = await fixture(t);
    const before = "<!-- GENERATED-BY: scripts/generate-agents-md.ps1 -->\n# Old generated file\n";
    await fs.writeFile(path.join(root, "AGENTS.md"), before);
    const store = await createStore(root, workspace);
    const draft = await store.mutate("draft", { version: 0,
        text: valid + 'testing:\n  smoke:\n    command: "touch NEVER_EXECUTE"\n' });
    const result = await store.mutate("save", { version: draft.version, reviewedHash: draft.hash });
    assert.equal(result.generation.status, "updated");
    assert.equal(await fs.readFile(path.join(root, result.generation.backup), "utf8"), before);
    await assert.rejects(fs.stat(path.join(root, "NEVER_EXECUTE")), { code: "ENOENT" });
});

test("external edits block saving and preserve both disk and draft", async t => {
    const { root, workspace } = await fixture(t);
    const store = await createStore(root, workspace);
    const draft = await store.mutate("edit", { version: 0, keys: ["identity", "project_name"], value: "draft" });
    const external = valid.replace('"example"', '"external"');
    await fs.writeFile(path.join(root, PROFILE), external);
    await assert.rejects(store.mutate("save", { version: draft.version, reviewedHash: draft.hash }), { code: "conflict" });
    assert.equal(await fs.readFile(path.join(root, PROFILE), "utf8"), external);
    assert.equal(store.snapshot().text, draft.text);
    assert.equal((await store.disk()).conflict, true);
});

test("simultaneous saves cannot silently overwrite one another", async t => {
    const { root } = await fixture(t);
    const a = valid.replace('"example"', '"A"'), b = valid.replace('"example"', '"B"');
    const results = await Promise.allSettled([
        saveProfile(root, a, digest(valid), template),
        saveProfile(root, b, digest(valid), template),
    ]);
    assert.equal(results.filter(r => r.status === "fulfilled").length, 1);
    assert.equal(results.filter(r => r.status === "rejected").length, 1);
    assert.ok([a, b].includes(await fs.readFile(path.join(root, PROFILE), "utf8")));
});

test("symbolic links and validation errors cannot be saved through the canvas", async t => {
    const { root } = await fixture(t);
    await assert.rejects(saveProfile(root, "identity: {}", digest(valid), template), { code: "validation_failed" });
    await fs.rename(path.join(root, PROFILE), path.join(root, "outside.yaml"));
    await fs.symlink(path.join(root, "outside.yaml"), path.join(root, PROFILE));
    await assert.rejects(loadProfile(root), { code: "unsafe_path" });
    assert.equal(await fs.readFile(path.join(root, "outside.yaml"), "utf8"), valid);
});

test("a linked configuration directory cannot redirect profile creation or saving", async t => {
    const { root } = await fixture(t);
    const outside = path.join(root, "outside");
    await fs.rename(path.join(root, ".github"), outside);
    await fs.symlink(outside, path.join(root, ".github"), process.platform === "win32" ? "junction" : "dir");
    await assert.rejects(loadProfile(root), { code: "unsafe_path" });
    await assert.rejects(saveProfile(root, valid, digest(valid), template), { code: "unsafe_path" });
    assert.equal(await fs.readFile(path.join(outside, "solution-profile.yaml"), "utf8"), valid);
});

test("HTTP API requires a capability, rejects foreign origins and never executes command strings", async t => {
    const { root, workspace } = await fixture(t);
    const store = await createStore(root, workspace);
    const server = await startServer(store);
    t.after(() => server.close());
    const url = new URL(server.url);
    const authorization = `Bearer ${url.hash.slice(1)}`;
    const headers = { authorization };
    const unauthorized = await fetch(`${url.origin}/api/state`);
    assert.equal(unauthorized.status, 401);
    const foreign = await fetch(`${url.origin}/api/state`, { headers: { ...headers, Origin: "https://example.com" } });
    assert.equal(foreign.status, 403);
    const response = await fetch(`${url.origin}/api/draft`, {
        method: "POST", headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ version: 0, text: valid + 'testing:\n  smoke:\n    command: "touch NEVER_EXECUTE"\n' }),
    });
    assert.equal(response.status, 200);
    await assert.rejects(fs.stat(path.join(root, "NEVER_EXECUTE")), { code: "ENOENT" });
    assert.equal(await fs.readFile(path.join(root, PROFILE), "utf8"), valid);
});

test("HTTP save failure reports the saved profile state without overwriting linked AGENTS.md", async t => {
    const { root, workspace } = await fixture(t);
    const owned = "# Team instructions\n";
    await fs.writeFile(path.join(root, "TEAM.md"), owned);
    await fs.symlink(path.join(root, "TEAM.md"), path.join(root, "AGENTS.md"));
    const store = await createStore(root, workspace);
    const draft = await store.mutate("edit", { version: 0, keys: ["identity", "project_name"], value: "kept" });
    const server = await startServer(store);
    t.after(() => server.close());
    const url = new URL(server.url);
    const response = await fetch(`${url.origin}/api/save`, {
        method: "POST",
        headers: { authorization: `Bearer ${url.hash.slice(1)}`, "Content-Type": "application/json" },
        body: JSON.stringify({ version: draft.version, reviewedHash: draft.hash }),
    });
    assert.equal(response.status, 500);
    const result = await response.json();
    assert.equal(result.error, "generation_failed");
    assert.equal(result.state.dirty, false);
    assert.equal(result.state.generation.status, "failed");
    assert.match(result.message, /Profile saved/);
    assert.equal(await fs.readFile(path.join(root, PROFILE), "utf8"), draft.text);
    assert.equal(await fs.readFile(path.join(root, "TEAM.md"), "utf8"), owned);
});
