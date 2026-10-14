# Engine options

Read for model/effort overrides, provider projection, optional engines.

- Defaults + engine-selection policy: [SKILL.md](../SKILL.md#engines).
- Explicit `gpt-6.1-sol`: same access-only `gpt-6-sol` retry.
  Explicit `gpt-6-sol`: access-only `gpt-6-luna` retry.
- Other explicit models, including Luna/Astra: no model fallback.
- Explicit `gpt-5.6-sol`: access-only `gpt-5.6-terra` retry.
- GPT-6.1 Sol rejects `none`/`minimal` effort before review preparation;
  GPT-6 Sol/Luna reject `minimal`. Effort-only override keeps default model.
- Honor explicit user engine/model choices. No automatic fallback between engines.

- Override defaults: `--engine`, `--model`, `--thinking`.
- Codex tier: Ultrafast when active model catalog lists it; otherwise Codex silently
  sends standard tier. Raw `--codex-config service_tier=...` keeps its value.
- `--codex-speed fast`: priority service. `--codex-speed default`: standard tier.
- Only Claude accepts `--fallback-model`.
- Per-engine environment overrides: `AUTOREVIEW_<ENGINE>_*`.

Account cannot access Sol/Luna: pin available model.
Require GPT-6 Astra without model fallback: select explicitly:

```bash
"$AUTOREVIEW" --mode local --model gpt-6-astra --thinking high
```

- GPT-6.1 Sol + GPT-6 Astra: `low`, `medium`, `high`, `xhigh`, `max`;
  neither supports `none`/`minimal`.
- GPT-6 Sol + Luna: additionally support `none`, never `minimal`.
- AutoReview default: `medium`; no fallback from explicit Luna/Astra selection.
- Codex `ultra`: automatic delegation; outside helper's supported effort levels.
  Deepest supported review: `max`.
- EU data residency: `--codex-speed default`; GPT-6 fast mode unavailable there.

See [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol),
[GPT-6 Sol](https://developers.openai.com/api/docs/models/gpt-6-sol), and
[GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) model docs
and [Codex reasoning modes](https://learn.chatgpt.com/docs/models#know-when-to-use-max-or-ultra).

Default: ChatGPT subscription; preserve only user authentication settings.
Live authentication failure → stop attempt fast; retry pass once on operator's
validated configured named command-auth route, including context + catalogue.
Definite credential failure → immediate stop; generic auth failure → stop after
3 lines within 60s. Single 401: allow Codex's reload/refresh recovery.
Explicit provider / non-auth failure / no valid configured route: no auth fallback.
Profile settings remain ignored. Force configured route before subscription attempt:

```bash
"$AUTOREVIEW" --mode local --codex-config 'model_provider="review_api"'
```

- Selector must match `model_provider` in operator's external `CODEX_HOME/config.toml`.
  Accepts one bare or simply quoted identifier; overrides cannot supply provider
  definitions or other capabilities.
- Projection requires Python 3.11 or `tomli`; default auth-only operation keeps
  existing fallback parser.

- Selected route must use `https://api.openai.com/v1` + command authentication
  with absolute external executable. Fixed arguments belong in executable's wrapper;
  omitted/empty `auth.args` accepted.
- Omitted `wire_api`/`requires_openai_auth`: keep Codex `responses`/`false` defaults,
  respectively. Optional auth timing/context settings: native defaults/semantics.

- POSIX: private launcher restores validated caller `HOME` only for selected
  authentication executable. Engine/reviewer tools keep isolated environment/filesystem access.
- Caller `HOME` must be available absolute directory; no repository-owned path
  or symlink provenance. Windows keeps native executable route.
- Command-auth runs: suppress raw provider diagnostics; report fixed failure
  categories; retain compact progress, usage, assistant report streaming.
- Command-auth runs use a separate empty file credential store, including on
  subscription fallback; they never inherit or refresh subscription credentials.
- Empty final report: fail without exposing captured stdout.

- Catalogue + authentication working-directory paths: resolve relative to operator
  config directory; must stay outside reviewed repository.
- Supplied catalogue: copy byte-for-byte into private client runtime;
  retries use same route/catalogue snapshot.
- Dry runs: same ownership/route shape checks; no authentication execution.
- Codex owns catalogue validation, model access, context clamping.
- Projection selected: other custom provider forms/split context overrides unsupported.

| Optional engine | Prerequisites                                                                                         |
| --------------- | ----------------------------------------------------------------------------------------------------- |
| Claude          | CLI 2.1.169+; safe mode with web-only tools                                                           |
| Amp             | `AMP_API_KEY` for a plugin-free account; local POSIX execution, no custom endpoint or cloud/orb agent |
| Pi              | CLI 0.79.0+; configured model; no tools or project resources                                          |

- `--engine kimi`: recognized, refused for reviews + `--dry-run` before any Kimi
  process, configuration read, or authentication setup.
- Supported Kimi Code prompt mode accepts review content only as command-line
  argument; helper has no supported private prompt input channel.
- Previous Kimi execution path intentionally retired; never expose bundle in
  process arguments. Existing `--kimi-bin` arguments accepted for same clear refusal.
- Never silently select another engine. Custom agent file ≠ equivalent replacement:
  changes input into templated system prompt.

## Native transport

`--engine native --native-stdio --engine-timeout-seconds <budget>` is a host
adapter contract, not a standalone CLI login. Stdin and stdout carry only binary
protocol frames; all human diagnostics and reports go to stderr. A directly
admitted trusted host can instead explicitly select `--native-fd <duplex fd>`.
These modes are mutually exclusive, POSIX-only, and never autodetected. Their
descriptors must be inherited pipes/sockets, not files, URLs, commands or paths.
Launch from the admitted repository root; Git resolving a different root fails.
The host owns the exact named-agent identity, requester restrictions, credentials,
and isolated inference admission. Model, effort, and credential overrides are
refused. The helper retains Git capture, prompt partitioning, evidence checks,
source attribution, complete-report validation, priority filtering, and final
drift rejection. No new report schema or weaker review gate is introduced.

Frames: four-byte big-endian UTF-8 JSON length, followed by that many bytes.
Every frame has `protocol: "autoreview-native-v1"` and `captureId`. The helper
sends `capture` (HEAD/index/working/evidence hashes, pass count); the host sends
`ready` for that capture. Each ordered `review` carries a one-based `pass`,
`promptSha256`, full `prompt`, and remaining `timeoutMs`. Reply `completion`
must echo capture/pass/prompt identity and contain `text` for canonical report
validation. After all passes and final drift checks, the helper sends `result`
with validated report, exit code, and evidence-coverage limits. The host must
require both that terminal frame and matching process exit before publishing it.
EOF, duplicate/out-of-order frames, malformed output, expired authority, or
transport failure never grants a clean outcome.

Limits: 512,000 UTF-8 prompt bytes per pass, 32 passes, 128 evidence manifest
entries, 4 MiB per frame, 8 MiB cumulative response frames, and one aggregate
deadline of at most 1,800 seconds. Backpressure consumes that same deadline.
Over-budget targets fail; nothing is truncated. The parent owns aborting,
joining, and cleaning up the helper and its private execution input. No native
dry-run can attest a host's runtime availability.

Adapters use an operator-installed canonical shared helper. They may pin its
source revision and SHA-256 metadata, but must not distribute a fork or vendor
its implementation/tests. Read and verify installed bytes once per adapter
lifecycle; execute those exact bytes through an immutable private copy or an
isolated interpreter's in-memory bootstrap to avoid a check-to-execution race.
Untrusted repository metadata must be inspected only inside its admitted
sandbox, never by a host helper against a shared projection. Reload after an
intentional installation update.

For the existing OpenClaw sandbox reaper, sanitized Git children retain only a
canonical UUID `CODEX_SANDBOX_EXEC_ID` membership marker. This non-secret value
grants no execution authority; other `CODEX_*` and credential variables remain
excluded. The adapter must preserve this marker through its bootstrap so
cleanup can join Git descendants even after the helper exits.
