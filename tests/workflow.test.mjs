import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

const root = new URL("..", import.meta.url).pathname;
const pluginRoot = join(root, "plugins", "sentry");

test("Sentry remediation retains bounded stateless and review-only behavior", async () => {
  const skill = await readFile(join(pluginRoot, "skills", "remediate-issues", "SKILL.md"), "utf8");
  assert.match(skill, /native scheduler is only its clock/i);
  assert.match(skill, /previous 24 hours/i);
  assert.match(skill, /stateless/i);
  assert.match(skill, /Never merge, deploy, or release automatically/);
  assert.match(skill, /Do not resolve, archive, merge, assign, comment/);
});
