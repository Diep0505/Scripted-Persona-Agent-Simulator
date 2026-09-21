"""
scenario_loader.py - Trình nạp Kịch bản Generic từ File Markdown (.md)

Sử dụng thư viện `python-frontmatter` để đọc và tách biệt:
- YAML Frontmatter: Metadata cấu hình kịch bản (Dynamic Pools, Rules, Actions, Test Config, Secret Rules).
- Markdown Body: Nội dung chỉ dẫn nhập vai chi tiết.

Tính an toàn tuyệt đối (Fallback Protection):
Nếu file .md bị thiếu form hoặc người dùng quên điền bất kỳ thuộc tính nào trong YAML, 
Pydantic Schema (ScenarioSchema) sẽ tự động bù đắp dữ liệu mặc định mà KHÔNG BAO GIỜ bị crash.
"""

import os
import frontmatter
from models import ScenarioSchema


def load_scenario_from_md(file_path: str) -> ScenarioSchema:
    """
    Đọc file kịch bản .md, phân tách YAML Frontmatter và Markdown Body,
    chuyển đổi an toàn thành đối tượng ScenarioSchema.

    Args:
        file_path (str): Đường dẫn tới file kịch bản .md

    Returns:
        ScenarioSchema: Đối tượng kịch bản đã qua kiểm duyệt Pydantic Schema với fallback an toàn.
    """
    if not os.path.exists(file_path):
        # Thử tìm tương đối với thư mục gốc của project nếu script chạy từ thư mục con (vd: tests/)
        project_root = os.path.dirname(os.path.abspath(__file__))
        alt_path = os.path.join(project_root, file_path)
        if os.path.exists(alt_path):
            file_path = alt_path
        else:
            raise FileNotFoundError(f"Không tìm thấy file kịch bản tại đường dẫn: {file_path}")

    # Đọc file markdown chứa frontmatter
    post = frontmatter.load(file_path)
    metadata = dict(post.metadata) if post.metadata else {}

    # Đưa nội dung phần Markdown Body vào trường instructions
    instructions_text = post.content.strip() if post.content else ""
    metadata["instructions"] = instructions_text

    # ScenarioSchema.model_validate tự động xử lý ép kiểu và bù đắp các giá trị mặc định thiếu
    scenario = ScenarioSchema.model_validate(metadata)
    return scenario


def list_available_scenarios(scenarios_dir: str = "scenarios") -> dict[str, str]:
    """
    Quét thư mục scenarios/ và trả về dictionary {Tên hiển thị: Đường dẫn file .md}.

    Args:
        scenarios_dir (str): Thư mục chứa các kịch bản .md

    Returns:
        dict[str, str]: Bản đồ tên kịch bản -> đường dẫn file .md
    """
    if not os.path.exists(scenarios_dir):
        os.makedirs(scenarios_dir, exist_ok=True)
        return {}

    scenario_files = {}
    for filename in sorted(os.listdir(scenarios_dir)):
        if filename.endswith(".md"):
            full_path = os.path.join(scenarios_dir, filename)
            try:
                sc = load_scenario_from_md(full_path)
                display_name = f"{sc.title} ({sc.role})"
                scenario_files[display_name] = full_path
            except Exception as e:
                scenario_files[f"File lỗi: {filename}"] = full_path

    return scenario_files
