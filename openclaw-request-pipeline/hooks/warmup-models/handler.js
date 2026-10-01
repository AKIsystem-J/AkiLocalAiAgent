import { spawn } from "node:child_process";

const PIPELINE = "/Users/akisys/Documents/AkiLocalAiAgent/openclaw-request-pipeline/bin/oc-pipeline";

export default function handler(event) {
  if (event.type !== "gateway" || event.action !== "startup") return;
  const child = spawn("python3", [PIPELINE, "warmup"], {
    detached: true,
    stdio: "ignore",
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  });
  child.unref();
  console.log("[warmup-models] started planner + vision keep_alive");
}
