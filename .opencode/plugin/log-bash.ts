/**
 * log-bash: OpenCode plugin that audits every Bash command the agent runs.
 *
 * Mirror of `.claude/hooks/log-bash.py` and `.codex/hooks/log-bash.py`.
 * Writes to the same `.coograph/session.log` global tail and
 * `.coograph/sessions/<session_id>.log` per-session files so all three
 * agents end up in the same scoped audit trail.
 *
 * OpenCode loads `.opencode/plugin/*.ts` automatically and fires
 * `tool.execute.before` before any tool runs. The plugin never blocks
 * the call — write failures are swallowed silently.
 */

import { appendFile, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";

const AGENT = "opencode";

function safeSid(raw: string): string {
  const cleaned = raw.replace(/[^A-Za-z0-9_-]/g, "");
  return (cleaned || "unknown").slice(0, 64);
}

function ts(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

export const LogBashPlugin = async ({ project, $ }: any) => ({
  "tool.execute.before": async (input: any, output: any) => {
    if (input?.tool !== "bash") return;

    const command: string = output?.args?.command || "";
    if (!command) return;

    const rawSid: string = String(input?.sessionID || input?.session_id || "unknown");
    const sid = safeSid(rawSid);
    const shortSid = sid.slice(0, 8);

    const cwd: string =
      project?.worktree ||
      project?.root ||
      output?.args?.cwd ||
      process.cwd();

    const logDir = join(cwd, ".coograph");
    const sessionsDir = join(logDir, "sessions");
    const stamp = ts();

    const globalLine = `[${stamp}] [${AGENT}] [${shortSid}] ${command}\n`;
    const perSessionLine = `[${stamp}] [${AGENT}] ${command}\n`;

    try {
      await mkdir(sessionsDir, { recursive: true });
      await appendFile(join(logDir, "session.log"), globalLine, "utf-8");
      await appendFile(join(sessionsDir, `${sid}.log`), perSessionLine, "utf-8");
    } catch {
      // never block the tool call
    }
  },
});
