"""
state_machine.py - Bộ quản lý Trạng thái & Vòng đời Hội thoại (State Machine & Lifecycle Validator)

Cải tiến kiến trúc:
1. Quản lý ConversationLifecycleState: ACTIVE, WAITING_FOR_RESPONSE, TRANSACTION_PENDING, COMPLETION_CANDIDATE, COMPLETED, MAX_TURNS_REACHED.
2. Bộ kiểm chứng kết thúc (validate_termination):
   - Độc lập xác thực xem cuộc hội thoại đã thực sự hoàn tất chưa.
   - conversation_end_requested từ LLM chỉ là ĐỀ NGHỊ (Request), không phải lệnh cưỡng chế.
   - Bắt buộc kiểm tra Pending Question (câu hỏi dở dang từ khách hàng).
   - KHÔNG chặn kết thúc khi khách hàng đã yêu cầu ngắt (conversation_end_requested=True) chỉ vì một yêu cầu xử lý offline trong tương lai (như "có gì báo lại tôi sau nhé").
   - Cơ chế Chống lặp hội thoại (Anti-Loop Circuit Breaker): Tự động phát hiện khi hai bên đã thống nhất bước tiếp theo và lặp lại các câu chào/hẹn báo lại để ngắt dứt khoát, không để hội thoại trôi đến max_turns.
3. Chuyển đổi trạng thái cảm xúc theo sự kiện (Event-driven):
   - Thay đổi Satisfaction, Patience, Stress một cách có quy luật dựa trên diễn biến.
4. Xóa bỏ luật lệ game cơ học Trust > 60 để mở bí mật; chuyển sang kiểm tra sự thật bối cảnh theo ngữ cảnh câu hỏi.
"""

import re
from typing import Optional, List, Dict, Any, Tuple
from models import InitialState, ConversationLifecycleState, CompletionRules, AgentResponse


# Các mẫu câu hỏi hoặc thắc mắc phổ biến trong Tiếng Việt và Tiếng Anh
QUESTION_PATTERNS = [
    r"\?",                                             # Dấu hỏi chấm
    r"\b(uống|dùng|sử dụng)\s+(như thế nào|lúc nào|khi nào|mấy viên|bao nhiêu)\b",
    r"\b(trước|sau)\s+khi\s+ăn\b",
    r"\b(có|dùng)\s+(chung|cùng)\s+với\b",
    r"\b(có\s+sao\s+không|có\s+ảnh\s+hưởng|có\s+tác\s+dụng\s+phụ)\b",
    r"\b(cho\s+tôi|cho\s+em|cho\s+mình)\s+hỏi\s+(thêm|chút|với)\b",
    r"\b(bao\s+nhiêu|bao\s+lâu|mấy\s+lần|giá\s+thế\s+nào)\b",
    r"\b(phải\s+không|đúng\s+không|được\s+không|hả|nhỉ|ạ\?)\b",
    r"\b(how\s+to|what\s+about|when\s+should|can\s+i|is\s+it\s+safe)\b",
]

QUESTION_REGEX = re.compile("|".join(QUESTION_PATTERNS), re.IGNORECASE)

# Các mẫu câu yêu cầu thông tin / tìm kiếm / tư vấn trực tiếp (Active Inquiry - KHÔNG PHẢI wrap-up)
ACTIVE_INQUIRY_PATTERNS = [
    r"\b(gửi\s+(giúp\s+)?(cho\s+)?(tôi|em|mình)?\s*(bảng\s+giá|thông\s+tin|chi\s+tiết|pháp\s+lý|thiết\s+kế|hình\s+ảnh|tài\s+liệu))\b",
    r"\b(tôi\s+đang\s+tìm|cần\s+tìm|tìm\s+căn|tìm\s+nhà|tìm\s+thuốc)\b",
    r"\b(bán\s+cho|lấy\s+cho|lấy\s+em|lấy\s+tôi|cắt\s+cho)\b",
    r"\b(tư\s+vấn\s+(cho|giúp)|giới\s+thiệu\s+(cho|giúp))\b",
    r"\b(có\s+(căn|dự\s+án|loại|thuốc|mẫu)\s+nào)\b",
    r"\b(báo\s+giá\s+(giúp|cho)|tài\s+chính\s+tầm)\b",
]

ACTIVE_INQUIRY_REGEX = re.compile("|".join(ACTIVE_INQUIRY_PATTERNS), re.IGNORECASE)

# Các mẫu câu thống nhất bước tiếp theo / chào kết thúc thực sự (Wrap-up / Next Steps Agreed / Farewell)
WRAP_UP_PATTERNS = [
    r"\b(chờ\s+tin|đợi\s+tin\s+từ\s+(bạn|anh|em|chị)|khi\s+nào\s+có\s+(kết\s+quả|tin|thông\s+tin)\s+thì\s+báo)\b",
    r"\b(báo\s+lại\s+(tôi|em|mình)\s+sau|liên\s+hệ\s+lại\s+sau|có\s+gì\s+báo\s+sau)\b",
    r"\b(chốt\s+lịch\s+sau|trao\s+đổi\s+sau|sắp\s+xếp\s+sau|hẹn\s+bữa\s+khác)\b",
    r"\b(tạm\s+biệt|hẹn\s+gặp\s+lại|chào\s+(bạn|chị|anh)\s+nhé|em\s+chào\s+(chị|anh)\s+ạ|xin\s+phép\s+(về|dừng))\b",
    r"\b(tôi\s+chờ\s+tin\s+nhé|tôi\s+đợi\s+nhé)\b",
]

WRAP_UP_REGEX = re.compile("|".join(WRAP_UP_PATTERNS), re.IGNORECASE)


def has_unresolved_question(text: str) -> bool:
    """
    Kiểm tra xem câu thoại có chứa câu hỏi, thắc mắc hoặc yêu cầu làm rõ đang chờ giải đáp hay không.
    """
    if not text:
        return False
    stripped = text.strip()
    return bool(QUESTION_REGEX.search(stripped))


def is_wrap_up_statement(text: str) -> bool:
    """
    Kiểm tra xem câu thoại có phải là lời chốt bước tiếp theo / chào kết thúc không.
    Nếu câu có chứa yêu cầu tìm kiếm, gửi thông tin, báo giá hoặc thắc mắc trực tiếp -> KHÔNG PHẢI wrap-up.
    """
    if not text:
        return False
    stripped = text.strip()
    if ACTIVE_INQUIRY_REGEX.search(stripped):
        return False
    return bool(WRAP_UP_REGEX.search(stripped))


def make_initial_state(initial_config: Optional[InitialState] = None) -> dict:
    """Tạo mới một dictionary trạng thái ban đầu dựa trên cấu hình kịch bản."""
    base_state = {
        "lifecycle_state": ConversationLifecycleState.ACTIVE.value,
        "patience": 100,
        "trust": 50,
        "stress": 10,
        "satisfaction": 80,
        "conversation_end": False,
        "completed_actions": [],
        "pending_customer_question": False,
        "pending_customer_request": False,
        "end_requested": False,
        "end_validated": False,
        "termination_reason": None,
        "context_facts_disclosed": [],
        "wrap_up_turn_count": 0,
    }

    if initial_config:
        base_state["patience"] = initial_config.patience
        base_state["trust"] = initial_config.trust
        base_state["stress"] = initial_config.stress
        base_state["satisfaction"] = getattr(initial_config, "satisfaction", 80)
        base_state["conversation_end"] = initial_config.conversation_end

    return base_state


def clamp_state(state: dict) -> None:
    """Cắt giới hạn điểm cảm xúc trong đoạn từ 0 đến 100."""
    for key in ["patience", "trust", "stress", "satisfaction"]:
        if key in state:
            state[key] = max(0, min(100, int(state[key])))


def handle_event(state: dict, event_name: Optional[str]) -> None:
    """
    Cập nhật trạng thái cảm xúc theo sự kiện ngữ nghĩa xác định (Deterministic Event Updates).
    """
    if not event_name:
        return

    event = event_name.strip().lower()

    if event in ["helpful_response", "good_advice", "clear_explanation"]:
        state["satisfaction"] = state.get("satisfaction", 80) + 10
        state["patience"] = state.get("patience", 100) + 5
        state["stress"] = state.get("stress", 10) - 5
        state["trust"] = state.get("trust", 50) + 5

    elif event in ["irrelevant_question", "repeated_question", "interrogation"]:
        state["satisfaction"] = state.get("satisfaction", 80) - 10
        state["patience"] = state.get("patience", 100) - 15
        state["stress"] = state.get("stress", 10) + 10

    elif event in ["customer_question_answered", "clear_answer"]:
        state["satisfaction"] = state.get("satisfaction", 80) + 10
        state["pending_customer_question"] = False

    elif event in ["payment_completed", "transaction_completed", "action_completed"]:
        state["satisfaction"] = state.get("satisfaction", 80) + 5

    elif event in ["customer_confused", "customer_dissatisfied"]:
        state["satisfaction"] = state.get("satisfaction", 80) - 15
        state["stress"] = state.get("stress", 10) + 15

    clamp_state(state)


def update_state(
    state: dict,
    new_trust: int,
    new_patience: int,
    new_stress: int,
    satisfaction: Optional[int] = None,
    detected_event: Optional[str] = None
) -> None:
    """
    Cập nhật điểm cảm xúc được chấm bởi Gemini API và xử lý sự kiện kèm theo.
    """
    state["trust"] = new_trust
    state["patience"] = new_patience
    state["stress"] = new_stress
    if satisfaction is not None:
        state["satisfaction"] = satisfaction

    if detected_event:
        handle_event(state, detected_event)

    clamp_state(state)


def reset_state(state: dict, initial_config: Optional[InitialState] = None) -> None:
    """Đặt lại trạng thái về ban đầu."""
    initial = make_initial_state(initial_config)
    state.clear()
    state.update(initial)


def record_action(state: dict, action_tag: str) -> None:
    """Ghi nhận một hành động nghiệp vụ đã hoàn tất."""
    if action_tag and action_tag != "NONE":
        clean_tag = action_tag.replace("[", "").replace("]", "").strip()
        if clean_tag and clean_tag not in state.get("completed_actions", []):
            if "completed_actions" not in state:
                state["completed_actions"] = []
            state["completed_actions"].append(clean_tag)


def validate_termination(
    state: dict,
    last_user_input: str,
    agent_response: AgentResponse,
    completion_rules: CompletionRules,
    current_turn: int,
    detected_actions: Optional[List[str]] = None
) -> Tuple[bool, ConversationLifecycleState, str]:
    """
    Bộ thẩm định tính hoàn tất của hội thoại (Conversation Termination Protocol).
    
    Quy tắc cốt lõi:
    - conversation_end_requested từ LLM là một YÊU CẦU ngắt, KHÔNG PHẢI MỆNH LỆNH.
    - Python Engine thẩm định độc lập các điều kiện:
      1. Turn limit: Nếu turn >= max_turns -> cưỡng chế ngắt (MAX_TURNS_REACHED).
      2. Pending Question: Nếu câu thoại vừa rồi của khách hàng có câu hỏi chưa giải đáp -> TỪ CHỐI ngắt.
      3. Pending Request: Chỉ chặn ngắt nếu khách hàng yêu cầu xử lý ngay trong phiên chat (conversation_end_requested == False).
         Nếu khách hàng đã muốn kết thúc hoặc hẹn báo lại sau offline -> KHÔNG CHẶN.
      4. Anti-Loop Circuit Breaker: Nếu hai bên đã thống nhất bước tiếp theo và lặp lại lời hẹn/chào -> TỰ ĐỘNG KẾT THÚC.
      5. Required Actions: Nếu kịch bản yêu cầu hành động bắt buộc (VD: PAYMENT) mà chưa làm -> TỪ CHỐI ngắt.
      6. End Request: Nếu các điều kiện trên thỏa mãn VÀ khách hàng đề xuất ngắt -> CHẤP THUẬN (COMPLETED).
    
    Returns:
        Tuple[bool, ConversationLifecycleState, str]:
        (is_terminated, lifecycle_state, reason_description)
    """
    max_turns = completion_rules.max_turns
    min_turns = getattr(completion_rules, "min_turns", 2)

    # 1. Ghi nhận các hành động nghiệp vụ vừa xuất hiện
    if detected_actions:
        for act in detected_actions:
            record_action(state, act)

    # 2. Cầu chì khẩn cấp: Đạt ngưỡng Max Turns
    if current_turn >= max_turns - 1:
        state["lifecycle_state"] = ConversationLifecycleState.MAX_TURNS_REACHED.value
        state["end_validated"] = True
        state["conversation_end"] = True
        reason = f"Đạt ngưỡng số lượt tối đa cho phép ({max_turns} turns) - Cầu chì khẩn cấp ngắt hội thoại an toàn."
        state["termination_reason"] = reason
        return True, ConversationLifecycleState.MAX_TURNS_REACHED, reason

    # 3. Chốt chặn số lượt tối thiểu (Min Turns Protection)
    # Tuyệt đối không cho phép kết thúc tự nhiên ở những lượt đầu khi hai bên chưa kịp trao đổi nghiệp vụ (Turn < min_turns - 1)
    if current_turn < min_turns - 1:
        state["lifecycle_state"] = ConversationLifecycleState.ACTIVE.value
        state["end_validated"] = False
        state["conversation_end"] = False
        state["wrap_up_turn_count"] = 0
        reason = f"Hội thoại mới ở lượt {current_turn + 1}/{min_turns}, chưa đủ số lượt trao đổi tối thiểu để kết thúc."
        state["termination_reason"] = reason
        return False, ConversationLifecycleState.ACTIVE, reason

    # 4. Kiểm tra Pending Question từ phía khách hàng
    reply_text = agent_response.reply
    has_question_in_reply = has_unresolved_question(reply_text)
    is_pending_question = agent_response.pending_question or has_question_in_reply

    state["pending_customer_question"] = is_pending_question
    state["end_requested"] = agent_response.conversation_end_requested

    if is_pending_question and not completion_rules.allow_end_with_pending_question:
        state["lifecycle_state"] = ConversationLifecycleState.ACTIVE.value
        state["end_validated"] = False
        state["conversation_end"] = False
        state["wrap_up_turn_count"] = 0
        reason = "Từ chối ngắt: Khách hàng vừa đặt một câu hỏi/thắc mắc cần được phản hồi tiếp."
        state["termination_reason"] = reason
        return False, ConversationLifecycleState.ACTIVE, reason

    # 5. Kiểm tra Required Actions (Hành động bắt buộc phải thực hiện)
    required_actions = completion_rules.required_actions or []
    completed_actions = state.get("completed_actions", [])
    missing_actions = [
        req.replace("[", "").replace("]", "").strip()
        for req in required_actions
        if req.replace("[", "").replace("]", "").strip() not in completed_actions
    ]

    if missing_actions:
        state["lifecycle_state"] = ConversationLifecycleState.TRANSACTION_PENDING.value
        state["end_validated"] = False
        state["conversation_end"] = False
        reason = f"Từ chối ngắt: Chưa hoàn tất thao tác nghiệp vụ bắt buộc: {missing_actions}"
        state["termination_reason"] = reason
        return False, ConversationLifecycleState.TRANSACTION_PENDING, reason

    # 6. Kiểm tra Pending Request / Active Inquiry trực tiếp
    # Nếu câu nói của khách chứa yêu cầu nhận thông tin (tìm nhà, gửi bảng giá/pháp lý, lấy thuốc...)
    # hoặc có cờ pending_request (và khách chưa chủ động xin kết thúc hội thoại)
    has_inquiry = bool(ACTIVE_INQUIRY_REGEX.search(reply_text))
    if has_inquiry or (agent_response.pending_request and not agent_response.conversation_end_requested):
        if not is_wrap_up_statement(reply_text):
            state["lifecycle_state"] = ConversationLifecycleState.ACTIVE.value
            state["end_validated"] = False
            state["conversation_end"] = False
            state["wrap_up_turn_count"] = 0
            reason = "Từ chối ngắt: Khách hàng còn yêu cầu xử lý/cung cấp thông tin trực tiếp chưa được đối phương đáp ứng."
            state["termination_reason"] = reason
            return False, ConversationLifecycleState.ACTIVE, reason

    # 7. Kiểm tra xem Agent có chủ động đề xuất kết thúc hội thoại không
    if agent_response.conversation_end_requested:
        state["lifecycle_state"] = ConversationLifecycleState.COMPLETED.value
        state["end_validated"] = True
        state["conversation_end"] = True
        reason = "Cuộc hội thoại đã kết thúc tự nhiên và trọn vẹn: Đã thống nhất phương án/xong việc và không còn thắc mắc dở dang."
        state["termination_reason"] = reason
        return True, ConversationLifecycleState.COMPLETED, reason

    # 8. Cơ chế Chống lặp (Anti-Loop Circuit Breaker):
    # Chỉ áp dụng khi:
    # - Hội thoại đã qua ít nhất 2 lượt trao đổi (current_turn >= 2)
    # - Cả 2 bên liên tục lặp lại các câu chốt hẹn bước tiếp theo / chào kết thúc (wrap_up_turn_count >= 2)
    # - Không có câu hỏi mới hoặc yêu cầu thông tin mới
    if current_turn >= 2:
        is_wrap_up = is_wrap_up_statement(reply_text)
        if is_wrap_up:
            state["wrap_up_turn_count"] = state.get("wrap_up_turn_count", 0) + 1
            if state["wrap_up_turn_count"] >= 2:
                state["lifecycle_state"] = ConversationLifecycleState.COMPLETED.value
                state["end_validated"] = True
                state["conversation_end"] = True
                reason = "Hai bên đã thống nhất xong bước xử lý tiếp theo và liên tục xác nhận. Tự động hoàn tất hội thoại tránh lặp lại."
                state["termination_reason"] = reason
                return True, ConversationLifecycleState.COMPLETED, reason
        else:
            state["wrap_up_turn_count"] = 0

    # 9. Nếu chưa ai yêu cầu kết thúc và chưa có tín hiệu chốt bước tiếp theo -> Tiếp tục
    state["lifecycle_state"] = ConversationLifecycleState.ACTIVE.value
    state["end_validated"] = False
    state["conversation_end"] = False
    reason = "Hội thoại đang diễn ra bình thường."
    state["termination_reason"] = reason
    return False, ConversationLifecycleState.ACTIVE, reason


def can_reveal_secret(state: dict) -> bool:
    """
    Hàm tương thích ngược.
    Không còn dùng luật Trust > 60 máy móc, trả về True nếu đã từng chia sẻ bối cảnh/nguy cơ.
    """
    return len(state.get("context_facts_disclosed", [])) > 0