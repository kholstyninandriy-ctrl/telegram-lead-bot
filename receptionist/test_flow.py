"""Офлайн-тест повного потоку: чат → слоти → бронювання → БД. OpenAI підмінено."""
import json
import os
import tempfile
from types import SimpleNamespace as NS

os.environ["RECEPTIONIST_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["OPENAI_API_KEY"] = "test"
for k in ("CALCOM_API_KEY", "GOOGLE_SERVICE_ACCOUNT_JSON", "TELEGRAM_BOT_TOKEN"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402

import app as appmod  # noqa: E402


def tc(i, name, args):
    return NS(id=f"c{i}", function=NS(name=name, arguments=json.dumps(args)))


class FakeCompletions:
    """Скриптований «LLM»: 1) просить слоти, 2) бронює перший, 3) підтверджує."""
    def __init__(self):
        self.step = 0

    def create(self, messages, **kw):
        assert messages[0]["role"] == "system" and "Skyline" in messages[0]["content"]
        self.step += 1
        if self.step == 1:
            msg = NS(content=None, tool_calls=[tc(1, "get_available_slots", {"days_ahead": 3})])
        elif self.step == 2:
            slots = json.loads(messages[-1]["content"])["slots"]
            msg = NS(content=None, tool_calls=[tc(2, "book_appointment",
                     {"start": slots[0]["start"], "name": "Олена", "phone": "067 123 4567", "notes": "2к квартира"})])
        else:
            res = json.loads(messages[-1]["content"])
            assert res["ok"], res
            msg = NS(content=f"Готово! Записала вас на {res['confirmed']}.", tool_calls=None)
        return NS(choices=[NS(message=msg)])


appmod.receptionist.client = NS(chat=NS(completions=FakeCompletions()))
c = TestClient(appmod.app)

r = c.post("/api/chat", json={"message": "Хочу на перегляд, Олена 0671234567"}).json()
print("chat:", r)
assert "Готово" in r["reply"]

# повторний запит у тій самій сесії — історія валідна для OpenAI (починається з user)
hist = appmod.sessions[r["session_id"]]["history"]
assert hist[0]["role"] == "user" and hist[-1]["role"] == "assistant"

from storage import list_bookings  # noqa: E402
b = list_bookings()
print("booking:", b[0])
assert b[0]["phone"] == "+380671234567" and b[0]["calendar"] == "mock"

# Vapi webhook
slots = c.post("/api/vapi/tools", json={"message": {"type": "tool-calls", "toolCallList": [
    {"id": "v1", "type": "function", "function": {"name": "get_available_slots", "arguments": {}}}]}}).json()
print("vapi slots:", slots["results"][0]["result"][:120])
first = json.loads(slots["results"][0]["result"])["slots"][0]["start"]
bk = c.post("/api/vapi/tools", json={"message": {"type": "tool-calls", "toolCallList": [
    {"id": "v2", "type": "function", "function": {"name": "book_appointment",
     "arguments": json.dumps({"start": first, "name": "John", "phone": "+1 415 555 2671"})}}]}}).json()
print("vapi book:", bk)
assert json.loads(bk["results"][0]["result"])["ok"]
# подвійне бронювання того ж слоту відхиляється
dup = c.post("/api/vapi/tools", json={"message": {"type": "tool-calls", "toolCallList": [
    {"id": "v3", "function": {"name": "book_appointment", "arguments": {"start": first, "name": "X", "phone": "+14155552671"}}}]}}).json()
assert not json.loads(dup["results"][0]["result"])["ok"]

assert c.get("/health").json()["calendar"] == "mock"
assert c.get("/").status_code == 200 and c.get("/widget.js").status_code == 200
cfg = c.get("/api/vapi/assistant-config?niche=dental").json()
assert cfg["model"]["tools"][0]["server"]["url"].endswith("/api/vapi/tools")
assert c.get("/api/bookings").status_code == 401
print("ALL OK")

# ─── Claude-провайдер: append-only історія, незмінний system, повний цикл бронювання ───
from anthropic.types.beta import BetaTextBlock, BetaThinkingBlock, BetaToolUseBlock  # noqa: E402


class FakeClaude:
    def __init__(self):
        self.calls = []

    def create(self, **kw):
        self.calls.append(json.loads(json.dumps(kw, default=str)))
        assert "temperature" not in kw and kw["fallbacks"] == "default"
        assert kw["tools"][0]["input_schema"]["type"] == "object"
        msgs = kw["messages"]
        last = msgs[-1]
        think = BetaThinkingBlock(type="thinking", thinking="", signature="sig%d" % len(self.calls))
        if isinstance(last["content"], str) and len(self.calls) == 1:
            blocks = [think, BetaToolUseBlock(type="tool_use", id="t1", name="get_available_slots", input={})]
            stop = "tool_use"
        elif isinstance(last["content"], list) and last["content"][0].get("tool_use_id") == "t1":
            slot = json.loads(last["content"][0]["content"])["slots"][0]["start"]
            blocks = [think, BetaToolUseBlock(type="tool_use", id="t2", name="book_appointment",
                      input={"start": slot, "name": "Ann", "phone": "+48 512 345 678"})]
            stop = "tool_use"
        elif isinstance(last["content"], list) and last["content"][0].get("tool_use_id") == "t2":
            res = json.loads(last["content"][0]["content"])
            assert res["ok"], res
            blocks = [think, BetaTextBlock(type="text", text="Записала на " + res["confirmed"])]
            stop = "end_turn"
        else:
            blocks = [think, BetaTextBlock(type="text", text="Ще щось?")]
            stop = "end_turn"
        return NS(content=blocks, stop_reason=stop, stop_details=None)


fake = FakeClaude()
appmod.receptionist.provider = "anthropic"
appmod.receptionist.model = "claude-opus-5-5"
appmod.receptionist.client = NS(beta=NS(messages=fake))
r1 = c.post("/api/chat", json={"message": "Hi, I want a viewing"}).json()
print("claude:", r1["reply"])
assert r1["reply"].startswith("Записала")
r2 = c.post("/api/chat", json={"message": "Дякую", "session_id": r1["session_id"]}).json()
assert r2["reply"] == "Ще щось?"
# system однаковий в усіх запитах сесії, а кожен запит — продовження попереднього (append-only)
assert len({call["system"] for call in fake.calls}) == 1
for prev, cur in zip(fake.calls, fake.calls[1:]):
    assert cur["messages"][: len(prev["messages"])] == prev["messages"]
# thinking-блоки з підписами передаються назад без змін
assert fake.calls[-1]["messages"][1]["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig1"}
print("CLAUDE OK")
