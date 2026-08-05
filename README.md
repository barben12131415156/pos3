# PSC-HELPER

**Current release:** 0.8.1.1 · **Official site:** [p-os.up.railway.app](https://p-os.up.railway.app) · **License:** [MIT](./LICENSE)

A self-hosted Discord bot for communities that need automated moderation, an in-character AI assistant (**P.OS**), application/complaint workflows, detailed audit logging, and media utilities such as on-the-fly GIF generation.

PSC-HELPER started in the [P.S.C. (Provision Security Complex)](https://github.com/Pembevich/PSC-HELPER) ecosystem and is offered **free of charge** for self-hosting.

## Who is this for?

**For Discord server owners who need free self-hosted moderation, AI assistance, application workflows, and audit logging.**

Typical use cases:

- Community servers that want layered automoderation without a paid SaaS bot
- Staff teams that need structured application and complaint forms
- Admins who want searchable audit trails across channels, roles, and moderation actions
- Servers that want a distinct AI persona with code-enforced safety boundaries around privileged tools

## Adoption / Community

PSC-HELPER is in early development. Public adoption figures are not published yet, and a dedicated project Discord server is still being prepared. Until then, use [GitHub Issues](https://github.com/Pembevich/PSC-HELPER/issues) for reproducible bug reports and feature proposals.

The project is free to self-host on Railway or other infrastructure; operators provide their own Discord and optional AI/reputation API credentials.

## Core features

- **Automated moderation** — canonical URL screening with Google Safe Browsing/VirusTotal support, attachment magic/archive checks, normalized spam detection, AI-assisted review, mass-mention protection, and persistent anti-raid state
- **P.OS AI assistant** — responds to mentions and replies, keeps conversational context, understands images and representative GIF/video frames, and can transcribe supported audio/video through Gemini
- **Owner-gated tools** — factual server inspection plus bans, timeouts, roles, channels, settings, and cross-server actions; owner commands execute directly, third-party requests require approval
- **Application workflows** — interactive forms for applications, reports, and staff review
- **Continuous security posture** — an initial audit plus persisted baselines for Discord MFA, verification/media filters, privileged roles, channel overwrites, bot permissions, webhooks, and AutoMod rules, with owner alerts on dangerous changes
- **Audit logging** — structured server event journals and a persistent, redacted history of P.OS tool activity and AI security detections
- **Media utilities** — adaptive `p.gif` conversion that preserves animation timing and searches for the best quality that fits the server upload limit
- **Grounded web research** — owner-only public HTTPS reading with DNS pinning, SSRF/redirect/content limits, optional Brave Search, and a Wikipedia fallback

## Security model (important)

High-privilege operations are **never delegated directly to the LLM**. The model may request actions through tool calls; `pos_ai.py` validates every argument against a closed schema, resolves targets to canonical Discord IDs, checks the current message's intent, permissions and role hierarchy, limits actions per turn, and protects the owner and bot before execution. Mutating requests do not expose channel history or visual payloads to the action-selection context.

The only direct privileged operator is Pumba, identified by the immutable Discord user ID `968698192411652176`. This trust boundary cannot be expanded through an environment variable. Pumba's verified Discord actions execute immediately and return the factual API result. A state-changing request from anyone else is sent to Pumba's DM for explicit button approval and expires after 10 minutes. Process shutdown still requires Pumba's separate confirmation.

AI moderation findings are advisory unless a deterministic signal or independently confirmed visual signal reaches the required confidence threshold. URL and file reputation also require corroborated verdicts before automatic punishment. This prevents a model response, one outlier scanner, or prompt-injected message from becoming an automatic punishment by itself.

Link reputation is optional and layered: local canonicalization and deception checks always run; Google Safe Browsing and VirusTotal run only when their keys are configured. Their caches are independent, and network/API failures are never stored as a safe verdict. Owner-requested web reading is isolated behind a separate public-HTTPS fetcher that rejects credentials, private/link-local/reserved IPs, revalidates every DNS answer and redirect, and bounds response types and sizes.

P.OS treats prompt injection as an expected hostile input, not as an authentication mechanism. Tools remain unavailable unless the current Discord message expresses a matching intent; authorization is bound to the immutable Discord ID in code. Injection detections are stored as hashes and reason labels without retaining the adversarial payload.

## Quick start (local)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env   # fill in DISCORD_TOKEN and AI keys
python main.py
```

Run tests:

```bash
python -m pip install -r requirements-dev.txt
pytest
```

System dependency: `ffmpeg` (see `apt.txt`) for video→GIF conversion.

## Railway deployment

Configure environment variables in Railway. A local `.env` is for development only.

### Required

| Variable | Description |
| --- | --- |
| `DISCORD_TOKEN` | Discord bot token |

### P.OS / AI (single-provider fallback)

| Variable | Description |
| --- | --- |
| `GITHUB_MODELS_TOKEN` | GitHub PAT with Models API access |
| `GITHUB_MODELS_MODEL` | Model id (default: `openai/gpt-4.1`) |
| `GITHUB_MODELS_ENDPOINT` | Default: `https://models.github.ai/inference/chat/completions` |
| `GITHUB_MODELS_API_VERSION` | Default: `2022-11-28` |

Legacy-compatible variables still work: `POS_AI_API_KEY`, `POS_AI_API_URL`, `POS_AI_MODEL`, `NVIDIA_API_KEY`, etc.

### Provider pool (rate-limit spreading)

| Variable | Description |
| --- | --- |
| `POS_AI_PROVIDER_KEYS` | CSV of API keys |
| `POS_AI_PROVIDER_URLS` | CSV of endpoints (index-aligned) |
| `POS_AI_PROVIDER_MODELS` | CSV of model names (index-aligned) |

Gemini-first example with a GitHub Models fallback:

```env
POS_AI_PROVIDER_KEYS=gemini_key,github_models_token
POS_AI_PROVIDER_URLS=https://generativelanguage.googleapis.com/v1beta/openai/chat/completions,https://models.github.ai/inference/chat/completions
POS_AI_PROVIDER_MODELS=gemini-3.6-flash,openai/gpt-4.1
```

An entry whose endpoint is on `googleapis.com` is treated as Gemini. P.OS uses
that entry first and can send bounded audio/video to Gemini's native
`generateContent` API; image/GIF/video-frame understanding still works when the
native media analysis is unavailable.

### Private Telegram relay (optional)

The relay uses a dedicated Telegram bot, not a personal Telegram account. It is
disabled unless all three identity variables are configured:

| Variable | Description |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Token for the dedicated relay bot |
| `TELEGRAM_OWNER_USER_ID` | Exact Telegram user ID allowed to answer requests |
| `TELEGRAM_OWNER_CHAT_ID` | Exact private chat where requests are delivered |

`TELEGRAM_CONTACT_MIN_INTERVAL_SECONDS`, `TELEGRAM_CONTACT_DAILY_LIMIT`,
`TELEGRAM_CONTACT_GLOBAL_HOURLY_LIMIT`, and
`TELEGRAM_CONTACT_MAX_PENDING_PER_USER` control abuse protection. Telegram
messages never expose the owner's username or chat ID to Discord users. Owner
replies are delivered by DM by default; `/public` explicitly posts a reply in
the source channel and `/dm` explicitly keeps it private.

### Other useful settings

- `POS_AI_SYSTEM_PROMPT` — optional owner context appended to the immutable P.OS identity and safety core
- `POS_AI_MAX_TOKENS`, `POS_AI_TEMPERATURE`, `POS_AI_TOP_P`, `POS_AI_TIMEOUT_SECONDS`, `POS_AI_MAX_CONCURRENT_REQUESTS`
- `PRIMARY_LOG_CHANNEL_ID`, `UPDATE_LOG_CHANNEL_ID`, `LOG_CATEGORY_ID`, `LOG_CATEGORY_NAME`
- `DB_BACKUP_CHANNEL_ID` — private Discord channel for gzip-compressed, integrity-checked SQLite backups (recommended on Railway)
- `GOOGLE_SAFEBROWSING_KEY`, `VIRUSTOTAL_KEY` — optional independent URL/file reputation sources
- `BRAVE_SEARCH_API_KEY` — optional independent full-web provider; a configured Gemini route enables Google Search grounding, then Brave/Wikipedia provide fallbacks as available
- `SECURITY_MONITOR_INTERVAL_SECONDS` — continuous Discord posture scan interval, clamped to 120-3600 seconds (default: 900)

See `.env.example` for the full list.

### Production security baseline

- Require 2FA for moderation, use an appropriate member verification level, and enable Discord's explicit-media filter for all members.
- Keep dangerous `@everyone` permissions and channel overwrites disabled. Place the P.OS role above the roles it must moderate and grant only the permissions reported by its initial security audit.
- Keep log and database-backup channels private, restrict webhook creation, and configure native Discord AutoMod as a separate fallback layer.
- Store tokens only in Railway variables, rotate any exposed credential, and enable both reputation providers when preparing a public server.

## Repository layout

| Path | Role |
| --- | --- |
| `main.py` | Entry point, cog loading, shutdown DB backup |
| `config.py` | Environment parsing, static Discord IDs, filter lists |
| `moderation.py` | Text/attachment filters, spam, AI moderation hooks |
| `antiraid.py` | Join-rate raid detection and reactions |
| `security_monitor.py` | Persisted Discord security posture snapshots and deterministic diffs |
| `pos_ai.py` | P.OS orchestration, context, tool execution policy |
| `ai_client.py` | OpenAI-compatible client with provider pooling |
| `media_intelligence.py` | Bounded image/GIF/video sampling and Gemini audio/video understanding |
| `web_research.py` | SSRF-safe public page reading and grounded owner-only research |
| `commands.py` | Генерация GIF для единственной пользовательской команды `p.gif` |
| `forms.py` | Application/report UI (views, modals) |
| `storage.py` | Serialized async SQLite persistence and backward-compatible gzip Discord backup/restore |
| `guild_config.py` | Per-guild settings merged with defaults |
| `logging_utils.py` | Log category/channel helpers |
| `cogs/` | Thin Discord event and command wrappers |

Cogs delegate to the top-level modules above. When changing behavior, edit the module, not only the cog.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md). Roadmap areas use labels: `good first issue`, `documentation`, `security`, `ai-system`, `moderation`.

## Releases

| Version | Notes |
| --- | --- |
| [v0.8.0](https://github.com/Pembevich/PSC-HELPER/releases/tag/v0.8.0) | Multi-server settings, expanded owner tools, AI-assisted moderation |
| [v0.8.1](https://github.com/Pembevich/PSC-HELPER/releases/tag/v0.8.1) | Raid quarantine default, owner ping/DM/lift tools, form fixes |
| [v0.8.2](https://github.com/Pembevich/PSC-HELPER/releases/tag/v0.8.2) | Technical publication tag for the completed P.OS 0.8.1 product line: security, reliability, GIF pipeline, `p.` prefix, and official site |
| [v0.8.3](https://github.com/Pembevich/PSC-HELPER/releases/tag/v0.8.3) | Final 0.8.1 site polish: automatic system theme selection with persistent Dark/Light override |
| [v0.8.1.1](https://github.com/Pembevich/PSC-HELPER/releases/tag/v0.8.1.1) | Current product patch: reliability, database recovery, moderation, AI tool execution, prompt-injection defenses, GIF quality, and continuous security monitoring |
| [v0.9.0](https://github.com/Pembevich/PSC-HELPER/releases/tag/v0.9.0) | Planned milestone (pre-release) |

## GitHub Models token hygiene

When using a fine-grained GitHub PAT, enable Models API access explicitly. If a token is exposed in a public channel or log, revoke it immediately and rotate Railway environment variables.

## License

MIT — see [LICENSE](./LICENSE).
