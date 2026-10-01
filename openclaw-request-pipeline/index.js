import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const ROOT = dirname(fileURLToPath(import.meta.url));
const PIPELINE = join(ROOT, "bin", "oc-pipeline");
const WRITE_TOOLS = new Set(["exec", "write", "edit", "apply_patch", "process"]);
const PLAN_STAGES = new Set(["ask_similar", "planning", "replanning", "awaiting_approval"]);
const INTERNAL_HEAD_RE =
  /^(?:\[?OpenClaw heartbeat poll\]?|Follow the heartbeat monitor|Continue the OpenClaw runtime event|Pre-compaction memory flush)/i;
const OK_RE = /^(ok|okay|yes|y|はい|ええ|うん|承認|許可|いいよ|それで|よろしく|実行して|go|lgtm)([!！.。\s]*)$/i;
const CONTINUE_TOKEN_RE = /^(?:VISION_READY|PLAN_APPROVED)\b/;
const EN_FAIL_RE =
  /Something went wrong while processing your request|Agent couldn't generate a response/i;
const JA_FAIL =
  "⚠️ 処理中にエラーが起きました。もう一度送ってください。新しい会話にするときは、先頭にスペースを付けて 「 /new」 と送ってください。";
const visionJobs = new Set();
const continueJobs = new Set();

function localizeFailure(text) {
  return EN_FAIL_RE.test(String(text || "")) ? JA_FAIL : null;
}

function extractText(value) {
  if (!value) return "";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(extractText).join("\n");
  if (typeof value === "object") {
    if (typeof value.text === "string") return value.text;
    if (typeof value.content === "string") return value.content;
    if (value.content) return extractText(value.content);
    if (value.body) return extractText(value.body);
  }
  return "";
}

function latestUserText(event) {
  const direct = extractText(event?.prompt) || extractText(event?.cleanedBody);
  if (direct.trim()) return direct;
  const messages = event?.messages || event?.sessionMessages || [];
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const msg = messages[i];
    if ((msg?.role || msg?.type) === "user") {
      const text = extractText(msg);
      if (text.trim()) return text;
    }
  }
  return "";
}

function latestAssistantText(event) {
  if (event?.lastAssistantMessage) return extractText(event.lastAssistantMessage);
  const texts = event?.assistantTexts;
  if (Array.isArray(texts) && texts.length) return texts.filter(Boolean).join("\n");
  if (event?.lastAssistant) return extractText(event.lastAssistant);
  const messages = event?.messages || event?.sessionMessages || [];
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const msg = messages[i];
    if ((msg?.role || msg?.type) === "assistant") {
      const text = extractText(msg);
      if (text.trim()) return text;
    }
  }
  return "";
}

function isInternalPrompt(text) {
  const raw = String(text || "").trim();
  if (!raw) return false;
  return INTERNAL_HEAD_RE.test(raw.split(/\n/, 1)[0].trim());
}

function isolatedUserText(event, sessionKey) {
  const cleaned = extractText(event?.cleanedBody || event?.prompt || event?.content).trim();
  const head = cleaned.split(/\n/, 1)[0].trim();
  if (CONTINUE_TOKEN_RE.test(head) || CONTINUE_TOKEN_RE.test(cleaned)) {
    return CONTINUE_TOKEN_RE.exec(head)?.[0] || CONTINUE_TOKEN_RE.exec(cleaned)?.[0] || head;
  }
  if (isInternalPrompt(head) || isInternalPrompt(cleaned)) return head;
  const inboxText = String((sessionKey && readInbox(sessionKey)?.text) || "").trim();
  if (OK_RE.test(cleaned) || OK_RE.test(head)) return head || cleaned;
  if (inboxText && cleaned.includes(inboxText)) return inboxText;
  return head || cleaned || inboxText;
}

function approvalText(event, sessionKey) {
  const isolated = isolatedUserText(event, sessionKey);
  if (CONTINUE_TOKEN_RE.test(isolated) || isInternalPrompt(isolated)) return "";
  return OK_RE.test(isolated) ? isolated : "";
}

function runPipeline(args, { timeoutMs = 180000 } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn("python3", [PIPELINE, ...args], {
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      reject(new Error(`pipeline timeout: ${args.join(" ")}`));
    }, timeoutMs);
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", (err) => {
      clearTimeout(timer);
      reject(err);
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        reject(new Error(stderr || stdout || `exit ${code}`));
        return;
      }
      const trimmed = stdout.trim();
      try {
        resolve(trimmed ? JSON.parse(trimmed) : { ok: true });
      } catch {
        resolve({ ok: true, raw: trimmed });
      }
    });
  });
}

function mediaFromEvent(event) {
  const facts = event?.media || event?.originalMedia || [];
  if (!Array.isArray(facts)) return [];
  return facts
    .map((item) => ({
      path: item.path || item.url || item.mediaPath,
      contentType: item.contentType || item.mediaType || "",
    }))
    .filter((item) => item.path);
}

function inboxFile(sessionKey) {
  const safe = String(sessionKey || "unknown").replace(/[^A-Za-z0-9._+\-@]/g, "_");
  const dir = join(
    process.env.HOME || "",
    ".openclaw",
    "workspace",
    ".pipeline-runtime",
    "inbox",
  );
  mkdirSync(dir, { recursive: true });
  return join(dir, `${safe}.json`);
}

function writeInbox(sessionKey, payload) {
  writeFileSync(inboxFile(sessionKey), JSON.stringify(payload, null, 2));
}

function readInbox(sessionKey) {
  try {
    return JSON.parse(readFileSync(inboxFile(sessionKey), "utf8"));
  } catch {
    return null;
  }
}

function isPipelineExec(params) {
  const command = String(params?.command || "");
  return command.includes("oc-pipeline") || command.includes("openclaw-request-pipeline");
}

function targetPaths(event) {
  const derived = event?.derivedPaths || [];
  const params = event?.params || {};
  const extra = [params.path, params.file_path, params.target].filter(Boolean);
  return [...derived, ...extra].map(String);
}

async function capturePlan(sessionKey, assistant) {
  if (!sessionKey || !String(assistant || "").trim()) return;
  try {
    await runPipeline(["capture-plan", "--session", sessionKey, "--text", assistant], {
      timeoutMs: 15000,
    });
  } catch {
    // no-op unless the request is in planning
  }
}

function kickVisionThenContinue(sessionKey, requestId) {
  if (!requestId || visionJobs.has(requestId)) return;
  visionJobs.add(requestId);
  runPipeline(["vision", "--request-id", requestId], { timeoutMs: 1200000 })
    .catch(() => {})
    .finally(() => {
      visionJobs.delete(requestId);
      kickContinue(sessionKey, "VISION_READY");
    });
}

async function approveFromOk(sessionKey, text, ctx) {
  let status = await runPipeline(["status", "--session", sessionKey], { timeoutMs: 8000 });
  let stage = status?.state?.stage || "";
  if (["planning", "replanning", "awaiting_approval"].includes(stage)) {
    const inbox = readInbox(sessionKey) || {};
    status = await runPipeline(
      [
        "ingest",
        "--session",
        sessionKey,
        "--text",
        text,
        "--media",
        "[]",
        "--sender",
        String(inbox.sender || ctx?.senderId || ""),
        "--channel",
        String(inbox.channel || ctx?.channelId || "slack"),
      ],
      { timeoutMs: 15000 },
    );
    stage = status?.state?.stage || "";
  }
  if (stage !== "executing" && stage !== "vision") return false;
  if (status?.state?.has_images && !status?.state?.vision_done) {
    kickVisionThenContinue(sessionKey, status.state.id);
  } else {
    kickContinue(sessionKey, "PLAN_APPROVED");
  }
  return true;
}

function gatewayCall(method, params = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn("openclaw", [
      "gateway",
      "call",
      method,
      "--params",
      JSON.stringify(params),
      "--json",
    ]);
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      reject(new Error(`${method} timeout`));
    }, 15000);
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", (err) => {
      clearTimeout(timer);
      reject(err);
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        reject(new Error(stderr || stdout || `exit ${code}`));
        return;
      }
      const trimmed = stdout.trim();
      try {
        resolve(trimmed ? JSON.parse(trimmed) : { ok: true });
      } catch {
        resolve({ ok: true, raw: trimmed });
      }
    });
  });
}

function resetGatewaySession(sessionKey) {
  return gatewayCall("sessions.reset", { key: sessionKey, reason: "new" });
}

function sessionTokenCount(row) {
  const entry = row?.entry || row?.session || row || {};
  const n = Number(entry.totalTokens ?? row?.totalTokens ?? 0);
  return Number.isFinite(n) ? n : 0;
}

async function maybeResetSession(sessionKey, text) {
  const peek = await runPipeline(["peek", "--session", sessionKey, "--text", text], {
    timeoutMs: 8000,
  });
  if (!peek?.reset) return false;
  let tokens = 0;
  try {
    const desc = await gatewayCall("sessions.describe", { key: sessionKey });
    tokens = sessionTokenCount(desc);
  } catch {
    tokens = 0;
  }
  if (tokens <= 0) return false;
  await resetGatewaySession(sessionKey);
  return true;
}

function kickContinue(sessionKey, message) {
  const key = `${sessionKey}:${message}`;
  if (continueJobs.has(key)) return;
  continueJobs.add(key);
  const child = spawn("openclaw", [
    "agent",
    "--session-key",
    sessionKey,
    "--message",
    message,
    "--deliver",
    "--channel",
    "last",
    "--timeout",
    "600",
  ], {
    detached: true,
    stdio: "ignore",
  });
  child.unref();
}

export default definePluginEntry({
  id: "request-pipeline",
  name: "Request Pipeline",
  description: "Plan-approve-execute pipeline with request folders and vision JSON.",
  register(api) {
    api.on("message_sending", (event) => {
      const ja = localizeFailure(event?.content);
      if (ja) return { content: ja };
    });

    api.on("reply_payload_sending", (event) => {
      const payload = event?.payload;
      if (!payload || typeof payload !== "object") return;
      const ja = localizeFailure(payload.text || payload.content);
      if (!ja) return;
      return { payload: { ...payload, text: ja } };
    });

    api.on("message_received", (event, ctx) => {
      const sessionKey = ctx?.sessionKey || event?.sessionKey || "unknown";
      writeInbox(sessionKey, {
        text: extractText(event?.content) || extractText(event?.bodyForAgent),
        media: mediaFromEvent(event),
        sender: event?.from || ctx?.senderId || "",
        channel: event?.channelId || "slack",
        at: new Date().toISOString(),
      });
    });

    api.on("before_dispatch", async (event, ctx) => {
      const text = extractText(event?.content || event?.body).trim();
      if (CONTINUE_TOKEN_RE.test(text) || isInternalPrompt(text)) return;
      const sessionKey = ctx?.sessionKey || event?.sessionKey || "agent:main:main";
      if (!OK_RE.test(text)) {
        try {
          await maybeResetSession(sessionKey, text);
        } catch {
          // keep the turn even if reset fails
        }
        return;
      }
      try {
        const ok = await approveFromOk(sessionKey, text, ctx);
        if (!ok) return;
        writeInbox(sessionKey, {
          ...(readInbox(sessionKey) || {}),
          text: "",
          handled: "ok",
          at: new Date().toISOString(),
        });
      } catch {
        return;
      }
      return { handled: true, text: "了解！開始します！" };
    });

    api.on(
      "before_prompt_build",
      async (event, ctx) => {
        const sessionKey = ctx?.sessionKey || "unknown";
        const inbox = readInbox(sessionKey) || {};
        const promptText = latestUserText(event);
        let text =
          inbox.text && promptText.includes(inbox.text)
            ? inbox.text
            : promptText || inbox.text || "";
        const media = mediaFromEvent(event);
        const mergedMedia = media.length ? media : inbox.media || [];
        if (
          !CONTINUE_TOKEN_RE.test(text) &&
          !isInternalPrompt(text) &&
          OK_RE.test(String(inbox.text || "").trim())
        ) {
          text = inbox.text.trim();
        }
        if (isInternalPrompt(text)) {
          return {
            prependContext:
              "<request_pipeline>\nstage: system\nこのターンの指示:\n内部ハートビート。ツールを使うな。NO_REPLY でよい。\n</request_pipeline>",
            toolsAllow: [],
          };
        }
        try {
          const result = await runPipeline(
            [
              "ingest",
              "--session",
              sessionKey,
              "--text",
              text,
              "--media",
              JSON.stringify(mergedMedia),
              "--sender",
              String(inbox.sender || ctx?.senderId || ""),
              "--channel",
              String(inbox.channel || "slack"),
            ],
            { timeoutMs: 540000 },
          );
          const stage = result?.state?.stage || "";
          const eventName = result?.event || "";
          const out = {};
          if (result?.context) out.prependContext = result.context;
          if (
            eventName === "chat" ||
            eventName === "system" ||
            eventName === "session_reset" ||
            stage !== "executing"
          ) {
            out.toolsAllow = [];
          }
          return Object.keys(out).length ? out : undefined;
        } catch (err) {
          return {
            prependContext: `<request_pipeline>\nERROR: ${String(err)}\n計画だけ出せ。実行するな。\n</request_pipeline>`,
            toolsAllow: [],
          };
        }
      },
      { timeoutMs: 580000 },
    );

    api.on("before_agent_run", (event) => {
      if (isInternalPrompt(event?.prompt)) {
        return { outcome: "block", reason: "internal-runtime-event" };
      }
    });

    api.on(
      "before_agent_reply",
      async (event, ctx) => {
        const sessionKey = ctx?.sessionKey || event?.sessionKey || "";
        const body = approvalText(event, sessionKey);
        if (!body) {
          if (isInternalPrompt(isolatedUserText(event, sessionKey))) {
            return { handled: true };
          }
          return;
        }
        if (!sessionKey) return;
        try {
          const ok = await approveFromOk(sessionKey, body, ctx);
          if (!ok) return;
          writeInbox(sessionKey, {
            ...(readInbox(sessionKey) || {}),
            text: "",
            handled: "ok",
            at: new Date().toISOString(),
          });
        } catch {
          return;
        }
        return {
          handled: true,
          reply: { text: "了解！開始します！" },
        };
      },
      { eligibleTriggers: ["user"] },
    );

    api.on("before_agent_finalize", async (event, ctx) => {
      const sessionKey = ctx?.sessionKey || event?.sessionKey;
      const inbox = readInbox(sessionKey) || {};
      if (OK_RE.test(String(inbox.text || "").trim())) return;
      await capturePlan(sessionKey, latestAssistantText(event));
    });

    api.on("agent_end", async (event, ctx) => {
      const sessionKey = ctx?.sessionKey || event?.sessionKey;
      const inbox = readInbox(sessionKey) || {};
      if (OK_RE.test(String(inbox.text || "").trim())) return;
      await capturePlan(sessionKey, latestAssistantText(event));
    });

    api.on(
      "before_tool_call",
      async (event, ctx) => {
        const sessionKey = ctx?.sessionKey || "";
        let stage = "";
        let folder = "";
        try {
          const status = await runPipeline(["status", "--session", sessionKey], { timeoutMs: 8000 });
          stage = status?.state?.stage || "";
          folder = status?.state?.id
            ? `${process.env.HOME}/Documents/ai_tasks/${status.state.id}`
            : "";
        } catch {
          return;
        }
        const tool = event.toolName;
        if (WRITE_TOOLS.has(tool) && stage !== "executing") {
          if (tool === "exec" && isPipelineExec(event.params)) return;
          return {
            block: true,
            blockReason: `stage=${stage || "chat"}: 承認前なので ${tool} は使えない。テキストだけで返せ。`,
          };
        }
        if (stage === "executing" && folder) {
          const paths = targetPaths(event);
          const escaped = paths.find((p) => p.startsWith("/") && !p.startsWith(folder));
          if (escaped && WRITE_TOOLS.has(tool) && tool !== "exec") {
            return {
              block: true,
              blockReason: `成果物は ${folder} の中だけに書いてください。`,
            };
          }
        }
      },
      { matcher: ["exec", "write", "edit", "apply_patch", "process"] },
    );

    api.registerTool({
      name: "pipeline",
      description:
        "Request-folder helper. Use save to write outputs, finish to close, status to inspect, log to append an execution log.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          action: { type: "string", enum: ["status", "save", "finish", "log"] },
          name: { type: "string", description: "output filename for save" },
          content: { type: "string", description: "file body for save, or log message" },
          request_id: { type: "string" },
        },
        required: ["action"],
      },
      async execute(_id, params, ctx) {
        const sessionKey = ctx?.sessionKey || "";
        const status = await runPipeline(["status", "--session", sessionKey], { timeoutMs: 8000 });
        const requestId = params.request_id || status?.state?.id;
        if (!requestId && params.action !== "status") {
          return { content: [{ type: "text", text: "active request not found" }] };
        }
        if (params.action === "status") {
          return { content: [{ type: "text", text: JSON.stringify(status, null, 2) }] };
        }
        if (params.action === "save") {
          const result = await runPipeline([
            "save",
            "--request-id",
            requestId,
            "--name",
            params.name || "output.md",
            "--content",
            params.content || "",
          ]);
          return { content: [{ type: "text", text: JSON.stringify(result) }] };
        }
        if (params.action === "finish") {
          const result = await runPipeline(["finish", "--request-id", requestId]);
          return { content: [{ type: "text", text: JSON.stringify(result) }] };
        }
        if (params.action === "log") {
          const result = await runPipeline([
            "log",
            "--request-id",
            requestId,
            "--message",
            params.content || "",
          ]);
          return { content: [{ type: "text", text: JSON.stringify(result) }] };
        }
        return { content: [{ type: "text", text: "unknown action" }] };
      },
    });
  },
});
