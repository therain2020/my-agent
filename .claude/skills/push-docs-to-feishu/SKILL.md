---
name: push-docs-to-feishu
description: >
  Push local project Markdown documents to Feishu Wiki using lark-cli.
  Handles creation (docs +create v2), wiki move, UTF-8 encoding, rate limiting,
  and CLAUDE.md reference updates. Two-step pipeline: create docx + move to wiki.
allowed-tools: [Read, Write, Edit, Bash, PowerShell, Glob, Grep]
triggers:
  - "推送文档到飞书"
  - "上传文档到飞书"
  - "同步文档到飞书"
  - "push docs to feishu"
  - "飞书文档"
  - "同步到飞书"
  - "推到飞书"
  - "上传到知识库"
---

# Push Docs to Feishu Wiki Skill

Push local Markdown files to a Feishu Wiki space using lark-cli.

## Prerequisites

- `lark-cli.exe` at `D:\GitHub\larksuite-cli\lark-cli.exe`
- Authenticated (`lark-cli wiki +space-list` returns `"ok": true`)
- Target wiki space ID: `7644823612574141651` (Agent 设计文档)

## The Pipeline

Each document goes through a two-step pipeline:

```
1. docs +create --api-version v2 --content @file --doc-format markdown --title "..."
   → returns document_id
2. wiki +move --obj-type docx --obj-token <doc_id> --target-space-id <space_id>
   → moves into wiki space
```

## Phase 1: Assess

1. List local docs to push: `Get-ChildItem <dir> -Filter "*.md"`
2. Check which ones already exist in the wiki (optional — use `wiki +space-list` and `wiki +node-list` to check)
3. Report: "Found N docs. M new, K already in wiki."

## Phase 2: Push

Use this PowerShell pattern. **Critical rules:**

- **UTF-8 no BOM**: `[System.Text.UTF8Encoding]::new($false)` — never use `Out-File -Encoding utf8`
- **Relative paths**: `Set-Location` to lark-cli directory before each call
- **Rate limit**: `Start-Sleep -Seconds 2` between each doc
- **Shell CWD**: lark-cli resets working directory after each call; always `Set-Location` before calling

```powershell
$cli = "D:\GitHub\larksuite-cli\lark-cli.exe"
$spaceId = "7644823612574141651"
$tmpDir = "D:\GitHub\larksuite-cli"

foreach ($f in Get-ChildItem $sourceDir -Filter "*.md" | Sort-Object Name) {
    $title = $f.BaseName -replace '-', ' '
    if ($title.Length -gt 60) { $title = $title.Substring(0, 60) }
    $content = [System.IO.File]::ReadAllText($f.FullName, [System.Text.UTF8Encoding]::new($false))
    [System.IO.File]::WriteAllText("$tmpDir\tmp-md.txt", $content, [System.Text.UTF8Encoding]::new($false))
    
    # Step 1: Create docx
    Set-Location $tmpDir
    $raw = & $cli docs +create --api-version v2 --content "@tmp-md.txt" --doc-format markdown --title "$title" 2>&1 | Out-String
    Set-Location "D:\GitHub\therain2020-agent"
    
    if ($raw -match '"document_id":\s*"([^"]+)"') {
        $docId = $matches[1]
        # Step 2: Move to wiki
        Set-Location $tmpDir
        $moveResult = & $cli wiki +move --obj-type docx --obj-token $docId --target-space-id $spaceId 2>&1 | Out-String
        Set-Location "D:\GitHub\therain2020-agent"
        if ($moveResult -match '"ok":\s*true') { Write-Host "  OK: $title" } else { Write-Host "  MOVE FAIL: $title" }
    } else { Write-Host "  CREATE FAIL: $title" }
    Start-Sleep -Seconds 2
}
Remove-Item "$tmpDir\tmp-md.txt" -ErrorAction SilentlyContinue
```

## Phase 3: Update References

After successful upload, update `CLAUDE.md` to add the new docs to the Design Reference or Project Docs table.

The wiki space URL is: `https://ycn21rm70xup.feishu.cn/wiki/space/7644823612574141651`

## Common Pitfalls

| Symptom | Cause | Fix |
|---------|-------|-----|
| `--data invalid JSON format` | File has UTF-8 BOM from `Out-File -Encoding utf8` | Use `[System.Text.UTF8Encoding]::new($false)` |
| `cannot read file "tmp-md.txt"` | CWD was reset by previous lark-cli call | `Set-Location $tmpDir` before every CLI call |
| `--content is required` | Using v1 syntax (`--markdown`) with v2 API | Use `--content @file --doc-format markdown` |
| First 18 docs OK, rest fail | Rate limiting | `Start-Sleep -Seconds 2` minimum |
| `unknown flag: --wiki-space` | v2 API removed this flag | Two-step: create + wiki move |

## Target Directories

| Local path | Content type | Wiki section |
|-----------|-------------|-------------|
| `D:\GitHub\agent-design\temp\` | 设计文档 (30篇) | Root of wiki space |
| `D:\GitHub\therain2020-agent\docs\` | 项目文档 (5篇) | Root of wiki space |
