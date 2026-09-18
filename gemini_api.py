"""
gemini_api.py - Động cơ Sinh Nhân vật & Gọi Gemini API với Structured Output

Cập nhật kiến trúc Realistic Persona Simulation & Khả năng chịu lỗi cao (Fault-Tolerant):
1. Tách bạch interaction_type (loại hình tương tác), intent, behavior_policy và context_facts.
2. Sinh bối cảnh thực tế (Context Facts) thay vì 'bí mật ẩn', có từ khóa kích hoạt khi được hỏi (when_asked_about).
3. Hỗ trợ trường hợp 0 bối cảnh ẩn (Giao dịch nhanh, mua thẳng) mượt mà, không ép nhân vật phải có bệnh/nguy cơ.
4. Tự động khắc phục lỗi quá tải tạm thời (503 UNAVAILABLE / 429 RESOURCE_EXHAUSTED):
   - Tự động Retry với Exponential Backoff khi API gặp demand spike.
   - Tự động chuyển đổi sang Fallback Models (như gemini-3.6-flash, gemini-3.5-flash-lite) nếu model chính quá tải.
5. Gọi Gemini API với Structured Output cho cả CharacterProfile và AgentResponse.
6. Bảo đảm 100% an toàn fallback khi xảy ra sự cố mạng hoặc lỗi API.
"""

import json
import time
import random
from typing import List, Optional, Any
from google import genai
from google.genai import types
from google.genai.errors import ServerError, APIError
from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    FALLBACK_MODELS,
    TEMPERATURE,
    MAX_OUTPUT_TOKENS,
    TOP_P,
)
from models import (
    ScenarioSchema,
    CharacterProfile,
    AgentResponse,
    BehaviorPolicy,
    ResponseStyle,
    InformationBehavior,
    InteractionBehavior,
    TransactionBehavior,
    ContextFact,
    FactDisclosure,
    InteractionTypeConfig,
)

# Khởi tạo Google GenAI Client
client = genai.Client(api_key=GEMINI_API_KEY)


def generate_content_with_retry(
    client: Any,
    model: str,
    contents: Any,
    config: Optional[types.GenerateContentConfig] = None,
    max_retries: int = 4,
    initial_delay: float = 2.0,
    fallback_models: Optional[List[str]] = None
) -> Any:
    """
    Gọi client.models.generate_content với cơ chế Exponential Backoff và Model Fallback
    khi gặp các lỗi quá tải tạm thời (503 UNAVAILABLE, 429 RESOURCE_EXHAUSTED, 500, 504).
    """
    models_to_try = [model]
    candidate_fallbacks = fallback_models or FALLBACK_MODELS or ["gemini-3.6-flash", "gemini-3.5-flash-lite"]
    for fb in candidate_fallbacks:
        if fb and fb not in models_to_try:
            models_to_try.append(fb)

    last_error = None

    for model_idx, current_model in enumerate(models_to_try):
        delay = initial_delay
        for attempt in range(max_retries):
            try:
                return client.models.generate_content(
                    model=current_model,
                    contents=contents,
                    config=config
                )
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                is_transient = (
                    isinstance(e, (ServerError, APIError)) or
                    "503" in err_str or
                    "unavailable" in err_str or
                    "429" in err_str or
                    "resource_exhausted" in err_str or
                    "high demand" in err_str or
                    "temporary" in err_str or
                    "500" in err_str or
                    "504" in err_str or
                    "timeout" in err_str or
                    "deadline" in err_str
                )

                if is_transient and attempt < max_retries - 1:
                    jitter = random.uniform(0.5, 1.5)
                    sleep_time = delay * jitter
                    print(f"⚠️ Model '{current_model}' đang quá tải tạm thời (503/429/Network). Thử lại sau {sleep_time:.1f}s (lần {attempt + 1}/{max_retries})...")
                    time.sleep(sleep_time)
                    delay *= 2
                else:
                    if model_idx + 1 < len(models_to_try):
                        next_model = models_to_try[model_idx + 1]
                        print(f"🔄 Model '{current_model}' không phản hồi sau {attempt + 1} lần thử. Tự động chuyển sang Model dự phòng: '{next_model}'...")
                    break

    raise last_error


def _get_default_behavior_policy(interaction_type: str) -> BehaviorPolicy:
    """Tạo chính sách hành vi mặc định phù hợp với từng loại tương tác."""
    if interaction_type == "named_purchase" or interaction_type == "quick_transaction":
        return BehaviorPolicy(
            response_style=ResponseStyle(verbosity="low", target_sentences="1-2", hard_max_sentences=3),
            information_behavior=InformationBehavior(spontaneous_disclosure=False, answer_when_asked=True, volunteer_extra_information="low"),
            interaction_behavior=InteractionBehavior(asks_questions_spontaneously=False, seeks_professional_advice=False, challenges_professional=False),
            transaction_behavior=TransactionBehavior(wants_fast_transaction=True, leaves_after_completion=True)
        )
    elif interaction_type == "symptom_consultation" or interaction_type == "consultation":
        return BehaviorPolicy(
            response_style=ResponseStyle(verbosity="low", target_sentences="1-3", hard_max_sentences=5),
            information_behavior=InformationBehavior(spontaneous_disclosure=True, answer_when_asked=True, volunteer_extra_information="moderate"),
            interaction_behavior=InteractionBehavior(asks_questions_spontaneously=True, seeks_professional_advice=True, challenges_professional=False),
            transaction_behavior=TransactionBehavior(wants_fast_transaction=False, leaves_after_completion=True)
        )
    elif interaction_type == "specific_request_with_risk" or interaction_type == "risk_case":
        return BehaviorPolicy(
            response_style=ResponseStyle(verbosity="low", target_sentences="1-3", hard_max_sentences=4),
            information_behavior=InformationBehavior(spontaneous_disclosure=False, answer_when_asked=True, volunteer_extra_information="low"),
            interaction_behavior=InteractionBehavior(asks_questions_spontaneously=False, seeks_professional_advice=False, challenges_professional=False),
            transaction_behavior=TransactionBehavior(wants_fast_transaction=True, leaves_after_completion=True)
        )
    # Default general
    return BehaviorPolicy(
        response_style=ResponseStyle(verbosity="low", target_sentences="1-3", hard_max_sentences=5),
        information_behavior=InformationBehavior(spontaneous_disclosure=False, answer_when_asked=True, volunteer_extra_information="low"),
        interaction_behavior=InteractionBehavior(asks_questions_spontaneously=False, seeks_professional_advice=False, challenges_professional=False),
        transaction_behavior=TransactionBehavior(wants_fast_transaction=True, leaves_after_completion=True)
    )


def generate_dynamic_persona(scenario: ScenarioSchema) -> CharacterProfile:
    """
    Tự động sinh Profile nhân vật (CharacterProfile) thông qua Gemini API.
    Xử lý phân loại interaction_type, sinh behavior_policy và context_facts thực tế.
    """
    pools = scenario.dynamic_pools

    # 🎲 1. Bốc ngẫu nhiên thông số nhân khẩu học bằng Python
    names = pools.names if pools.names else ["Nguyễn Văn A", "Trần Thị B"]
    occupations = pools.occupations if pools.occupations else ["Sinh viên", "Nhân viên"]
    personalities = pools.personalities if pools.personalities else ["Cởi mở, hợp tác"]
    age_ranges = pools.age_ranges if pools.age_ranges else [[20, 30]]

    selected_name = random.choice(names)
    selected_occupation = random.choice(occupations)
    selected_personality = random.choice(personalities)

    selected_range = random.choice(age_ranges)
    min_age = selected_range[0] if len(selected_range) > 0 else 20
    max_age = selected_range[1] if len(selected_range) > 1 else min_age + 5
    selected_age = random.randint(min_age, max_age)

    # 🎲 2. Xác định Loại hình Tương tác (interaction_type & intent)
    selected_itype = "general"
    selected_intent = "general_intent"
    selected_goal = scenario.goal or "Hoàn thành phiên giao tiếp"

    if scenario.interaction_types and len(scenario.interaction_types) > 0:
        cfg = random.choice(scenario.interaction_types)
        selected_itype = cfg.id
        selected_intent = cfg.intent
        if cfg.goal:
            selected_goal = cfg.goal
    else:
        # Tự động phân loại dựa trên personality hoặc pools
        pers_lower = selected_personality.lower()
        if "mua theo thói quen" in pers_lower or "mua nhanh" in pers_lower or "khách nét" in pers_lower or "tra cứu" in pers_lower:
            selected_itype = "named_purchase"
            selected_intent = "buy_specific_product"
        elif "chủ động" in pers_lower or "tư vấn" in pers_lower or "sự cố" in pers_lower:
            selected_itype = "symptom_consultation"
            selected_intent = "seek_professional_advice"
        elif "thụ động" in pers_lower or "cẩn trọng" in pers_lower:
            selected_itype = "specific_request_with_risk"
            selected_intent = "buy_requested_product"

    default_policy = _get_default_behavior_policy(selected_itype)

    # 🎲 3. Xử lý logic Chief Complaint (Lý do mở đầu)
    preselected_complaint = None
    if scenario.chief_complaint:
        preselected_complaint = scenario.chief_complaint
    elif pools.chief_complaints and len(pools.chief_complaints) > 0:
        preselected_complaint = random.choice(pools.chief_complaints)

    complaint_instruction = ""
    if preselected_complaint:
        complaint_instruction = f"""
    - LÝ DO MỞ ĐẦU (chief_complaint): BẮT BUỘC GIỮ NGUYÊN chuỗi đã chọn sau đây: "{preselected_complaint}"
    """
    else:
        rules = scenario.complaint_generation_rules
        instr = rules.instruction if rules else "Sinh ra 1 câu lý do mở đầu/yêu cầu ngắn gọn, tự nhiên."
        scopes = ", ".join(rules.allowed_symptom_scopes) if (rules and rules.allowed_symptom_scopes) else "Chung"
        complaint_instruction = f"""
    - TỰ SINH LÝ DO MỞ ĐẦU (chief_complaint): Hãy sáng tạo 1 câu mở đầu/yêu cầu ban đầu thật tự nhiên và ngắn gọn (1-2 câu đời thường).
      + Loại hình tương tác: {selected_itype} (Ý định: {selected_intent})
      + Chỉ dẫn: {instr}
      + Phạm vi chủ đề cho phép: [{scopes}]
      + Phù hợp độ tuổi ({selected_age}), nghề nghiệp ({selected_occupation}) và vai trò ({scenario.role}).
    """

    # 🎲 4. Xử lý logic Context Facts / Risk Factors
    has_hardcoded_secrets = scenario.hidden_secrets is not None and len(scenario.hidden_secrets) > 0
    secret_instruction = ""

    if has_hardcoded_secrets:
        secret_instruction = f"""
    - BỐI CẢNH CỐ ĐỊNH: BẮT BUỘC giữ nguyên các thông tin sau và đưa vào context_facts: {scenario.hidden_secrets}
    """
    else:
        sec_rules = scenario.secret_generation_rules
        min_sec = sec_rules.min_secrets if sec_rules else 0
        max_sec = sec_rules.max_secrets if sec_rules else 2
        instr = sec_rules.instruction if sec_rules else "Sinh ra bối cảnh/nguy cơ thực tế liên quan đến vấn đề đang hỏi."
        topics = ", ".join(sec_rules.secret_topics) if (sec_rules and sec_rules.secret_topics) else "Thông tin bối cảnh thực tế"

        if selected_itype == "named_purchase" and min_sec == 0:
            secret_instruction = f"""
    - BỐI CẢNH THỰC TẾ (context_facts): Nhân vật thuộc loại hình 'named_purchase' (mua nhanh/hỏi thẳng không bệnh nền).
      BẮT BUỘC để `context_facts` là mảng rỗng `[]` (0 yếu tố nguy cơ/0 bối cảnh ẩn).
    """
        else:
            secret_instruction = f"""
    - TỰ SINH YẾU TỐ BỐI CẢNH / NGUY CƠ (context_facts): Thiết kế từ {min_sec} đến {max_sec} thông tin bối cảnh thực tế hoặc tiền sử/nguy cơ.
      + Chỉ dẫn: {instr}
      + Chủ đề: [{topics}]
      + Lưu ý quan trọng: Đây KHÔNG PHẢI là bí mật để chơi trò giấu giếm, mà là bối cảnh đời thường. Thiết lập `disclosure.when_asked_about` là danh sách các từ khóa/chủ đề khi đối phương hỏi tới thì nhân vật sẽ chia sẻ thật thà.
    """

    # Đề tài đồ án (nếu có trong pool student)
    project_topic_str = ""
    if pools.project_topics and len(pools.project_topics) > 0:
        selected_topic = random.choice(pools.project_topics)
        project_topic_str = f"- Đề tài / Công việc: {selected_topic}"

    # Prompt tổng thể cho Gemini
    prompt_instruction = f"""
    Bạn là chuyên gia thiết kế hồ sơ nhân vật mô phỏng giao tiếp thực tế đời thường (Generic Persona Simulation).
    Hãy tạo một hồ sơ nhân vật (CharacterProfile) chi tiết dựa trên các thông số cấu hình sau:

    --- THAM SỐ CỐ ĐỊNH (BẮT BUỘC GIỮ NGUYÊN) ---
    - Tên: {selected_name}
    - Tuổi: {selected_age} (Khoảng: {min_age}-{max_age})
    - Nghề nghiệp: {selected_occupation}
    - Nét tính cách: {selected_personality}
    - Loại hình tương tác (interaction_type): {selected_itype}
    - Ý định chính (intent): {selected_intent}
    {project_topic_str}

    --- BỐI CẢNH KỊCH BẢN ---
    - Vai trò nhân vật: {scenario.role}
    - Bối cảnh: {scenario.scenario}
    - Chi tiết tình huống: {scenario.case}
    - Mục tiêu thực tế (goal): {selected_goal}

    --- QUY TẮC SINH CHIEF COMPLAINT ---
    {complaint_instruction}

    --- QUY TẮC SINH CONTEXT FACTS ---
    {secret_instruction}

    Yêu cầu bổ sung:
    1. Viết tiểu sử (background) ngắn gọn 2-3 câu gắn liền với hoàn cảnh sống đời thường.
    2. Điền `behavior_policy` tuân thủ nguyên tắc: văn phong ngắn gọn (1-3 câu), dân dã, không nói lan man, không kịch hóa.
    3. Trả về đúng định dạng JSON tuân thủ CharacterProfile schema.
    """

    try:
        response = generate_content_with_retry(
            client=client,
            model=GEMINI_MODEL,
            contents=prompt_instruction,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CharacterProfile,
                temperature=0.75,
            ),
        )

        persona_data = json.loads(response.text)
        persona = CharacterProfile(**persona_data)

        # Fallback bổ sung & đồng bộ dữ liệu
        persona.interaction_type = selected_itype
        persona.intent = selected_intent
        if not persona.goal:
            persona.goal = selected_goal

        if preselected_complaint and not persona.chief_complaint:
            persona.chief_complaint = preselected_complaint

        # Đồng bộ giữa context_facts và hidden_secrets để đảm bảo tương thích ngược
        if persona.context_facts and not persona.hidden_secrets:
            persona.hidden_secrets = [f.information for f in persona.context_facts]
        elif persona.hidden_secrets and not persona.context_facts:
            persona.context_facts = [
                ContextFact(
                    id=f"fact_{i}",
                    information=sec,
                    category="general",
                    relevance="high",
                    disclosure=FactDisclosure(spontaneous=False, when_asked_about=["bệnh nền", "tiền sử", "sức khỏe", "thông tin"])
                )
                for i, sec in enumerate(persona.hidden_secrets)
            ]

        # Đảm bảo behavior_policy có giá trị hợp lệ
        if not persona.behavior_policy or not persona.behavior_policy.response_style:
            persona.behavior_policy = default_policy

        return persona

    except Exception as e:
        print(f"⚠️ Lỗi khi gọi Gemini API sinh nhân vật: {e}. Sử dụng Fallback bối cảnh an toàn.")
        fallback_facts = []
        if scenario.hidden_secrets:
            fallback_facts = [
                ContextFact(
                    id=f"fact_{i}",
                    information=sec,
                    category="general",
                    relevance="high",
                    disclosure=FactDisclosure(spontaneous=False, when_asked_about=["tiền sử", "bệnh nền"])
                )
                for i, sec in enumerate(scenario.hidden_secrets)
            ]

        return CharacterProfile(
            name=selected_name,
            age=selected_age,
            occupation=selected_occupation,
            personality=selected_personality,
            background=f"Nhân vật {selected_name}, {selected_age} tuổi, làm nghề {selected_occupation}.",
            chief_complaint=preselected_complaint or "Tôi muốn hỏi mua thuốc/dịch vụ.",
            interaction_type=selected_itype,
            intent=selected_intent,
            behavior_policy=default_policy,
            context_facts=fallback_facts,
            hidden_secrets=scenario.hidden_secrets or [f.information for f in fallback_facts],
            goal=selected_goal
        )


def ask_gemini(system_prompt: str, user_input: str) -> AgentResponse:
    """
    Gửi System Prompt và tin nhắn người dùng tới Gemini API với cơ chế tự động thử lại và dự phòng.
    Bắt buộc Gemini trả về Structured JSON tuân thủ AgentResponse Schema.
    """
    response = generate_content_with_retry(
        client=client,
        model=GEMINI_MODEL,
        contents=f"""
{system_prompt}

Tin nhắn/Hành động mới nhất từ đối phương:
{user_input}
""",
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=AgentResponse,
            temperature=TEMPERATURE,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            top_p=TOP_P,
        ),
    )

    agent_res = AgentResponse.model_validate_json(response.text)
    # Đồng bộ tương thích ngược cờ conversation_end
    if agent_res.conversation_end_requested and not agent_res.conversation_end:
        agent_res.conversation_end = True
    elif agent_res.conversation_end and not agent_res.conversation_end_requested:
        agent_res.conversation_end_requested = True

    return agent_res