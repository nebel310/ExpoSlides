import { build } from "esbuild";
import { mkdir } from "node:fs/promises";
import { spawnSync } from "node:child_process";

await mkdir(new URL(".test-build/", import.meta.url), { recursive: true });
await build({
  entryPoints: ["tests/studio.test.tsx", "tests/upload-form.test.tsx", "tests/slide-game.test.tsx", "tests/datasets.test.tsx", "tests/navigation.test.tsx"], bundle: true, platform: "node",
  format: "esm", packages: "external", outdir: ".test-build", outExtension: { ".js": ".mjs" },
});
const result = spawnSync(process.execPath, ["--test", ".test-build/studio.test.mjs", ".test-build/upload-form.test.mjs", ".test-build/slide-game.test.mjs", ".test-build/datasets.test.mjs", ".test-build/navigation.test.mjs"], { stdio: "inherit" });
process.exitCode = result.status ?? 1;
