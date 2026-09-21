"""
test_suite.py - Unit and Regression Test Suite for Realistic Persona Agent Simulation

Bao gồm các test case kiểm chứng cốt lõi:
- Test A: Valid termination (Mục tiêu xong + Hết thắc mắc + Hoàn tất thao tác nghiệp vụ -> Kết thúc)
- Test B: Invalid termination due to pending question (Khách vừa hỏi thêm sau khi thanh toán -> KHÔNG ngắt, tiếp tục)
- Test C: Invalid termination due to incomplete required transaction (Chưa thanh toán PAYMENT -> KHÔNG ngắt, tiếp tục)
- Test D: Invalid termination when customer asks clarification (Khách hỏi cách dùng / tác dụng phụ -> KHÔNG ngắt, tiếp tục)
- Test E: Maximum turn safety cutoff (Đạt ngưỡng max_turns -> Ngắt an toàn với mã MAX_TURNS_REACHED)
- Test F: Context facts disclosure check (Không tự xả thông tin khi chưa ai hỏi, trả lời khi hỏi đúng bối cảnh)
- Test G: Loading and compatibility for all scenarios (Pharmacy, Real Estate, Customer Service)
"""

import sys
import os
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from models import (
    InitialState,
    CompletionRules,
    AgentResponse,
    ConversationLifecycleState,
    ScenarioSchema,
    CharacterProfile,
    BehaviorPolicy,
    ContextFact,
    FactDisclosure,
)
from scenario_loader import load_scenario_from_md
from state_machine import make_initial_state, validate_termination, record_action, has_unresolved_question


class TestConversationTermination(unittest.TestCase):

    def setUp(self):
        self.completion_rules = CompletionRules(
            max_turns=6,
            completion_keywords=["[DONE]", "[PAYMENT]"],
            required_actions=["PAYMENT"],
            allow_end_with_pending_question=False
        )
        self.state = make_initial_state(InitialState())

    def test_A_valid_termination(self):
        """Test A — Valid termination: Goal completed + No pending question + Required action completed = END"""
        record_action(self.state, "PAYMENT")
        agent_res = AgentResponse(
            reply="Dạ vâng, em cảm ơn chị nhiều nhé. Em xin phép về trước ạ.",
            conversation_end_requested=True,
            pending_question=False,
            pending_request=False
        )
        ended, lifecycle, reason = validate_termination(
            state=self.state,
            last_user_input="[PAYMENT] Thuốc của bạn đây, tổng cộng 50.000đ nhé.",
            agent_response=agent_res,
            completion_rules=self.completion_rules,
            current_turn=2
        )
        self.assertTrue(ended, "Hội thoại phải kết thúc khi mục tiêu xong và không còn thắc mắc")
        self.assertEqual(lifecycle, ConversationLifecycleState.COMPLETED)
        self.assertTrue(self.state["end_validated"])

    def test_B_invalid_termination_customer_has_question(self):
        """Test B — Invalid termination because customer has question after payment: Continue"""
        record_action(self.state, "PAYMENT")
        agent_res = AgentResponse(
            reply="Dạ đây là 50 nghìn. Mà chị ơi, thuốc này uống trước hay sau khi ăn vậy?",
            conversation_end_requested=True,  # LLM mistakenly requests end
            pending_question=True             # But customer still has a question!
        )
        ended, lifecycle, reason = validate_termination(
            state=self.state,
            last_user_input="[PAYMENT] Của bạn 50.000đ nhé.",
            agent_response=agent_res,
            completion_rules=self.completion_rules,
            current_turn=2
        )
        self.assertFalse(ended, "Hội thoại KHÔNG ĐƯỢC ngắt khi khách hàng còn câu hỏi chưa giải đáp")
        self.assertEqual(lifecycle, ConversationLifecycleState.ACTIVE)
        self.assertFalse(self.state["end_validated"])
        self.assertTrue(self.state["pending_customer_question"])

    def test_C_invalid_termination_transaction_incomplete(self):
        """Test C — Invalid termination because transaction incomplete (missing PAYMENT)"""
        agent_res = AgentResponse(
            reply="Dạ vâng em cảm ơn.",
            conversation_end_requested=True,
            pending_question=False,
            pending_request=False
        )
        ended, lifecycle, reason = validate_termination(
            state=self.state,
            last_user_input="[GIVE_MEDICINE] Tôi đưa bạn thuốc giảm đau nhé.",
            agent_response=agent_res,
            completion_rules=self.completion_rules,
            current_turn=1,
            detected_actions=["GIVE_MEDICINE"]
        )
        self.assertFalse(ended, "Hội thoại KHÔNG ĐƯỢC ngắt khi thao tác nghiệp vụ bắt buộc (PAYMENT) chưa hoàn tất")
        self.assertEqual(lifecycle, ConversationLifecycleState.TRANSACTION_PENDING)
        self.assertFalse(self.state["end_validated"])

    def test_D_question_detection_in_text(self):
        """Test D — Interrogative question detection in customer response"""
        self.assertTrue(has_unresolved_question("Thuốc này uống lúc nào vậy chị?"))
        self.assertTrue(has_unresolved_question("Cho tôi hỏi thêm có dùng chung với thuốc huyết áp được không?"))
        self.assertTrue(has_unresolved_question("Loại này có ảnh hưởng gì tới dạ dày không ạ?"))
        self.assertTrue(has_unresolved_question("Thế tôi có cần ăn trước khi uống không?"))
        self.assertFalse(has_unresolved_question("Dạ vâng, em cảm ơn chị nhiều."))
        self.assertFalse(has_unresolved_question("Tôi hiểu rồi, chào dược sĩ nhé."))
    def test_F_offline_request_allows_termination(self):
        """Test F — Offline follow-up request ('có gì báo lại tôi nhé') with end_requested MUST allow termination"""
        rules = CompletionRules(max_turns=10, required_actions=[])
        agent_res = AgentResponse(
            reply="Được rồi, vậy có thông tin gì mới bạn báo tôi ngay nhé. Tôi chờ tin của bạn.",
            conversation_end_requested=True,
            pending_question=False,
            pending_request=True  # offline request, should not block!
        )
        ended, lifecycle, reason = validate_termination(
            state=self.state,
            last_user_input="Tôi sẽ ưu tiên xử lý đề xuất này và liên hệ lại anh/chị ngay.",
            agent_response=agent_res,
            completion_rules=rules,
            current_turn=5
        )
        self.assertTrue(ended, "Hội thoại phải cho phép kết thúc khi khách đã hẹn báo lại offline")
        self.assertEqual(lifecycle, ConversationLifecycleState.COMPLETED)
        self.assertTrue(self.state["end_validated"])

    def test_E_maximum_turn_safety(self):
        """Test E — Maximum turns: Safe circuit-breaker cutoff"""
        agent_res = AgentResponse(
            reply="Tôi vẫn chưa rõ lắm...",
            conversation_end_requested=False,
            pending_question=True
        )
        # Turn 5 with max_turns=6 (0-indexed 5 is turn 6)
        ended, lifecycle, reason = validate_termination(
            state=self.state,
            last_user_input="Bạn có muốn hỏi gì nữa không?",
            agent_response=agent_res,
            completion_rules=self.completion_rules,
            current_turn=5
        )
        self.assertTrue(ended, "Phải cưỡng chế ngắt an toàn khi chạm ngưỡng max_turns")
        self.assertEqual(lifecycle, ConversationLifecycleState.MAX_TURNS_REACHED)
        self.assertIn("tối đa", reason.lower())

    def test_H_opening_greeting_and_inquiry_never_terminates_early(self):
        """Test H — Opening greeting with active inquiry (e.g. Real Estate turn 0) MUST NOT terminate"""
        rules = CompletionRules(max_turns=10, min_turns=3, required_actions=[])
        agent_res = AgentResponse(
            reply="Chào bạn, tôi đang tìm căn hộ 2 phòng ngủ khu vực quận 7 với tài chính tầm 3,5 tỷ. Bạn có căn nào pháp lý chuẩn, đã có sổ hoặc tiến độ xây dựng ổn định thì gửi thông tin chi tiết qua tôi xem nhé.",
            conversation_end_requested=False,
            pending_question=False,
            pending_request=True
        )
        ended, lifecycle, reason = validate_termination(
            state=self.state,
            last_user_input="Chào anh/chị, tôi là chuyên viên tư vấn bất động sản, anh/chị đang quan tâm dự án nào ạ?",
            agent_response=agent_res,
            completion_rules=rules,
            current_turn=0
        )
        self.assertFalse(ended, "Lượt mở đầu chào hỏi và yêu cầu thông tin TUYỆT ĐỐI KHÔNG ĐƯỢC ngắt")
        self.assertEqual(lifecycle, ConversationLifecycleState.ACTIVE)
        self.assertFalse(self.state["end_validated"])


class TestScenarioCompatibility(unittest.TestCase):

    def test_load_all_scenarios(self):
        """Test G — Load and validate all scenario configurations"""
        scenarios = [
            "scenarios/patient_pharmacy.md",
            "scenarios/customer_real_estate.md",
            "scenarios/customer_service_complaint.md"
        ]
        for sc_path in scenarios:
            schema = load_scenario_from_md(sc_path)
            self.assertIsNotNone(schema.title)
            self.assertIsNotNone(schema.role)
            self.assertIsNotNone(schema.user_role)
            self.assertGreater(len(schema.interaction_types), 0, f"{sc_path} must have interaction_types")
            self.assertGreater(schema.completion_rules.max_turns, 0)
            self.assertGreater(len(schema.user_actions), 0)


if __name__ == "__main__":
    unittest.main()
