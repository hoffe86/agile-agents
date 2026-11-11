import { createHash, randomUUID } from "node:crypto";
import * as fs from "node:fs/promises";
import path from "node:path";
import { isAlias, isMap, isScalar, isSeq, parseDocument, visit } from "yaml";

export const PROFILE = ".github/solution-profile.yaml";
export const TEMPLATE = "plugins/agile-agents-core/skills/solution-profile-interview/references/solution-profile.template.yaml";
export const MAX_BYTES = 1024 * 1024;
export const REQUIRED = [
    "identity.project_name", "identity.lifecycle_stage", "documentation.location",
    "backlog.platform", "tech_stack.primary_languages", "tech_stack.test_discipline",
];
const CHECKS = ["lint", "typecheck", "unit_test", "integration_test", "coverage", "mutation"];
const ENUMS = {
    "identity.lifecycle_stage": ["poc", "pilot", "production", "sunset"],
    "backlog.platform": ["github-issues", "ado-boards", "jira", "linear", "none"],
    "tech_stack.test_discipline": ["tdd", "bdd", "test-after", "none"],
    "infrastructure.deploy_verify": ["off", "dev"],
};

export class ProfileError extends Error {
    constructor(code, message, status = 400) {
        super(message);
        this.code = code;
        this.status = status;
    }
}

export function digest(text) {
    return createHash("sha256").update(text).digest("hex");
}

export function parseProfile(text) {
    if (typeof text !== "string" || Buffer.byteLength(text) > MAX_BYTES)
        throw new ProfileError("invalid_yaml", "YAML must be text no larger than 1 MiB.");
    const doc = parseDocument(text, { keepSourceTokens: true, uniqueKeys: true, stringKeys: true });
    const problems = [...doc.errors, ...doc.warnings];
    if (problems.length) throw new ProfileError("invalid_yaml", problems.map(p => p.message).join("\n"));
    if (!isMap(doc.contents)) throw new ProfileError("invalid_yaml", "The profile must be one YAML mapping.");
    if (doc.directives.yaml.version !== "1.2")
        throw new ProfileError("unsupported_yaml", "Use YAML 1.2; quote values such as \"off\".");
    visit(doc, {
        Node(_, node) {
            if (isAlias(node) || node.anchor || node.tag)
                throw new ProfileError("unsupported_yaml", "Anchors, aliases and explicit tags need manual editing outside this canvas.");
        },
    });
    return doc;
}

function leaves(node, keys = []) {
    if (isMap(node) && node.items.length)
        return node.items.flatMap(pair => leaves(pair.value, [...keys, pair.key.value]));
    return [{ keys, node }];
}

function entries(node, keys = []) {
    return [{ keys, node }, ...(isMap(node)
        ? node.items.flatMap(pair => entries(pair.value, [...keys, pair.key.value])) : [])];
}

function valueAt(doc, key) {
    return doc.getIn(key.split("."));
}

function plain(node) {
    return node?.toJSON ? node.toJSON() : node;
}

const empty = value => value == null || value === "" || (Array.isArray(value) && !value.length);
const commandSet = value => typeof value === "string" ? !!value.trim()
    : Array.isArray(value) && value.length > 0 && value.every(v => typeof v === "string" && !!v.trim());

export function validateProfile(text, template) {
    const errors = [];
    const warnings = [];
    let doc;
    try { doc = parseProfile(text); }
    catch (error) {
        if (!(error instanceof ProfileError)) throw error;
        return { errors: [{ path: "", message: error.message }], warnings };
    }
    const get = key => plain(valueAt(doc, key));
    const add = (key, message) => errors.push({ path: key, message });
    for (const key of REQUIRED) {
        const value = get(key);
        if (empty(value) || (typeof value === "string" && !value.trim())) add(key, "Required value is missing.");
        else if (key !== "tech_stack.primary_languages" && typeof value !== "string") add(key, "Must be text.");
    }
    const languages = get("tech_stack.primary_languages");
    if (languages != null && (!Array.isArray(languages) || languages.some(v =>
        !(typeof v === "string" && v.trim()) &&
        !(v && typeof v === "object" && typeof v.name === "string" && v.name.trim()))))
        add("tech_stack.primary_languages", "Use a nonempty list of language names or { name, version } entries.");
    for (const [key, choices] of Object.entries(ENUMS)) {
        const value = get(key);
        if (!empty(value) && !choices.includes(value)) add(key, `Choose: ${choices.join(", ")}.`);
    }
    for (const { keys, node } of entries(parseProfile(template).contents)) {
        if (!keys.length) continue;
        if (!doc.hasIn(keys)) continue;
        const actual = doc.getIn(keys, true);
        const expected = plain(node);
        const value = plain(actual);
        const key = keys.join(".");
        if (key.endsWith(".command") &&
            (key.startsWith("quality_gates.test_bar.") || key === "testing.smoke.command")) {
            if (typeof value !== "string" && !(Array.isArray(value) && value.every(v => typeof v === "string")))
                add(key, "Use a command string or an argv list of strings.");
        } else if (isSeq(node) && !Array.isArray(value)) add(key, "Must be a list.");
        else if (isMap(node) && !isMap(actual)) add(key, "Must be a mapping.");
        else if (expected !== null && isScalar(node) && typeof value !== typeof expected)
            add(key, `Must be ${typeof expected}.`);
    }
    const deploy = doc.getIn(["infrastructure", "deploy_verify"], true);
    if (plain(deploy) === "off" && !["QUOTE_DOUBLE", "QUOTE_SINGLE"].includes(deploy.type))
        add("infrastructure.deploy_verify", 'Quote "off" to preserve its string type across YAML readers.');
    const bar = get("quality_gates.test_bar");
    if (bar?.enabled !== false) {
        for (const check of CHECKS) {
            const config = bar?.[check];
            if (config?.enabled === true && !commandSet(config.command))
                add(`quality_gates.test_bar.${check}.command`, "Enabled check needs an explicit command.");
        }
    }
    if (bar) for (const check of CHECKS) {
        const config = bar[check];
        if (config?.enabled === false)
            warnings.push({ path: `quality_gates.test_bar.${check}`, message: "Disabled: this check will be skipped." });
    }
    const e2e = get("testing.e2e");
    if (e2e != null) {
        for (const key of ["framework", "base_url", "headless", "parallelism", "flake_retries"])
            if (!Object.hasOwn(e2e, key)) add(`testing.e2e.${key}`, "Required when the e2e section is present.");
        for (const [key, min] of [["parallelism", 1], ["flake_retries", 0]])
            if (!Number.isInteger(e2e[key]) || e2e[key] < min) add(`testing.e2e.${key}`, `Must be an integer >= ${min}.`);
    }
    if (get("infrastructure.deploy_verify") === "dev" &&
        (empty(get("infrastructure.environment_chain")) || empty(get("cicd.platform"))))
        add("infrastructure.deploy_verify", "dev needs an environment chain and CI/CD platform.");
    if (get("data_science.enabled") === true && empty(get("data_science.data_privacy.pii_policy")))
        add("data_science.data_privacy.pii_policy", "Enabled data science needs a PII policy.");
    if (!commandSet(get("testing.smoke.command")) || empty(get("testing.smoke.url")))
        warnings.push({ path: "testing.smoke", message: "Startup is not verified. Resolve from repo evidence, or explicitly justify not applicable in the test bar." });
    return { errors, warnings };
}

function fragment(text, node) {
    const [start, end] = node.range;
    const indent = start - text.lastIndexOf("\n", start - 1) - 1;
    return text.slice(start, end).replaceAll(`\n${" ".repeat(indent)}`, "\n").replace(/\r?\n$/, "");
}

export function describeFields(text, baseText, template, exists, suggestions = {}) {
    const doc = parseProfile(text);
    const base = parseProfile(baseText);
    const model = parseProfile(template);
    const fields = leaves(doc.contents).map(({ keys, node }) => {
        const key = keys.join(".");
        const value = plain(node);
        const original = base.getIn(keys, true);
        const hint = model.getIn(keys, true);
        const kind = isSeq(node) || isMap(node) ? "yaml" : value === null ? "nullable" : typeof value;
        let origin = empty(value) ? "Unknown" : exists && original ? "Existing profile" : "Template default";
        if (JSON.stringify(value) !== JSON.stringify(plain(original))) origin = "Edited";
        return {
            keys, key, kind, value: kind === "yaml" ? fragment(text, node) : value,
            origin, required: REQUIRED.includes(key), choices: ENUMS[key],
            hint: hint?.comment?.trim() || node?.comment?.trim() || "",
            suggestion: suggestions[key],
        };
    });
    for (const key of REQUIRED) if (!fields.some(f => f.key === key))
        fields.push({ key, keys: key.split("."), kind: "missing", value: "", required: true,
            origin: "Unknown", hint: "Missing key: add it in the YAML editor.", suggestion: suggestions[key] });
    return fields;
}

// Patch only the selected source range; stringify never rewrites the document.
export function editField(text, keys, input) {
    const doc = parseProfile(text);
    if (!Array.isArray(keys) || !keys.length || keys.some(k => typeof k !== "string"))
        throw new ProfileError("invalid_field", "Invalid field path.");
    const node = doc.getIn(keys, true);
    if (!node?.range) throw new ProfileError("invalid_field", "Missing fields must be added in the YAML editor.");
    const value = plain(node);
    let replacement;
    if (isMap(node) || isSeq(node)) {
        if (typeof input !== "string") throw new ProfileError("invalid_field", "Enter a YAML fragment.");
        if (input === fragment(text, node)) return text;
        const indent = node.range[0] - text.lastIndexOf("\n", node.range[0] - 1) - 1;
        replacement = input.replace(/\r\n/g, "\n").replaceAll("\n", `\n${" ".repeat(indent)}`);
        if (text.slice(...node.range.slice(0, 2)).endsWith("\n")) replacement += "\n";
    } else {
        if (value !== null && typeof input !== typeof value)
            throw new ProfileError("invalid_field", `Expected ${typeof value}.`);
        if (!["string", "boolean", "number"].includes(typeof input) && input !== null)
            throw new ProfileError("invalid_field", "Enter a scalar value.");
        if (typeof input === "number" && !Number.isFinite(input))
            throw new ProfileError("invalid_field", "Enter a finite number.");
        replacement = JSON.stringify(input);
        if (/^[|>]/.test(text.slice(node.range[0], node.range[0] + 1))) {
            // Block-scalar headers may contain comments; don't silently drop them.
            if (node.comment) throw new ProfileError("manual_edit", "Edit this commented block scalar in YAML to retain its comment.");
            replacement += "\n";
        }
        if (node.range[0] === node.range[1]) replacement = ` ${replacement} `;
    }
    const next = text.slice(0, node.range[0]) + replacement + text.slice(node.range[1]);
    const updated = parseProfile(next);
    if (isScalar(node) && plain(updated.getIn(keys, true)) !== input)
        throw new ProfileError("manual_edit", "This YAML value needs manual editing in the YAML view.");
    return next;
}

export function diffText(before, after) {
    if (before === after) return "No changes.";
    const a = before.split("\n"), b = after.split("\n");
    let start = 0, end = 0;
    while (start < a.length && start < b.length && a[start] === b[start]) start++;
    while (end < a.length - start && end < b.length - start && a.at(-end - 1) === b.at(-end - 1)) end++;
    const from = Math.max(0, start - 2);
    const toA = Math.min(a.length, a.length - end + 2);
    const toB = Math.min(b.length, b.length - end + 2);
    return [`--- saved profile`, `+++ draft`, `@@ -${from + 1},${toA - from} +${from + 1},${toB - from} @@`,
        ...a.slice(from, start).map(l => ` ${l}`),
        ...a.slice(start, a.length - end).map(l => `-${l}`),
        ...b.slice(start, b.length - end).map(l => `+${l}`),
        ...b.slice(b.length - end, toB).map(l => ` ${l}`)].join("\n");
}

export async function safeFile(root, relative, optional = false) {
    const target = path.join(root, relative);
    let current = root;
    const parts = relative.split("/");
    for (const part of parts) {
        current = path.join(current, part);
        let stat;
        try { stat = await fs.lstat(current); }
        catch (error) {
            if (optional && error.code === "ENOENT" && current === target) return null;
            throw error;
        }
        if (stat.isSymbolicLink()) throw new ProfileError("unsafe_path", `Symbolic links are not allowed: ${relative}`);
        if (current === target && (!stat.isFile() || stat.nlink !== 1 || stat.size > MAX_BYTES))
            throw new ProfileError("unsafe_path", `Expected a regular, unlinked file <= 1 MiB: ${relative}`);
    }
    return fs.readFile(target, "utf8");
}

export async function discover(root) {
    const suggestions = {};
    const entries = await fs.readdir(root, { withFileTypes: true });
    if (entries.some(e => e.name === "docs" && e.isDirectory()))
        suggestions["documentation.location"] = { value: "docs/", source: "docs/ directory", origin: "Discovered (confirm)" };
    const names = new Set(entries.filter(e => e.isFile()).map(e => e.name));
    const languages = [];
    if (names.has("pyproject.toml") || names.has("requirements.txt")) languages.push({ name: "python" });
    if (names.has("tsconfig.json")) languages.push({ name: "typescript" });
    else if (names.has("package.json")) languages.push({ name: "javascript" });
    if ([...names].some(n => n.endsWith(".csproj"))) languages.push({ name: "csharp" });
    if (languages.length) suggestions["tech_stack.primary_languages"] = {
        value: languages, source: "Root language manifests (not verified commands)", origin: "Discovered (confirm)",
    };
    return suggestions;
}

export async function loadProfile(root) {
    const text = await safeFile(root, PROFILE, true);
    const template = await safeFile(root, TEMPLATE);
    return { text: text ?? template, baseText: text ?? template, exists: text !== null,
        revision: text === null ? "missing" : digest(text), template, suggestions: await discover(root) };
}

export async function saveProfile(root, text, revision, template) {
    const validation = validateProfile(text, template);
    if (validation.errors.length) throw new ProfileError("validation_failed", "Fix validation errors before saving.", 422);
    return saveFile(root, PROFILE, text, revision);
}

export async function saveFile(root, relative, text, revision) {
    const target = path.join(root, relative);
    const lockPath = `${target}.canvas-lock`;
    let lock;
    try { lock = await fs.open(lockPath, "wx", 0o600); }
    catch (error) {
        if (error.code === "EEXIST") throw new ProfileError("save_busy", "Another save owns the lock. Retry after it completes; inspect an abandoned lock before removing it.", 409);
        throw error;
    }
    const temporary = `${target}.canvas-new-${randomUUID()}`;
    const backup = `${target}.canvas-backup-${randomUUID()}`;
    let preserved = false;
    try {
        const current = await safeFile(root, relative, true);
        if ((current === null ? "missing" : digest(current)) !== revision)
            throw new ProfileError("conflict", "The file changed on disk. Keep your draft, compare with disk, then reload deliberately.", 409);
        if (current === text) return { revision, backup: null };
        const handle = await fs.open(temporary, "wx", 0o600);
        try { await handle.writeFile(text); await handle.sync(); }
        finally { await handle.close(); }
        if (current !== null) {
            // Retain the displaced inode, including late external writes, for recovery.
            await fs.rename(target, backup);
            preserved = true;
            const displaced = await fs.readFile(backup, "utf8");
            if (digest(displaced) !== revision) throw new ProfileError("conflict", "Concurrent edit detected during save.", 409);
            const stat = await fs.stat(backup);
            await fs.chmod(temporary, stat.mode & 0o777);
        }
        // Exclusive link, unlike rename, cannot overwrite a concurrently-created file.
        await fs.link(temporary, target);
        return { revision: digest(text), backup: preserved ? path.relative(root, backup) : null };
    } catch (error) {
        if (preserved) {
            try { await fs.link(backup, target); await fs.unlink(backup); preserved = false; }
            catch (restoreError) {
                if (restoreError.code !== "EEXIST")
                    throw new ProfileError("recovery_required", `Restore failed (${restoreError.code}). Original retained at ${path.relative(root, backup)}.`, 409);
            }
        }
        if (preserved) throw new ProfileError("conflict", `Concurrent file preserved. Your previous file is at ${path.relative(root, backup)}; draft remains unsaved.`, 409);
        if (error.code === "EEXIST") throw new ProfileError("conflict", "A concurrent file appeared. Draft not saved.", 409);
        throw error;
    } finally {
        await fs.rm(temporary, { force: true });
        await lock.close();
        await fs.unlink(lockPath);
    }
}
