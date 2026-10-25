import { execFileSync } from "node:child_process";
import { resolve } from "node:path";

// Read the canonical Python literal fixtures without importing application code,
// contacting providers, or creating a second independently maintained mock packet.
export const guidedSources = JSON.parse(
  execFileSync(
    "python3",
    [
      "-c",
      `
import ast,json,sys
module=ast.parse(open(sys.argv[1]).read())
values={}
for node in module.body:
 if isinstance(node,ast.Assign):
  for target in node.targets:
   if isinstance(target,ast.Name) and target.id in ('_INITIAL','_REVISED'):
    values[target.id]=ast.literal_eval(node.value)
print(json.dumps(values))
`,
      resolve("../app/guided_demo.py"),
    ],
    { encoding: "utf8" },
  ),
) as { _INITIAL: Record<string, unknown>[]; _REVISED: Record<string, unknown> };
