---
name: wrap-up-doc
disable-model-invocation: true
description: Report the finished task as a Claude artifact, a Bear note tagged guest-suite/claude-report, and a Slack DM with both links.
---

# Wrap-up

Turn the session's finished work into three linked deliverables, in this order — each later step embeds the links produced by the earlier ones:

1. a Claude artifact presenting what was done,
2. a Bear note tagged `guest-suite/claude-report` linking to the artifact,
3. a Slack DM to Raphaël with both links.

## 1. Collect

From the current session, gather: the original ask, what was done, decisions taken and their why, files/configs touched, and any external links already produced (PRs, tickets, dashboards). Done when every deliverable and every decision of the session is accounted for — a reader of the report can tell what changed and why without opening the transcript.

## 2. Artifact

Load the `artifact-design` skill, then write the report page to the scratchpad and publish it with the Artifact tool.

- The page presents the work clearly: what was asked, what was done, decisions and their rationale, and anything left open.
- Capture the artifact URL from the tool result — the note and the DM both need it.

## 3. Bear note

Use the full path (a `bearcli` symlink exists on PATH, but the app path is authoritative):

```
/Applications/Bear.app/Contents/MacOS/bearcli
```

Note conventions (Raphaël's, not Bear defaults):

- Title = the task topic.
- Tags come first, on top of the note body, then the body. Put `#guest-suite/claude-report` as the first line of the content and skip `--tags` (bearcli appends `--tags` at the position configured in Bear settings, which may not be the top).
- Body: a compact Markdown version of the report, ending with the artifact link.

Create from a scratchpad file and capture the note id:

```bash
/Applications/Bear.app/Contents/MacOS/bearcli create "<task topic>" --format json --fields id,title < note.md
```

The note link is `bear://x-callback-url/open-note?id=<id>`.

## 4. Slack DM

Send with `slack_send_message` to `channel_id: U0BMPQE4GQY` (Raphaël's member ID — a member ID as channel_id opens the DM).

The message is short: a few lines summarizing the task outcome, then both links — the artifact URL and the `bear://x-callback-url/open-note?id=<id>` link.

## Finish

End the turn with a confirmation restating both links so they are also reachable from the conversation.
