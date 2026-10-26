"""Unit and integration tests for Question Answer Generator subagent and Study Notes PDF tools."""
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from chat_agent.agents.prompt import INSTRUCTION, QA_GENERATOR_INSTRUCTION
from chat_agent.config import settings
from chat_agent.infographics.config import find_icon
from chat_agent.infographics.notes_builder import generate_handwritten_notes_pdf
from chat_agent.tools.tool_factory import (
    generate_infographic_pdf,
    generate_study_notes_pdf,
    upload_file_to_slack,
)


def test_find_icon_resolves_project_asset() -> None:
    """Verify find_icon successfully discovers root branding icon assets."""
    icon_path = find_icon()
    assert icon_path is not None
    assert Path(icon_path).exists()
    assert any(icon_path.lower().endswith(ext) for ext in [".jpg", ".png", ".ico", ".jpeg"])


def test_generate_handwritten_notes_pdf_direct() -> None:
    """Verify direct handwritten notes PDF creation in OS temp directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_file = str(Path(tmp_dir) / "test_notes.pdf")
        result_path = generate_handwritten_notes_pdf(
            title="ICSE Grade 5 - Plant Life",
            content="# Photosynthesis\nPlants make food using sunlight and chlorophyll.\n- Point 1\n- Point 2\n\n> Important: Remember chlorophyll!",
            subject="Science",
            tags=["ICSE", "Grade5", "Science"],
            margin_tip="Remember the sunlight equation",
            output_path=out_file,
        )
        assert Path(result_path).exists()
        assert Path(result_path).stat().st_size > 500


def test_generate_study_notes_pdf_tool() -> None:
    """Verify the background compile pipeline (sync core) produces the PDF."""
    from chat_agent.tools.tool_factory import _generate_study_notes_pdf_sync

    res = _generate_study_notes_pdf_sync(
        title="Fractions & Decimals",
        content="## Key Rules\n1. Like fractions have same denominators.\n2. Add numerators directly.",
        subject="Mathematics",
        tags=["Math", "Fractions"],
        margin_tip="Simplify at the end!",
    )
    assert res["status"] == "success"
    assert res["title"] == "Fractions & Decimals"
    assert Path(res["pdf_path"]).exists()
    assert res["file_size_bytes"] > 500


def test_generate_study_notes_pdf_returns_queued() -> None:
    """Verify the public tool returns immediately with 'queued' and delegates to the sync pipeline."""
    import time

    with patch("chat_agent.tools.tool_factory._generate_study_notes_pdf_sync") as mock_sync:
        res = generate_study_notes_pdf(title="Queued", content="# Q", subject="Science")
        assert res["status"] == "queued"
        for _ in range(200):
            if mock_sync.called:
                break
            time.sleep(0.01)
        mock_sync.assert_called_once()


def test_generate_infographic_pdf_tool() -> None:
    """Verify the background infographic pipeline (sync core) produces the PDF."""
    from chat_agent.tools.tool_factory import _generate_infographic_pdf_sync

    lesson_data = {
        "title": "Human Digestive System",
        "subject": "Biology",
        "summary": "Step by step digestion process in humans.",
        "fun_fact": "The small intestine is about 20 feet long!",
        "key_takeaways": ["Mouth chews food", "Stomach digests proteins"],
        "steps": [
            {"title": "Ingestion", "desc": "Food enters the mouth."},
            {"title": "Digestion", "desc": "Enzymes break down nutrients."},
        ],
        "vocabulary": [{"term": "Enzyme", "def": "Biological catalyst."}],
    }
    res = _generate_infographic_pdf_sync(lesson_data)
    assert res["status"] == "success"
    assert Path(res["pdf_path"]).exists()
    assert res["file_size_bytes"] > 500


def test_generate_infographic_pdf_returns_queued() -> None:
    """Verify the public infographic tool returns immediately with 'queued'."""
    import time

    with patch("chat_agent.tools.tool_factory._generate_infographic_pdf_sync") as mock_sync:
        res = generate_infographic_pdf({"title": "Queued Poster"})
        assert res["status"] == "queued"
        for _ in range(200):
            if mock_sync.called:
                break
            time.sleep(0.01)
        mock_sync.assert_called_once()


def test_prompt_definitions_available() -> None:
    """Verify the preserved prompt definitions exist and carry pedagogical context."""
    assert "ICSE" in INSTRUCTION
    assert "{CURRENT_DATE}" in INSTRUCTION
    assert "ICSE" in QA_GENERATOR_INSTRUCTION
    assert "{CURRENT_DATE}" in QA_GENERATOR_INSTRUCTION


def test_channel_and_thread_normalization() -> None:
    """Verify model-supplied channel/thread_ts shapes are coerced to plain strings."""
    from chat_agent.tools.tool_factory import _normalize_channel_ref, _normalize_thread_ts

    assert _normalize_channel_ref({"channel_id": "D123"}) == "D123"
    assert _normalize_channel_ref({"channel": "C456"}) == "C456"
    assert _normalize_channel_ref(" C789 ") == "C789"
    assert _normalize_channel_ref({"foo": 1}) == ""
    assert _normalize_channel_ref(None) == ""
    assert _normalize_thread_ts(1790622780.716599) == "1790622780.716599"
    assert _normalize_thread_ts("123.45") == "123.45"
    assert _normalize_thread_ts(None) == ""


def test_generate_study_notes_pdf_ignores_unsafe_output_path() -> None:
    """Verify caller-chosen output_path outside allowed dirs is ignored in favor of the default notes dir."""
    from chat_agent.tools.tool_factory import _generate_study_notes_pdf_sync

    unsafe_path = str(Path.cwd() / "evil_notes.pdf")
    res = _generate_study_notes_pdf_sync(
        title="Guarded Path",
        content="# Guard\n- point",
        subject="Science",
        output_path=unsafe_path,
    )
    assert res["status"] == "success"
    assert "aryhant_notes" in res["pdf_path"]
    assert Path(res["pdf_path"]).exists()
    assert not Path(unsafe_path).exists()


def test_upload_file_to_slack_missing_config_or_file() -> None:
    """Verify upload_file_to_slack gracefully skips when file is missing or token is unconfigured."""
    from chat_agent.infographics.notes_builder import get_notes_dir

    res_missing_file = upload_file_to_slack("non_existent_file_12345.pdf", "C123456")
    assert res_missing_file["status"] == "error"
    assert "not found" in res_missing_file["error"].lower()

    notes_dir = get_notes_dir()
    temp_file = str(Path(notes_dir) / "upload_guard_test.pdf")
    Path(temp_file).write_bytes(b"%PDF-1.4 test")

    outside_file = str(Path(tempfile.gettempdir()) / "upload_guard_outside.pdf")
    Path(outside_file).write_bytes(b"%PDF-1.4 test")

    try:
        with patch.dict(os.environ, {"ARYHANT_SLACK_BOT_TOKEN": ""}):
            with patch.object(settings, "ARYHANT_SLACK_BOT_TOKEN", ""):
                res_no_token = upload_file_to_slack(temp_file, "C123456")
                assert res_no_token["status"] == "skipped"
                assert "not configured" in res_no_token["reason"]

        with patch.object(settings, "ARYHANT_SLACK_BOT_TOKEN", "xoxb-mock-token"):
            res_blocked = upload_file_to_slack(outside_file, "C123456")
            assert res_blocked["status"] == "error"
            assert "restricted" in res_blocked["error"].lower()
    finally:
        for path in (temp_file, outside_file):
            if os.path.exists(path):
                os.remove(path)


def test_upload_file_to_slack_sync_mocked_success() -> None:
    """Verify 3-step Slack upload flow with mocked HTTP responses."""
    from chat_agent.infographics.notes_builder import get_notes_dir
    from chat_agent.tools.tool_factory import _upload_file_to_slack_sync

    temp_file = str(Path(get_notes_dir()) / "upload_mock_test.pdf")
    Path(temp_file).write_bytes(b"%PDF-1.4 mock content")

    try:
        mock_get_url_resp = MagicMock()
        mock_get_url_resp.status_code = 200
        mock_get_url_resp.json.return_value = {
            "ok": True,
            "upload_url": "https://slack.com/mock-upload",
            "file_id": "F12345678",
        }

        mock_post_file_resp = MagicMock()
        mock_post_file_resp.status_code = 200

        mock_complete_resp = MagicMock()
        mock_complete_resp.status_code = 200
        mock_complete_resp.json.return_value = {
            "ok": True,
            "files": [{"id": "F12345678", "title": "Test Notes"}],
        }

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.post.side_effect = [
                mock_get_url_resp,
                mock_post_file_resp,
                mock_complete_resp,
            ]

            res = _upload_file_to_slack_sync(
                file_path=temp_file,
                channel="C12345",
                thread_ts="1234567890.123456",
                title="Test Notes",
                initial_comment="Here are your notes!",
                token="xoxb-mock-token",
            )
            assert res["status"] == "success"
            assert res["file_id"] == "F12345678"
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)


def test_upload_file_to_slack_queues_background_thread() -> None:
    """Verify the public tool returns immediately with 'queued' and delegates to the sync uploader."""
    import time

    from chat_agent.infographics.notes_builder import get_notes_dir

    temp_file = str(Path(get_notes_dir()) / "upload_queue_test.pdf")
    Path(temp_file).write_bytes(b"%PDF-1.4 queue test")

    try:
        with patch.object(settings, "ARYHANT_SLACK_BOT_TOKEN", "xoxb-mock-token"):
            with patch("chat_agent.tools.tool_factory._upload_file_to_slack_sync") as mock_sync:
                res = upload_file_to_slack(temp_file, "C12345", thread_ts="123.456")
                assert res["status"] == "queued"
                assert res["file_name"] == "upload_queue_test.pdf"
                for _ in range(200):
                    if mock_sync.called:
                        break
                    time.sleep(0.01)
                mock_sync.assert_called_once()
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)


def test_clean_math_text_converts_fractions_and_latex() -> None:
    """Verify clean_math_text converts raw LaTeX math expressions into human-readable strings."""
    from chat_agent.utils.math_formatter import clean_math_text

    raw_input = (
        "• Proper Fraction: Numerator is smaller than the denominator (e.g., $\\frac{3}{5}$). Value is less than 1.\n"
        "• Improper Fraction: Numerator is greater than or equal to the denominator (e.g., $\\frac{7}{4}$).\n"
        "• Mixed Fraction: Consists of a whole number and a proper fraction (e.g., $1 \\frac{3}{4}$).\n"
        "• Like Fractions: Fractions with the same denominators (e.g., $\\frac{2}{7}$, $\\frac{5}{7}$).\n"
        "• Equivalent Fractions: Fractions that represent the same part (e.g., $\\frac{1}{2} = \\frac{2}{4}$)."
    )

    cleaned = clean_math_text(raw_input)
    assert "$\\frac{3}{5}$" not in cleaned
    assert "3/5" in cleaned
    assert "7/4" in cleaned
    assert "1 3/4" in cleaned
    assert "2/7" in cleaned
    assert "5/7" in cleaned
    assert "1/2 = 2/4" in cleaned
    assert "$" not in cleaned
    assert "\\frac" not in cleaned


def test_get_pillow_font_universal_fallback() -> None:
    """Verify get_pillow_font loads fonts or falls back cleanly without warning on all environments."""
    from PIL import ImageFont
    from chat_agent.infographics.config import find_truetype_font, get_pillow_font
    from chat_agent.infographics.diagrams import _get_font
    from chat_agent.infographics.notes_builder import _get_sketch_font

    # 1. Normal resolution
    font = get_pillow_font(size=14, bold=False)
    assert font is not None
    assert isinstance(font, (ImageFont.ImageFont, ImageFont.FreeTypeFont))

    bold_font = get_pillow_font(size=16, bold=True)
    assert bold_font is not None

    # 2. Diagrams and sketch helper delegation
    d_font = _get_font(12, bold=False)
    assert d_font is not None

    s_font = _get_sketch_font(11, bold=True)
    assert s_font is not None

    # 3. Fallback when no TTF exists on disk (simulating bare container)
    with patch("chat_agent.infographics.config.find_truetype_font", return_value=None):
        fallback_font = get_pillow_font(size=12)
        assert fallback_font is not None

    # 4. Non-existent font probe returns None cleanly
    assert find_truetype_font(["non_existent_font_1234567.ttf"]) is None


def test_generate_handwritten_notes_pdf_hindi_and_bengali() -> None:
    """Verify handwritten notes PDF generation with Hindi and Bengali Unicode scripts."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        hindi_out = str(Path(tmp_dir) / "hindi_notes.pdf")
        res_hindi = generate_handwritten_notes_pdf(
            title="हिंदी व्याकरण - संज्ञा और सर्वनाम",
            content="# पाठ १: संज्ञा\nकिसी व्यक्ति, वस्तु या स्थान के नाम को संज्ञा कहते हैं।\n- राम\n- हिमालय\n\n> अभ्यास करें!",
            subject="Hindi",
            tags=["हिंदी", "व्याकरण"],
            margin_tip="संज्ञा की परिभाषा",
            output_path=hindi_out,
        )
        assert Path(res_hindi).exists()
        assert Path(res_hindi).stat().st_size > 1000

        bengali_out = str(Path(tmp_dir) / "bengali_notes.pdf")
        res_bengali = generate_handwritten_notes_pdf(
            title="বাংলা ব্যাকরণ - বিশেষ্য পদ",
            content="# অধ্যায় ১: বিশেষ্য\nযে শব্দ দ্বারা কোনো ব্যক্তি বা স্থানের নাম বোঝায়।\n- রবীন্দ্রনাথ\n- গঙ্গা\n\n> মনে রাখবেন!",
            subject="Bengali",
            tags=["বাংলা", "ব্যাকরণ"],
            margin_tip="বিশেষ্যের সংজ্ঞা",
            output_path=bengali_out,
        )
        assert Path(res_bengali).exists()
        assert Path(res_bengali).stat().st_size > 1000


def test_generate_lesson_infographic_hindi_and_bengali() -> None:
    """Verify lesson infographic generation with Hindi and Bengali lesson content and diagrams."""
    from chat_agent.infographics.builder import generate_lesson_infographic

    with tempfile.TemporaryDirectory() as tmp_dir:
        hindi_out = str(Path(tmp_dir) / "hindi_info.pdf")
        res_hindi = generate_lesson_infographic(
            {
                "title": "प्रकाश संश्लेषण",
                "subject": "विज्ञान",
                "grade": "5",
                "overview": "पौधे सूर्य के प्रकाश से भोजन बनाते हैं।",
                "steps": [
                    {
                        "step_number": 1,
                        "title": "सौर ऊर्जा अवशोषण",
                        "concept": "पत्तियों का क्लोरोफिल सौर ऊर्जा अवशोषित करता है।",
                        "visual_suggestion": "[सूर्य -> पत्ती -> क्लोरोफिल]",
                        "key_takeaways": ["क्लोरोफिल हरा वर्णक है", "सौर ऊर्जा अवशोषित होती है"],
                        "checkpoint": "क्लोरोफिल का कार्य क्या है?",
                    }
                ],
            },
            output_path=hindi_out,
        )
        assert Path(res_hindi).exists()
        assert Path(res_hindi).stat().st_size > 1000

        bengali_out = str(Path(tmp_dir) / "bengali_info.pdf")
        res_bengali = generate_lesson_infographic(
            {
                "title": "সালোকসংশ্লেষ",
                "subject": "বিজ্ঞান",
                "grade": "5",
                "overview": "উদ্ভিদ সূর্যালোক ও জল দ্বারা খাদ্য প্রস্তুত করে।",
                "steps": [
                    {
                        "step_number": 1,
                        "title": "সৌরশক্তি শোষণ",
                        "concept": "পাতার ক্লোরোফিল সূর্যালোক শোষণ করে।",
                        "visual_suggestion": "[সূর্য -> পাতা -> ক্লোরোফিল]",
                        "key_takeaways": ["ক্লোরোফিল সবুজ রঞ্জক", "রাসায়নিক শক্তিতে রূপান্তর"],
                        "checkpoint": "ক্লোরোফিলের ভূমিকা কী?",
                    }
                ],
            },
            output_path=bengali_out,
        )
        assert Path(res_bengali).exists()
        assert Path(res_bengali).stat().st_size > 1000


def test_get_pillow_font_indic_selection() -> None:
    """Verify get_pillow_font detects Indic script and loads an Indic-capable font."""
    from chat_agent.infographics.config import get_pillow_font

    font_hindi = get_pillow_font(size=14, for_text="प्रकाश संश्लेषण")
    assert font_hindi is not None

    font_bengali = get_pillow_font(size=14, for_text="সালোকসংশ্লেষ")
    assert font_bengali is not None


def test_generate_handwritten_notes_pdf_multipage() -> None:
    """Verify multi-page notes PDF generation (regression: header font used before assignment)."""
    content = "\n\n".join(f"# Section {i}\n" + ("Line of notes text. " * 40) for i in range(6))
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_path = str(Path(tmp_dir) / "multipage_notes.pdf")
        result = generate_handwritten_notes_pdf(
            title="Multi Page Notes",
            content=content,
            subject="Test",
            output_path=out_path,
        )
        assert Path(result).exists()
        assert Path(result).stat().st_size > 1000

