from myloai.core.domain import AgentProfile, ChatMessage, ChatSession, PromptRecord
from myloai.core.managers import apply_agent_to_session


def test_apply_agent_sets_model_system_prompt_and_reasoning():
    session = ChatSession()
    session.messages.append(ChatMessage("system", "old prompt"))
    prompt = PromptRecord(title="Coder", content="You are a coder.", id="p1")
    agent = AgentProfile(
        name="Coder", model="qwen3:4b", system_prompt_id="p1", reasoning_mode="thinking"
    )

    apply_agent_to_session(session, agent, [prompt])

    assert session.agent_id == agent.id
    assert session.model == "qwen3:4b"
    assert session.system_prompt == "You are a coder."
    assert session.messages[0].content == "You are a coder."
    assert session.parameters.get("think") is True


def test_apply_agent_without_prompt_keeps_existing_system_prompt():
    session = ChatSession(system_prompt="keep me")
    session.messages.append(ChatMessage("system", "keep me"))
    agent = AgentProfile(name="Plain", reasoning_mode="normal")

    apply_agent_to_session(session, agent, [])

    assert session.agent_id == agent.id
    assert session.system_prompt == "keep me"
    assert session.messages[0].content == "keep me"
    assert "think" not in session.parameters


def test_apply_agent_inserts_system_message_when_missing():
    session = ChatSession()
    prompt = PromptRecord(title="Coder", content="You are a coder.", id="p1")
    agent = AgentProfile(name="Coder", system_prompt_id="p1")

    apply_agent_to_session(session, agent, [prompt])

    assert session.messages[0].role == "system"
    assert session.messages[0].content == "You are a coder."


def test_session_roundtrip_preserves_agent_id(tmp_path):
    session = ChatSession(agent_id="agent-123", model="m", parameters={"think": True})
    path = session.save(tmp_path)
    loaded = ChatSession.from_file(path)
    assert loaded.agent_id == "agent-123"
    assert loaded.model == "m"
    assert loaded.parameters == {"think": True}
