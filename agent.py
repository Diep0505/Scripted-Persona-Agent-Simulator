"""
agent.py - Điều phối Nhân vật Agent (Persona Agent Orchestrator)

Quản lý vòng đời hoạt động của Persona Agent:
- Khởi tạo hồ sơ nhân vật động từ ScenarioSchema (bao gồm interaction_type, behavior_policy và context_facts).
- Thực thi từng lượt giao tiếp (ask_agent) thông qua State Machine, Gemini API và Termination Validator.
- Tự động phát hiện tag hành động nghiệp vụ trong tin nhắn người dùng để ghi nhận vào trạng thái.
- Độc lập thẩm định tính hợp lệ của việc kết thúc cuộc hội thoại (không ngắt vội khi khách hàng còn thắc mắc).
"""

import re
from typing import List, Dict, Any, Tuple
from models import ScenarioSchema, CharacterProfile, AgentResponse, Stage, ConversationLifecycleState
from gemini_api import ask_gemini, generate_dynamic_persona
from state_machine import update_state, reset_state, make_initial_state, validate_termination, record_action
from prompt_builder import build_generic_prompt


def create_agent_persona(scenario: ScenarioSchema) -> CharacterProfile:
    """
    Tạo hồ sơ nhân vật động dựa trên kịch bản nạp vào.
    """
    print(f"🎲 Đang khởi tạo nhân vật thực tế cho kịch bản: '{scenario.title}'...")
    return generate_dynamic_persona(scenario)


def _extract_actions_from_input(user_input: str) -> List[str]:
    """Trích xuất tất cả các tag hành động nghiệp vụ dạng [ACTION_TAG] từ tin nhắn."""
    if not user_input:
        return []
    tags = re.findall(r"\[([A-Za-z0-9_]+)\]", user_input)
    return [t.upper() for t in tags]


def _check_facts_disclosed(character_profile: CharacterProfile, text: str, state: Dict[str, Any]) -> None:
    """Kiểm tra xem câu nói của nhân vật có chứa nội dung của context_fact nào không."""
    if not text:
        return
    text_lower = text.lower()
    for fact in character_profile.context_facts:
        if fact.id and fact.id not in state.get("context_facts_disclosed", []):
            # Kiểm tra một số từ khóa chính trong thông tin fact
            words = [w.lower() for w in fact.information.split() if len(w) > 3]
            match_count = sum(1 for w in words if w in text_lower)
            if match_count >= 2 or fact.information.lower() in text_lower:
                if "context_facts_disclosed" not in state:
                    state["context_facts_disclosed"] = []
                state["context_facts_disclosed"].append(fact.id)


def ask_agent(
    user_input: str,
    state: Dict[str, Any],
    scenario: ScenarioSchema,
    character_profile: CharacterProfile,
    dialogue_history: List[Dict[str, str]],
    turn: int = 0
) -> Tuple[str, Dict[str, Any]]:
    """
    Thực thi 1 lượt tương tác của Agent với quy trình xác thực kết thúc đa lớp.
    """
    # 1. Trích xuất và ghi nhận các hành động nghiệp vụ từ tin nhắn của đối phương
    detected_actions = _extract_actions_from_input(user_input)
    for act in detected_actions:
        record_action(state, act)

    # 2. Dựng System Prompt tổng quát cho turn hiện tại
    prompt = build_generic_prompt(
        scenario=scenario,
        character_profile=character_profile,
        state=state,
        turn=turn,
        history=dialogue_history
    )

    # 3. Gọi Gemini API nhận phản hồi cấu trúc AgentResponse
    agent_response: AgentResponse = ask_gemini(system_prompt=prompt, user_input=user_input)

    # 4. Cập nhật State Machine (Cảm xúc + Xử lý sự kiện nếu có)
    update_state(
        state=state,
        new_trust=agent_response.new_trust,
        new_patience=agent_response.new_patience,
        new_stress=agent_response.new_stress,
        satisfaction=agent_response.satisfaction,
        detected_event=agent_response.detected_event
    )

    # 5. Kiểm tra thông tin bối cảnh/nguy cơ đã được chia sẻ chưa
    _check_facts_disclosed(character_profile, agent_response.reply, state)

    # 6. Độc lập thẩm định kết thúc hội thoại (Termination Validation)
    is_terminated, lifecycle_state, termination_reason = validate_termination(
        state=state,
        last_user_input=user_input,
        agent_response=agent_response,
        completion_rules=scenario.completion_rules,
        current_turn=turn,
        detected_actions=detected_actions
    )

    # 7. Dựng nhật ký debug trace chi tiết
    stage_name = Stage.GREETING.value if turn == 0 else Stage.MAIN_CHAT.value
    trace_info = {
        "turn": turn,
        "stage": stage_name,
        "lifecycle_state": lifecycle_state.value if hasattr(lifecycle_state, "value") else str(lifecycle_state),
        "end_requested": agent_response.conversation_end_requested,
        "end_validated": is_terminated,
        "pending_question": state.get("pending_customer_question", False),
        "termination_reason": termination_reason,
        "completed_actions": list(state.get("completed_actions", [])),
        "prompt": prompt,
        "json_response": agent_response.model_dump()
    }

    return agent_response.reply, trace_info


def reset_agent(state: Dict[str, Any], scenario: ScenarioSchema) -> CharacterProfile:
    """
    Đặt lại trạng thái và sinh ra một nhân vật mới cho kịch bản.
    """
    reset_state(state, scenario.initial_state)
    return create_agent_persona(scenario)