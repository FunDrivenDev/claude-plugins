"""Unit tests of the handover plugin's YOLO guard (guard_hit in scripts/handover.py): a YOLO run may run the
plugin's own handover commands, and nothing else that names the plugin, its data or the settings that load it."""

import os
import sys
import tempfile
import unittest

HOME = tempfile.mkdtemp()
DATA = os.path.join(HOME, ".claude", "plugins", "data", "handover-fundrivendev")
os.environ.update(HOME=HOME, CLAUDE_PLUGIN_DATA=DATA)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "handover", "scripts"))

import handover as H

SCRIPT = os.path.join(H.plugin_root(), "scripts", "handover.py")
CALL = f'python3 {SCRIPT} --data-dir "{DATA}"'


def hit(command, tool="Bash"):
    key = "command" if tool == "Bash" else "file_path"
    return H.guard_hit({"tool_name": tool, "tool_input": {key: command}, "cwd": HOME})


class OwnCommands(unittest.TestCase):
    def test_the_handover_skill_may_request_a_handover(self):
        self.assertIsNone(hit(f"{CALL} request --cause model --session abc --reason 'context past 150K'"))

    def test_the_trigger_and_relay_requests_and_the_read_only_commands_pass(self):
        for args in ("request --cause user --session abc", "request --relay --cause user --session abc", "status"):
            self.assertIsNone(hit(f"{CALL} {args}"), args)
        self.assertIsNone(hit(f"{CALL} stats --json"))

    def test_commands_that_change_the_run_or_the_options_stay_denied(self):
        for args in ('config --set \'{"yolo_guard_paths": ""}\'', "afk --off --session abc", "hook", "write"):
            self.assertIsNotNone(hit(f"{CALL} {args}"), args)

    def test_anything_chained_to_an_own_command_stays_denied(self):
        for tail in (f"; rm -rf {DATA}", f"&& rm -rf {DATA}", f"> {SCRIPT}", f"| tee {SCRIPT}", "$(touch x)", "`x`"):
            self.assertIsNotNone(hit(f"{CALL} status {tail}"), tail)

    def test_a_dollar_or_a_line_break_is_denied_even_in_quotes(self):
        for reason in ("'costs $5'", "'a\nb'", '"$(touch x)"', "'`x`'"):
            self.assertIsNotNone(hit(f"{CALL} request --cause model --session abc --reason {reason}"), reason)

    def test_a_denied_own_command_is_named_for_the_refusal(self):
        # As an AFK run once sent it: the appended `echo rc=$?` made the guard deny the handover request.
        command = f"{CALL} request --cause model --session abc --reason 'done'; echo rc=$?"
        self.assertIsNotNone(hit(command))
        self.assertEqual(H.own_call_attempt(command), "request")
        self.assertIsNone(H.own_call_attempt(f"rm -rf {DATA}"))

    def test_another_script_under_the_plugin_stays_denied(self):
        other = os.path.join(H.plugin_root(), "scripts", "notify.py")
        self.assertIsNotNone(hit(f"python3 {other} request --session abc"))


def installed(*parts):
    path = os.path.join(HOME, ".claude", "plugins", *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("#!/bin/sh\n")
    return path


TOOLKIT = os.path.join("cache", "guest-suite", "gs-dev-toolkit", "4.49.1", "scripts")
PROOF = installed(TOOLKIT, "gs-review-proof.sh")
QGATE = installed(TOOLKIT, "qgate.sh")
CLONED = installed("marketplaces", "guest-suite", "plugins", "gs-dev-toolkit", "scripts", "qgate.sh")
OWN_INSTALLED = installed("cache", "fundrivendev", "handover", "0.20.0", "scripts", "handover.py")
IN_DATA = installed("data", "gs-dev-toolkit-guest-suite", "tool.sh")


class InstalledScripts(unittest.TestCase):
    def test_a_review_record_with_dollars_and_line_breaks_in_single_quotes_passes(self):
        record = '\'{"verdict": "validé",\n "note": "costs $5, `x` and $(y) stay text"}\''
        self.assertIsNone(hit(f"bash {PROOF} write --record {record} --head 55e9b8f"))

    def test_an_installed_script_runs_directly_or_through_an_interpreter(self):
        tilde = "~" + QGATE[len(HOME) :]
        for command in (f"{QGATE} --json", f"sh {QGATE}", f"bash {tilde} run", f"bash {CLONED}", f'"{QGATE}" -q'):
            self.assertIsNone(hit(command), command)

    def test_anything_chained_redirected_or_expanded_stays_denied(self):
        for tail in (
            "; rm -rf ~/.claude/plugins",
            "&& touch x",
            "| tee x",
            "> x",
            "--out $HOME/x",
            '--out "$HOME"',
            "`x`",
            "\nrm x",
            "~/.claude/plug*",
            "{a,b}",
        ):
            self.assertIsNotNone(hit(f"bash {QGATE} {tail}"), tail)

    def test_a_guarded_path_among_the_arguments_stays_denied(self):
        for arg in (DATA, "~/.claude/settings.json", "'~/.claude/'plugins", QGATE):
            self.assertIsNotNone(hit(f"bash {QGATE} --out {arg}"), arg)

    def test_a_shell_wrapper_or_an_interpreter_flag_stays_denied(self):
        for command in (f"bash -c {QGATE}", f"bash -c '{QGATE}'", f"eval {QGATE}", f"env {QGATE}", f"X=1 {QGATE}"):
            self.assertIsNotNone(hit(command), command)

    def test_a_copy_or_a_move_into_the_plugins_stays_denied(self):
        self.assertIsNotNone(hit(f"cp x {QGATE}"))
        self.assertIsNotNone(hit(f"mv {QGATE} x"))

    def test_a_plain_perl_call_of_an_installed_script_passes(self):
        # As gs-dev-toolkit's review workflow sent it 278 times on 2026-11-09 and 10, refused for want of perl.
        select = installed(TOOLKIT, "doc-select.pl")
        self.assertIsNone(hit(f"perl '{select}' --stack php --diff-files 'src/a.php,src/b.php'"))
        self.assertIsNotNone(hit(f"perl -e 'unlink q({select})'"))

    def test_this_plugins_own_scripts_and_scripts_outside_cache_and_marketplaces_stay_denied(self):
        for script in (OWN_INSTALLED, IN_DATA, os.path.join(H.plugin_root(), "scripts", "notify.py")):
            self.assertIsNotNone(hit(f"python3 {script} config --set x"), script)


class Guard(unittest.TestCase):
    def test_writing_the_plugin_or_its_data_is_denied(self):
        self.assertIsNotNone(hit(f"rm -rf {DATA}"))
        self.assertIsNotNone(hit("echo x >> ~/.claude/settings.json"))
        self.assertIsNotNone(hit(SCRIPT, tool="Edit"))
        self.assertIsNotNone(hit("claude plugin disable handover"))

    def test_reading_stays_free(self):
        self.assertIsNone(hit(SCRIPT, tool="Read"))
        for tool in ("Read", "Glob", "Grep"):
            self.assertIsNone(hit(INDEX, tool=tool), tool)

    def test_a_structured_result_naming_a_plugin_script_passes(self):
        # A workflow agent's result once quoted the qgate launch it ran, and was refused 57 times.
        out = {"tool_name": "StructuredOutput", "tool_input": {"command": f"bash {QGATE} launch --slug s"}}
        self.assertIsNone(H.guard_hit({**out, "cwd": HOME}))


KNOWLEDGE = os.path.join(HOME, ".claude", "plugins", "cache", "guest-suite", "gs-dev-toolkit", "4.61.0", "knowledge")


class ReadOnlyBash(unittest.TestCase):
    def test_a_bash_command_that_only_reads_other_plugins_files_passes(self):
        # The review workflow's knowledge listing, refused 502 times (agent-a711db52bd4bf16b6, 2026-11-09).
        listing = (
            f'W=/r/bim-4375; K={KNOWLEDGE}; echo "== knowledge"; '
            f'find "$K" -name \'*.md\' 2>/dev/null | sed "s|^$K/||"; '
            'echo "== composer"; jq -r \'(.require // {}) | keys[]\' "$W/composer.json" 2>/dev/null || echo ABSENT'
        )
        for command in (
            listing,
            f"ls -la {KNOWLEDGE} && head -40 {KNOWLEDGE}/php.md",
            f"git -C /r log -3 --oneline; git -C /r cat-file -p HEAD:x; cat {INDEX}",
            f"grep -E 'a|b;c' {INDEX}; grep -c \\; {INDEX}",
            f"R=/r; git -C $R ls-files; git -C $R config --get remote.origin.url; ls {KNOWLEDGE}",
            f'for f in {KNOWLEDGE}/*.md; do\n  wc -l "$f"\ndone',
            f"sed -n '1,60p' {INDEX}",
            f"sed -ne 1p {INDEX}",
            f"find {KNOWLEDGE} -name '*.md' -print",
            f"[ -f {INDEX} ] && cat {INDEX}",
            f"cat {KNOWLEDGE}/*.md",
            "grep -rn 'qgate' $HOME/.claude/plugins/cache 2>&1 | head -5",
            f"printf '%s\\n' {INDEX}; printf '%-20s|%b%%' a b",
            f"cat < {INDEX}",
            f'K={KNOWLEDGE}; for f in php.md; do test -f "$K/$f" && head -5 "$K/$f"; done',
            # An assignment before `&&` always runs.
            f"K={KNOWLEDGE} && find \"$K\" -name '*.md'",
            f"R=/tmp && git -C $R log -1; cat {INDEX}",
            # The thirteenth review: a descriptor before a redirection is no argument.
            f"git -C /tmp branch -a 2>/dev/null; ls {KNOWLEDGE}",
            f"git -C /tmp config --get user.name 2>/dev/null; cat {INDEX}",
            f"git -C /tmp remote -v 2>/dev/null; cat {INDEX}",
            f"cat {INDEX} 2>&-; cat {INDEX} 1>&2",
        ):
            self.assertIsNone(hit(command), command)

    def test_a_command_that_writes_runs_or_hides_what_it_runs_stays_denied(self):
        for command in (
            f"find {KNOWLEDGE} -name '*.md' -delete",
            f"X=-delete; find {KNOWLEDGE} $X",
            f"find {KNOWLEDGE} $X",
            f"sed -i '' 's/a/b/' {INDEX}",
            f"sed -n 's/a/b/w {INDEX}' /tmp/x",
            f"cat /tmp/x > {INDEX}",
            f"cat {INDEX} | tee {INDEX}.bak",
            f"ls {KNOWLEDGE}; rm -rf {KNOWLEDGE}",
            f"cat $(ls {KNOWLEDGE})",
            f"cat {INDEX} &",
            f"tail -f {INDEX}",
            f"sort -o {INDEX} {INDEX}",
            f"$CMD {INDEX}",
            f"cat <<EOF > {INDEX}\nx\nEOF",
        ):
            self.assertIsNotNone(hit(command), command)

    def test_what_bash_reads_otherwise_than_the_parse_stays_denied(self):
        # The bypasses a review of claude-plugins#80 ran: each one wrote or ran something under bash.
        for command in (
            f"ls {KNOWLEDGE}#; touch ~/PWN1",
            f"X='-name n -delete'; find {KNOWLEDGE} $X",
            f"X=-delete; X=a true; find {KNOWLEDGE} $X",
            f"X=a; for X in -delete; do find {KNOWLEDGE} $X; done",
            f"X=a; printf -v X %s -delete; find {KNOWLEDGE} $X",
            f"echo -delete; find {KNOWLEDGE} $_",
            f"find {KNOWLEDGE} ${{X:=-delete}}",
            f"find {KNOWLEDGE} $'-delete'",
            f'sed -n "1w {INDEX}" /dev/null',
            f"sed -n '$w {INDEX}' /dev/null",
            f"sed -n '/x/w {INDEX}' /dev/null",
            f"sed -n --expression='1w {INDEX}' /dev/null",
            f"sed -n -f /tmp/script {INDEX}",
            f"sed --in {INDEX}",
            f"git -C /r log -1 --output={INDEX}",
            f"git -C /r log -1 --out={INDEX}",
            f"find {KNOWLEDGE} -de\\\nlete",
            f"sort --o={INDEX} {INDEX}",
            f"sort --compress-program=sh {INDEX}",
            f"file -C -m {INDEX}",
            f"tail --fo {INDEX}",
            # The second review's bypasses (bash and zsh).
            f"GIT_EXTERNAL_DIFF='touch {INDEX};:' git diff --no-index {INDEX} {INDEX}",
            f"X='touch {INDEX};:' git --config-env=diff.external=X diff --no-index {INDEX} {INDEX}",
            f"git -C /r -ccore.fsmonitor='touch {INDEX};:' status",
            f"find {KNOWLEDGE} {{-delete,-print}}",
            f"X=-delete; find {KNOWLEDGE} $=X",
            f'Y=a; echo "${{(e)Y}}" {INDEX}',
            f"IFS=_; X=_-delete; find {KNOWLEDGE} -print$X",
            f"X=a; printf -vX %s -delete; find {KNOWLEDGE} $X",
            f'X=a; test -v "a[$X]"; cat {INDEX}',
            f"sed -n 's/a/b/w{INDEX}' {INDEX}",
            f"sed -n '\\%a%w {INDEX}' {INDEX}",
            f"sort -uo{INDEX} {INDEX}",
            f"tail -1f {INDEX}",
            f"rg --hostname-bin=/tmp/x --hyperlink-format=default a {INDEX}",
            f"PATH=/tmp; ls {INDEX}",
            # The third review's bypasses (bash and zsh).
            f"ls {KNOWLEDGE} #'\ntouch ~/PWN\n#'",
            f"X=DELETE; find {KNOWLEDGE} -$X:l",
            f"X=O; sort -$X:l {INDEX} {INDEX}",
            f"for IFS in _; do X=_-delete; find {KNOWLEDGE} -print$X; done",
            f"for PATH in /tmp/evil; do ls {KNOWLEDGE}; done",
            f"find {KNOWLEDGE} -dele*",
            f"sort {INDEX} *",
            f"READNULLCMD=sh; < /tmp/evil.sh; ls {KNOWLEDGE}",
            f"sed -ne '1w {INDEX}' {INDEX}",
            # The fourth review's bypasses (zsh with extendedglob, as Claude Code runs it, and bash).
            f"XY=a/-delete; find {KNOWLEDGE} $XY:t",
            f"find {KNOWLEDGE} -deletee#",
            f"find {KNOWLEDGE} ^pl",
            f"find {KNOWLEDGE} -delete~x",
            f"for x PATH in a pbin; do cat {INDEX}; done",
            f"for x do cat {INDEX}; done",
            f"for x in -v; do printf $x PATH pbin; cat {INDEX}; done",
            f"printf *; cat {INDEX}",
            f"test *; cat {INDEX}",
            f"[ * ]; cat {INDEX}",
            # The fifth review's bypasses: zsh printf arithmetic, bash 5.3 `test -v`, git's attached and abbreviated
            # options.
            f"printf %d 'HOME=[##36]-12'; file $HOME -m {INDEX}",
            f"printf '%*s' 'HOME=5' x; cat {INDEX}",
            f"printf '%1$s' x; cat {INDEX}",
            f"Y=a\\[\\$\\(touch\\ pwned\\)\\]; for X in v; do [ -$X 'a[Y]' ]; done; ls {KNOWLEDGE}",
            f"git -C {KNOWLEDGE} branch -uorigin/main",
            f"git -C {KNOWLEDGE} branch --unset-up",
            f"git -C {KNOWLEDGE} branch --edit",
            f"git -C {KNOWLEDGE} branch --delete-merged=x",
            f"R='-v a[Y]'; Y=a\\[\\$\\(touch\\ pwned\\)\\]; [ $R ]; ls {KNOWLEDGE}",
            f'for f in v; do [ "-$f" "a[Y]" ]; done; ls {KNOWLEDGE}',
            f'for f in -v; do [ "$f" "a[Y]" ]; done; ls {KNOWLEDGE}',
            f"for f in a; do test -f {KNOWLEDGE}/$f; done",
            f'for f in %d; do printf "$f" HOME=1; done; ls {KNOWLEDGE}',
            # The sixth review's bypasses: a later variable of a test word, git reflog write.
            f'ls {KNOWLEDGE}; A=\\$; Z="a[${{A}}(touch pwned2)]"; for Y in \' -a -v a[Z]\'; do [ "x$X"$Y ]; done',
            f"K=' -v'; [ \"x$X\"$K ]; ls {KNOWLEDGE}",
            f"git -C {KNOWLEDGE} reflog write HEAD 1 1 m",
            # The seventh review's bypasses: variables bash and zsh read, git subcommands that run the repository's
            # config (textconv, diff.external, core.fsmonitor, a transport, the editor), a null command.
            f"MODULE_PATH=/tmp/m; echo $WATCH; cat {INDEX}",
            f"EXECIGNORE=/usr/bin/cat:/bin/cat; cat {INDEX}",
            f"git -C {KNOWLEDGE} config edit",
            f"git -C {KNOWLEDGE} config edit --global",
            f"git -C {KNOWLEDGE} cat-file --te HEAD:f",
            f"git -C {KNOWLEDGE} cat-file --filters HEAD:f",
            f"git -C {KNOWLEDGE} diff",
            f"git -C {KNOWLEDGE} show HEAD",
            f"git -C {KNOWLEDGE} blame f",
            f"git -C {KNOWLEDGE} status",
            f"git -C {KNOWLEDGE} log -p",
            f"git -C {KNOWLEDGE} log --format=%G?",
            f"git -C {KNOWLEDGE} reflog show -p",
            f"git -C {KNOWLEDGE} describe --dirty",
            f"git -C {KNOWLEDGE} describe --dir",
            f"git remote show https://example.com/x; cat {INDEX}",
            f"< {INDEX}",
            f"cat {INDEX}; < {INDEX}",
            f"git log; cat {INDEX}",
            f"git -C r log; cat {INDEX}",
            f"git -C /r/../{KNOWLEDGE} log",
            f"git -C /r status; cat {INDEX}",
            # The tenth review: a quoted or escaped operator is a word, so the words after it belong to the same
            # command (`find x '<' -delete` deletes).
            f"find {KNOWLEDGE} '<' -delete",
            f"find {KNOWLEDGE} \\; cat -delete",
            f"find {KNOWLEDGE} ';' cat -exec sh -c 'id' ';'",
            f'find {KNOWLEDGE} "||" cat -delete',
            f"rg x {KNOWLEDGE} '<' --pre=/bin/sh",
            f"sort {INDEX} '<' -o/tmp/out",
            f"sort {INDEX} \\< -o/tmp/out",
            # The eleventh review: an assignment that may not run leaves `$X` empty, shifting the words after it;
            # `>&٣` is a file, not a descriptor; a keyword is no command before a lone redirection.
            f"[ a = b ] && X=p; sed -n -e $X 's/.*/x/w {INDEX}' {INDEX}",
            f"X=p | true; sed -n -e $X 's/.*/x/w {INDEX}' {INDEX}",
            f"for i in; do X=p; done; sed -n -e $X 's/.*/x/w {INDEX}' {INDEX}",
            f'cd {KNOWLEDGE}; [ a = b ] && X=/tmp; git -C "$X" ls-files',
            f"cd {KNOWLEDGE}; echo x >&\u0663",
            f"cat {INDEX}; if true; then < {INDEX}; fi",
            # The twelfth review: a block's nesting is not counted (a keyword not first, or quoted, fooled it); an
            # empty statement after `&&` keeps that separator; zsh skips an assignment whose redirection fails.
            f"! until true; do true; X=p; done; sed -n -e $X 's/.*/x/w {INDEX}' {INDEX}",
            (
                f"if true; then while [ a = b ]; do true; done; fi; while [ a = b ]; do true; X=p; done; "
                f"sed -n -e $X 's/.*/x/w {INDEX}' {INDEX}"
            ),
            f"while [ a = b ]; do true; 'done'; X=p; done; sed -n -e $X 's/.*/x/w {INDEX}' {INDEX}",
            f"! for i in; X=p; sed -n -e $X 's/.*/x/w {INDEX}' {INDEX}",
            f"[ a = b ] && \nX=p\nsed -n -e $X 's/.*/x/w {INDEX}' {INDEX}",
            f"X=p </nonexistent; sed -n -e $X 's/.*/x/w {INDEX}' {INDEX}",
            f"X=p >&9; sed -n -e $X 's/.*/x/w {INDEX}' {INDEX}",
            # The thirteenth review: the descriptor of `2>` is no printf format; a carriage return is in a word.
            f"Y=\\$; Z='(touch {KNOWLEDGE}/PW)'; printf 2>/dev/null %d 'path[${{(e)${{:-$Y$Z}}}}]'",
            f"printf 2>/dev/null -v HOME %s /tmp; git -C $HOME log -1; cat {INDEX}",
            f"sed -n -e 'p;'\r's/.*/x/w {INDEX}' {INDEX}",
            # The fourteenth review: only an unquoted descriptor against its operator is one, not a numeric argument.
            f"git -C /tmp branch 2 >/dev/null; cat {INDEX}",
            f"git -C /tmp branch '2'>/dev/null; cat {INDEX}",
            f"git -C /tmp branch 2&>/dev/null; cat {INDEX}",
            f"git -C /tmp branch \u00b2>/dev/null; cat {INDEX}",
            f"git -C /tmp config user.name 2 >/dev/null; cat {INDEX}",
            f"git -C /tmp config --global gc.auto 0 >/dev/null; cat {INDEX}",
            # The fifteenth review: zsh reads one digit as a descriptor (`12>` is the argument 12), and an escaped
            # blank opens no word.
            f"git -C /tmp branch 12>/dev/null; cat {INDEX}",
            f"git -C /tmp config k.x 12>/dev/null; cat {INDEX}",
            # The eighth review: git runs what a repository's own config names (gpg.program for a plain `log` with
            # log.showSignature, core.fsmonitor for ls-files or a `:path`): no git on a repository among the plugins.
            f"git -C {KNOWLEDGE} log -3 --oneline",
            f"git -C {KNOWLEDGE} branch -a --contains=HEAD",
            f"git -C {KNOWLEDGE} branch --show-current",
            f"git -C {KNOWLEDGE} reflog -5; git -C {KNOWLEDGE} reflog show HEAD",
            f"git -C {KNOWLEDGE} log -3 --format=%h%x09%s --name-only; git -C {KNOWLEDGE} describe --tags --always",
            f"git -C {KNOWLEDGE} cat-file -p HEAD:index.json; git -C {KNOWLEDGE} config --get remote.origin.url",
        ):
            self.assertIsNotNone(hit(command), command)

    def test_git_on_another_spelling_of_the_plugins_directory_stays_denied(self):
        # The ninth review: macOS reaches the plugins through the /System/Volumes/Data firmlink, which realpath keeps.
        os.makedirs(KNOWLEDGE, exist_ok=True)
        real = os.path.realpath(KNOWLEDGE)
        self.assertTrue(H.inside_plugins(KNOWLEDGE))
        self.assertFalse(H.inside_plugins(HOME))
        firmlink = "/System/Volumes/Data" + real
        if not os.path.isdir(firmlink):
            self.skipTest("no /System/Volumes/Data firmlink on this system")
        self.assertTrue(H.inside_plugins(firmlink))
        self.assertIsNotNone(hit(f"git -C {firmlink} log --oneline -1"))

    def test_reading_this_plugin_its_data_or_the_settings_by_bash_stays_denied(self):
        for command in (
            f"cat {SCRIPT}",
            f"ls {DATA}",
            "cat ~/.claude/settings.json",
            f"cat {INDEX} {DATA}/audit.jsonl",
        ):
            self.assertIsNotNone(hit(command), command)


INDEX = os.path.join(HOME, ".claude", "plugins", "cache", "x", "y", "index.json")


def reason(command, tool="Bash"):
    key = "command" if tool == "Bash" else "file_path"
    inp = {"tool_name": tool, "tool_input": {key: command}, "cwd": HOME}
    found = H.guard_hit(inp)
    return found and H.guard_reason(inp, found)


class Refusal(unittest.TestCase):
    def test_a_bash_read_of_another_plugins_file_is_pointed_to_the_reading_tools(self):
        # As a gs-knowledge-loading run once sent it: refused with "do the work another way", the agent gave up.
        for command in (
            "jq '.routes' ~/.claude/plugins/cache/x/y/index.json | python3 -m json.tool",
            f"ls {os.path.dirname(INDEX)} > /tmp/listing",
        ):
            got = reason(command)
            self.assertIsNotNone(got, command)
            self.assertIn("use the Read, Glob or Grep tool", got, command)
            self.assertIn("Writes stay refused", got, command)

    def test_a_call_of_an_installed_script_that_is_not_plain_is_told_how_to_run_it(self):
        # As a review launcher once sent it: the refusal named only the reading tools, so the script looked off limits.
        script = "~/.claude/plugins/cache/x/y/scripts/qgate.sh"
        for command in (f"bash {script} state-check --repo /r; echo done", f'bash {script} state-check --repo "$PWD"'):
            got = reason(command)
            self.assertIsNotNone(got, command)
            self.assertIn("one plain call", got, command)
            self.assertIn("use the Read, Glob or Grep tool", got, command)

    def test_the_plugins_own_files_its_audit_log_and_the_settings_keep_the_plain_refusal(self):
        audit = os.path.join(DATA, "audit.jsonl")
        for command in (
            f"cat {audit}",
            "jq . ~/.claude/settings.json",
            f"grep x {SCRIPT}",
            "ls ~/.claude/hooks",
            f"jq . {INDEX} {audit}",
            f"cat {INDEX}; claude plugin disable handover",
        ):
            got = reason(command)
            self.assertIsNotNone(got, command)
            self.assertNotIn("Read, Glob or Grep", got, command)
            self.assertIn("must leave", got, command)

    def test_an_edit_of_another_plugins_file_keeps_the_plain_refusal(self):
        got = reason(INDEX, tool="Edit")
        self.assertIsNotNone(got)
        self.assertNotIn("Read, Glob or Grep", got)

    def test_a_denied_own_command_keeps_its_own_refusal(self):
        got = reason(f"{CALL} request --cause model --session abc --reason 'done'; echo rc=$?")
        self.assertTrue(got.startswith("Denied: in this YOLO run, the plugin's own `request`"), got)


if __name__ == "__main__":
    unittest.main()
