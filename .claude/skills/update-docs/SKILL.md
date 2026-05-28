---
name: update-docs
description: >
  Update all project documentation, repository metadata, and progress tracking
  when the codebase has significantly changed. Handles README (EN/CN), CLAUDE.md,
  CHANGELOG, pyproject.toml, GitHub About/description/topics, and release notes.
  CRITICAL: bilingual docs are written independently, NOT translated.
allowed-tools: [Read, Write, Edit, Bash, PowerShell, Glob, Grep]
triggers:
  - "更新项目文档"
  - "更新文档"
  - "更新 README"
  - "更新仓库信息"
  - "更新 about"
  - "同步项目进度"
  - "更新仓库"
  - "写文档"
  - "完善文档"
  - "文档同步"
  - "项目文档"
  - "仓库文档"
---

# Update Project Documentation Skill

When triggered, follow this workflow. Never skip steps.

## Phase 1: Assess Current State

1. Read the current state of all docs that may need updating:
   - `README.md` — English readme
   - `README.zh-CN.md` — Chinese readme
   - `CLAUDE.md` — project instructions for Claude
   - `CHANGELOG.md` — release history
   - `pyproject.toml` — version + description
2. Check current test count: `pytest tests/ -q`
3. Check current GitHub repo state: `gh repo view --json description,homepageUrl,topics`
4. Review recent commits since last release to understand what changed.

## Phase 2: Plan Content (Critical Step)

**Before writing a single word**, list what needs to change in each doc:

| Doc | What changed | Action |
|-----|-------------|--------|
| README.md | ... | add / rewrite / remove |
| README.zh-CN.md | ... | add / rewrite / remove |
| CLAUDE.md | ... | update table / test count |
| CHANGELOG.md | ... | add new version entry |
| pyproject.toml | ... | bump version / update description |
| GitHub About | ... | update description + topics |

## Phase 3: Write (Bilingual Rule — Most Important)

### The Golden Rule

**English and Chinese READMEs are written INDEPENDENTLY. Never translate.**

Translation produces unnatural Chinese that reads like machine output. Signs of bad translation:
- English word order forced into Chinese sentences
- Overly long sentences with too many clauses
- Stiff academic vocabulary where colloquial would be natural
- Directly translated metaphors that don't work in Chinese

### How to write each version

**English (README.md):**
- Direct, developer-oriented
- Explain the "why" explicitly
- Use concrete examples
- Active voice, present tense
- Short paragraphs, clear headings

**Chinese (README.zh-CN.md):**
- Natural Chinese engineering prose — write like a Chinese developer would
- Shorter sentences. Chinese reads faster. Be concise.
- The "why" is often implied through contrast, not spelled out
- Technical terms: use standard Chinese translations where they exist (不要中英混杂), but keep code identifiers in English
- Bullet points should be terse — one clause each
- Avoid: 进行/予以/有着/具有 — just say the verb directly

### Content parity, not translation parity

Both READMEs should cover the same topics, but the structure, emphasis, and phrasing differ:
- English might spend 3 sentences explaining a concept; Chinese might nail it in 8 characters
- Chinese might use a concrete analogy that resonates with Chinese developers; English might use a different one
- The order of sections may differ if one language flows better that way

## Phase 4: Update All Artifacts

1. **README.md** — write naturally in English
2. **README.zh-CN.md** — write naturally in Chinese, independently
3. **CLAUDE.md** — update architecture table, test count, any stale references
4. **CHANGELOG.md** — add new version entry with bullet-point summary
5. **pyproject.toml** — bump version if releasing, update description
6. **GitHub repo** — update About description, homepage URL, topics

Update GitHub repo with:
```bash
gh repo edit --description "..." --homepage "..."
gh repo edit --add-topic "..."  # repeat for each topic
```

## Phase 5: Verify

1. `ruff check . --fix --unsafe-fixes` — lint clean
2. `pytest tests/ -q` — all tests pass
3. `git diff --stat` — review what changed
4. Read both READMEs aloud in your head — does each sound natural in its language?

## Release Flow (if version bump needed)

```bash
python scripts/bump_version.py patch|minor|major
# Then follow standard-dev-workflow for the release PR.
```

## Common Mistakes to Avoid

- Don't just copy English README into Chinese and tweak wording — rewrite from scratch
- Don't use 进行 + verb (e.g., 进行操作 → just use the verb)
- Don't leave stale test counts in badges or body text
- Don't forget GitHub About — it's separate from README
- Don't forget to update `CLAUDE.md` architecture table when modules are added/removed
- Don't use machine-translation filler words like 此外、与此同时、值得注意的是
