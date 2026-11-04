# Install ember-cli with a local open-weights model

This guide takes a Windows PC with an NVIDIA GPU from a fresh `git clone` to a working
`ember-cli` that runs a local model and can search the web, fetch web pages and drive your
desktop. Everything on this page is done from the repository root.

This is the open-weights route: the model is a third-party open model (Qwen), downloaded
from Hugging Face. It is not an Ember-trained model, and using it does not change the
Ember training claims in the [repository README](../../README.md).

## Before you start

| You need | Notes |
|---|---|
| Windows 10 or 11 | The setup script and the automatic llama.cpp download are Windows only. Linux and macOS: see the last section. |
| An NVIDIA GPU with 6 GiB of VRAM or more, and the current NVIDIA driver (525 or newer) | `nvidia-smi` must work in a terminal. 24 GiB gives the best model. Without a GPU see "No GPU" under Troubleshooting. |
| git | To clone. Setup only warns if it is missing; the agent needs it to work with your repositories. |
| 30 GiB or more of free disk | The larger models are 15 to 20 GB. Choose another drive with `-ModelsDir`. |
| Internet access | github.com (llama.cpp runtime), huggingface.co (model), registry.npmjs.org (dependencies), bun.sh (only if Bun is missing). |

Installed for you by `Ember-Open-Setup`:

- Bun 1.2 or newer, the JavaScript runtime ember-cli runs on. If it is missing the script
  tells you what it will do and asks first; it installs into your user profile and needs no
  administrator rights.
- The ember-cli dependencies (`bun install`).
- The model, and the official llama.cpp runtime (`llama-server`) if the machine has none.

Not installed for you: git, the NVIDIA driver, Windows itself.

## The one command

```text
git clone <repository-url>
cd <repository-folder>
.\Ember-Open-Setup.cmd
```

The leading `.\` is needed in PowerShell (the default in Windows Terminal) and also works in
cmd.exe. To see what it would do without downloading anything, add `-DryRun`:

```text
.\Ember-Open-Setup.cmd -DryRun
```

It is safe to run again at any time. Finished steps are skipped, and when everything is in
place it prints "Nothing to do: everything was already set up" (only after a real run has
selected a model; `-DryRun` and `-SkipModel` instead list each step as "already in place"). If a step fails it stops with
one line saying what is wrong and one line saying how to fix it, then run the same command
again.

Options (all optional):

| Option | Effect |
|---|---|
| `-DryRun` | Do everything except download the model: the last step prints the model, quant and context it would pick. |
| `-Yes` | Do not ask before installing Bun (unattended runs). |
| `-ModelsDir <folder>` | Put the model files there instead of under the ember home. |
| `-EmberHome <folder>` | Use this ember home for this run (see "Where files go"). |
| `-Model <owner/repo[:QUANT]>` | Pull this model instead of the one ember would pick. |
| `-SkipModel` | Install Bun and the dependencies only. |
| `-Repull` | Pull again even though a working model is already selected. |
| `-AllowNoGpu` | Continue without an NVIDIA GPU (you must supply a CPU `llama-server`). |
| `-PullArgs '<args>'` | Extra arguments for `ember pull`, for example `'--no-calibrate'`. |

When it is started by double-clicking, the window waits for a key press at the end so you can
read the result. Set `EMBER_SETUP_NO_PAUSE=1` to turn that off.

## What the command does

1. **Prerequisites.** Checks the Windows version, git (warning only), the NVIDIA GPU and driver
   (CUDA 12 or newer is needed for the runtime ember downloads) and the free disk space.
2. **Bun.** Finds Bun, or installs it with the official installer after asking. Requires 1.2.0
   or newer.
3. **Dependencies.** Runs `bun install --production --frozen-lockfile` in the ember-cli source
   folder and checks that ember-cli starts. Its version line ends with `SOURCE_UNBOUND`;
   that is normal in open-weights mode (no owned Ember model is bound) and not an error.
4. **Model and runtime.** Runs `ember pull` (below). If a working model is already selected in
   `models.json` this step is skipped.
5. **Summary.** Says what it did, what was already in place, and how to start ember.

`ember pull` is ember-cli's own command; the launcher for it is `Ember-Open pull`. It:

- reads your GPU and free VRAM and picks the best model from a fixed list that fits
  (see "Choosing a model");
- finds a `llama-server`, or downloads the official llama.cpp Windows CUDA build into the
  ember home (about 0.6 GB, sha256 verified);
- downloads the model from Hugging Face (resumable, sha256 verified) and starts it once to
  prove it loads. The selection is written to `models.json` only after that live load works;
- calibrates the model (see "Calibration").

## Choosing a model

`ember pull` ranks a built-in list (Qwen3.8-27B, Qwen3-Coder-30B-A3B, Qwen3-30B-A3B,
Qwen3-14B, Qwen3-8B, Qwen3-4B) and takes the best one that fits your free VRAM with at least an
8192-token context. Context size is preferred over a bigger quant. The budget is the smaller of
(total VRAM minus 2 GiB) and (free VRAM minus 0.5 GiB), so other programs that are using the GPU
make ember pick a smaller model.

See the choice before committing to a download:

```text
Ember-Open pull --dry-run
```

Example on a 24 GiB card with the GPU otherwise idle:

```text
[ember pull] device: NVIDIA GeForce RTX 4090; VRAM 24.0 GiB (23.4 free); RAM 63.6 GiB
[ember pull] stock llama.cpp (no turbo KV types): fit rule uses q8_0 KV
[ember pull] VRAM budget for weights + KV + buffers: 22.0 GiB
[ember pull] selected unsloth/Qwen3.8-27B-GGUF / Qwen3.8-27B-UD-Q4_K_XL.gguf (16.4 GiB), context 98304, KV q8_0/q8_0, estimated VRAM 21.2 GiB -- ...; vision projector mmproj-F16.gguf (0.86 GiB)
[ember pull] dry run: nothing downloaded or changed
```

On a machine with no `llama-server` yet, `--dry-run` also prints that a real pull will download
the official llama.cpp build; the dry run itself downloads nothing.

Typical results by card size. These are computed from the same fit rule `ember pull` uses
(standard llama.cpp, q8_0 KV cache, an otherwise idle GPU), not measured on each card. Your
`--dry-run` is the authority:

| VRAM | Model and quant | Context at pull time |
|---|---|---|
| 6 GiB | Qwen3-4B-Instruct-2507 Q4_K_M | 8192 |
| 8 GiB | Qwen3-4B-Instruct-2507 Q4_K_M | 32768 |
| 10 GiB | Qwen3-8B Q4_K_M | 32768 |
| 12 GiB | Qwen3-14B Q4_K_M | 8192 (tight) |
| 16 GiB | Qwen3-14B Q4_K_M | 49152 |
| 20 GiB | Qwen3.8-27B UD-IQ4_XS (vision) | 65536 |
| 24 GiB | Qwen3.8-27B UD-Q4_K_XL (vision) | 98304 |
| 32 GiB | Qwen3.8-27B UD-Q5_K_XL (vision) | 131072 |

On a 12 GiB card the rule picks the 14B model with a small context. If you want a longer
context instead, take the smaller model explicitly:

```text
Ember-Open pull Qwen/Qwen3-8B-GGUF:Q4_K_M
```

Calibration afterwards can raise the context, up to the model's native size, by switching the
KV cache to q4_0; the numbers above are the starting point, not the final setting. On one 24 GiB
RTX 4090 desktop, calibrating Qwen3.8-27B with the default 1 GiB of headroom selected a context of
131072, and `--headroom-mib 256` selected 262144 with q4_0 KV and speculative decoding.

To choose a model yourself, pass it as `<owner>/<repo>:<QUANT>`:

```text
.\Ember-Open-Setup.cmd -Model unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_XL
```

**If you already have the GGUF file:** put it in a folder and pass that folder as `-ModelsDir`
together with the matching `-Model`. The download step verifies the file's sha256 against
Hugging Face and skips the download when it is already complete.

## Calibration

After a fresh pull ember measures what this machine can do with the model and saves the
winning settings. You do not have to do anything; it takes several minutes and fills the GPU
while it runs, so do not start other GPU work. It:

- starts the model at its native context (for example 262144 for Qwen3.8-27B) and steps the
  context down until it loads while leaving 1 GiB of VRAM free;
- tries the q4_0 and q8_0 KV cache types;
- turns on multi-token-prediction speculative decoding (`--spec-type draft-mtp`) when the GGUF
  has the prediction head and the runtime supports it;
- checks recall of a fact planted at about 90 % of the context (needle test);
- retries with a smaller physical batch (`-ub`) if the memory does not fit.

The result is saved as `calibration\<model>.json` in the ember home and used from then on.
Useful options of `Ember-Open pull`:

| Option | Effect |
|---|---|
| `--calibrate` | Re-measure the model that is already selected; downloads nothing. |
| `--no-calibrate` | Skip calibration after a pull. |
| `--headroom-mib <n>` | VRAM every candidate must leave free (default 1024). A smaller value allows a longer context, for example 256 on a 24 GiB card, but leaves little room for anything else on the GPU. |
| `--skip-recall`, `--skip-slot` | Skip the long needle test, or the KV-slot save/restore test. |
| `--no-runtime-update` | Never download a llama.cpp runtime. |

## Where files go

The ember home is the `EMBER_HOME` environment variable, or `%USERPROFILE%\.ember` when it is
not set. A dry run creates nothing there. To keep a different location for every future terminal run
`setx EMBER_HOME "<folder>"` once and open a new terminal.

| What | Where |
|---|---|
| Selected model, server binary, context (`models.json`) | `<ember home>\models.json` |
| Model files and the load log of the last pull (`pull-smoke.log`) | `<ember home>\models` or the `-ModelsDir` folder |
| Downloaded llama.cpp runtime | `<ember home>\runtime\<release tag>` |
| Calibration results | `<ember home>\calibration` |
| Log of the model server ember starts | `<ember home>\llama_stderr.log` |
| Saved conversations | `<ember home>\sessions` |
| Computer-use screenshots | `<ember home>\screens` |
| Bun | `%USERPROFILE%\.bun` |

Setup itself writes nothing into the repository folder except `node_modules` in the ember-cli
source folder.

## Start ember

From the folder you want to work in:

```text
<repository-folder>\Ember-Open.cmd
```

Put the repository folder on your `PATH` to type `Ember-Open` from anywhere; from inside the
repository folder in PowerShell, write `.\Ember-Open`. The table below writes plain `Ember-Open`:

| Command | What it does |
|---|---|
| `Ember-Open` | Interactive session in the current folder. |
| `Ember-Open -p "task"` | One headless task: runs it, prints the answer, exits. |
| `Ember-Open pull --dry-run` | Show which model would be pulled. |
| `Ember-Open pull --help` | Options of `pull`. |

ember starts the model server itself when it starts and picks a free local port (from 8082
upward) every time, so there is nothing to configure and no server to start by hand. Do not
start `llama-server` yourself for ember. Inside a session, `/model status` shows the model
and server in use, and `/help` lists every command.

## Check that each feature works

Each check is one request to type into `Ember-Open`, or to run with `-p`. They show that the
model can use the tool; they do not prove the answer is right, so read the result.

**Model and file tools**

```text
Ember-Open -p "Create a file named hello.txt containing the word hello, then change it to goodbye, and show me the final contents."
```

The file appears in the current folder with the word `goodbye`.

**WebSearch** (needs internet; no account or API key)

```text
Ember-Open -p "Search the web for the latest stable release of Bun. Tell me the version number and give the source URL."
```

The answer names a version and a URL, and the session shows a WebSearch tool call. Search
asks DuckDuckGo, Brave and Wikipedia in parallel and merges the results.

**WebFetch** (needs internet and the model server)

```text
Ember-Open -p "Fetch https://example.com and tell me in one sentence what the page says."
```

The answer says the page is an example domain used for illustrations. WebFetch summarises the
page with the local model. If you see `[No model summary (...); returning page markdown]`
instead, ember could not reach the model server, see Troubleshooting.

**Computer use** (Windows only)

```text
Ember-Open -p "List the windows that are open on this computer, then take a screenshot of the first one."
```

The answer lists window titles; the screenshot is saved under `<ember home>\screens`. The
model can only look at the screenshot if the model has a vision projector (the 27B model does;
`ember pull` fetches it and turns vision on). Without one it works from the window's UI element
tree instead.

By default computer use is non-intrusive: it reads windows and uses UI Automation (invoke,
set a field, toggle, select, scroll), opens applications and closes only windows it opened.
It does not move your mouse or press keys. Typing keys and clicking at coordinates are off
until you opt in by setting `EMBER_COMPUTER_REAL_INPUT=1` in the terminal before starting
ember, and each use still asks for permission. Do not enable it on a desktop you are working
at, because the model then controls the real mouse and keyboard.

**MCP**

ember does not connect to external MCP servers yet. `Ember-Open --mcp` runs ember itself as an
MCP server over stdio, but it does not expose any tools in this version. Treat MCP as not
available until the MCP client lands (tracked in issue 2375).

## Update, re-run and uninstall

- **Update the code:** `git pull`, then `Ember-Open-Setup.cmd` again. It re-checks the
  dependencies and keeps the selected model.
- **Change the model:** `Ember-Open-Setup.cmd -Repull`, or `Ember-Open pull <owner>/<repo>:<QUANT>`.
- **Re-measure after a driver or hardware change:** `Ember-Open pull --calibrate`.
- **Uninstall:** delete the repository folder, the ember home folder, and (if you no longer want
  it) `%USERPROFILE%\.bun`. Setup changes nothing else on the machine, except Bun's entry in your
  user `PATH` if setup installed Bun.

## Troubleshooting

| What you see | Cause and fix |
|---|---|
| `Ember-Open-Setup.cmd` is not recognized ("... but was not found in the current location") | PowerShell does not run programs from the current folder unless you say so: write `.\Ember-Open-Setup.cmd`. Also check that you are inside the cloned repository folder. |
| `[FAIL] No NVIDIA driver found` | `nvidia-smi` is not on `PATH`. Install the current driver from nvidia.com and run setup again. |
| `[FAIL] NVIDIA driver ... supports CUDA ...` | The driver is too old for the runtime ember downloads (it needs CUDA 12 or newer). Update the driver (525 or newer). |
| `Bun is required and was not installed` | Setup did not install Bun because it was run unattended or you answered no. Run it with `-Yes`, or install Bun from bun.sh. |
| `Bun ... is older than the 1.2.0` | Run `bun upgrade`, then setup again. |
| `bun` is not found right after Bun was installed | The installer changes your user `PATH` for new terminals only. Open a new terminal, or just run setup again; `Ember-Open.cmd` also looks in `%USERPROFILE%\.bun\bin`. |
| `bun install failed` | No access to registry.npmjs.org, or the checkout has local changes to `package.json` or `bun.lock`. Check the connection and `git status`, then run setup again. |
| Running the `.ps1` directly says scripts are disabled | Use `Ember-Open-Setup.cmd`; it starts PowerShell with the execution policy bypassed for that one run. |
| `no candidate fits this machine; nothing changed`, and setup stops with "No model fits or loads on this machine right now" | Not enough free VRAM. Something else is using the GPU (a browser with video, a game, another model server); setup warns "Only N GiB of the VRAM is free" in step 1 when that is the case. Close it and check `nvidia-smi`. `ember pull` sizes the model to the memory that is free, not to the card's total. |
| The same message after a model was started and failed to load | The chosen model did not load in the free VRAM. Close other GPU programs, or pick a smaller model with `Ember-Open pull Qwen/Qwen3-8B-GGUF:Q4_K_M`. The load log is `pull-smoke.log` in the models folder. |
| Load log says `missing tensor` or `unknown model architecture` | The llama.cpp on the machine is older than the model. ember sees this itself and downloads the official llama.cpp build for your driver into `<ember home>\runtime`, once, then retries. Stepping the context down cannot fix this, so it does not try. Turn this off with `--no-runtime-update`. |
| `no ggml-org/llama.cpp release ... found` or `rate limited` | The runtime download needs the GitHub release listing. The unauthenticated limit is 60 requests per hour: wait and run setup again, or install llama.cpp yourself and set `EMBER_LLAMA_SERVER` to its `llama-server.exe`. Only builds that are at least 24 hours old are used. |
| A runtime download stopped half way | Run setup again. A runtime folder is reused only when it holds the file `.ember-runtime-complete`; otherwise it is fetched again. |
| The model download stopped | Run setup again; the download resumes and is checked against its sha256. |
| `Not enough disk` | Use `-ModelsDir <folder on a larger drive>`. |
| A port is in use | Nothing to fix: ember picks a free port from 8082 upward each time it starts. If ember cannot reach its server read `<ember home>\llama_stderr.log`. |
| `ember pull: unknown option ...` | A mistyped option. Options that are not recognised are refused; `Ember-Open pull --help` lists them. |
| `All search engines failed: ...` | WebSearch asks DuckDuckGo, Brave and Wikipedia in parallel and reports each failure by name. When all three fail, the network or a proxy is blocking them; one working engine is enough. |
| WebFetch returns `[No model summary ...]` | The model server is not running or not reachable. Start ember normally (it starts the server) and try again. |
| Computer use says `real_input_disabled` | `type_text` and `click_at` need `EMBER_COMPUTER_REAL_INPUT=1` (see above). The other actions need no opt-in. |
| The GPU is still busy after quitting ember | A model server from an earlier session may still be running. Look in `nvidia-smi` for a `llama-server` process that you started, and end that one from Task Manager. |
| No GPU | The model runs only with a CUDA GPU as set up here. For a CPU-only machine: run setup with `-AllowNoGpu`, install a CPU build of llama.cpp yourself, set `EMBER_LLAMA_SERVER` to its `llama-server.exe`, and expect only the 4B model to be considered and generation to be slow. |

## Limits of this release

- The vendored TurboQuant llama.cpp build (experimental low-bit KV cache types) cannot load
  Qwen3.8 models, because it does not know their multi-token-prediction tensors. For those models
  ember uses the official llama.cpp runtime and the standard KV cache types (q8_0, q4_0). The
  TurboQuant types are only available with a model that build can load. Setup does not install
  the TurboQuant build.
- KV-slot restore is not wired into normal use yet. Calibration measures whether saving and
  restoring a slot works, but ember does not yet use it to resume a conversation without
  re-reading it, so a long conversation is re-processed after a restart.
- The automatic llama.cpp download is Windows and NVIDIA only. The choice of runtime and model
  is made once at pull time; changing GPU needs `Ember-Open pull --calibrate`.
- The hardware table is computed, not measured on each card size.
- MCP is not available yet (see above).
- Computer use is Windows only, and keyboard and mouse input is opt in.

## Linux and macOS

The setup script is Windows only, and these steps have not been tested:

1. Install Bun 1.2 or newer (bun.sh).
2. In `src/ember/infrastructure/tools/ember-cli/src` run `bun install --production --frozen-lockfile`.
3. Install a current llama.cpp (`llama-server`) and set `EMBER_LLAMA_SERVER` to it.
4. Set `EMBER_OPEN_WEIGHTS=1` and `EMBER_SOURCE_ROOT` to the repository folder, then run
   `bun run entrypoints/main.ts pull --dry-run` from that source folder, and `pull` without
   `--dry-run` once the plan looks right. Start ember the same way without `pull`.

WebSearch and WebFetch should work there; computer use does not.
