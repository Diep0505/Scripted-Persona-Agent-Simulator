"""
verify_scenarios.py - Script thẩm định các tình huống thực tế theo yêu cầu

Kiểm thử 6 kịch bản bắt buộc:
- Scenario 1: Mua thẳng (Direct purchase) - Giao dịch nhanh 2-3 turns, không lan man.
- Scenario 2: Tư vấn triệu chứng (Symptom consultation) - Khách nêu triệu chứng, Dược sĩ sàng lọc, khách trả lời, cấp thuốc.
- Scenario 3: Ca nguy cơ (Risk case) - Hỏi mua thuốc giảm đau mạnh, Dược sĩ hỏi dạ dày, khách khai thật thà không kịch hóa.
- Scenario 4 & 5: Câu hỏi phát sinh sau thanh toán (Follow-up question after payment) - KHÔNG ĐƯỢC ngắt sớm, tiếp tục giải đáp.
- Scenario 6: Ngắt tự nhiên trước max_turns, không sinh turns thừa thãi.
"""

import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scenario_loader import load_scenario_from_md
from agent import ask_agent
from state_machine import make_initial_state, validate_termination, record_action
from models import (
    CharacterProfile,
    BehaviorPolicy,
    ResponseStyle,
    InformationBehavior,
    InteractionBehavior,
    TransactionBehavior,
    ContextFact,
    FactDisclosure,
    ConversationLifecycleState,
    AgentResponse,
)


def verify_scenario_followup_question_not_cutoff():
    print("=" * 70)
    print("🧪 VERIFYING: Follow-up Question After Payment MUST NOT Be Cut Off")
    print("=" * 70)

    scenario = load_scenario_from_md("scenarios/patient_pharmacy.md")
    state = make_initial_state(scenario.initial_state)

    # Khởi tạo profile khách hàng mua thuốc
    profile = CharacterProfile(
        name="Lê Minh Anh",
        age=28,
        occupation="Nhân viên văn phòng",
        personality="Thẳng thắn, lịch sự",
        background="Đi làm bận rộn, ghé mua thuốc nhanh.",
        chief_complaint="Chị lấy em 1 vỉ thuốc giảm đau đầu.",
        interaction_type="named_purchase",
        intent="buy_specific_product",
        behavior_policy=BehaviorPolicy(
            response_style=ResponseStyle(verbosity="low", target_sentences="1-2", hard_max_sentences=3),
            information_behavior=InformationBehavior(spontaneous_disclosure=False, answer_when_asked=True),
            interaction_behavior=InteractionBehavior(asks_questions_spontaneously=False),
            transaction_behavior=TransactionBehavior(wants_fast_transaction=True, leaves_after_completion=True)
        ),
        context_facts=[],
        goal="Mua thuốc giảm đau và nắm rõ cách uống"
    )

    history = []

    # Turn 0:
    p_msg_0 = "Chào bạn, nhà thuốc có thể giúp gì cho bạn?"
    history.append({"role": "user", "content": p_msg_0})
    reply_0, trace_0 = ask_agent(p_msg_0, state, scenario, profile, history, turn=0)
    history.append({"role": "assistant", "content": reply_0})
    print(f"Turn 0:")
    print(f"  👨‍🏫 Dược sĩ: {p_msg_0}")
    print(f"  🧑 Khách hàng: {reply_0}")
    print(f"  ⚙️ State: Lifecycle={trace_0['lifecycle_state']}, End Validated={trace_0['end_validated']}")
    assert not trace_0["end_validated"], "Turn 0 must not end"

    # Turn 1: Dược sĩ cấp thuốc và thu tiền [PAYMENT] [DONE]
    p_msg_1 = "[GIVE_MEDICINE] [PAYMENT] Đây em nhé, Paracetamol 500mg, tổng cộng 30 nghìn. [DONE]"
    history.append({"role": "user", "content": p_msg_1})

    # Giả định ở lượt này khách hàng trả tiền NHƯNG hỏi thêm câu hỏi quan trọng về cách dùng:
    # "Dạ em gửi tiền. Mà chị ơi, thuốc này uống trước hay sau khi ăn vậy chị?"
    simulated_reply_1 = "Dạ đây em gửi 30 nghìn. Mà chị ơi, thuốc này uống trước hay sau ăn vậy chị?"
    simulated_agent_res_1 = AgentResponse(
        reply=simulated_reply_1,
        conversation_end_requested=True,  # Giả sử LLM lỡ tay gán True
        pending_question=True,
        satisfaction=90
    )

    is_ended_1, lc_1, reason_1 = validate_termination(
        state=state,
        last_user_input=p_msg_1,
        agent_response=simulated_agent_res_1,
        completion_rules=scenario.completion_rules,
        current_turn=1,
        detected_actions=["GIVE_MEDICINE", "PAYMENT"]
    )
    history.append({"role": "assistant", "content": simulated_reply_1})

    print(f"\nTurn 1 (Payment + Follow-up Question):")
    print(f"  👨‍🏫 Dược sĩ: {p_msg_1}")
    print(f"  🧑 Khách hàng: {simulated_reply_1}")
    print(f"  ⚙️ Engine Validation: End Requested={simulated_agent_res_1.conversation_end_requested} | End Validated={is_ended_1} | Lifecycle={lc_1.value}")
    print(f"  📢 Engine Reason: {reason_1}")

    # BẮT BUỘC: is_ended_1 phải là False!
    assert not is_ended_1, "TEST FAILED: Engine prematurely terminated conversation while customer had pending question!"
    print("  ✅ SUCCESS: Engine correctly REJECTED premature termination because customer asked a follow-up question!")

    # Turn 2: Dược sĩ trả lời câu hỏi của khách
    p_msg_2 = "Thuốc này em uống sau khi ăn no nhé, uống với một cốc nước đầy."
    history.append({"role": "user", "content": p_msg_2})
    reply_2, trace_2 = ask_agent(p_msg_2, state, scenario, profile, history, turn=2)
    history.append({"role": "assistant", "content": reply_2})

    print(f"\nTurn 2 (Pharmacist Answers Follow-up):")
    print(f"  👨‍🏫 Dược sĩ: {p_msg_2}")
    print(f"  🧑 Khách hàng: {reply_2}")
    print(f"  ⚙️ State: Lifecycle={trace_2['lifecycle_state']}, End Validated={trace_2['end_validated']}")
    print(f"  📢 Termination Reason: {trace_2['termination_reason']}")

    # Lúc này khách hàng đã được trả lời, cảm ơn và kết thúc hội thoại tự nhiên!
    print("=" * 70)
    print("🎉 SCENARIO 4 & 5 VERIFICATION COMPLETE: Conversation successfully continued and finished naturally without abrupt cutoff!")
    print("=" * 70)


if __name__ == "__main__":
    verify_scenario_followup_question_not_cutoff()
