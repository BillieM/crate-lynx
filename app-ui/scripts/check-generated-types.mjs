import { readFile, writeFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";

const generatedTypesPath = new URL("../src/lib/api-types.ts", import.meta.url);
const original = await readFile(generatedTypesPath);
const result = spawnSync(
  "npx",
  ["openapi-typescript", "../openapi.json", "-o", "src/lib/api-types.ts"],
  {
    cwd: new URL("..", import.meta.url),
    encoding: "utf8",
  },
);

if (result.stdout) {
  process.stdout.write(result.stdout);
}
if (result.stderr) {
  process.stderr.write(result.stderr);
}
if (result.error) {
  throw result.error;
}
if (result.status !== 0) {
  const detail = (result.stderr || result.stdout || "No generator output")
    .trim()
    .split("\n")
    .slice(-3)
    .join(" | ")
    .replaceAll("%", "%25")
    .replaceAll("\r", "%0D")
    .replaceAll("\n", "%0A");
  process.stderr.write(
    `::error file=app-ui/src/lib/api-types.ts::API type generation failed (${result.status}): ${detail}\n`,
  );
  process.exit(result.status ?? 1);
}

const generated = await readFile(generatedTypesPath);
if (!original.equals(generated)) {
  const digest = (value) => createHash("sha256").update(value).digest("hex");
  await writeFile(generatedTypesPath, original);
  process.stderr.write(
    `::error file=app-ui/src/lib/api-types.ts::Generated API types differ (committed=${digest(original)}, generated=${digest(generated)})\n`,
  );
  process.stderr.write(
    "Generated API types are out of date. Run `npm run codegen` and include the resulting file.\n",
  );
  process.exit(1);
}
