"""
auto_test.py - Automated LLM-vs-LLM Simulation & QA Evaluation Framework

Hệ thống Kiểm thử Tự động 2 AI (LLM-vs-LLM) cho Generic Markdown Scenario Engine:
- Nạp kịch bản .md bất kỳ (Y tế, BĐS, CSKH...).
- AI 1 (Tester Agent): Đóng vai Tester/Chuyên viên, tuân thủ quy trình thực tế.
- Target Agent (Persona Agent): Đóng vai khách hàng thực tế theo interaction_type, behavior_policy và context_facts.
- Tự động chịu lỗi & thử lại với Exponential Backoff khi API quá tải (503 UNAVAILABLE / 429 RESOURCE_EXHAUSTED).
- Cơ chế Ngắt Hội thoại Độc lập (Validated Termination Protocol):
  1. Chỉ dừng khi Engine xác nhận `end_validated == True` (mục tiêu xong, không còn câu hỏi dở dang).
  2. Không bao giờ ngắt cụt khi khách hàng vừa hỏi thêm câu hỏi sau thanh toán.
  3. Cầu chì khẩn cấp: Ngắt an toàn khi chạm ngưỡng max_turns.
- AI 2 (Evaluator Agent): Đánh giá QA toàn diện theo các chỉ số đo lường tính chân thực, tự nhiên và thời điểm kết thúc.
"""

import os
import json
import time
import argparse
from typing import Dict, Any, List
from google import genai
from google.genai import types

from config import TEST_AGENT_API_KEY, TEST_AGENT_MODEL
from models import ScenarioSchema, CharacterProfile, EvaluationReport, ConversationLifecycleState
from scenario_loader import load_scenario_from_md
from agent import ask_agent, create_agent_persona
from gemini_api import generate_content_with_retry
from state_machine import make_initial_state

# Khởi tạo GenAI Client cho AI 1 (Tester) và AI 2 (Evaluator)
client = genai.Client(api_key=TEST_AGENT_API_KEY)


# ===========================================================================
# 1. Target Agent Wrapper (Môi trường kiểm thử cô lập)
# ===========================================================================
class PersonaAgentWrapper:
    """
    Wrapper adapter cho Agent cần kiểm thử.
    Duy trì trạng thái cảm xúc, vòng đời và lịch sử thoại cô lập hoàn toàn.
    """

    def __init__(self, scenario: ScenarioSchema):
        self.scenario = scenario
        self.state = make_initial_state(scenario.initial_state)
        self.profile = create_agent_persona(scenario)
        self.dialogue_history: List[Dict[str, str]] = []

    def step(self, user_text: str, turn: int, action_tag: str = "NONE") -> Dict[str, Any]:
        """
        Thực thi 1 lượt phản hồi của Agent.
        """
        if action_tag and action_tag != "NONE":
            full_user_input = f"[{action_tag}] {user_text}"
        else:
            full_user_input = user_text

        self.dialogue_history.append({"role": "user", "content": full_user_input})

        reply_text, trace_info = ask_agent(
            user_input=full_user_input,
            state=self.state,
            scenario=self.scenario,
            character_profile=self.profile,
            dialogue_history=self.dialogue_history,
            turn=turn
        )

        self.dialogue_history.append({"role": "assistant", "content": reply_text})

        return {
            "text": reply_text,
            "trust": self.state.get("trust", 50),
            "patience": self.state.get("patience", 100),
            "stress": self.state.get("stress", 10),
            "satisfaction": self.state.get("satisfaction", 80),
            "lifecycle_state": self.state.get("lifecycle_state", ConversationLifecycleState.ACTIVE.value),
            "end_requested": trace_info.get("end_requested", False),
            "end_validated": trace_info.get("end_validated", False),
            "pending_question": trace_info.get("pending_question", False),
            "termination_reason": trace_info.get("termination_reason", ""),
            "trace_info": trace_info
        }

    def get_profile(self) -> Dict[str, Any]:
        """Trả về dictionary profile nhân vật."""
        return self.profile.model_dump()


# ===========================================================================
# 2. AI 1: Tester Agent (Giả lập Người dùng / Chuyên gia / Dược sĩ)
# ===========================================================================
def run_tester_agent(scenario: ScenarioSchema, history_logs: List[Dict[str, Any]], current_turn: int) -> Dict[str, str]:
    """
    Sinh hành động và lời thoại của AI 1 (Tester) dựa trên scenario.test_config.
    """
    test_config = scenario.test_config
    valid_actions = [act.action_tag for act in scenario.user_actions] + ["NONE"]
    actions_desc = "\n".join([f"- {act.action_tag}: {act.description}" for act in scenario.user_actions])

    tester_system_prompt = f"""
Bạn là AI 1 đóng vai trò kiểm thử: {test_config.tester_role}.
Bạn đang tương tác với: {scenario.role}.

--- HƯỚNG DẪN VAI TRÒ TESTER ---
{test_config.tester_system_prompt}

--- CÁC THAO TÁC (ACTIONS) BẠN CÓ THỂ CHỌN ---
{actions_desc}
- NONE: Không chọn hành động đặc biệt nào.

--- THÔNG TIN KỊCH BẢN ---
- Kịch bản: {scenario.title}
- Vai trò đối phương: {scenario.role}
- Từ khóa kết thúc hội thoại: {scenario.completion_rules.completion_keywords}

--- ĐỊNH DẠNG ĐẦU RA BẮT BUỘC ---
ACTION: <MÃ_TAG_HÀNH_ĐỘNG> (Phải là một trong: {', '.join(valid_actions)})
SAY: <Lời nói của bạn (1-2 câu ngắn gọn, đời thường, không giải thích dài dòng)>

--- QUY TẮC QUAN TRỌNG VỀ TỪ KHÓA KẾT THÚC & TRÁNH LẶP LẠI ---
1. TUYỆT ĐỐI KHÔNG đưa từ khóa kết thúc {scenario.completion_rules.completion_keywords} vào khi bạn ĐANG ĐẶT CÂU HỎI hoặc đang chờ khách hàng phản hồi.
2. Nếu khách hàng đặt thêm câu hỏi (kể cả sau khi đã nhận đồ/thanh toán), BẠN BẮT BUỘC PHẢI TRẢ LỜI câu hỏi đó một cách chu đáo, ngắn gọn 1 câu (ACTION: NONE).
3. Khi hai bên đã thống nhất xong phương án (đã lấy hàng/thanh toán, đã chốt lịch hẹn, HOẶC đã hẹn sẽ kiểm tra/làm việc với chủ đầu tư và báo lại sau cho khách), HÃY CHÀO TẠM BIỆT VÀ GẮN TAG KẾT THÚC [DONE]. Tuyệt đối không lặp lại câu hứa hẹn chào qua chào lại nhiều lần.
"""

    dialogue_history = []
    for log in history_logs:
        act_note = f" [Action: {log.get('tester_action', 'NONE')}]" if log.get("tester_action", "NONE") != "NONE" else ""
        dialogue_history.append(f"{test_config.tester_role}{act_note}: {log['tester_said']}")
        dialogue_history.append(f"{scenario.role}: {log['target_said']}")

    if current_turn == 0:
        user_prompt = "Hãy bắt đầu buổi tương tác bằng lời chào khách hàng ngắn gọn (1 câu) và hỏi nhu cầu cần hỗ trợ gì. ACTION chọn NONE."
    else:
        user_prompt = f"""
Lịch sử hội thoại gần đây:
{chr(10).join(dialogue_history[-6:])}

Hãy tạo lượt thoại tiếp theo (Chọn 1 ACTION phù hợp và phát biểu trong SAY).
Nếu khách hàng vừa hỏi thêm câu hỏi, hãy trả lời thẳng thắn câu hỏi đó.
"""

    response = generate_content_with_retry(
        client=client,
        model=TEST_AGENT_MODEL,
        contents=f"{tester_system_prompt}\n\nNhiệm vụ:\n{user_prompt}",
        config=types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=250,
        ),
    )

    return _parse_tester_output(response.text, valid_actions)


def _parse_tester_output(raw_text: str, valid_actions: List[str]) -> Dict[str, str]:
    """
    Phân tích định dạng đầu ra 'ACTION: ...\nSAY: ...' từ AI 1 Tester.
    """
    text = raw_text.strip()
    action = "NONE"
    say = text

    lines = text.splitlines()
    action_line = next((l for l in lines if l.strip().upper().startswith("ACTION:")), None)
    say_line_idx = next((i for i, l in enumerate(lines) if l.strip().upper().startswith("SAY:")), None)

    if action_line:
        candidate = action_line.split(":", 1)[1].strip().upper()
        candidate = candidate.replace("[", "").replace("]", "")
        if candidate in valid_actions:
            action = candidate

    if say_line_idx is not None:
        say = "\n".join(lines[say_line_idx:]).split(":", 1)[1].strip()

    say = say.strip('"\n ')
    return {"action": action, "say": say}


# ===========================================================================
# 3. AI 2: QA Evaluator (Đánh giá Chân thực & Tự nhiên)
# ===========================================================================
def run_evaluator(scenario: ScenarioSchema, conversation_logs: List[Dict[str, Any]], target_profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Gửi toàn bộ nhật ký cuộc hội thoại tới AI 2 để chấm điểm theo các chỉ số đo lường tính chân thực.
    """
    eval_criteria_str = "\n".join([f"- {c}" for c in scenario.test_config.evaluation_criteria])
    logs_json = json.dumps(conversation_logs, indent=2, ensure_ascii=False)
    profile_json = json.dumps(target_profile, indent=2, ensure_ascii=False)

    evaluator_system_prompt = f"""
Bạn là AI 2 - Chuyên gia Đánh giá Thực tế & Chất lượng Giao tiếp (Communication Realism & Termination Evaluator).
Nhiệm vụ của bạn là phân tích toàn bộ nhật ký hội thoại giả lập và hồ sơ nhân vật để đánh giá chất lượng phiên tương tác.

CÂU HỎI TIÊU CHUẨN CỐT LÕI:
"Nếu cuộc trò chuyện này diễn ra giữa 2 con người thật ngoài đời trong hoàn cảnh này, nó có tự nhiên, hợp lý và đáng tin không?"

--- TIÊU CHÍ ĐÁNH GIÁ TỪ KỊCH BẢN ---
{eval_criteria_str}

--- CÁC CHỈ SỐ BẮT BUỘC ĐÁNH GIÁ (Thang điểm 1-10) ---
- out_of_character (bool): True nếu vi phạm vai diễn, nói văn mẫu sáo rỗng, hoặc nói dài quá 5 câu.
- dialogue_naturalness (int 1-10): Độ tự nhiên, đời thường, dân dã của câu từ (trừ điểm nếu nói như sách giáo khoa, kịch tính hóa giả tạo).
- interaction_realism (int 1-10): Tính hợp lý của phản ứng hai bên trong đời thực.
- information_timing (int 1-10): Thời điểm chia sẻ thông tin (trừ điểm nặng nếu tự xả thông tin bối cảnh khi chưa ai hỏi, cộng điểm nếu trả lời đúng lúc khi được hỏi).
- behavior_consistency (int 1-10): Tính nhất quán của hành vi so với loại hình tương tác.
- transaction_realism (int 1-10): Quy trình cấp hàng/dịch vụ/thanh toán có hợp lý không.
- termination_correctness (int 1-10): Kết thúc đúng lúc. QUAN TRỌNG: Nếu hội thoại bị ngắt quá sớm (chỉ 1-2 lượt thoại khi khách vừa nêu nhu cầu mà bên tư vấn chưa kịp gửi thông tin dự án, chưa tư vấn hay giao dịch gì), BẮT BUỘC chấm điểm <= 3/10! 10 điểm nếu kết thúc trọn vẹn sau khi hết thắc mắc.
- unnecessary_turns (int): Số lượt thoại thừa thãi (0 nếu tối ưu).
- premature_termination (bool): BẮT BUỘC gán True nếu hội thoại kết thúc khi chỉ mới 1-2 lượt thoại, hoặc mục tiêu/thắc mắc của khách chưa được đáp ứng.
- abrupt_cutoff (bool): BẮT BUỘC gán True nếu hội thoại bị ngắt đột ngột, thiếu vắng câu trả lời/cung cấp thông tin của đối phương.
- emotion_logic_score (int 1-10): Tính logic khi biến đổi cảm xúc (hài lòng/kiên nhẫn/căng thẳng).
- unlock_turn (int): Lượt thoại đầu tiên chia sẻ bối cảnh/nguy cơ (-1 nếu không có nguy cơ hoặc không chia sẻ).
- critique (str): Nhận xét chi tiết bằng Tiếng Việt. Phải nêu rõ lý do tại sao đạt hoặc không đạt tính thực tế.

BẮT BUỘC trả về kết quả định dạng JSON tuân thủ EvaluationReport schema.
"""

    eval_prompt = f"""
Hồ sơ Nhân vật Agent:
{profile_json}

Nhật ký Mô phỏng Hội thoại:
{logs_json}

Hãy chấm điểm phiên mô phỏng.
"""

    response = generate_content_with_retry(
        client=client,
        model=TEST_AGENT_MODEL,
        contents=f"{evaluator_system_prompt}\n\n{eval_prompt}",
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=EvaluationReport,
            temperature=0.2,
        ),
    )

    return json.loads(response.text)


# ===========================================================================
# 4. Thực thi Mô phỏng với Engine Termination Validator
# ===========================================================================
def run_automated_test(scenario_path: str = "scenarios/patient_pharmacy.md", report_path: str = "test_report.json") -> Dict[str, Any]:
    """
    Thực thi vòng lặp test tự động LLM-vs-LLM với cơ chế kết thúc được thẩm định độc lập.
    """
    print("=" * 70)
    print("🤖 STARTING AUTOMATED LLM-VS-LLM TEST (REALISTIC PERSONA ENGINE)")
    print("=" * 70)

    # 1. Nạp kịch bản
    scenario = load_scenario_from_md(scenario_path)
    print(f"📖 Loaded Scenario: '{scenario.title}' from '{scenario_path}'")
    print(f"   Agent Role: {scenario.role} | Tester Role: {scenario.test_config.tester_role}")
    print(f"   Max Turns Limit: {scenario.completion_rules.max_turns}")
    print(f"   Required Actions: {scenario.completion_rules.required_actions}")
    print("-" * 70)

    # 2. Khởi tạo Agent kiểm thử
    target_agent = PersonaAgentWrapper(scenario)
    profile = target_agent.get_profile()

    print(f"👤 Generated Persona Profile:")
    print(f"   Name: {profile.get('name')} | Age: {profile.get('age')} | Job: {profile.get('occupation')}")
    print(f"   Interaction Type: {profile.get('interaction_type')} | Intent: {profile.get('intent')}")
    print(f"   Personality: {profile.get('personality')}")
    print(f"   Chief Complaint: {profile.get('chief_complaint')}")
    print(f"   Context Facts: {len(profile.get('context_facts', []))} items: {[f.get('information') for f in profile.get('context_facts', [])]}")
    print("-" * 70)

    conversation_logs = []
    max_turns = scenario.completion_rules.max_turns
    unlock_turn_detected = -1

    for turn in range(max_turns):
        print(f"\n💬 [Turn {turn + 1}/{max_turns}]")

        # --- Lượt của AI 1 (Tester) ---
        tester_res = run_tester_agent(scenario, conversation_logs, current_turn=turn)
        tester_action = tester_res["action"]
        tester_said = tester_res["say"]

        act_note = f" [{tester_action}]" if tester_action != "NONE" else ""
        print(f"👨‍🏫 {scenario.test_config.tester_role}{act_note}: {tester_said}")

        # --- Lượt của Target Agent ---
        target_res = target_agent.step(tester_said, turn=turn, action_tag=tester_action)
        target_said = target_res["text"]
        trust = target_res["trust"]
        patience = target_res["patience"]
        stress = target_res["stress"]
        satisfaction = target_res.get("satisfaction", 80)
        end_requested = target_res["end_requested"]
        end_validated = target_res["end_validated"]
        pending_q = target_res["pending_question"]
        lifecycle = target_res["lifecycle_state"]
        term_reason = target_res["termination_reason"]

        print(f"🧑 {scenario.role}: {target_said}")
        print(f"   📊 Satisfaction: {satisfaction}/100 | Patience: {patience}/100 | Stress: {stress}/100")
        print(f"   ⚙️ Lifecycle: {lifecycle} | End Requested: {end_requested} | End Validated: {end_validated} | Pending Q: {pending_q}")

        # Ghi nhận thời điểm chia sẻ bối cảnh
        if len(target_agent.state.get("context_facts_disclosed", [])) > 0 and unlock_turn_detected == -1:
            unlock_turn_detected = turn

        conversation_logs.append({
            "turn": turn,
            "tester_action": tester_action,
            "tester_said": tester_said,
            "target_said": target_said,
            "trust": trust,
            "patience": patience,
            "stress": stress,
            "satisfaction": satisfaction,
            "lifecycle_state": lifecycle,
            "end_requested": end_requested,
            "end_validated": end_validated,
            "pending_question": pending_q,
            "termination_reason": term_reason
        })

        # --- KIỂM TRA ĐIỀU KIỆN KẾT THÚC HỘI THOẠI ĐÃ ĐƯỢC XÁC THỰC ---
        if end_validated:
            if lifecycle == ConversationLifecycleState.MAX_TURNS_REACHED.value:
                print(f"\n🛑 [CIRCUIT BREAKER]: {term_reason}")
            else:
                print(f"\n🏁 [VALIDATED END]: {term_reason}")
            break

        time.sleep(1)

    # 5. Chạy AI 2 (Evaluator) chấm điểm
    print("\n" + "=" * 70)
    print("🔍 RUNNING QA EVALUATOR AGENT (AI 2)...")
    print("=" * 70)

    eval_result = run_evaluator(scenario, conversation_logs, profile)

    if eval_result.get("unlock_turn") is None:
        eval_result["unlock_turn"] = unlock_turn_detected

    print("\n📊 QA EVALUATION RESULTS:")
    print(f"   - Out Of Character: {eval_result.get('out_of_character')}")
    print(f"   - Dialogue Naturalness: {eval_result.get('dialogue_naturalness')}/10")
    print(f"   - Interaction Realism: {eval_result.get('interaction_realism')}/10")
    print(f"   - Information Timing: {eval_result.get('information_timing')}/10")
    print(f"   - Behavior Consistency: {eval_result.get('behavior_consistency')}/10")
    print(f"   - Transaction Realism: {eval_result.get('transaction_realism')}/10")
    print(f"   - Termination Correctness: {eval_result.get('termination_correctness')}/10")
    print(f"   - Unnecessary Turns: {eval_result.get('unnecessary_turns')}")
    print(f"   - Premature Termination: {eval_result.get('premature_termination')}")
    print(f"   - Abrupt Cutoff: {eval_result.get('abrupt_cutoff')}")
    print(f"   - Emotion Logic Score: {eval_result.get('emotion_logic_score')}/10")
    print(f"   - Context Disclosed Turn: {eval_result.get('unlock_turn')}")
    print(f"   - Critique:\n{eval_result.get('critique')}\n")

    # 6. Ghi báo cáo JSON
    report_data = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "scenario_file": scenario_path,
        "scenario_title": scenario.title,
        "target_profile": profile,
        "conversation_logs": conversation_logs,
        "evaluation": eval_result
    }

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)

    print(f"✅ Test report successfully saved to '{report_path}'!")
    return report_data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run LLM-vs-LLM automated test on markdown scenario.")
    parser.add_argument("--scenario", type=str, default="scenarios/patient_pharmacy.md", help="Path to scenario .md file")
    parser.add_argument("--output", type=str, default="test_report.json", help="Path to output report JSON file")
    args = parser.parse_args()

    run_automated_test(scenario_path=args.scenario, report_path=args.output)