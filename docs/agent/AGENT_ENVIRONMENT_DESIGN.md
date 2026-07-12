# QuantDinger — Multi-Agent Runtime Environments (Design)

| Item | Value |
|------|--------|
| Status | Draft (for review and phased rollout) |
| Audience | Maintainers and developers using Cursor, Claude Code, Codex, or similar coding agents |
| Repository | [QuantDinger](https://github.com/brokermr810/QuantDinger) — self-hosted quant stack: research, strategies, backtests, live trading |

---

## 1. Background and goals

### 1.1 Background

When multiple coding agents and IDE assistants (Cursor, Claude Code, OpenAI Codex, CLI/sandbox bots) work in the same repository without shared conventions, teams often see:

- Agents re-reading a very long README, wasting context and misreading intent;
- Guessed HTTP paths and payloads that do not match the backend;
- Accidental touches to secrets, production databases, or money-adjacent paths;
- Per-tool documentation that drifts from the repo.

### 1.2 Goals

Without locking into a single vendor, make this repository **stable and predictable** for many agent environments:

1. **Code collaboration** — When changing strategies, fixing bugs, or adding APIs, agents can quickly find directories and verification commands.
2. **Capability discovery** — Humans and machines can learn what is allowed, what is forbidden, and how to validate changes.
3. **Optional extensions** — MCP, OpenAPI, and similar layers can be added later without replacing this structure.

### 1.3 Non-goals (explicit for this phase)

- Not every agent product must support MCP.
- No real secrets, internal-only URLs, or production credentials in design docs.
- No promise of **fully unattended live trading** in v1; live and capital flows stay behind human review and explicit strategy boundaries.

---

## 2. Design principles

| Principle | Meaning |
|-----------|---------|
| **Single source of truth (SSOT)** | “How to work in this repo” for agents lives in one primary doc (see §8); the root README only indexes it briefly. |
| **Layered contracts** | Documentation (intent) → commands (local) → API / MCP (product capabilities). Upper layers may depend on lower ones; do not mix layers in one blob. |
| **Minimal context pack** | Token-limited environments get a short, linkable doc (quick path) instead of irrelevant full-tree context. |
| **Secure by default** | Secrets, `.env`, production writes, and undocumented order APIs are **not** encouraged for autonomous agents; red lines must be explicit in Layer 1. |
| **Decoupled from implementation** | This design states **what should exist**; filenames (e.g. `AGENTS.md`) may change at rollout time while semantics stay the same. |

---

## 3. Architecture — three layers

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1 — Documentation contract (humans + agents)         │
│  Repo map, red lines, recommended workflow, pointers to 2/3 │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  Layer 2 — Command contract (terminal / CI / CLI agents)    │
│  Stable scripts or Make: install, lint, test, docker compose │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  Layer 3 — Machine interfaces (HTTP / MCP, optional)        │
│  OpenAPI or equivalent schema; optional MCP tools (narrow)   │
└─────────────────────────────────────────────────────────────┘
```

### 3.1 Layer 1 — Documentation contract

**Role:** Any agent that can read repo text knows **where to start and how to self-check** without calling the network.

Suggested structure (may be split across files; one index is mandatory):

- Top-level directory roles (`backend_api_python/`, `frontend/`, `docs/`, `scripts/`).
- Indicator and strategy entry points (link to `docs/INDICATOR_DEV_GUIDE.md` and `docs/STRATEGY_DEV_GUIDE.md` — avoid duplicating long excerpts).
- **Red lines** — Never commit `.env`; never put secrets in docs or examples; money/live changes require human review.
- **Happy path** — e.g. “Python-only strategy change → how to bring up Docker → how to run backend tests” in 3–5 steps.

**Relationship to the root README** — README keeps user-facing install and product story; add a short “For coding agents” pointer to `docs/agent/`.

### 3.2 Layer 2 — Command contract

**Role:** Every action that should reproduce locally or in CI is exposed as a **small set of stable commands**, not ad-hoc shell one-liners.

Implementation choices (Make, `npm` scripts, `invoke`, etc.) are up to maintainers:

| Category | Example intent (names may vary) |
|----------|----------------------------------|
| Environment | Copy env template, generate secrets (aligned with `env.example`, `scripts/`) |
| Run | Documented equivalent of `docker compose up` / build |
| Quality | lint, format, typecheck (if adopted) |
| Tests | Backend unit/integration entrypoints matching the repo’s stack |

**Constraint:** One official entry per goal; if two spellings exist (`docker-compose` vs `docker compose`), document the recommended one and compatibility notes.

### 3.3 Layer 3 — Machine interfaces (optional evolution)

**Role:** When an agent or external tool must **drive product behavior** (health, listings, backtests), it must not rely on guessing HTTP.

- **HTTP + OpenAPI (or equivalent)** — Machine-consumable contract for REST; update the contract when routes change.
- **MCP (Model Context Protocol)** — Expose **narrow, auditable** operations as tools (e.g. read-only health, read-only strategy list). Write and trading tools need separate review and allowlists.

**Principle:** Layer 3 is additive; agents without MCP should still complete most code tasks via Layers 1 + 2.

---

## 4. Mapping to agent environments

Product names evolve; map by **capability**, not brand-only details.

| Environment | Primary layers | Notes |
|-------------|----------------|-------|
| **Cursor** | Layer 1 + optional `.cursor/rules`; optional MCP | Rules: permanent red lines and repo terminology; MCP aligns with Layer 3. |
| **Claude Code** | Layer 1 + Layer 2 | Heavy use of terminal and in-repo docs; Bash/PowerShell must be explicit. |
| **OpenAI Codex (CLI/IDE)** | Layer 1 + Layer 2 | Similar to Claude Code; avoid vendor-only config as the sole source of truth. |
| **Lightweight CLI / sandbox bots** | Minimal context pack in Layer 1 + Layer 2 | Mount one short file or system prompt instead of the whole tree. |
| **Vendor-hosted agents** | Layer 1 index + HTTP (Layer 3) | If only APIs are visible, OpenAPI and auth docs are critical. |

**Note:** For specific products (e.g. OpenClaw, NanoBot), add one appendix row at rollout: **product → config / protocol → which layer(s)**. No separate architecture fork.

---

## 5. Security and compliance boundaries

### 5.1 Data and secrets

- Keys, API tokens, and DB passwords come only from environment variables or local `.env` (and `.env` is gitignored).
- Design docs, agent rules, and `AGENTS.md`-style files must **not** contain real secrets or production connection strings; use placeholders in examples.

### 5.2 Capital and live trading

- Order placement, transfers, and exchange credential changes are **not** in unattended agent flows by default.
- If a subset is ever exposed via MCP, require auth, audit logs, rate limits, human toggles, and document in Layer 1.

### 5.3 Strategy code and multi-tenancy

- For multi-user deployments, distinguish **platform core** paths from **user strategy / plugin** paths so agents do not rewrite shared security logic.

---

## 6. Repository anchors (facts)

Keep implementation aligned with the current tree (update this section if layout changes):

| Area | Typical path | Agent focus |
|------|--------------|-------------|
| Backend API | `backend_api_python/` | Routes, services, `env.example` |
| Frontend | `frontend/` (includes prebuilt `dist`) | Matches README “Node optional” story |
| Ops / one-command stack | `docker-compose.yml`, `scripts/` | Layer 2 commands should mirror this |
| Indicator / strategy guides | `docs/INDICATOR_DEV_GUIDE.md`, `docs/STRATEGY_DEV_GUIDE.md`, localized variants | Layer 1 links; do not duplicate long guides |

---

## 7. Phased roadmap (suggested)

| Phase | Deliverable | Value |
|-------|-------------|--------|
| **P0** | `docs/agent/` index + one-line README link; red lines and repo map | One SSOT for all agents |
| **P1** | 3–5 official commands (scripts or Make) listed in docs | Fewer broken ad-hoc shells |
| **P2** | Exported or hand-maintained OpenAPI for the backend | Reliable integrations and codegen |
| **P3** | Optional MCP server (read-only first, then expand) | Deeper Cursor / Claude-style tooling |

Phases are independently reviewable; **P0 does not depend on P2/P3**.

---

## 8. Document and file checklist (for implementation)

- [x] `docs/agent/AGENT_ENVIRONMENT_DESIGN.md` — this design (English SSOT).
- [x] `.cursor/skills/quantdinger-agent-workflow/` — project Cursor skill (English) pointing agents here.
- [x] `docs/agent/README.md` — short Layer 1 index for `docs/agent/`.
- [ ] Root `README.md` — dedicated “For coding agents” subsection pointing to the index above.
- [ ] (Optional) Root `AGENTS.md` — industry-style filename; may forward to `docs/agent/`.
- [ ] (Optional) `.cursor/rules/` — repo-specific terms and red lines only; avoid duplicating Layer 1 at length.
- [ ] Layer 2 — `scripts/agent-*.sh` or Makefile targets (names TBD at implementation).
- [ ] Layer 2 — Windows PowerShell + Bash notes (consistent with root README).
- [ ] P2/P3 — OpenAPI location, MCP package location (separate ADR acceptable).

---

## 9. Open questions (for review)

1. **OpenAPI source** — Generate static JSON from Flask at runtime, or generate in CI and commit? Tradeoff: drift vs build deps.
2. **MCP packaging** — Monorepo next to the API vs small standalone repo for MCP-only installs?

**Resolved:** Agent-facing documentation and project `.cursor/skills/` are **English only**; human product docs may remain multilingual elsewhere in `docs/`.

---

## 10. Revision history

| Version | Date | Notes |
|---------|------|--------|
| 0.1 | 2026-05-02 | First draft: three layers, security, roadmap, checklist |
| 0.2 | 2026-05-02 | Language policy: agent design and project skills are English-only; consolidated from former CN draft |
