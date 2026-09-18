"""
app.py - Streamlit Dynamic UI cho Generic Markdown Scenario Engine

Giao diện Web động theo kiến trúc Realistic & Validated Persona Simulation:
1. Tự động quét kịch bản (.md) từ thư mục scenarios/ và hiển thị Dropdown trên Sidebar.
2. Hiển thị thông tin nhân khẩu học, loại hình tương tác (interaction_type), intent và chính sách hành vi.
3. Dynamic Action Bar: Render trực tiếp các nút bấm từ danh sách user_actions trong .md file.
4. Quản lý vòng đời hội thoại độc lập (Lifecycle State):
   - ACTIVE / TRANSACTION_PENDING / COMPLETION_CANDIDATE / COMPLETED / MAX_TURNS_REACHED.
   - Không ngắt vội khi khách hàng vừa đặt thêm câu hỏi sau thanh toán.
5. Developer Trace & Debriefing: Hiển thị minh bạch lý do tiếp tục/ngắt hội thoại và các Context Facts.
"""

import streamlit as st
import os
from scenario_loader import load_scenario_from_md, list_available_scenarios
from agent import ask_agent, reset_agent, create_agent_persona
from state_machine import make_initial_state
from models import ConversationLifecycleState

st.set_page_config(page_title="Generic Scenario Engine", page_icon="🎭", layout="wide")

st.title("🎭 Generic Markdown Scenario Engine")
st.caption("Hệ thống Giả lập Đa Vai trò điều khiển hoàn toàn bằng File Markdown (.md) & Gemini AI")

# ---------------------------------------------------------------------------
# 1. Quét và Lựa chọn Kịch bản từ thư mục scenarios/
# ---------------------------------------------------------------------------
scenarios_map = list_available_scenarios("scenarios")

if not scenarios_map:
    st.error("⚠️ Không tìm thấy file kịch bản (.md) nào trong thư mục `scenarios/`!")
    st.stop()

# Khởi tạo Session State
if "selected_scenario_path" not in st.session_state:
    st.session_state.selected_scenario_path = list(scenarios_map.values())[0]

if "current_scenario" not in st.session_state or st.session_state.current_scenario is None:
    st.session_state.current_scenario = load_scenario_from_md(st.session_state.selected_scenario_path)

if "hidden_state" not in st.session_state:
    st.session_state.hidden_state = make_initial_state(st.session_state.current_scenario.initial_state)

if "current_profile" not in st.session_state:
    st.session_state.current_profile = None

if "messages" not in st.session_state:
    st.session_state.messages = []

if "dialogue_history" not in st.session_state:
    st.session_state.dialogue_history = []

if "trace_logs" not in st.session_state:
    st.session_state.trace_logs = []

if "selected_action" not in st.session_state:
    st.session_state.selected_action = None

# Shortcut reference
hs = st.session_state.hidden_state
scenario = st.session_state.current_scenario

# Sidebar: Chọn kịch bản
st.sidebar.title("⚙️ Chọn Kịch bản (.md)")
selected_name = st.sidebar.selectbox(
    "Danh sách kịch bản:",
    options=list(scenarios_map.keys()),
    index=0
)

chosen_path = scenarios_map[selected_name]

# Reset nếu người dùng chuyển kịch bản mới
if chosen_path != st.session_state.selected_scenario_path:
    st.session_state.selected_scenario_path = chosen_path
    st.session_state.current_scenario = load_scenario_from_md(chosen_path)
    scenario = st.session_state.current_scenario
    st.session_state.hidden_state = make_initial_state(scenario.initial_state)
    st.session_state.current_profile = create_agent_persona(scenario)
    st.session_state.messages = []
    st.session_state.dialogue_history = []
    st.session_state.trace_logs = []
    st.session_state.selected_action = None
    st.rerun()

# Tạo nhân vật nếu chưa có
if st.session_state.current_profile is None:
    st.session_state.current_profile = create_agent_persona(scenario)

# Sidebar: Nút Reset Nhân vật
if st.sidebar.button("🔄 New Persona / Reset", use_container_width=True):
    st.session_state.current_profile = reset_agent(st.session_state.hidden_state, scenario)
    st.session_state.messages = []
    st.session_state.dialogue_history = []
    st.session_state.trace_logs = []
    st.session_state.selected_action = None
    st.rerun()

# Sidebar: Thông tin Kịch bản & Nhân vật
st.sidebar.markdown("---")
st.sidebar.subheader("📌 Thông tin Kịch bản")
st.sidebar.write(f"**Tiêu đề:** {scenario.title}")
st.sidebar.write(f"**Vai trò Agent:** `{scenario.role}`")
st.sidebar.write(f"**Vai trò User:** `{scenario.user_role}`")
st.sidebar.write(f"**Max Turns:** `{scenario.completion_rules.max_turns}`")
if scenario.completion_rules.required_actions:
    st.sidebar.write(f"**Hành động bắt buộc:** `{scenario.completion_rules.required_actions}`")

st.sidebar.markdown("---")
st.sidebar.subheader("👤 Hồ sơ Nhân vật Thực tế")
profile = st.session_state.current_profile
st.sidebar.write(f"**Họ tên:** {profile.name} ({profile.age} tuổi)")
st.sidebar.write(f"**Nghề nghiệp:** {profile.occupation}")
st.sidebar.write(f"**Loại hình tương tác:** `{profile.interaction_type}`")
st.sidebar.write(f"**Ý định cốt lõi:** `{profile.intent}`")
st.sidebar.write(f"**Tính cách:** {profile.personality}")
st.sidebar.write(f"**Yêu cầu ban đầu:** {profile.chief_complaint}")

st.sidebar.markdown("---")
st.sidebar.subheader("📊 Trạng thái Trải nghiệm & Vòng đời")
lifecycle_val = hs.get("lifecycle_state", ConversationLifecycleState.ACTIVE.value)
st.sidebar.info(f"**Vòng đời Hội thoại:** `{lifecycle_val}`")

satisfaction_val = hs.get("satisfaction", 80)
st.sidebar.progress(satisfaction_val / 100, text=f"⭐ Hài lòng (Satisfaction): {satisfaction_val}/100")
st.sidebar.progress(hs.get("patience", 100) / 100, text=f"Kiên nhẫn (Patience): {hs.get('patience', 100)}/100")
st.sidebar.progress(hs.get("stress", 10) / 100, text=f"Căng thẳng (Stress): {hs.get('stress', 10)}/100")

# ---------------------------------------------------------------------------
# 2. Hiển thị Khung Chat Lịch sử
# ---------------------------------------------------------------------------
for role, content in st.session_state.messages:
    with st.chat_message(role):
        st.write(content)

# ---------------------------------------------------------------------------
# 3. Dynamic Action Bar (Nút bấm thao tác sinh tự động từ user_actions)
# ---------------------------------------------------------------------------
st.markdown(f"### ⚡ Action Bar của `{scenario.user_role}`")

user_actions = scenario.user_actions
if user_actions:
    cols = st.columns(len(user_actions) + 1)
    for idx, act in enumerate(user_actions):
        with cols[idx]:
            if st.button(act.label, help=act.description, use_container_width=True):
                st.session_state.selected_action = act.action_tag
    with cols[-1]:
        if st.button("❌ Xóa Action", use_container_width=True):
            st.session_state.selected_action = None

if st.session_state.selected_action:
    st.info(f"Đã chọn Thao tác: **[{st.session_state.selected_action}]** (Sẽ gắn tag vào tin nhắn tiếp theo)")

# ---------------------------------------------------------------------------
# 4. Cầu chì Ngắt Hội thoại Độc lập (Validated Termination Protocol)
# ---------------------------------------------------------------------------
current_turn = len([m for m in st.session_state.messages if m[0] == "user"])
max_turns = scenario.completion_rules.max_turns
is_max_turn_reached = current_turn >= max_turns
is_conv_ended = hs.get("end_validated", False) or (lifecycle_val in [ConversationLifecycleState.COMPLETED.value, ConversationLifecycleState.MAX_TURNS_REACHED.value]) or is_max_turn_reached

if is_conv_ended:
    st.markdown("---")
    if is_max_turn_reached or lifecycle_val == ConversationLifecycleState.MAX_TURNS_REACHED.value:
        st.warning(f"🛑 **Cuộc hội thoại đã ngắt do đạt ngưỡng tối đa {max_turns} turns (Max Turns Safety).**")
    else:
        st.success("✅ **Cuộc hội thoại đã kết thúc thành công (Conversation Completed Trọn vẹn).**")

    if hs.get("termination_reason"):
        st.caption(f"Lý do: {hs.get('termination_reason')}")

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("🔄 Tạo phiên mới với nhân vật mới", use_container_width=True):
            st.session_state.current_profile = reset_agent(st.session_state.hidden_state, scenario)
            st.session_state.messages = []
            st.session_state.dialogue_history = []
            st.session_state.trace_logs = []
            st.session_state.selected_action = None
            st.rerun()
    with col_btn2:
        if st.button("💬 Tiếp tục nhắn (Bỏ cờ kết thúc)", use_container_width=True):
            hs["end_validated"] = False
            hs["conversation_end"] = False
            hs["lifecycle_state"] = ConversationLifecycleState.ACTIVE.value
            st.rerun()

# ---------------------------------------------------------------------------
# 5. Ô Nhập tin nhắn Chat (Chat Input)
# ---------------------------------------------------------------------------
message = st.chat_input("Nhập tin nhắn giao tiếp...", disabled=is_conv_ended)

if message:
    # Xử lý gắn tag Action
    if st.session_state.selected_action:
        user_display_text = f"[{st.session_state.selected_action}] {message}"
        full_user_input = f"[{st.session_state.selected_action}] {message}"
        st.session_state.selected_action = None
    else:
        user_display_text = message
        full_user_input = message

    # Hiển thị và lưu tin nhắn User
    with st.chat_message("user"):
        st.write(user_display_text)

    st.session_state.messages.append(("user", user_display_text))
    st.session_state.dialogue_history.append({"role": "user", "content": full_user_input})

    # Gọi Agent xử lý
    with st.spinner(f"_{profile.name}_ ({scenario.role}) đang suy nghĩ..."):
        reply, trace_info = ask_agent(
            user_input=full_user_input,
            state=st.session_state.hidden_state,
            scenario=scenario,
            character_profile=profile,
            dialogue_history=st.session_state.dialogue_history,
            turn=current_turn
        )

    # Hiển thị và lưu tin nhắn Assistant
    with st.chat_message("assistant"):
        st.write(reply)

    st.session_state.messages.append(("assistant", reply))
    st.session_state.dialogue_history.append({"role": "assistant", "content": reply})
    st.session_state.trace_logs.append(trace_info)
    st.rerun()

# ---------------------------------------------------------------------------
# 6. Sidebar Expander: Debriefing (Sự thật bối cảnh) & Developer Logs
# ---------------------------------------------------------------------------
with st.sidebar.expander("🕵️ Xem Bối cảnh Thực tế (Context Facts)"):
    st.write("**Mục tiêu cốt lõi:**", profile.goal)
    st.write("**Bối cảnh thực tế / Yếu tố nguy cơ (Context Facts):**")
    if profile.context_facts:
        for f in profile.context_facts:
            st.write(f"- **[{f.category}]** {f.information}")
            if f.disclosure.when_asked_about:
                st.caption(f"  _Hé lộ khi hỏi:_ {', '.join(f.disclosure.when_asked_about)}")
    elif profile.hidden_secrets:
        for s in profile.hidden_secrets:
            st.write(f"- {s}")
    else:
        st.write("*(0 Context Fact - Không có yếu tố nguy cơ / Ca mua nhanh)*")

with st.expander("🛠️ Developer Logs & Lifecycle Trace"):
    if st.session_state.trace_logs:
        for log in st.session_state.trace_logs:
            st.markdown(f"### 📍 Turn {log.get('turn')} - Lifecycle: `{log.get('lifecycle_state')}`")
            st.write(f"- **End Requested từ LLM:** `{log.get('end_requested')}`")
            st.write(f"- **End Validated bởi Engine:** `{log.get('end_validated')}`")
            st.write(f"- **Pending Question:** `{log.get('pending_question')}`")
            st.write(f"- **Lý do:** {log.get('termination_reason')}")
            st.write(f"- **Thao tác đã ghi nhận:** `{log.get('completed_actions')}`")
            st.markdown("**Structured Output JSON:**")
            st.json(log.get("json_response", {}))
            st.markdown("**System Prompt gửi tới Gemini:**")
            st.code(log.get("prompt", ""), language="markdown")
            st.divider()
    else:
        st.info("Chưa có thông tin trace log. Gửi tin nhắn để bắt đầu xem prompt.")