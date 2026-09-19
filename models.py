"""
models.py - Khung dữ liệu Pydantic Schema cho Generic Markdown Scenario Engine

Cập nhật kiến trúc Realistic & Non-Interruptive Dialogue Simulation:
1. Tách biệt rõ ràng giữa Persona (con người), InteractionType (loại hình tương tác) và BehaviorPolicy (chính sách hành vi).
2. Thay thế tư duy trò chơi "Bí mật ẩn / Trust > 60" bằng Context Facts (thông tin bối cảnh / nguy cơ thực tế có quy tắc hé lộ theo ngữ cảnh).
3. Thêm ConversationLifecycleState quản lý vòng đời hội thoại: ACTIVE, WAITING_FOR_RESPONSE, TRANSACTION_PENDING, COMPLETION_CANDIDATE, COMPLETED, MAX_TURNS_REACHED.
4. AgentResponse phân định rõ giữa conversation_end_requested (yêu cầu từ LLM) và pending_question/pending_request (thắc mắc đang chờ).
5. EvaluationReport nâng cấp toàn diện các chỉ số đo lường tính tự nhiên (naturalness, timing, termination correctness).
6. Duy trì 100% tương thích ngược với các trường cũ.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from enum import Enum


class Stage(str, Enum):
    """Các giai đoạn của cuộc hội thoại"""
    GREETING = "Greeting"
    MAIN_CHAT = "Main Chat"


class ConversationLifecycleState(str, Enum):
    """Vòng đời hội thoại được kiểm chứng bởi Engine"""
    ACTIVE = "ACTIVE"
    WAITING_FOR_RESPONSE = "WAITING_FOR_RESPONSE"
    TRANSACTION_PENDING = "TRANSACTION_PENDING"
    COMPLETION_CANDIDATE = "COMPLETION_CANDIDATE"
    COMPLETED = "COMPLETED"
    MAX_TURNS_REACHED = "MAX_TURNS_REACHED"


# ===========================================================================
# 1. Chính sách Hành vi (Behavior Policy) & Quy tắc Phản hồi
# ===========================================================================
class ResponseStyle(BaseModel):
    """Đặc trưng phong cách lời thoại"""
    verbosity: str = Field(default="low", description="Mức độ dài dòng: low, moderate, high")
    target_sentences: str = Field(default="1-3", description="Số câu mục tiêu mỗi lượt")
    hard_max_sentences: int = Field(default=5, description="Số câu tối đa tuyệt đối cho phép")


class InformationBehavior(BaseModel):
    """Hành vi chia sẻ thông tin bối cảnh"""
    spontaneous_disclosure: bool = Field(default=False, description="Có chủ động tự xả thông tin khi chưa ai hỏi không")
    answer_when_asked: bool = Field(default=True, description="Sẵn sàng trả lời thành thật khi được hỏi đúng trọng tâm")
    volunteer_extra_information: str = Field(default="low", description="Mức độ nói thêm thông tin ngoài lề: low, moderate, high")


class InteractionBehavior(BaseModel):
    """Hành vi tương tác và thái độ đối với chuyên gia/người dùng"""
    asks_questions_spontaneously: bool = Field(default=False, description="Có chủ động hỏi ngoài lề không")
    seeks_professional_advice: bool = Field(default=False, description="Có chủ động xin tư vấn chuyên sâu không")
    challenges_professional: bool = Field(default=False, description="Có tranh cãi hay thử thách đối phương không")


class TransactionBehavior(BaseModel):
    """Hành vi liên quan đến giao dịch và kết thúc"""
    wants_fast_transaction: bool = Field(default=True, description="Muốn xử lý việc nhanh gọn rồi đi")
    leaves_after_completion: bool = Field(default=True, description="Rời đi ngay sau khi mục tiêu thực tế hoàn tất")


class BehaviorPolicy(BaseModel):
    """Chính sách hành vi điều khiển cách nhân vật ứng xử thay vì dựa vào mô tả chung chung"""
    response_style: ResponseStyle = Field(default_factory=ResponseStyle)
    information_behavior: InformationBehavior = Field(default_factory=InformationBehavior)
    interaction_behavior: InteractionBehavior = Field(default_factory=InteractionBehavior)
    transaction_behavior: TransactionBehavior = Field(default_factory=TransactionBehavior)


# ===========================================================================
# 2. Bối cảnh Thực tế & Nguy cơ (Context Facts - Thay thế Secret Game Mechanics)
# ===========================================================================
class FactDisclosure(BaseModel):
    """Quy tắc điều kiện tiết lộ sự thật bối cảnh"""
    spontaneous: bool = Field(default=False, description="Chủ động nói ra ngay từ đầu")
    when_asked_about: List[str] = Field(
        default_factory=list,
        description="Các chủ đề/từ khóa mà khi đối phương hỏi đến, nhân vật sẽ trả lời thật thà"
    )


class ContextFact(BaseModel):
    """
    Sự thật bối cảnh / Yếu tố nguy cơ thực tế.
    Không phải là 'bí mật cần giấu để thử thách', mà là thông tin đời thường chưa được nhắc tới nếu không cần thiết.
    """
    id: str = Field(default="", description="Mã định danh sự thật")
    information: str = Field(description="Nội dung thông tin bối cảnh thực tế")
    category: str = Field(default="general", description="Phân loại: medical_history, financial, preference, etc.")
    relevance: str = Field(default="high", description="Mức độ liên quan tới tình huống: low, moderate, high")
    disclosure: FactDisclosure = Field(default_factory=FactDisclosure)


# ===========================================================================
# 3. Phân loại Loại hình Tương tác (Interaction Type)
# ===========================================================================
class InteractionTypeConfig(BaseModel):
    """Cấu hình loại hình tương tác được kịch bản hỗ trợ"""
    id: str = Field(default="general", description="Mã loại hình: named_purchase, symptom_consultation, etc.")
    name: str = Field(default="Tương tác chung", description="Tên mô tả loại tương tác")
    intent: str = Field(default="general_intent", description="Ý định cốt lõi: buy_specific_product, seek_advice, etc.")
    goal: str = Field(default="", description="Mục tiêu thực tế cần đạt để kết thúc hội thoại")
    risk_context_topics: List[str] = Field(default_factory=list, description="Các chủ đề nguy cơ thường gặp")
    default_behavior_policy: Optional[BehaviorPolicy] = Field(default=None, description="Chính sách hành vi mặc định")


# ===========================================================================
# 4. Pools & Rules sinh dữ liệu từ Scenario
# ===========================================================================
class DynamicPools(BaseModel):
    """Bể dữ liệu động bốc ngẫu nhiên thông số nhân vật."""
    names: List[str] = Field(
        default_factory=lambda: ["Nguyễn Văn A", "Trần Thị B"],
        description="Danh sách tên ngẫu nhiên"
    )
    age_ranges: List[List[int]] = Field(
        default_factory=lambda: [[20, 30]],
        description="Các khoảng tuổi ngẫu nhiên [min_age, max_age]"
    )
    occupations: List[str] = Field(
        default_factory=lambda: ["Sinh viên", "Nhân viên"],
        description="Danh sách nghề nghiệp ngẫu nhiên"
    )
    personalities: List[str] = Field(
        default_factory=lambda: ["Cởi mở, hợp tác", "Rụt rè, ngần ngại", "Gắt gỏng, vội vã"],
        description="Danh sách các nét tính cách (chủ yếu ảnh hưởng giọng điệu/cách nói)"
    )
    chief_complaints: List[str] = Field(
        default_factory=list,
        description="Bể lý do đến khám / yêu cầu ban đầu (nếu có)"
    )
    project_topics: List[str] = Field(
        default_factory=list,
        description="Bể đề tài đồ án / công việc (nếu có)"
    )


class ComplaintGenerationRules(BaseModel):
    """Cấu hình hướng dẫn Gemini AI tự động sinh lý do mở đầu (chief_complaint) sống động."""
    instruction: str = Field(
        default="Sinh ra 1 câu lý do đến khám/yêu cầu ngắn gọn, tự nhiên và phù hợp với vai trò nhân vật.",
        description="Chỉ dẫn chuyên biệt cho Gemini sinh lý do mở đầu"
    )
    allowed_symptom_scopes: List[str] = Field(
        default_factory=lambda: ["Các vấn đề sức khỏe phổ biến", "Tư vấn chuyên môn"],
        description="Phạm vi chủ đề hoặc triệu chứng được phép sinh"
    )


class SecretGenerationRules(BaseModel):
    """Cấu hình cho phép Gemini AI tự động sinh bối cảnh / nguy cơ ẩn (Context Facts)."""
    min_secrets: int = Field(default=0, description="Số lượng thông tin bối cảnh tối thiểu cần sinh")
    max_secrets: int = Field(default=3, description="Số lượng thông tin bối cảnh tối đa cần sinh")
    instruction: str = Field(
        default="Sinh ra yếu tố bối cảnh/nguy cơ thực tế liên quan đến vấn đề đang hỏi và hoàn cảnh nhân vật.",
        description="Chỉ dẫn cho Gemini khi sinh bối cảnh ẩn"
    )
    secret_topics: List[str] = Field(
        default_factory=lambda: ["Thói quen xấu", "Thông tin chưa kể", "Tiền sử"],
        description="Danh sách chủ đề gợi ý để AI sinh yếu tố bối cảnh"
    )


class InitialState(BaseModel):
    """Điểm trạng thái cảm xúc ban đầu của nhân vật (0-100)."""
    trust: int = Field(default=50, description="Điểm tin tưởng ban đầu (0-100)")
    patience: int = Field(default=100, description="Điểm kiên nhẫn ban đầu (0-100)")
    stress: int = Field(default=10, description="Điểm căng thẳng ban đầu (0-100)")
    satisfaction: int = Field(default=80, description="Mức độ hài lòng trải nghiệm dịch vụ ban đầu (0-100)")
    conversation_end: bool = Field(default=False, description="Cờ trạng thái kết thúc cuộc hội thoại (tương thích ngược)")


class CompletionRules(BaseModel):
    """Quy tắc ngắt cuộc hội thoại và kiểm chứng tính hoàn tất."""
    max_turns: int = Field(default=10, description="Số turn tối đa trước khi cưỡng chế ngắt khẩn cấp")
    min_turns: int = Field(default=2, description="Số lượt thoại tối thiểu trước khi được phép kết thúc tự nhiên (tránh ngắt sớm ở lượt đầu)")
    completion_keywords: List[str] = Field(
        default_factory=lambda: ["[DONE]", "[PASSED]", "[FAILED]", "[PAYMENT]", "[DONE_DEFENSE]", "[AGREED_VIEWING]", "[DEAL_CANCELLED]", "[ISSUE_RESOLVED]"],
        description="Từ khóa/tag hành động từ phía User hoặc Tester"
    )
    required_actions: List[str] = Field(
        default_factory=list,
        description="Danh sách tag hành động nghiệp vụ bắt buộc phải hoàn thành trước khi được phép kết thúc hội thoại (VD: ['PAYMENT'])"
    )
    allow_end_with_pending_question: bool = Field(
        default=False,
        description="Có cho phép ngắt khi đối phương hoặc nhân vật còn câu hỏi chưa được giải đáp không (mặc định False)"
    )


class UserAction(BaseModel):
    """Định nghĩa nút bấm thao tác nghiệp vụ trên Dynamic Action Bar."""
    label: str = Field(default="Thao tác", description="Tên hiển thị trên nút bấm")
    action_tag: str = Field(default="NONE", description="Mã tag đính kèm vào tin nhắn chat")
    description: str = Field(default="", description="Mô tả công dụng của hành động")


class TestConfig(BaseModel):
    """Cấu hình kiểm thử tự động LLM-vs-LLM cho auto_test.py."""
    tester_role: str = Field(default="Evaluator", description="Vai trò của AI 1 (Tester)")
    tester_system_prompt: str = Field(default="", description="System prompt định hướng cho AI 1")
    evaluation_criteria: List[str] = Field(
        default_factory=list,
        description="Các tiêu chí đánh giá cho AI 2 (Evaluator)"
    )


class ScenarioSchema(BaseModel):
    """
    Pydantic Schema đại diện cho Kịch bản (.md file).
    100% linh hoạt và dùng cho mọi ngành nghề (Y tế, BĐS, CSKH, Giáo dục).
    """
    title: str = Field(default="Kịch bản mặc định", description="Tiêu đề kịch bản")
    role: str = Field(default="Nhân vật mô phỏng", description="Vai trò của Agent")
    user_role: str = Field(default="Người tương tác", description="Vai trò của User")
    scenario: str = Field(default="", description="Tóm tắt bối cảnh tổng quan")
    case: str = Field(default="", description="Chi tiết tình huống cụ thể")
    
    # Tương thích ngược
    chief_complaint: Optional[str] = Field(default=None, description="Lý do mở đầu tĩnh")
    hidden_secrets: Optional[List[str]] = Field(default=None, description="Bí mật ẩn dạng chuỗi tĩnh (tương thích ngược)")
    
    # Kiến trúc mới
    interaction_types: List[InteractionTypeConfig] = Field(
        default_factory=list,
        description="Các loại hình tương tác được hỗ trợ trong kịch bản"
    )
    context_facts: Optional[List[ContextFact]] = Field(
        default=None,
        description="Danh sách sự thật bối cảnh / yếu tố nguy cơ có cấu trúc"
    )
    
    # Quy tắc sinh động
    complaint_generation_rules: Optional[ComplaintGenerationRules] = Field(
        default_factory=ComplaintGenerationRules,
        description="Quy tắc tự động sinh lý do mở đầu ngẫu nhiên qua Gemini API"
    )
    secret_generation_rules: Optional[SecretGenerationRules] = Field(
        default_factory=SecretGenerationRules,
        description="Quy tắc tự động sinh bối cảnh / nguy cơ ẩn ngẫu nhiên qua Gemini API"
    )
    
    goal: str = Field(default="", description="Mục tiêu cốt lõi của nhân vật")
    
    dynamic_pools: DynamicPools = Field(default_factory=DynamicPools, description="Bể dữ liệu bốc ngẫu nhiên")
    initial_state: InitialState = Field(default_factory=InitialState, description="Trạng thái cảm xúc khởi tạo")
    completion_rules: CompletionRules = Field(default_factory=CompletionRules, description="Quy tắc ngắt hội thoại")
    user_actions: List[UserAction] = Field(default_factory=list, description="Thao tác nghiệp vụ trên Action Bar")
    test_config: TestConfig = Field(default_factory=TestConfig, description="Cấu hình chạy auto test")
    
    instructions: str = Field(default="", description="Nội dung Markdown Body (chứa chỉ dẫn chuyên sâu)")


# ===========================================================================
# 5. Hồ sơ Nhân vật (Character Profile)
# ===========================================================================
class CharacterProfile(BaseModel):
    """
    Profile chi tiết của nhân vật.
    Mô hình hóa một con người thực tế với mục tiêu và chính sách hành vi rõ ràng.
    """
    name: str = Field(default="Nguyễn Văn A", description="Họ tên nhân vật")
    age: int = Field(default=22, description="Tuổi nhân vật")
    occupation: str = Field(default="Sinh viên", description="Nghề nghiệp")
    personality: str = Field(default="Cởi mở, hợp tác", description="Nét tính cách (chủ yếu ảnh hưởng cách nói)")
    background: str = Field(default="", description="Tiểu sử / Hoàn cảnh chi tiết")
    chief_complaint: str = Field(default="", description="Lý do / Lời mở đầu công khai")
    
    # Kiến trúc tương tác & hành vi mới
    interaction_type: str = Field(default="general", description="Loại hình tương tác cụ thể của lượt mô phỏng")
    intent: str = Field(default="general_intent", description="Ý định của nhân vật")
    behavior_policy: BehaviorPolicy = Field(default_factory=BehaviorPolicy, description="Chính sách hành vi")
    context_facts: List[ContextFact] = Field(default_factory=list, description="Danh sách sự thật bối cảnh / nguy cơ có cấu trúc")
    
    # Tương thích ngược
    hidden_secrets: List[str] = Field(default_factory=list, description="Danh sách các bí mật/nguy cơ dạng text")
    goal: str = Field(default="", description="Mục tiêu hành động thực tế")


# ===========================================================================
# 6. Phản hồi Cấu trúc của Agent (Agent Response)
# ===========================================================================
class AgentResponse(BaseModel):
    """
    Structured Output JSON nhận từ Gemini API cho mỗi lượt thoại của Agent.
    Phân định rõ ràng giữa yêu cầu ngắt hội thoại và trạng thái thắc mắc dở dang.
    """
    reply: str = Field(
        description="Lời thoại nhập vai của nhân vật (1-3 câu ngắn gọn, đời thường, dân dã, không kịch hóa)"
    )
    conversation_end_requested: bool = Field(
        default=False,
        description="True nếu nhân vật cảm thấy mục tiêu thực tế đã hoàn thành và muốn rời đi/chào tạm biệt"
    )
    conversation_end: bool = Field(
        default=False,
        description="Trường tương thích ngược, phản ánh cờ kết thúc do LLM đề xuất"
    )
    pending_question: bool = Field(
        default=False,
        description="True nếu câu nói của nhân vật chứa một câu hỏi hoặc thắc mắc đang chờ đối phương giải đáp"
    )
    pending_request: bool = Field(
        default=False,
        description="True nếu nhân vật còn một yêu cầu thực tế chưa được đáp ứng"
    )
    action_requested: Optional[str] = Field(
        default=None,
        description="Hành động mà nhân vật yêu cầu đối phương thực hiện (nếu có)"
    )
    detected_event: Optional[str] = Field(
        default=None,
        description="Sự kiện cảm xúc/nghiệp vụ nhận diện được từ lượt thoại (VD: helpful_response, irrelevant_question, payment_completed, etc.)"
    )
    satisfaction: int = Field(
        default=80,
        description="Mức độ hài lòng thực tế với dịch vụ (0-100)"
    )
    new_trust: int = Field(
        default=50,
        description="Điểm tin tưởng mới cập nhật (0-100)"
    )
    new_patience: int = Field(
        default=100,
        description="Điểm kiên nhẫn mới cập nhật (0-100)"
    )
    new_stress: int = Field(
        default=10,
        description="Điểm căng thẳng mới cập nhật (0-100)"
    )


# ===========================================================================
# 7. Đánh giá Chất lượng Mô phỏng (Evaluation Report)
# ===========================================================================
class EvaluationReport(BaseModel):
    """
    Kết quả chấm điểm phiên mô phỏng từ AI 2 (Evaluator).
    Đo lường trực tiếp tính chân thực, tự nhiên và sự chuẩn xác trong kết thúc hội thoại.
    """
    out_of_character: bool = Field(
        description="True nếu Agent đóng sai vai hoặc vi phạm nguyên tắc persona"
    )
    dialogue_naturalness: int = Field(
        default=8,
        description="Điểm 1-10: Độ tự nhiên, đời thường của ngôn ngữ đối thoại (không văn mẫu, không kịch hóa)"
    )
    interaction_realism: int = Field(
        default=8,
        description="Điểm 1-10: Tính chân thực của diễn biến so với giao tiếp ngoài đời thực"
    )
    information_timing: int = Field(
        default=8,
        description="Điểm 1-10: Thời điểm cung cấp thông tin (không xả trước, trả lời tự nhiên khi được hỏi)"
    )
    behavior_consistency: int = Field(
        default=8,
        description="Điểm 1-10: Tính nhất quán của hành vi so với interaction_type và behavior_policy"
    )
    transaction_realism: int = Field(
        default=8,
        description="Điểm 1-10: Tính hợp lý của quy trình trao đổi, thao tác nghiệp vụ và thanh toán"
    )
    termination_correctness: int = Field(
        default=8,
        description="Điểm 1-10: Tính đúng đắn khi kết thúc (không ngắt vội khi còn câu hỏi dở dang, không kéo dài thừa thãi)"
    )
    unnecessary_turns: int = Field(
        default=0,
        description="Số lượt thoại dư thừa không cần thiết"
    )
    premature_termination: bool = Field(
        default=False,
        description="True nếu hội thoại bị ngắt sớm khi còn câu hỏi hoặc giao dịch dở dang"
    )
    abrupt_cutoff: bool = Field(
        default=False,
        description="True nếu kết thúc đột ngột, thiếu tự nhiên"
    )
    emotion_logic_score: int = Field(
        default=8,
        description="Điểm 1-10 đánh giá tính logic khi biến đổi cảm xúc"
    )
    unlock_turn: int = Field(
        default=-1,
        description="Lượt thoại đầu tiên chia sẻ bối cảnh/nguy cơ (-1 nếu không có)"
    )
    critique: str = Field(
        description="Đánh giá chi tiết chuyên sâu bằng Tiếng Việt"
    )