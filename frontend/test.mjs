import { build } from "esbuild";
import { mkdir } from "node:fs/promises";
import { spawnSync } from "node:child_process";

await mkdir(new URL(".test-build/", import.meta.url), { recursive: true });
await build({
  entryPoints: ["tests/studio.test.tsx"], bundle: true, platform: "node",
  format: "esm", packages: "external", outfile: ".test-build/studio.test.mjs",
});
const result = spawnSync(process.execPath, ["--test", ".test-build/studio.test.mjs"], { stdio: "inherit" });
process.exitCode = result.status ?? 1;
