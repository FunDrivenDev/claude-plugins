# Notifications

How the plugin calls you back to the keyboard: when the relay halts, when an AFK run ends (done, blocked, idle), waits on a prompt or stops on an API error. [Back to the README](../README.md)

## How it works

Every alert goes through one port, `Notifier.notify(title, message)` in `scripts/notify.py`. Adapters plug into it, and the `notifier` option picks which ones run. The terminal bell (the session's tmux pane, else `/dev/tty`) rings whatever the choice. An adapter that fails is ignored: the plugin goes on.

| `notifier` | Adapters | Needs |
|---|---|---|
| `auto` (default) | the desktop notifier of this environment, when it has one; plus `notify_command` when set | — |
| `macos` | `osascript` | macOS |
| `linux` | `notify-send` (GNOME, KDE…) | `libnotify-bin` on Ubuntu |
| `command` | `notify_command` only | the command's own tools |
| `bell` | none: the bell alone | — |

`notify_command` is run by `sh` with `HANDOVER_TITLE` and `HANDOVER_MESSAGE` in its environment, and the session's project as its working directory. The title and the message never go into the command line, so a message cannot inject shell. It must finish within 5 s.

## Which environment it detects

`auto` decides from where Claude Code runs:

| Detected | When | Desktop notifier |
|---|---|---|
| `macos` | macOS | `osascript` |
| `linux`, desktop | a display (`DISPLAY` or `WAYLAND_DISPLAY`) and a session bus (`DBUS_SESSION_BUS_ADDRESS`, or `$XDG_RUNTIME_DIR/bus`) | `notify-send`, when installed |
| `linux`, headless | no display (a server, an SSH session) or no session bus | none: set `notify_command` |
| `wsl` | `/proc/version` names Microsoft, or `WSL_DISTRO_NAME` is set | none: `notify-send` reaches no Windows desktop |
| `other` | any other platform | none |

Under tmux, Claude Code sees the environment of the tmux session: one started from a desktop terminal has its display, one started over SSH has none, even when you attach to it from the desktop later.

## Check it

```sh
python3 <plugin>/scripts/handover.py notifier          # what is detected and picked, as JSON
python3 <plugin>/scripts/handover.py notifier --test   # and send a test alert through it
```

`relay doctor check` and `relay notifier test` run the same ([FunDrivenDev/relay](https://github.com/FunDrivenDev/relay)). The report gives the environment, the adapters, `reaches_you` (false when only the bell rings) and `hints`: what to install or set. It says whether `notify_command` is set, never its value.

## Configure it

With `/handover:config`, in `/config`, with `claude plugin configure handover@fundrivendev`, or in `settings.json`:

```json
{
  "pluginConfigs": {
    "handover@fundrivendev": {
      "options": {"notifier": "auto", "notify_command": "$HOME/.local/bin/handover-notify-slack"}
    }
  }
}
```

Give the command as an absolute path (`$HOME` is expanded): the hooks' `PATH` may not hold `~/.local/bin`. Keep secrets (a webhook URL, a token) out of `settings.json`: the command reads them from the keyring or a private file.

## Slack

### A channel, through an incoming webhook

1. At api.slack.com/apps, create an app in your workspace, turn on **Incoming Webhooks**, **Add New Webhook to Workspace**, pick the channel (`#claude-afk`, or your own DMs), and copy the URL.
2. Store the URL where only you read it:

   ```sh
   # Ubuntu desktop (sudo apt-get install libsecret-tools)
   secret-tool store --label='handover Slack webhook' service handover-slack
   # macOS
   security add-generic-password -U -a "$USER" -s handover-slack -w '<url>'
   # A server without a keyring
   mkdir -p ~/.config/handover && (umask 077 && printf '%s' '<url>' >~/.config/handover/slack-webhook)
   ```

3. Save this as `~/.local/bin/handover-notify-slack`, then `chmod +x` it:

   ```sh
   #!/bin/sh
   # Posts a handover alert to Slack through an incoming webhook.
   set -eu
   url=$(secret-tool lookup service handover-slack 2>/dev/null ||
     security find-generic-password -a "$USER" -s handover-slack -w 2>/dev/null ||
     cat "${XDG_CONFIG_HOME:-$HOME/.config}/handover/slack-webhook")
   PROJECT=$(basename "$PWD") HOST=$(hostname) \
     SESSION=$(tmux display-message -p '#S' 2>/dev/null || echo -) \
     python3 -c '
   import json, os
   e = os.environ
   text = "*{}*: {}\n`{}` on {}, tmux session `{}`".format(
       e["HANDOVER_TITLE"], e["HANDOVER_MESSAGE"], e["PROJECT"], e["HOST"], e["SESSION"])
   print(json.dumps({"text": text}))' |
     curl -fsS -m 4 -H 'Content-type: application/json' --data @- "$url" >/dev/null
   ```

4. Set `notify_command` to `$HOME/.local/bin/handover-notify-slack` (keep `notifier` on `auto` to get the desktop notification too, or `command` for Slack alone), then send a test: `handover.py notifier --test`.

A message reads: **Claude Code handover**: AFK run done: CI is green · `my-repo` on `dev-box`, tmux session `afk-my-repo`.

### Any channel, with a mention, through a bot token

To post in a shared channel and ping yourself, use a bot instead: give the app the `chat:write` scope, install it, invite it to the channel (`/invite @<app>`), and store its `xoxb-…` token as above (`service handover-slack-bot`). In the script, build the payload with the channel ID and your member ID (Slack profile, **Copy member ID**), and post it to `chat.postMessage`:

```sh
token=$(secret-tool lookup service handover-slack-bot)
python3 -c '
import json, os
e = os.environ
print(json.dumps({"channel": "C0123456789", "text": "<@U0123456789> *{}*: {}".format(e["HANDOVER_TITLE"], e["HANDOVER_MESSAGE"])}))' |
  curl -fsS -m 4 -H "Authorization: Bearer $token" -H 'Content-type: application/json; charset=utf-8' \
    --data @- https://slack.com/api/chat.postMessage >/dev/null
```

## Other channels

- **ntfy** (a phone, no account): `curl -fsS -m 4 -H "Title: $HANDOVER_TITLE" -d "$HANDOVER_MESSAGE" ntfy.sh/<a-topic-only-you-know>` as `notify_command`, with the ntfy app subscribed to that topic.
- **WSL**: no desktop notifier is detected; use Slack or ntfy, or a Windows-side tool called through `powershell.exe` from your command.
- **A new built-in adapter**: a class with a `name` and a `notify(title, message)` method returning whether it got through, added to `_pick()` in `scripts/notify.py` with its `notifier` value, and to `tests/notify.py`.
