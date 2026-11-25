from pathlib import Path

import pytest

from claude_reviewer_bot import guards
from claude_reviewer_bot.config import ConfigError, parse_config
from claude_reviewer_bot.github import NotAPullRequest, iter_json_values
from claude_reviewer_bot.models import MARKER, CommentKind, Job, Outcome, PullRequest
from claude_reviewer_bot.notifier import NullNotifier
from claude_reviewer_bot.prompt import build_prompt, load_template
from claude_reviewer_bot.scanner import CommentScanner, parse_command
from claude_reviewer_bot.service import ReviewService
from claude_reviewer_bot.state import State, StateStore


def make_cfg(**kw):
    return parse_config({"allowed_user": "Alice", "repos": {"o/r": "/tmp/clone"}, **kw})


def make_pr(**kw):
    base = dict(
        repo="o/r",
        number=1,
        title="T",
        body="",
        state="open",
        head_sha="abcdef123",
        head_repo="o/r",
        changed_files=3,
    )
    return PullRequest(**(base | kw))


# ---------- config ----------
def test_config_defaults_and_long_repo_form():
    cfg = parse_config(
        {
            "allowed_user": "a",
            "repos": {"o/r": "~/x", "o/s": {"path": "~/y", "template": "~/t.md"}},
            "max_words": 100,
        }
    )
    assert cfg.max_words == 100 and cfg.max_files == 60
    assert cfg.template_for("o/r") is None
    assert cfg.template_for("o/s") == Path("~/t.md").expanduser()


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"allowed_user": "a", "repos": {}},
        {"allowed_user": "a", "repos": {"o/r": "x"}, "foo": 1},
    ],
)
def test_config_invalid(raw):
    with pytest.raises(ConfigError):
        parse_config(raw)


# ---------- parsing ----------
def test_parse_command():
    assert parse_command("hola\n/claude-review revisa seguridad") == "revisa seguridad"
    assert parse_command("/claude-review") == ""
    assert parse_command("> /claude-review citado") is None
    assert parse_command("texto /claude-review en medio") is None


def test_iter_json_values():
    assert list(iter_json_values('{"a":1}\n{"b":2} ')) == [{"a": 1}, {"b": 2}]


# ---------- scanner ----------
class FakeGH:
    def __init__(self, comments=None, pr=None, diff="d"):
        self.comments, self.pr, self._diff = comments or {}, pr, diff
        self.posted = []

    def comments_since(self, repo, kind, since):
        return self.comments.get(kind, [])

    def pull_request(self, repo, n):
        if self.pr is None:
            raise NotAPullRequest()
        return self.pr

    def diff(self, pr):
        return self._diff

    def comment(self, repo, n, body):
        self.posted.append(body)

    def react(self, job):
        pass


def test_scanner_filters():
    def c(i, login, body):
        return {
            "id": i,
            "user": {"login": login} if login else None,
            "body": body,
            "issue_url": "https://x/issues/7",
        }

    gh = FakeGH(
        {
            CommentKind.ISSUE: [
                c(1, "alice", "/claude-review foco en tests"),
                c(2, "bob", "/claude-review"),
                c(3, "alice", f"{MARKER}\n/claude-review"),
                c(4, None, "/claude-review"),
                c(5, "alice", "nada"),
                c(6, "alice", "/claude-review"),
            ]
        }
    )
    jobs = CommentScanner(make_cfg(), gh).scan("since", known={"o/r:i:6"})
    assert [(j.cid, j.n, j.extra) for j in jobs] == [(1, 7, "foco en tests")]


# ---------- guards ----------
@pytest.mark.parametrize(
    "pr",
    [
        make_pr(state="closed"),
        make_pr(head_repo=None),
        make_pr(head_repo="evil/r"),
        make_pr(changed_files=999),
    ],
)
def test_guards_skip(pr):
    with pytest.raises(guards.Skip):
        guards.enforce(guards.PR_RULES, pr, make_cfg())


def test_diff_guard():
    with pytest.raises(guards.Skip):
        guards.enforce(guards.DIFF_RULES, "x" * 11, make_cfg(max_diff_chars=10))


# ---------- prompt ----------
def test_prompt_template_substitution(tmp_path):
    tpl = tmp_path / "t.md"
    tpl.write_text("---\nname: x\n---\nPR $number de $repo: $extra {llaves} $diff")
    out = build_prompt(load_template(tpl), make_pr(), "DIFF $x", "", 10)
    assert out == "PR 1 de o/r: (ninguna: revisión general) {llaves} DIFF $x"


def test_default_template_has_no_leftover_vars():
    out = build_prompt(load_template(), make_pr(), "diff", "extra", 10)
    assert "$" not in out and "---" not in out.splitlines()[0]


# ---------- state ----------
def test_state_roundtrip(tmp_path):
    from datetime import UTC, datetime

    store = StateStore(tmp_path)
    job = Job("k", "o/r", CommentKind.REVIEW, 1, 2, "x", 1)
    store.save(State(datetime(2026, 1, 1, tzinfo=UTC), ["a"], [job]))
    loaded = store.load()
    assert loaded.pending == [job] and loaded.known_keys() == {"a", "k"}
    with store.exclusive() as ok:
        assert ok
        with store.exclusive() as ok2:
            assert not ok2


# ---------- service ----------
class FailingService(ReviewService):
    def review(self, job):
        raise RuntimeError("boom")


def test_service_retry_then_give_up():
    gh = FakeGH()
    svc = FailingService(make_cfg(max_attempts=2), gh, None, NullNotifier())
    job = Job("k", "o/r", CommentKind.ISSUE, 1, 2)
    assert svc.process(job) is Outcome.RETRY
    assert svc.process(job) is Outcome.DONE
    assert "falló 2 veces" in gh.posted[0]


def test_service_skip_and_not_pr():
    job = Job("k", "o/r", CommentKind.ISSUE, 1, 2)
    gh = FakeGH(pr=make_pr(state="closed"))
    assert ReviewService(make_cfg(), gh, None, NullNotifier()).process(job) is Outcome.DONE
    assert "No se hizo la revisión" in gh.posted[0]

    gh = FakeGH(pr=None)
    assert ReviewService(make_cfg(), gh, None, NullNotifier()).process(job) is Outcome.DONE
    assert gh.posted == []
