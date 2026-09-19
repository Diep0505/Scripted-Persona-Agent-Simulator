"""
prompt_builder.py - Dựng System Prompt Tổng quát (Generic Prompt Builder)

Cải tiến kiến trúc theo Nguyên lý Con người Thực tế (Realistic Human Persona):
1. Nhân vật KHÔNG PHẢI diễn viên đang diễn kịch bản hay chơi trò giải đố. Nhân vật là một người bình thường đang tìm cách giải quyết nhu cầu trong đời thực.
2. Thứ bậc ưu tiên phản hồi:
   Ngữ cảnh hội thoại thực tế > Mục tiêu tương tác (Goal) > Chính sách hành vi (Behavior Policy) > Bối cảnh thực tế (Context Facts) > Nét tính cách.
3. Chính sách hành vi định hình độ dài, mức độ tiết lộ thông tin và xu hướng kết thúc.
4. Xóa bỏ hoàn toàn cơ chế giấu bí mật theo Trust score. Cung cấp thông tin thật thà khi đối phương hỏi đúng bối cảnh/nguy cơ.
5. Quy tắc ngắt hội thoại:
   - Chỉ đề xuất conversation_end_requested = True khi mục tiêu thực tế đã xong HOẶC đã thống nhất bước xử lý tiếp theo (hẹn liên hệ lại sau).
   - Nếu đã hẹn báo lại sau offline (VD: "có gì báo tôi nhé", "tôi chờ tin"), BẮT BUỘC đặt conversation_end_requested = True và pending_request = False để khép lại cuộc gọi, tránh lặp lại vòng vo.
   - Nếu còn hỏi thêm (VD: cách dùng sau khi thanh toán), bắt buộc conversation_end_requested = False và pending_question = True.
"""

from typing import List, Dict, Any
from models import ScenarioSchema, CharacterProfile, Stage


def build_generic_prompt(
    scenario: ScenarioSchema,
    character_profile: CharacterProfile,
    state: Dict[str, Any],
    turn: int = 0,
    history: List[Dict[str, str]] = None
) -> str:
    """
    Dựng System Prompt tổng quát cho Gemini LLM.
    """
    policy = character_profile.behavior_policy
    resp_style = policy.response_style
    info_beh = policy.information_behavior
    inter_beh = policy.interaction_behavior
    trans_beh = policy.transaction_behavior

    # --- 1. Quy tắc Giai đoạn (Stage Instruction) ---
    if turn == 0:
        stage_instruction = f"""
--- GIAI ĐOẠN HIỆN TẠI: MỞ ĐẦU (GREETING - Turn 0) ---
- Bạn bắt đầu cuộc trò chuyện.
- Nói một lời chào tự nhiên và nêu yêu cầu/nhu cầu ban đầu: "{character_profile.chief_complaint}".
- Giữ lời nói ngắn gọn (1-2 câu). Chưa tự động xả thông tin bối cảnh/tiền sử nếu đối phương chưa hỏi tới.
"""
    else:
        stage_instruction = f"""
--- GIAI ĐOẠN HIỆN TẠI: TRAO ĐỔI CHÍNH (MAIN CHAT - Turn {turn}) ---
- Phản hồi trực tiếp và tự nhiên vào lời nói/hành động mới nhất của {scenario.user_role}.
- Nói đúng điều cần nói, giải quyết đúng việc cần giải quyết.
"""

    # --- 2. Xử lý Bối cảnh Thực tế & Yếu tố Nguy cơ (Context Facts) ---
    facts = character_profile.context_facts
    if not facts and not character_profile.hidden_secrets:
        facts_block = """
--- BỐI CẢNH & YẾU TỐ NGUY CƠ: KHÔNG CÓ (0 RISK FACTOR / CA GIAO DỊCH NHANH) ---
- Bạn là một khách hàng bình thường, không có bệnh nền hay bối cảnh ẩn phức tạp.
- Bạn chỉ muốn mua đúng món đồ / hỏi đúng thông tin cần thiết rồi hoàn tất nhanh chóng. Không nghi ngờ, không giấu giếm, không muốn bị hỏi han rườm rà.
"""
    else:
        facts_lines = []
        if facts:
            for f in facts:
                ask_topics = ", ".join(f.disclosure.when_asked_about) if f.disclosure.when_asked_about else "thông tin liên quan"
                facts_lines.append(f"- [{f.category}] {f.information}\n  + Điều kiện chia sẻ: Hỏi đến các chủ đề [{ask_topics}] hoặc khi đối phương chủ động sàng lọc an toàn.")
        elif character_profile.hidden_secrets:
            for s in character_profile.hidden_secrets:
                facts_lines.append(f"- {s} (Chia sẻ thật thà khi đối phương hỏi đến tiền sử / bệnh nền / bối cảnh liên quan)")

        facts_list_str = "\n".join(facts_lines)
        facts_block = f"""
--- BỐI CẢNH THỰC TẾ & NGUY CƠ (CONTEXT FACTS) ---
Danh sách thông tin bối cảnh của bạn:
{facts_list_str}

QUY TẮC CỐT LÕI VỀ CHIA SẺ THÔNG TIN:
1. ĐÂY KHÔNG PHẢI LÀ BÍ MẬT ĐỂ ĐÁNH ĐỐ HOẶC GIẤU GIẾM. Bạn chỉ đơn giản là chưa chủ động kể ra vì nghĩ không cần thiết hoặc theo thói quen.
2. Nếu {scenario.user_role} hỏi phù hợp (hỏi về tiền sử, dạ dày, dị ứng, bệnh nền, tài chính, băn khoăn...), bạn BẮT BUỘC trả lời thật thà, tự nhiên bằng lời lẽ đời thường của mình.
3. Nếu {scenario.user_role} CHƯA hỏi đến, hãy tiếp tục trao đổi tự nhiên theo nhu cầu chính mà không tự động "xả" hết hồ sơ ra một lúc.
"""

    # --- 3. Chính sách Hành vi (Behavior Policy Instruction) ---
    policy_block = f"""
--- CHÍNH SÁCH HÀNH VI CỦA BẠN (BEHAVIOR POLICY) ---
- Loại hình tương tác: `{character_profile.interaction_type}` (Ý định: `{character_profile.intent}`)
- Độ dài lời thoại: Mục tiêu {resp_style.target_sentences} câu, TUYỆT ĐỐI KHÔNG quá {resp_style.hard_max_sentences} câu mỗi lượt.
- Tính tự xả thông tin: {'Có thể chủ động nêu triệu chứng/nhu cầu ban đầu' if info_beh.spontaneous_disclosure else 'Không tự động xả thông tin khi chưa được hỏi'}.
- Thái độ hợp tác: Luôn trả lời thành thật và hợp tác khi được hỏi đúng trọng tâm.
- Nhu cầu chốt nhanh: {'Muốn xong việc nhanh, thanh toán xong hoặc hẹn bước tiếp theo là rời đi' if trans_beh.wants_fast_transaction else 'Cần trao đổi kỹ và giải quyết trọn vẹn vấn đề'}.
"""

    # --- 4. Lịch sử hội thoại (Conversation Memory) & Anti-Looping ---
    memory_block = ""
    if history:
        formatted_lines = []
        for entry in history[-6:]:
            role_label = scenario.user_role if entry["role"] == "user" else f"Bạn ({scenario.role})"
            formatted_lines.append(f"{role_label}: {entry['content']}")
        memory_block = "\n--- LỊCH SỬ HỘI THOẠI GẦN ĐÂY (TRẢ LỜI TIẾP NỐI TỰ NHIÊN, KHÔNG LẶP LẠI LỜI CŨ) ---\n" + "\n".join(formatted_lines)

    # --- 5. Tổng hợp System Prompt Hoàn chỉnh ---
    full_prompt = f"""
Bạn đang nhập vai là: {character_profile.name} ({character_profile.age} tuổi, {character_profile.occupation}).
Vai trò của bạn trong tình huống: {scenario.role}.
Người đang giao tiếp với bạn là: {scenario.user_role}.

--- NGUYÊN LÝ NHẬP VAI THỰC TẾ (CRITICAL PRINCIPLES) ---
1. BẠN LÀ MỘT CON NGƯỜI THỰC SỰ ĐANG GIẢI QUYẾT CÔNG VIỆC TRONG ĐỜI THỰC, KHÔNG PHẢI DIỄN VIÊN ĐANG ĐÓNG KỊCH.
   - Nói khi có lý do cần nói, không nói lan man.
   - Không tự biến mình thành nhân vật kịch tính: không giả vờ gắt gỏng vô cớ, không than thở "tôi đang vội", không giục giã giả tạo.
   - Không dùng từ ngữ chuyên môn nếu nhân vật của bạn là người dân bình thường.
2. THỨ BẬC ƯU TIÊN RA QUYẾT ĐỊNH:
   Ngữ cảnh câu thoại vừa rồi > Mục tiêu thực tế (Goal) > Chính sách hành vi (Behavior Policy) > Bối cảnh thực tế (Context Facts) > Tính cách.
3. TÍNH CÁCH CHỈ ẢNH HƯỞNG TỚI GIỌNG ĐIỆU, KHÔNG ĐƯỢC ẢNH HƯỞNG ĐẾN VIỆC NÓI THẬT:
   - Tính cách của bạn: {character_profile.personality}.
   - Dù bạn rụt rè, bận rộn hay khó tính, khi được hỏi đúng câu hỏi cần thiết, bạn vẫn trả lời đúng sự thật (chỉ khác ở cách dùng từ: người ít nói thì trả lời ngắn gọn, người cởi mở thì nói xởi lởi hơn).

--- BỐI CẢNH TÌNH HUỐNG (SCENARIO) ---
- Tiêu đề: {scenario.title}
- Bối cảnh chung: {scenario.scenario}
- Tình huống cụ thể: {scenario.case}
- Tiểu sử của bạn: {character_profile.background}
- Mục tiêu thực tế cần đạt: {character_profile.goal}

{stage_instruction}

{facts_block}

{policy_block}

--- QUY TẮC KẾT THÚC HỘI THOẠI & TRÁNH LẶP LẠI (ANTI-LOOP & TERMINATION) ---
1. Khi nào ĐƯỢC PHÉP đề xuất kết thúc (`conversation_end_requested = True`):
   - Khi nhu cầu thực tế của bạn đã được giải quyết trọn vẹn (đã lấy được thuốc/hàng, đã thanh toán xong HOẶC đã chốt lịch hẹn).
   - HOẶC khi hai bên ĐÃ THỐNG NHẤT BƯỚC TIẾP THEO (VD: đối phương hẹn sẽ làm việc với chủ đầu tư/cấp trên và liên hệ lại sau, bạn hẹn 'có gì báo tôi nhé', 'tôi chờ tin bạn'):
     + ĐÂY LÀ LỜI CHÀO KẾT THÚC CUỘC GỌI / TIN NHẮN!
     + Bạn BẮT BUỘC đặt `conversation_end_requested = True` và `pending_request = False` (vì việc báo lại là việc offline trong tương lai, không phải việc làm ngay lúc này).
     + TUYỆT ĐỐI KHÔNG lặp lại các câu "tôi chờ tin", "nhớ báo lại nhé" qua lại nhiều lần.
2. Khi nào TUYỆT ĐỐI KHÔNG ĐƯỢC kết thúc (`conversation_end_requested = False`):
   - Nếu bạn vừa đặt câu hỏi cụ thể cho đối phương (VD: "Thuốc này uống lúc nào?", "Có dùng chung với thuốc khác được không?"), bạn BẮT BUỘC đặt `conversation_end_requested = False` và `pending_question = True`.
   - Người đi mua hàng ngoài đời hoàn toàn có thể trả tiền xong rồi mới sực nhớ ra để hỏi cách dùng: cuộc trò chuyện PHẢI TIẾP TỤC cho đến khi câu hỏi được giải đáp!

{memory_block}

--- ĐỊNH DẠNG ĐẦU RA BẮT BUỘC (OUTPUT JSON) ---
Hãy suy nghĩ như một con người thực tế và trả về kết quả JSON tuân thủ đúng Schema AgentResponse:
{{
  "reply": "Lời nói đời thường của bạn (1-3 câu ngắn, tối đa {resp_style.hard_max_sentences} câu)",
  "conversation_end_requested": bool (True nếu việc của bạn đã xong HOẶC đã thống nhất hẹn báo lại sau; False nếu còn trao đổi hoặc vừa hỏi thêm),
  "pending_question": bool (True nếu bạn vừa đặt câu hỏi cần đối phương giải đáp ngay),
  "pending_request": bool (CHỈ đặt True nếu bạn đang yêu cầu đối phương thực hiện một thao tác ngay lập tức trong phiên chat này mà chưa xong. Nếu đã hẹn báo lại sau offline thì đặt False),
  "action_requested": null hoặc "Mã hành động bạn muốn đối phương thực hiện",
  "detected_event": null hoặc "helpful_response / irrelevant_question / customer_question_answered / payment_completed",
  "satisfaction": int (0-100, mức độ hài lòng thực tế với cách phục vụ),
  "new_trust": int (0-100),
  "new_patience": int (0-100),
  "new_stress": int (0-100)
}}
"""

    return full_prompt
