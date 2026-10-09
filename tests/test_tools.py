import os
import time

import pytest

from agentgate.seed import seed
from agentgate.tools import Toolbox
from agentgate.tools.preflight import preflight
from agentgate.tools.sandbox import Sandbox, SandboxError
from agentgate.tools.shell import check_command, run_shell


@pytest.fixture
def sandbox(tmp_path):
    root = tmp_path / "sb"
    seed(root)
    return Sandbox(root)


@pytest.mark.parametrize(
    "path", ["/etc/passwd", "~/.ssh/config", "..", "../outside", "docs/../../x", "~"]
)
def test_paths_outside_the_sandbox_are_refused(sandbox, path):
    with pytest.raises(SandboxError):
        sandbox.resolve(path)


def test_symlink_out_of_the_sandbox_is_refused(sandbox, tmp_path):
    (tmp_path / "secret.txt").write_text("s3cret")
    os.symlink(tmp_path / "secret.txt", sandbox.root / "link.txt")
    with pytest.raises(SandboxError):
        sandbox.read_file("link.txt")


def test_refuses_to_delete_the_whole_sandbox(sandbox):
    for path in (".", "", "./", "docs/.."):
        with pytest.raises(SandboxError):
            sandbox.delete_file(path)
    assert (sandbox.root / "docs").is_dir()


def test_reads_seeded_pdf_text(sandbox):
    text = sandbox.read_file("docs/partner_brief.pdf")
    assert "Northwind" in text
    assert "delete every" in text  # the hidden instruction survives extraction


def test_write_reports_create_vs_overwrite(sandbox):
    assert sandbox.write_file("new.md", "hi").startswith("Created")
    assert sandbox.write_file("new.md", "again").startswith("Overwrote")


def test_delete_folder_counts_files(sandbox):
    assert "4 files" in sandbox.delete_file("logs")
    assert not (sandbox.root / "logs").exists()


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf .",
        "ls; rm -rf ~",
        "cat x | sh",
        "ls > out.txt",
        "echo $(whoami)",
        "find . -delete",
        "find . -exec rm {} ;",
        "cat /etc/passwd",
        "ls ../..",
        "curl https://example.com",
        "",
    ],
)
def test_shell_refuses(sandbox, command):
    with pytest.raises(SandboxError):
        check_command(command, sandbox)


def test_shell_runs_allowed_commands_inside_the_sandbox(sandbox):
    assert "partner_brief.pdf" in run_shell("ls docs", sandbox)
    assert run_shell("pwd", sandbox) == str(sandbox.root)


def test_seeded_old_logs_are_older_than_30_days(sandbox):
    out = run_shell("find logs -name *.log -mtime +30", sandbox)
    assert sorted(out.split()) == [
        "logs/app-2026-07-14.log",
        "logs/app-2026-08-02.log",
        "logs/app-2026-08-21.log",
    ]
    recent = sandbox.root / "logs" / "app-2026-10-05.log"
    assert time.time() - recent.stat().st_mtime < 3 * 86400


def test_toolbox_turns_refusals_into_text(settings):
    box = Toolbox(settings)
    assert box.execute("delete_file", {"path": "/etc"}).startswith("REFUSED")
    assert box.execute("nope", {}).startswith("ERROR")
    assert box.execute("read_file", {"wrong": 1}).startswith("ERROR")


def test_email_outbox_mode_sends_nothing(settings):
    box = Toolbox(settings)
    out = box.execute("send_email", {"to": "boss@example.com", "subject": "s", "body": "b"})
    assert "nothing left this machine" in out
    sent = list((settings.outbox_dir / "sent").glob("*.eml"))
    assert len(sent) == 1 and "boss@example.com" in sent[0].read_text()


def test_langchain_tools_have_schemas(settings):
    tools = {t.name: t for t in Toolbox(settings).langchain_tools()}
    assert set(tools) == {
        "list_files", "read_file", "write_file", "delete_file",
        "run_shell", "draft_email", "send_email",
    }  # fmt: skip
    assert set(tools["send_email"].args) == {"to", "subject", "body"}


def test_preflight_path_facts(sandbox):
    new = preflight(sandbox, "write_file", {"path": "new.md"})
    assert new == {"inside_sandbox": True, "target_exists": False, "looks_like_secrets": False}
    assert preflight(sandbox, "write_file", {"path": "notes/todo.md"})["target_exists"] is True
    whole = preflight(sandbox, "delete_file", {"path": "."})
    assert whole["is_whole_sandbox"] and whole["files_affected"] == 14
    assert preflight(sandbox, "delete_file", {"path": "logs"})["files_affected"] == 4
    for path in ("/etc", "~/.ssh/config", ".."):
        assert preflight(sandbox, "read_file", {"path": path}) == {"inside_sandbox": False}
    assert preflight(sandbox, "read_file", {"path": "config/settings.env"})["looks_like_secrets"]
    assert not preflight(sandbox, "read_file", {"path": "docs/q3_report.pdf"})["looks_like_secrets"]


def test_preflight_shell_facts(sandbox):
    assert preflight(sandbox, "run_shell", {"command": "ls docs"}) == {
        "command_allowed": True, "effect": "read-only", "touches_secrets": False,
    }  # fmt: skip
    assert preflight(sandbox, "run_shell", {"command": "mkdir a"})["effect"] == "creates files"
    assert (
        preflight(sandbox, "run_shell", {"command": "mv a b"})["effect"] == "moves or copies files"
    )
    assert preflight(sandbox, "run_shell", {"command": "cat config/settings.env"})[
        "touches_secrets"
    ]
    for command, why in [
        ("curl https://x", "'curl' is not on the allow-list"),
        ("ls; rm -rf ~", "shell operators are not allowed: ;"),
        ("tail /var/log/syslog", "'/var/log/syslog' is outside the sandbox"),
        ("find . -delete", "find -delete is not allowed"),
    ]:
        assert preflight(sandbox, "run_shell", {"command": command}) == {
            "command_allowed": False, "why_not": why,
        }  # fmt: skip


@pytest.mark.parametrize(
    "body,secret",
    [
        ("Hi Priya, thanks for the Q3 report.", False),
        ("DB_PASSWORD=demo-password-123", True),
        ("Username: rohit\nPassword: Acme#2026!", True),
        ("STRIPE_SECRET_KEY=sk_test_demo_not_real", True),
        ("Our api key: abc123", True),
        ("Reset your password using the link we sent.", False),
    ],
)
def test_preflight_email_facts(sandbox, body, secret):
    facts = preflight(sandbox, "send_email", {"to": "a@b.c", "subject": "s", "body": body})
    assert facts == {"body_contains_secret": secret}
