import { readFile, writeFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";

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
  process.exit(result.status ?? 1);
}

const generated = await readFile(generatedTypesPath);
if (!original.equals(generated)) {
  await writeFile(generatedTypesPath, original);
  process.stderr.write(
    "Generated API types are out of date. Run `npm run codegen` and include the resulting file.\n",
  );
  process.exit(1);
}
