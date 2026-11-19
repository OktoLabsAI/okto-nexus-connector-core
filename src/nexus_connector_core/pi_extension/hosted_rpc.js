import { createHash } from "node:crypto";
import { readFile, realpath } from "node:fs/promises";
import { registerHooks } from "node:module";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { startHostedRenderer } from "./hosted_renderer.js";
import { fenceHostedRpcSteer } from "./hosted_steer.js";

// These files define the version-specific handoff between Pi's own CLI and RPC.
// Core also seals the selected installation's full artifact closure at launch.
const reviewed = {
  "package.json": "627631b613ba4ca29eba8df793f5280fd20b19f01d73826e9ffda14c15def5dc",
  "dist/bundle/cli.js": "e79626f2dd6f94aa45d30f3fa63cd84319a6eefcd150b353cfaf274366926774",
  "dist/main.js": "5a9473442cd761b21d07c374bb137967dd11474f5a7754d1c32f585e7b1a1f49",
  "dist/cli/setup.js": "4a2a7a0dbf82e2e5d18cec90896b36cbedce78b3d09e78d4040ac94fa3fbeba8",
  "dist/core/agent-session.js": "5ebfae51db5a900596145159428e7cb57d195af9d54a28f41d4ac8ff1bfd5729",
  "dist/modes/index.js": "42bd65ff8aee4f60dfcfcfb9db66772219281585cdbef845df747c8846618a87",
  "dist/modes/rpc/rpc-mode.js": "bdd94e753e6d19731d9fb9ea370462d095d64f1e78bddd7651320663fa57c4ff",
  "dist/modes/rpc/jsonl.js": "049a9f8ca4242c79f1911ed977949e8d8906b4561f424c2729687f426fabaacf",
  "dist/modes/interactive/interactive-mode.js": "7dc366e8609d7d1e81fb85952e466aea9933b13e74842c2a9b9df678d267d12e",
  "dist/modes/interactive/tui-renderer.js": "b215548e8deb8eb6b89b8e42f4d0c7fce57f728f54f22ab04a40b21971687ddb",
};

let handoff;
let filterInput;

export function attachOwnedRpcInput(attach, input, onLine) {
  return attach(input, filterInput ? filterInput(onLine) : onLine);
}

export async function runOwnedRpc(runtime) {
  const next = handoff;
  handoff = undefined;
  if (!next) throw new Error("Pi RPC owner handoff is unavailable");
  return next(runtime);
}

/** Run Pi's canonical settings, auth, resource loader and RPC on one owner. */
export async function runHostedPiRpc(cli, args, observeOwner, options) {
  if (process.platform !== "win32" || process.arch !== "x64" || process.version !== "v24.15.0") {
    throw new Error("The Node build is outside the reviewed Pi host");
  }
  if (args[0] !== "--mode" || args[1] !== "rpc") {
    throw new Error("The hosted Pi launch must select RPC");
  }
  const root = path.resolve(cli, "../../..");
  if (!path.isAbsolute(cli) || path.join(root, "dist", "bundle", "cli.js") !== cli) {
    throw new Error("The selected Pi entry point is invalid");
  }
  for (const [relative, expected] of Object.entries(reviewed)) {
    const filename = path.join(root, relative);
    if (await realpath(filename) !== filename ||
        createHash("sha256").update(await readFile(filename)).digest("hex") !== expected) {
      throw new Error("The selected Pi files are outside the reviewed host");
    }
  }
  const url = (relative) => pathToFileURL(path.join(root, relative)).href;
  const mainUrl = url("dist/main.js");
  const modesUrl = url("dist/modes/index.js");
  const rpcUrl = url("dist/modes/rpc/rpc-mode.js");
  // Substitute only the modes import made by the reviewed CLI. All other
  // modules, including Pi's own RPC implementation, resolve normally.
  const shim = "data:text/javascript," + encodeURIComponent(
    `export { InteractiveMode, runPrintMode } from ${JSON.stringify(modesUrl)};\n` +
    `export { runOwnedRpc as runRpcMode } from ${JSON.stringify(import.meta.url)};`,
  );
  const jsonlShim = "data:text/javascript," + encodeURIComponent(
    `import { attachJsonlLineReader as attach, serializeJsonLine } from ${JSON.stringify(url("dist/modes/rpc/jsonl.js"))};\n` +
    `import { attachOwnedRpcInput } from ${JSON.stringify(import.meta.url)};\n` +
    `export { serializeJsonLine };\n` +
    `export const attachJsonlLineReader = (input, onLine) => attachOwnedRpcInput(attach, input, onLine);\n`,
  );
  const { setupCli } = await import(url("dist/cli/setup.js"));
  let resolutions = 0;
  let inputResolutions = 0;
  const hooks = registerHooks({
    resolve(specifier, context, nextResolve) {
      if (context.parentURL === mainUrl && specifier === "./modes/index.js") {
        resolutions += 1;
        return { url: shim, shortCircuit: true };
      }
      if (context.parentURL === rpcUrl && specifier === "./jsonl.js") {
        inputResolutions += 1;
        return { url: jsonlShim, shortCircuit: true };
      }
      return nextResolve(specifier, context);
    },
  });
  let main, InteractiveMode, runRpcMode;
  try {
    ({ InteractiveMode, runRpcMode } = await import(modesUrl));
    ({ main } = await import(mainUrl));
  } finally {
    hooks.deregister();
  }
  if (resolutions !== 1 || inputResolutions !== 1) throw new Error("The reviewed Pi RPC handoff was not selected");
  handoff = async (runtime) => {
    await observeOwner(runtime, InteractiveMode);
    return runRpcMode(runtime);
  };
  setupCli();
  await main(args, options);
  throw new Error("The hosted Pi RPC owner returned unexpectedly");
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) {
  const [, , cli, ...args] = process.argv;
  const rendererKey = process.env.NEXUS_PI_RENDERER_KEY;
  delete process.env.NEXUS_PI_RENDERER_KEY;
  // Pi redirects ordinary stdout to diagnostics before it enters RPC mode.
  // Confirm one frame on the original pipe before starting the RPC reader.
  const writeProtocol = process.stdout.write.bind(process.stdout);
  void runHostedPiRpc(cli, args, async (owner, InteractiveMode) => {
    filterInput = fenceHostedRpcSteer(owner, writeProtocol);
    const port = await startHostedRenderer(InteractiveMode, owner, rendererKey);
    const notice = { type: "nexus_pi_owned_rpc", revision: 1, session_id: owner.session.sessionId, renderer_port: port };
    await new Promise((resolve, reject) => {
      writeProtocol(JSON.stringify(notice) + "\n", (error) => error ? reject(error) : resolve());
    });
  }).catch(() => {
    console.error("The reviewed Pi RPC owner could not start.");
    process.exitCode = 1;
  });
}
