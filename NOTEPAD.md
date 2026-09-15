# Product notepad

Implementation checklist. Checked items are covered by code and automated tests.

## Homepage

- [x] Replace the current "Did you know?" measurement copy with concise, sourced facts about MCP itself.
- [x] Remove the `destructiveHint` framework-count blurb and improve the dataset CTA.
- [x] Move measured frameworks above the fold.
- [x] Remove the Coverage section from the homepage.
- [x] Remove the subtitles beneath "New" and "Popular."
- [x] Make heading underlines and divider rules subtler and less visually dominant.
- [x] Make the navbar larger, including its height, link text, spacing, and click targets, while preserving mobile fit.
- [x] Open Settings in an accessible modal instead of navigating to a standalone page.
- [x] Fix the conflicting interaction between Search history and the MCP picker. Opening either closes search history.
- [x] Explain the apparent `2/5`: it is the count of same-revision captures, not a support score. The homepage and Settings now use that precise label and separately name incompatible and mismatched runs.

## News automation

- [x] Automatically refresh the ticker so news does not require manual updates.
- [x] Run a scheduled, fixed search across an approved list of MCP sources.
- [x] Extract title, publication date, source, canonical URL, and source-provided description without using an LLM to rewrite the story.
- [x] Reject stale, undated, inaccessible, or duplicate results. Source approval replaces keyword relevance guessing.
- [x] Sort accepted stories newest-first and regenerate `site/src/data/news.json`.
- [x] Run link checks and `scripts/validate_news.mjs`.
- [x] Replace the validator's hardcoded verification date with dynamic freshness validation.
- [x] Open a draft update pull request only when the generated feed changes.
- [x] Keep the deployed ticker static; discovery and validation happen before build time.

## Dataset and framework coverage

- Expand the dataset with more MCP capabilities, frameworks, tested versions, historical measurements, and source evidence.
- Required framework coverage:
  - LangChain
  - Claude Agent SDK
  - Vercel AI SDK
  - Antigravity
  - OpenAI Agents SDK
  - Pydantic AI
  - Pi
- Expand enterprise ecosystem coverage:
  - xAI/Grok agent SDKs and adapters
  - Google Gemini and Agent Development Kit
  - Microsoft Agent Framework
  - Microsoft Semantic Kernel
  - Microsoft Copilot Studio
- Measure concrete agent SDKs and adapters rather than model names alone.
- Verify exact packages, repositories, and tested versions before adding coverage.

## Copy and quality

- [x] Remove em dashes site-wide.
- [ ] Rewrite remaining UI copy to be concise, specific, natural, and free of filler.
- [x] Perform automated responsive QA across every route at 320, 375, 390, 768, and 1024px.
- [x] Audit every rendered internal link, local file, external-link behavior, and accessible name across all routes.
- [ ] Run `npm run audit:links -- --external` through an approved network path to verify all external response statuses.

## MCP Arena concept

- Let a user submit a real task.
- Run the task through four different MCP flows.
- Present anonymized outputs side by side.
- Let the user choose a favorite.
- Offer a "Set up in Arcade" action that configures the selected flow in Cursor.
- Preserve normal authentication and confirmation requirements for real actions.
