#!/usr/bin/env node
// Read a prompt from stdin, run it through the local Codex SDK, print answer to stdout.
//
// Usage:
//   echo "Question" | node scripts/codex_qa.mjs --key <conversation-key>
//
// Notes:
// - Requires Node.js 18+ and `@openai/codex-sdk` installed (see scripts/package.json).

import { Codex } from "@openai/codex-sdk";
import fs from "node:fs";
import path from "node:path";

async function readStdin() {
  return await new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => (data += chunk));
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
  });
}

function extractText(result) {
  if (typeof result === "string") return result;
  if (!result || typeof result !== "object") return String(result ?? "");

  // Best-effort: try common fields first.
  for (const key of ["finalResponse", "text", "output", "result", "message", "content"]) {
    const v = result[key];
    if (typeof v === "string" && v.trim()) return v;
  }

  try {
    return JSON.stringify(result, null, 2);
  } catch {
    return String(result);
  }
}

const prompt = (await readStdin()).trim();
if (!prompt) {
  console.error("Empty prompt.");
  process.exit(2);
}

function parseArgs(argv) {
  const out = { key: "default", reset: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--key") {
      out.key = String(argv[i + 1] || "").trim() || "default";
      i++;
    } else if (a === "--reset") {
      out.reset = true;
    }
  }
  return out;
}

const args = parseArgs(process.argv.slice(2));
const mapPath = path.resolve(process.cwd(), ".codex_threads.json");
let map = {};
try {
  if (fs.existsSync(mapPath)) {
    map = JSON.parse(fs.readFileSync(mapPath, "utf8")) || {};
  }
} catch {
  map = {};
}

function readEntry(mapObj, key) {
  const v = mapObj[key];
  if (typeof v === "string") {
    return { threadId: v, model: null };
  }
  if (v && typeof v === "object") {
    return {
      threadId: typeof v.threadId === "string" ? v.threadId : null,
      model: typeof v.model === "string" ? v.model : null,
    };
  }
  return { threadId: null, model: null };
}

function writeEntry(mapObj, key, entry) {
  const out = {};
  if (entry.threadId) out.threadId = entry.threadId;
  if (entry.model) out.model = entry.model;
  mapObj[key] = out;
}

function safeKey(key) {
  // chat_id is already safe-ish (e.g. oc_xxx), but sanitize anyway.
  return String(key || "default").replace(/[^a-zA-Z0-9_.-]/g, "_");
}

function listFilesRecursive(rootDir) {
  const out = [];
  function walk(dir) {
    let entries = [];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const ent of entries) {
      const abs = path.join(dir, ent.name);
      if (ent.isDirectory()) {
        walk(abs);
      } else if (ent.isFile()) {
        out.push(abs);
      }
    }
  }
  walk(rootDir);
  return out;
}

function isImageFile(p) {
  const ext = path.extname(p).toLowerCase();
  return [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"].includes(ext);
}

const artifactsRoot = path.resolve(process.cwd(), "codex_artifacts");
const artifactsDir = path.join(artifactsRoot, safeKey(args.key));
try {
  fs.mkdirSync(artifactsDir, { recursive: true });
} catch {
  // non-fatal
}
const beforeArtifacts = new Set(listFilesRecursive(artifactsDir));

const codex = new Codex({ env: { ...process.env } });
const entry = readEntry(map, args.key);
let threadId = entry.threadId;
const model =
  String(process.env.CODEX_MODEL || "").trim() ||
  entry.model ||
  String(process.env.CODEX_MODEL_DEFAULT || "").trim() ||
  null;

const threadOpts = {
  workingDirectory: process.cwd(),
  skipGitRepoCheck: true,
  sandboxMode: "workspace-write",
  approvalPolicy: "never",
  additionalDirectories: [artifactsDir],
  model: model || undefined,
};
let thread =
  threadId && !args.reset
    ? codex.resumeThread(threadId, threadOpts)
    : codex.startThread(threadOpts);

function buildPrompt(promptText) {
  const guardrailsOn = !["1", "true", "yes", "y"].includes(
    String(process.env.CODEX_DISABLE_GUARDRAILS || "").trim().toLowerCase()
  );
  const customSuffix = String(process.env.CODEX_PROMPT_SUFFIX || "").trim();

  const base = String(promptText || "").trim();
  const lines = [];
  if (guardrailsOn) {
    lines.push("Constraints:");
    lines.push(
      "- Do not perform real-world side effects (do not actually send emails, purchase, or modify remote systems)."
    );
  }
  lines.push(`- If you create files/images, write them under: ${artifactsDir}`);
  if (customSuffix) {
    lines.push("");
    lines.push(customSuffix);
  }

  return base + "\n\n" + lines.join("\n") + "\n";
}

try {
  let result;
  try {
    result = await thread.run(buildPrompt(prompt));
  } catch (e) {
    // If resume failed (e.g. thread missing), start a new one and retry once.
    const msg = e?.message ? String(e.message) : String(e);
    if (threadId && /thread not found|rollout|session/i.test(msg)) {
      thread = codex.startThread(threadOpts);
      result = await thread.run(buildPrompt(prompt));
    } else {
      throw e;
    }
  }

  if (thread.id) {
    writeEntry(map, args.key, { threadId: thread.id, model });
    try {
      fs.writeFileSync(mapPath, JSON.stringify(map, null, 2), "utf8");
    } catch {
      // Non-fatal: still return the answer.
    }
  }

  const afterArtifacts = new Set(listFilesRecursive(artifactsDir));
  const newArtifacts = [];
  for (const p of afterArtifacts) {
    if (!beforeArtifacts.has(p)) newArtifacts.push(p);
  }

  const payload = {
    answer: extractText(result).trimEnd(),
    threadId: thread.id || null,
    model: model,
    artifacts: newArtifacts.map((p) => ({
      path: p,
      kind: isImageFile(p) ? "image" : "file",
    })),
  };
  process.stdout.write(JSON.stringify(payload));
} catch (err) {
  // Avoid dumping huge stacks into chat.
  const msg = err?.message ? String(err.message) : String(err);
  process.stderr.write(msg);
  process.exit(1);
}
