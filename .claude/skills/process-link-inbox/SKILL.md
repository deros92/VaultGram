---
name: process-link-inbox
description: Processes the queue of links captured by your personal Telegram bot and files them as notes in your Obsidian vault, following the conventions already in use there. Use this skill when the user asks to "process the links", "clear the Telegram inbox", or similar.
---

# Process Link Inbox

> **Template notice**: this skill ships with a generic, illustrative filing
> policy (fake folder names, fake examples). Before relying on it, edit
> section 3b/3c below to match **your own vault's actual structure** — the
> whole point of this skill is that it encodes decisions specific to how
> *you* organize *your* notes. Read your vault's own index/README files (if
> you have any) at the start of every run, the same way this skill's example
> does for its fictitious `Security/README.md`.

Processes the links accumulated through your personal Telegram bot (project
`VaultGram`) and turns them into organized notes inside
your Obsidian vault.

## Paths

- Script project: wherever you cloned this repo.
- Queue: `data/queue.jsonl` (one JSON object per line: `id, message_id,
  chat_id, date, url, note, status`; `status` can be:
  - `pending` — not processed yet
  - `processed` — archived with real content: gets cleaned up from Telegram
  - `duplicate` — a link already seen before (marked automatically by
    `fetch_links.py`), **must not be summarized again**: gets cleaned up
    from Telegram alongside `processed` items, **unless following its
    `duplicate_of` chain leads back to a `failed` item** — in that case the
    content was never archived anywhere, so the duplicate stays in the chat
    too, same treatment as a `failed` item (this typically happens when the
    user re-sends the same failed link hoping for a retry: that re-send does
    NOT trigger a new fetch attempt, it just gets queued as a `duplicate` of
    the original `failed` row — to actually get a retry, the user needs to
    supply new content, e.g. pasted text or a manual clip)
  - `failed` — content could not be recovered in any way (see step 3a):
    **cleanup always ignores it on purpose**, the Telegram message stays
    visible in the chat as a reminder until the user resolves it)
- Vault: your configured `vault_path` (see `config.local.json`).
- Visible inbox note: `<vault_path>/_Inbox/Pending Links.md` (regenerated
  automatically by the script — do not edit it by hand).

## Procedure

1. **Refresh the queue**: run `python fetch_links.py` in the project folder
   to bring `queue.jsonl` up to date and sync `_Inbox/Pending Links.md`.

2. **Read the queue**: open `data/queue.jsonl`, consider only rows with
   `status: "pending"`. If it's empty, tell the user and stop.

3. **For each pending link**:
   a. Try to fetch its content. If the direct fetch fails (403 / bot
      blocking), try a targeted web search on the URL/title before giving
      up: search engines often have enough indexed content/snippets to
      reconstruct a useful summary even when the page blocks direct
      fetching — in that case say so explicitly in the note (a `> ⚠️` block
      stating "summary reconstructed from search snippets, not the full
      text"), instead of presenting it as if you'd read the whole page. If
      the search also fails and there's no `note` from the user giving
      enough context (no content recoverable at all — e.g. LinkedIn behind a
      login, a persistent 403, JS-only content): **do not invent a summary
      and do not mark it `processed`**. Mark the item `failed` (see 3e) and
      move on — **do NOT delete the Telegram message of a `failed` item**:
      it must stay visible in the chat, it's the only way the user knows
      which links haven't been archived yet. If the user later supplies the
      content themselves (e.g. by clipping it manually into the vault), pick
      it up from there on the next run.

      **Known problematic platforms** — these are JS-heavy and/or login-walled,
      so don't spend a full fetch attempt expecting real content; go straight
      to the approach below (verified working as of this writing, not a
      guess):
      - **YouTube** (`youtube.com`, `youtu.be`): the watch page is almost
        entirely JS-rendered — a generic fetch gets little more than the
        `<title>`, no description, no view count, no transcript. Use the
        official oEmbed endpoint instead —
        `https://www.youtube.com/oembed?url=<video_url>&format=json` — for a
        reliable title + channel name + thumbnail, no API key needed. This is
        still not the video's actual content: a title and channel name are
        **not enough** to write a `processed` note. Mark it `failed` with
        that metadata in `fail_reason`, unless the user's own `note` gives
        real content to work with.
      - **TikTok** (`tiktok.com`): has a public oEmbed too —
        `https://www.tiktok.com/oembed?url=<video_url>` — returns the
        caption text, author, and thumbnail (a bit more than YouTube's, since
        the caption often *is* the content, but still not the video itself).
        If the caption gives enough substance, it's fine to use as the note's
        content (say so — "caption via oEmbed", not "watched the video");
        otherwise mark `failed` the same way.
      - **LinkedIn, Facebook, Instagram** (`linkedin.com`, `facebook.com`,
        `instagram.com`): no free/no-auth metadata endpoint exists for these
        (Meta locked oEmbed behind app tokens years ago), and *profile* pages
        are reliably blocked/empty. But **still attempt a direct fetch first,
        don't skip straight to search** — individual public *posts* are
        inconsistent: sometimes fully readable (text, comments, linked URLs)
        even though the profile behind them isn't, sometimes blocked outright
        (both have been observed in testing on real LinkedIn post URLs — it's
        not predictable from the URL alone). If the direct fetch comes back
        empty/blocked, move to the search fallback above; if that's also
        empty, mark `failed`.
      - **X/Twitter** (`x.com`, `twitter.com`): oEmbed used to be free but now
        returns HTTP 402 Payment Required — no working no-auth option as of
        this writing. Same treatment as LinkedIn/Facebook/Instagram: search
        fallback, then `failed`.

      The rule from above still applies to all of these: if all you actually
      have is a title/caption with no real substance, that's not enough for
      `processed` — mark it `failed` instead of writing a note that pretends
      to summarize content you never actually read or watched.
   b. Look at your vault's existing top-level folders and, if present, each
      one's index/README file, to understand what's already there and
      decide the destination. **Few, well-chosen notes per folder** — never
      one file per link. Decision criteria:
      - **Point-in-time event/news**, likely to recur over time (an
        incident, a release, an announcement): becomes a **section added at
        the top** of an existing topical log in the folder relevant to the
        event's subject (not necessarily the "obvious" one — e.g. a security
        breach involving an AI model belongs in a security-focused folder,
        not an AI-focused one, if that's how your vault is organized). If no
        relevant log exists yet and this is the first entry of a topic
        you expect to recur, create it (descriptive, plural name); if it's a
        one-off you don't expect to repeat, consider a dedicated note
        instead (next point).
      - **GitHub repo**: by default goes as a **compact section** in a
        `Notable_Repos.md` log in the folder relevant to the repo's topic —
        create it if it doesn't exist yet. A dedicated note only if the user
        explicitly says they're working with/deep-diving into it (not by
        default).
      - **Reference content** (guide, concept — not tied to a specific
        moment, and not a repo): deserves its **own dedicated note**.
      - None of the above fits well and the topic isn't covered by any
        existing folder: create a new subfolder.
   c. Write the content (log section or dedicated note) following your
      vault's own conventions. If you don't have established conventions
      yet, here's a reasonable starting point:
      - **raw/clipped content** as a dedicated note (a full article/post to
        preserve faithfully): frontmatter with
        `title / source / author / published / created / description / tags: [clippings]`;
      - **curated/synthesized dedicated note** (guide, concept, repo): plain
        markdown with headings;
      - **log section** (event): heading `## Title — YYYY-MM-DD`, line
        `**Source:** <url>`, then the summary;
      - **log section** (GitHub repo) — **compact, never an exhaustive
        README rehash, to avoid wasting tokens**: heading `## owner/repo —
        YYYY-MM-DD` (capture date), line `**Source:** <url>`, then ONLY these
        points:
        - **What it does**: 1-2 sentences, giving enough context to
          understand the project's domain/purpose even if the reader has
          never heard of it.
        - **Pros** / **Cons**: 2-4 bullets each, **an actual bullet list**
          (one line per point, not one semicolon-joined sentence). Each
          bullet must stand on its own: if it names a repo-specific detail
          (an output format, a mode, an internal mechanism), briefly explain
          what it means and why it's a pro/con — don't assume the reader
          knows the repo. Compact doesn't mean cryptic.
        - **Local models**: yes / no / partial, with the minimal detail that
          justifies it — **only include this field when relevant** (AI/LLM-
          related repos); omit it for unrelated repos instead of forcing it
          in.
        Stop there — no extra sections, no step-by-step install guide, no
        long quotes from the README.
      - **In all cases** (dedicated note or log section): the **source
        link** and the **publication date** of the original must appear
        visibly in the body (not only in frontmatter, which wouldn't be
        enough once a file has multiple entries) — if the publication date
        isn't available, use the link's capture date (`date` in
        `queue.jsonl`) and label it as such.
      - Claims with extraordinary numbers/events not verifiable from a
        primary source: a `> ⚠️ Critical note:` block at the top of the
        entry, instead of reporting them as established fact.
      - If the folder involved has (or deserves) an index/README file,
        update it with a line describing the new note or log.
   d. **Managing growing logs (token efficiency)**: a log file (like
      `Notable_Repos.md`) accumulates entries over months — don't re-read
      the whole thing on every run just to add one more entry at the top.
      - **The folder's README is the single pointer to the active file**
        once a log has been split (e.g. a line like `Notable_Repos_2027.md
        — active log, write new entries here`). You already read the README
        at the start of a run — finding out where to write costs nothing
        extra.
      - **To add a new entry**: entries go at the top of the active file
        (most recent first), so you only need the first ~20-30 lines (the
        anchor point right after the intro) to insert — not the whole file.
      - **When a log genuinely gets large** (rough guideline: once it's
        grown past a couple hundred lines, or covers a year or more of
        entries, or skimming it stops being quick — use judgment, there's no
        fixed number): split it by time period (rename the active file to
        include the period it covers, e.g. `Notable_Repos.md` →
        `Notable_Repos_2026.md`, and start a fresh `Notable_Repos_2027.md`
        for new entries) or by sub-topic if one is clearly dominating the
        log. Update the folder's README's pointer to the new active file —
        older files become a read-only archive.
      - **Duplicate checking, two layers, don't confuse them**:
        - *Exact same URL sent again* (even years apart) is already caught
          upstream, before you ever get involved: `fetch_links.py` checks
          every new link against the **entire history** of `queue.jsonl`
          (a flat, cheap-to-scan list of URLs — not vault prose), regardless
          of how the vault's own files have been split or archived. An item
          that reaches you as `pending` is, by construction, not a URL
          you've already queued before. Nothing to do here.
        - *A different URL about the same topic/repo* is NOT caught by
          that — this is where the **folder-wide entry index** below earns
          its keep.
      - **Folder-wide entry index (in the README, covers full history,
        not just the active file)**: maintain a running table in the
        folder's README — one compact row per entry ever added to *any* log
        in that folder, across every split/archive:
        ```
        | Date | Entry | File#Section |
        |---|---|---|
        | 2026-08-29 | owner/repo-name | Notable_Repos_2026.md#owner/repo-name |
        | 2027-03-10 | Some Incident Title | Notable_Incidents_2027.md#Some Incident Title |
        ```
        Append one row every time you write a new log entry or dedicated
        note (regardless of which physical file it landed in). Before
        writing something new, scan this table (cheap — one line per entry,
        it stays small even after years) to check whether the same
        topic/repo was already logged in an *older, archived* file that you
        otherwise wouldn't open. This is what actually solves cross-time
        duplicate topics — the "only check the active file's headings"
        shortcut from the point above is not enough on its own for that
        case, only for recent/same-period duplicates.
   e. Update the corresponding row in `queue.jsonl`:
      - successfully archived content: `status: "processed"` + a
        `destination` field with the path of the note/log created or
        extended (for a log section, use `file.md#Section Title`);
      - unrecoverable content (see 3a): `status: "failed"` + a
        `fail_reason` field with a short reason (e.g. "persistent 403, no
        content via search") — **no `destination`**, nothing was written to
        the vault.

4. **Regenerate `_Inbox/Pending Links.md`**: re-running `python
   fetch_links.py` at the end would only pick up new messages (it doesn't
   touch already-processed items), so regenerate the note yourself from the
   updated content of `queue.jsonl` (same logic as the script: a bullet list
   of the remaining `pending` items), so items just processed disappear from
   the list.

5. **Telegram cleanup**: run `python fetch_links.py --cleanup`. This
   automatically deletes (on both sides, without asking for confirmation —
   this is the default behavior once you've set it up this way) the original
   Telegram messages of items marked `processed`, and of `duplicate` items
   whose `duplicate_of` chain leads back to a `processed` item: the content
   now lives permanently in the vault, keeping it on Telegram too would just
   be a duplicate. **`failed` items are never touched by cleanup, and
   neither are `duplicate` items whose chain leads back to a `failed` one**
   (by design, `resolve_root_status()` + `CLEANUP_STATUSES` exclude both) —
   they stay in the chat on purpose, since that content was never archived
   anywhere. Older items without a saved `message_id`/`chat_id` (captured
   before this feature existed) are silently skipped, not an error.

6. **Final summary**: for each processed link, tell the user where it ended
   up (new or extended note, path). List `failed` items **separately and
   clearly** (URL + reason) — they're still in the Telegram chat and in
   `_Inbox/Pending Links.md`, waiting for the user to resolve them. Also
   report how many messages were deleted on Telegram.

## Example: illustrative filing policy (replace with your own)

The example below is **entirely fictitious** — no real vault has this exact
structure. It's here only to show the pattern in action; replace it with
your own folders and conventions in section 3b/3c above.

> Suppose a vault has `Security/`, `Programming/`, `Finance/` as top-level
> folders, and `Security/README.md` says: *"`Notable_Incidents.md` is a
> chronological log of security incidents; `Notable_Repos.md` is a compact
> log of interesting security-related repos; anything AI-security-related
> goes here too, not in `Programming/`, even if it involves an AI model."*
>
> A link about a company data breach → new section at the top of
> `Security/Notable_Incidents.md`, dated, sourced, with a critical-note
> block if the figures look unverified.
>
> A link to a GitHub pentesting tool → new compact section in
> `Security/Notable_Repos.md`, using the repo template from step 3c.
>
> A link to an in-depth tutorial on a specific technique, not tied to one
> event → its own dedicated note, e.g. `Security/OSINT_Techniques.md`.

## Security notes (do not change)

The authorized-sender filter (`allowed_user_id`) lives in `fetch_links.py`
and must be left as-is: it's the only control that stops anyone else who
messages the bot from ending up in the queue. Don't disable it for
debugging.
