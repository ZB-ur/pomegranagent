from __future__ import annotations

import ast
import copy
import ipaddress
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = ROOT / "docs" / "lovable"
DATA_PATH = PACK_DIR / "sanitized-demo-data.json"
PROMPT_PATH = PACK_DIR / "teacher-prototype-prompt.md"
CHECKLIST_PATH = PACK_DIR / "teacher-prototype-checklist.md"
PACK_PATHS = (DATA_PATH, PROMPT_PATH, CHECKLIST_PATH)

ALLOWED_CHILD_NAMES = {"小雨", "乐乐", "安安", "果果"}
ALLOWED_DUCK_NAMES = {"豆豆", "团团"}
EXPECTED_STATES = [
    "loading",
    "empty",
    "failed",
    "retrying",
    "dirty",
    "saving",
    "saved",
    "confirmed",
    "revision_conflict",
    "analysis_failed",
    "reduced_motion",
]
EXPECTED_DIMENSIONS = {"语言表达能力", "同理心", "勤劳启蒙"}
EXPECTED_CHECKLIST_HEADINGS = [
    "范围与数据安全",
    "今日任务工作台",
    "值日审阅工作台",
    "状态与错误恢复",
    "键盘与无障碍",
    "视觉层级与响应式",
    "评审结论",
]
ALLOWED_INTEGRATION_SENTENCES = {"不连接 Supabase。", "不连接 GitHub。"}

FORBIDDEN_PATTERNS = {
    "absolute user path": re.compile(r"(?:/Users/|/home/|~/|[A-Za-z]:[\\/])"),
    "repository/config path": re.compile(r"(?:pomegranagent|\.git\b|\.env\b)", re.I),
    "network endpoint": re.compile(
        r"(?:https?://|wss?://|localhost|127(?:\.\d{1,3}){1,3}|0\.0\.0\.0|::1|(?:0{1,4}:){7}0{0,3}1)",
        re.I,
    ),
    "database/config secret": re.compile(
        r"(?:sqlite|APP_DB_PATH|DATABASE_URL|API_KEY|SECRET|TOKEN|DeepSeek|OpenAI|sk-[A-Za-z0-9_-]+)",
        re.I,
    ),
    "source dump": re.compile(
        r"(?:<script\b|function\s+|import\s+|BEGIN [A-Z ]+ KEY|Traceback \(most recent call last\)|```)",
        re.I,
    ),
    "environment assignment": re.compile(
        r"(?:^|[\s;])(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=\s*\S+",
        re.I,
    ),
    "email": re.compile(
        r"(?<![A-Z0-9._%+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![A-Z0-9.-])",
        re.I,
    ),
    "mobile phone": re.compile(
        r"(?<!\d)(?:\+?86[\s.-]*)?\(?1[\s.-]*[3-9][\s.-]*\d\)?(?:[\s.-]*\d){8}(?!\d)"
    ),
    "landline phone": re.compile(r"(?<!\d)\(?0\d{2,3}\)?[\s.-]*\d(?:[\s.-]*\d){6,7}(?!\d)"),
    "international chinese phone": re.compile(
        r"(?<!\d)(?:(?:\+|00)86)[\s.-]*\(?0?[1-9]\d{1,2}\)?(?:[\s.-]*\d){7,8}(?!\d)"
    ),
}

IPV6_CANDIDATE = re.compile(
    r"(?<![0-9A-Fa-f:%])\[?[0-9A-Fa-f:.%_-]*:[0-9A-Fa-f:.%_-]+\]?(?![0-9A-Fa-f:%])"
)


def _read_utf8(path: Path) -> str:
    assert path.is_file(), f"missing sanitized pack file: {path.relative_to(ROOT)}"
    raw = path.read_bytes()
    assert len(raw) < 32 * 1024, f"sanitized pack file is too large: {path.name}"
    return raw.decode("utf-8")


def _exact_keys(value: Any, keys: set[str], where: str) -> dict[str, Any]:
    assert type(value) is dict, f"{where} must be an object"
    assert set(value) == keys, f"{where} has unexpected keys"
    return value


def _nonblank(value: Any, where: str, *, maximum: int) -> str:
    assert type(value) is str and value.strip() == value and value, f"{where} must be nonblank trimmed text"
    assert len(value) <= maximum, f"{where} is too long"
    return value


def _timestamp(value: Any, where: str) -> datetime:
    text = _nonblank(value, where, maximum=30)
    assert text.startswith("2026-08-23T") and text.endswith("Z"), f"{where} must use the anchor date in UTC"
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None, f"{where} must be timezone-aware"
    return parsed


def _demo_id(value: Any, prefix: str, where: str) -> str:
    assert type(value) is str and re.fullmatch(rf"demo-{re.escape(prefix)}-\d{{2}}", value), (
        f"{where} must be a namespaced synthetic ID"
    )
    return value


def validate_demo_data(value: Any) -> None:
    data = _exact_keys(
        value,
        {"metadata", "children", "ducks", "today_roster", "review_queues", "selected_review", "ui_states"},
        "root",
    )

    metadata = _exact_keys(data["metadata"], {"fictional", "classification", "runtime_mode", "anchor_date"}, "metadata")
    assert metadata == {
        "fictional": True,
        "classification": "public-prototype-fixture",
        "runtime_mode": "local-mock-only",
        "anchor_date": "2026-08-23",
    }

    children = data["children"]
    assert type(children) is list and len(children) == 4
    child_ids: set[str] = set()
    child_names: set[str] = set()
    for index, raw_child in enumerate(children, 1):
        child = _exact_keys(raw_child, {"id", "name", "nickname", "avatar_label", "active"}, f"children[{index - 1}]")
        child_id = _demo_id(child["id"], "child", f"children[{index - 1}].id")
        assert child_id == f"demo-child-{index:02d}"
        assert child["name"] in ALLOWED_CHILD_NAMES
        _nonblank(child["nickname"], f"children[{index - 1}].nickname", maximum=12)
        _nonblank(child["avatar_label"], f"children[{index - 1}].avatar_label", maximum=12)
        assert child["active"] is True
        child_ids.add(child_id)
        child_names.add(child["name"])
    assert child_names == ALLOWED_CHILD_NAMES and len(child_ids) == 4

    ducks = data["ducks"]
    assert type(ducks) is list and len(ducks) == 2
    duck_ids: set[str] = set()
    duck_names: set[str] = set()
    for index, raw_duck in enumerate(ducks, 1):
        duck = _exact_keys(raw_duck, {"id", "name", "summary", "active"}, f"ducks[{index - 1}]")
        duck_id = _demo_id(duck["id"], "duck", f"ducks[{index - 1}].id")
        assert duck_id == f"demo-duck-{index:02d}"
        assert duck["name"] in ALLOWED_DUCK_NAMES
        _nonblank(duck["summary"], f"ducks[{index - 1}].summary", maximum=80)
        assert duck["active"] is True
        duck_ids.add(duck_id)
        duck_names.add(duck["name"])
    assert duck_names == ALLOWED_DUCK_NAMES and len(duck_ids) == 2

    roster = data["today_roster"]
    assert type(roster) is list and len(roster) == 2
    roster_children: list[str] = []
    roster_ducks: list[str] = []
    for index, raw_entry in enumerate(roster):
        entry = _exact_keys(raw_entry, {"date", "child_id", "duck_id", "shift"}, f"today_roster[{index}]")
        assert entry["date"] == "2026-08-23"
        assert entry["child_id"] in child_ids and entry["duck_id"] in duck_ids
        assert entry["shift"] == ("上午" if index == 0 else "下午")
        roster_children.append(entry["child_id"])
        roster_ducks.append(entry["duck_id"])
    assert len(set(roster_children)) == 2 and len(set(roster_ducks)) == 2

    queues = _exact_keys(data["review_queues"], {"pending", "processing", "failed"}, "review_queues")
    expected_pairs = {
        "pending": ("succeeded", "draft"),
        "processing": ("processing", "unavailable"),
        "failed": ("failed", "unavailable"),
    }
    queue_rows: dict[str, dict[str, Any]] = {}
    queue_child_ids: set[str] = set()
    queue_times: list[datetime] = []
    for index, queue_name in enumerate(("pending", "processing", "failed"), 1):
        rows = queues[queue_name]
        assert type(rows) is list and len(rows) == 1
        row = _exact_keys(
            rows[0],
            {"conversation_id", "child_id", "completed_at", "round", "analysis_status", "review_status", "revision"},
            f"review_queues.{queue_name}[0]",
        )
        assert _demo_id(row["conversation_id"], "conversation", f"review_queues.{queue_name}[0].conversation_id") == f"demo-conversation-{index:02d}"
        assert row["child_id"] in child_ids
        assert (row["analysis_status"], row["review_status"]) == expected_pairs[queue_name]
        assert type(row["round"]) is int and row["round"] > 0
        assert type(row["revision"]) is int and row["revision"] >= 0
        queue_child_ids.add(row["child_id"])
        queue_times.append(_timestamp(row["completed_at"], f"review_queues.{queue_name}[0].completed_at"))
        queue_rows[queue_name] = row
    assert len(queue_child_ids) == 3 and queue_times == sorted(queue_times)

    selected = _exact_keys(
        data["selected_review"],
        {"conversation_id", "child_id", "duck_id", "messages", "feeding_logs", "emotion", "insight", "scores"},
        "selected_review",
    )
    pending = queue_rows["pending"]
    assert selected["conversation_id"] == pending["conversation_id"]
    assert selected["child_id"] == pending["child_id"] and selected["duck_id"] in duck_ids

    messages = selected["messages"]
    assert type(messages) is list and len(messages) == 6
    message_times: list[datetime] = []
    for index, raw_message in enumerate(messages, 1):
        message = _exact_keys(raw_message, {"id", "speaker", "speaker_id", "text", "sent_at"}, f"selected_review.messages[{index - 1}]")
        assert _demo_id(message["id"], "message", f"selected_review.messages[{index - 1}].id") == f"demo-message-{index:02d}"
        expected_speaker = "child" if index % 2 else "diary"
        assert message["speaker"] == expected_speaker
        assert message["speaker_id"] == (selected["child_id"] if expected_speaker == "child" else selected["duck_id"])
        _nonblank(message["text"], f"selected_review.messages[{index - 1}].text", maximum=80)
        message_times.append(_timestamp(message["sent_at"], f"selected_review.messages[{index - 1}].sent_at"))
    assert message_times == sorted(message_times) and len(set(message_times)) == 6

    logs = selected["feeding_logs"]
    assert type(logs) is list and len(logs) == 2
    for index, raw_log in enumerate(logs, 1):
        log = _exact_keys(raw_log, {"id", "duck_id", "category", "content"}, f"selected_review.feeding_logs[{index - 1}]")
        assert _demo_id(log["id"], "feeding", f"selected_review.feeding_logs[{index - 1}].id") == f"demo-feeding-{index:02d}"
        assert log["duck_id"] in duck_ids
        assert log["category"] in {"喂食", "清洁", "观察", "其它"}
        _nonblank(log["content"], f"selected_review.feeding_logs[{index - 1}].content", maximum=80)

    emotion = _exact_keys(selected["emotion"], {"label", "intensity", "note"}, "selected_review.emotion")
    _nonblank(emotion["label"], "selected_review.emotion.label", maximum=20)
    assert type(emotion["intensity"]) is int and 1 <= emotion["intensity"] <= 5
    _nonblank(emotion["note"], "selected_review.emotion.note", maximum=80)
    _nonblank(selected["insight"], "selected_review.insight", maximum=120)

    scores = selected["scores"]
    assert type(scores) is list and len(scores) == 3
    dimensions: set[str] = set()
    for index, raw_score in enumerate(scores):
        score = _exact_keys(raw_score, {"dimension", "score", "reason"}, f"selected_review.scores[{index}]")
        assert score["dimension"] in EXPECTED_DIMENSIONS
        assert type(score["score"]) is int and 1 <= score["score"] <= 5
        _nonblank(score["reason"], f"selected_review.scores[{index}].reason", maximum=100)
        dimensions.add(score["dimension"])
    assert dimensions == EXPECTED_DIMENSIONS
    assert data["ui_states"] == EXPECTED_STATES


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        assert key not in result, f"duplicate JSON member: {key}"
        result[key] = value
    return result


def parse_demo_json(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text, object_pairs_hook=_strict_object)
    except json.JSONDecodeError as error:
        raise AssertionError("sanitized demo data must be valid JSON") from error
    assert type(value) is dict, "sanitized demo data root must be an object"
    return value


def _load_demo_data() -> dict[str, Any]:
    return parse_demo_json(_read_utf8(DATA_PATH))


def _expect_assertion(callback) -> None:
    try:
        callback()
    except AssertionError:
        return
    raise AssertionError("expected unsafe input to be rejected")


def _iter_strings(value: Any):
    if type(value) is dict:
        for key, item in value.items():
            yield str(key)
            yield from _iter_strings(item)
    elif type(value) is list:
        for item in value:
            yield from _iter_strings(item)
    elif type(value) is str:
        yield value


def _assert_no_loopback(text: str, where: str) -> None:
    for match in IPV6_CANDIDATE.finditer(text):
        candidate = match.group(0).strip("[]").split("%", 1)[0]
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        mapped = getattr(address, "ipv4_mapped", None)
        assert not address.is_loopback and not (mapped is not None and mapped.is_loopback), (
            f"{where} contains forbidden loopback address"
        )


def assert_safe_text(text: str, where: str, *, allow_integration_sentences: bool = False) -> None:
    normalized = text
    if allow_integration_sentences:
        for sentence in ALLOWED_INTEGRATION_SENTENCES:
            occurrences = normalized.count(sentence)
            assert occurrences <= 1, f"{where} repeats an integration exception"
            normalized = normalized.replace(sentence, "")
    assert re.search(r"(?:supabase|github)", normalized, re.I) is None, (
        f"{where} contains an unapproved integration mention"
    )
    _assert_no_loopback(normalized, where)
    for label, pattern in FORBIDDEN_PATTERNS.items():
        assert pattern.search(normalized) is None, f"{where} contains forbidden {label}"


def test_sanitized_demo_data_contract() -> None:
    data = _load_demo_data()
    validate_demo_data(data)


def test_teacher_prototype_prompt_contract() -> None:
    prompt = _read_utf8(PROMPT_PATH)
    assert len(prompt.encode("utf-8")) < 8 * 1024
    assert prompt.count("今日任务工作台") >= 1
    assert prompt.count("值日审阅工作台") >= 1
    assert "只生成两个桌面页面" in prompt
    assert "1024×768" in prompt
    assert "这是仅供视觉评审的投影数据，不是鸭鸭日记本 API 数据结构。" in prompt
    assert "你粘贴的本提示词和脱敏 JSON 是两份完整输入文档，不接受也不需要其他输入。" in prompt
    for sentence in ALLOWED_INTEGRATION_SENTENCES:
        assert prompt.count(sentence) == 1
    for state in EXPECTED_STATES:
        assert f"`{state}`" in prompt
    for copy in ("保存草稿", "保存并确认", "该审阅已在别处更新，请复制当前修改后重新加载。", "分析失败，请返回今日任务重试。"):
        assert copy in prompt
    for requirement in ("44px", "键盘", "焦点", "对比度", "减少动态效果", "本地 mock", "固定保存栏"):
        assert requirement in prompt


def test_teacher_prototype_checklist_contract() -> None:
    checklist = _read_utf8(CHECKLIST_PATH)
    lines = [line.strip() for line in checklist.splitlines() if line.strip()]
    assert lines[0] == "# Lovable 教师端原型评审清单"
    assert lines[1] == "视觉参考，不连接鸭鸭日记本后端"
    headings = [line[3:] for line in lines if line.startswith("## ")]
    assert headings == EXPECTED_CHECKLIST_HEADINGS
    assert "- [x]" not in checklist.lower()
    assert checklist.count("- [ ]") >= 28
    for required in (
        "只生成两个桌面页面",
        "视觉投影，不是应用 API 数据结构",
        "44px",
        "键盘顺序",
        "可见焦点",
        "焦点恢复",
        "对比度",
        "200%",
        "1024×768",
        "水平滚动",
        "减少动态效果",
        "固定保存栏",
        "GO with changes",
        "NO-GO",
    ):
        assert required in checklist


def test_pack_recursively_excludes_sensitive_content() -> None:
    data = _load_demo_data()
    validate_demo_data(data)
    for index, value in enumerate(_iter_strings(data)):
        assert_safe_text(value, f"json string {index}")
    for path in (PROMPT_PATH, CHECKLIST_PATH):
        assert_safe_text(_read_utf8(path), path.name, allow_integration_sentences=True)


def test_duplicate_json_members_are_rejected_before_validation() -> None:
    original = _read_utf8(DATA_PATH)
    marker = '"insight": "能够按顺序说明照料过程，并用具体动作描述小鸭的反应。"'
    assert original.count(marker) == 1
    duplicate = original.replace(marker, '"insight": "https://invalid.example",\n    ' + marker)
    _expect_assertion(lambda: parse_demo_json(duplicate))


def test_forbidden_matcher_rejects_decoded_paths_source_imports_and_integration_bypasses() -> None:
    hostile_values = (
        r"C:\private\child.txt",
        ".git",
        "import os",
        "SuPaBaSe",
        "gItHuB",
        "不连接 Supabase。",
    )
    for value in hostile_values:
        _expect_assertion(lambda value=value: assert_safe_text(value, "json", allow_integration_sentences=False))
    for sentence in ALLOWED_INTEGRATION_SENTENCES:
        assert_safe_text(sentence, "prompt", allow_integration_sentences=True)
    _expect_assertion(lambda: assert_safe_text("请连接 GitHub。", "prompt", allow_integration_sentences=True))


def test_forbidden_matcher_rejects_adjacent_integrations_source_variants_loopbacks_assignments_and_spaced_phones() -> None:
    hostile_values = (
        "连接Supabase数据库",
        "GitHub原型",
        'import {x} from "module"',
        'import * as namespace from "module"',
        'import "module"',
        "function () {}",
        "127.1.2.3",
        "[::1]",
        "0:0:0:0:0:0:0:1",
        "X=value",
        "export FOO=value",
        "lower=value",
        "138-0013-8000",
        "+86 138 0013 8000",
    )
    missed: list[str] = []
    for value in hostile_values:
        try:
            assert_safe_text(value, "hostile")
        except AssertionError:
            continue
        missed.append(value)
    assert not missed, f"forbidden matcher missed: {missed}"


def test_forbidden_matcher_rejects_ipv6_loopback_phone_variants_and_any_fenced_block() -> None:
    hostile_values = (
        "::0001",
        "0:0:0:0::0:0:1",
        "010-12345678",
        "(138) 0013 8000",
        "138.0013.8000",
        "```py\nprint('hidden')\n```",
        "```js\nvoid 0\n```",
    )
    missed: list[str] = []
    for value in hostile_values:
        try:
            assert_safe_text(value, "hostile")
        except AssertionError:
            continue
        missed.append(value)
    assert not missed, f"forbidden matcher missed: {missed}"


def test_forbidden_matcher_rejects_international_phones_home_paths_and_adjacent_email() -> None:
    hostile_values = (
        "+86 10 1234 5678",
        "0086 10 1234 5678",
        "008613800138000",
        "C:/private/child.txt",
        "~/private/child.txt",
        "联系child@example.com",
    )
    missed: list[str] = []
    for value in hostile_values:
        try:
            assert_safe_text(value, "hostile")
        except AssertionError:
            continue
        missed.append(value)
    assert not missed, f"forbidden matcher missed: {missed}"


def test_safety_test_uses_only_standard_library_imports() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
    assert imported_roots <= {
        "__future__", "ast", "copy", "ipaddress", "json", "re", "datetime", "pathlib", "typing"
    }


def _validate_hostile_variant(mutate) -> None:
    data = _load_demo_data()
    validate_demo_data(data)
    hostile = copy.deepcopy(data)
    mutate(hostile)

    def validate() -> None:
        validate_demo_data(hostile)
        for index, value in enumerate(_iter_strings(hostile)):
            assert_safe_text(value, f"hostile json string {index}")

    _expect_assertion(validate)


def test_hostile_nested_variants_are_rejected_transcript_url() -> None:
    _validate_hostile_variant(lambda data: data["selected_review"]["messages"][0].update(text="访问 https://invalid.example"))


def test_hostile_nested_variants_are_rejected_unknown_child_name() -> None:
    _validate_hostile_variant(lambda data: data["children"][0].update(name="真实姓名"))


def test_hostile_nested_variants_are_rejected_dangling_speaker_id() -> None:
    _validate_hostile_variant(lambda data: data["selected_review"]["messages"][0].update(speaker_id="demo-child-99"))


def test_hostile_nested_variants_are_rejected_duplicate_score_dimension() -> None:
    _validate_hostile_variant(lambda data: data["selected_review"]["scores"][1].update(dimension="语言表达能力"))


def test_hostile_nested_variants_are_rejected_integer_id() -> None:
    _validate_hostile_variant(lambda data: data["children"][0].update(id=1))


def test_hostile_nested_variants_are_rejected_secret_shape() -> None:
    _validate_hostile_variant(lambda data: data["selected_review"].update(insight="API_KEY=demo-secret"))


def test_hostile_nested_variants_are_rejected_source_shape() -> None:
    _validate_hostile_variant(lambda data: data["selected_review"].update(insight="function leak() { return true; }"))


def test_hostile_nested_variants_are_rejected_extra_key() -> None:
    _validate_hostile_variant(lambda data: data["selected_review"]["emotion"].update(debug="hidden"))
