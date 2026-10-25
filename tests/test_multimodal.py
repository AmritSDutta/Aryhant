"""Hermetic unit tests for Multimodal processing, Slack attachment extraction, and GenAI content conversion."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from google.genai import types

from chat_agent.agents.gemini_model_runner import _prune_prior_binary_parts
from chat_agent.config import settings
from chat_agent.slack.slack_http import (
    handle_slack_payload,
    is_duplicate_event,
    remove_dedup_event,
)
from chat_agent.utils.input_validation import get_LLM_feedback_on_input
from chat_agent.utils.multimodal import (
    build_adk_multimodal_content,
    download_slack_file,
    extract_and_download_slack_attachments,
    extract_slack_files,
    validate_multimodal_payload,
)


def test_extract_slack_files_filtering():
    raw_event = {
        "files": [
            {
                "id": "F1",
                "name": "diagram.png",
                "mimetype": "image/png",
                "size": 1024,
                "url_private_download": "https://files.slack.com/diagram.png",
            },
            {
                "id": "F2",
                "name": "audio.mp3",
                "mimetype": "audio/mp3",
                "size": 2048,
                "url_private": "https://files.slack.com/audio.mp3",
            },
            {
                "id": "F3",
                "name": "report.pdf",
                "mimetype": "application/pdf",
                "size": 4096,
                "url_private_download": "https://files.slack.com/report.pdf",
            },
            {
                "id": "F4",
                "name": "doc.html",
                "mimetype": "text/html",
                "size": 1024,
                "url_private_download": "https://files.slack.com/doc.html",
            },
            {
                "id": "F5",
                "name": "malicious.exe",
                "mimetype": "application/x-msdownload",
                "size": 512,
                "url_private_download": "https://files.slack.com/malicious.exe",
            },
            {
                "id": "F6",
                "name": "no_url.txt",
                "mimetype": "text/plain",
            },
        ]
    }

    files = extract_slack_files(raw_event)
    assert len(files) == 4
    assert files[0]["name"] == "diagram.png"
    assert files[0]["mimetype"] == "image/png"
    assert files[1]["name"] == "audio.mp3"
    assert files[1]["mimetype"] == "audio/mp3"
    assert files[2]["name"] == "report.pdf"
    assert files[2]["mimetype"] == "application/pdf"
    assert files[3]["name"] == "doc.html"
    assert files[3]["mimetype"] == "text/html"


@pytest.mark.asyncio
async def test_download_slack_file_success():
    fake_bytes = b"GIF89a\x01\x00\x01\x00\x80\x00\x00"
    mock_response = MagicMock()
    mock_response.content = fake_bytes
    mock_response.headers = {"content-type": "image/gif; charset=utf-8"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("httpx.AsyncClient", return_value=mock_client):
        data, mime = await download_slack_file("https://files.slack.com/test.gif", bot_token="xoxb-test")
        assert data == fake_bytes
        assert mime == "image/gif"
        mock_client.get.assert_awaited_once_with(
            "https://files.slack.com/test.gif",
            headers={"Authorization": "Bearer xoxb-test"},
        )


@pytest.mark.asyncio
async def test_download_slack_file_single_file_500kb_exceeded():
    large_bytes = b"x" * (501 * 1024)
    mock_response = MagicMock()
    mock_response.content = large_bytes
    mock_response.headers = {"content-type": "application/pdf"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ValueError, match="exceeds maximum limit"):
            await download_slack_file("https://files.slack.com/big.pdf")


@pytest.mark.asyncio
async def test_download_slack_file_html_cdn_error_rejected():
    mock_response = MagicMock()
    mock_response.content = b"<html><body>Slack Error</body></html>"
    mock_response.headers = {"content-type": "text/html; charset=utf-8"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ValueError, match="Received HTML error response"):
            await download_slack_file("https://files.slack.com/file.png")


@pytest.mark.asyncio
async def test_extract_and_download_slack_attachments_preserves_slack_mimetype_and_cumulative_cap():
    event = {
        "files": [
            {
                "id": "F1",
                "name": "diagram.png",
                "mimetype": "image/png",
                "url_private_download": "https://files.slack.com/diagram.png",
            },
            {
                "id": "F2",
                "name": "huge.mp3",
                "mimetype": "audio/mp3",
                "url_private_download": "https://files.slack.com/huge.mp3",
            },
        ]
    }

    async def mock_dl(url, bot_token=None, max_size_bytes=None):
        if "diagram.png" in url:
            return (b"png-data" * 100, "application/octet-stream")
        return (b"huge-data" * (3 * 1024 * 1024), "audio/mp3")

    with patch("chat_agent.utils.multimodal.download_slack_file", side_effect=mock_dl):
        attachments = await extract_and_download_slack_attachments(event)
        assert len(attachments) == 1
        assert attachments[0][1] == "image/png"


def test_build_adk_multimodal_content():
    media_items = [
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"ID3\x03\x00\x00\x00", "audio/mp3"),
        (b"%PDF-1.4", "application/pdf"),
    ]
    content = build_adk_multimodal_content("Analyze these files", media_items)
    assert isinstance(content, types.Content)
    assert content.role == "user"
    assert len(content.parts) == 4
    assert content.parts[0].text == "Analyze these files"
    assert content.parts[1].inline_data.mime_type == "image/png"
    assert content.parts[2].inline_data.mime_type == "audio/mp3"
    assert content.parts[3].inline_data.mime_type == "application/pdf"


@pytest.mark.asyncio
async def test_validate_multimodal_payload_cumulative_limit_exceeded():
    huge_media = [(b"x" * (3 * 1024 * 1024), "image/jpeg")]
    assert await validate_multimodal_payload("Look", huge_media) is False


@pytest.mark.asyncio
async def test_validate_multimodal_payload_bypasses_external_moderation_when_gemini_moderation_enough():
    media = [(b"fake-image", "image/jpeg")]
    with patch.object(settings, "IS_GEMINI_MODERATION_ENOUGH", True), patch(
        "chat_agent.utils.multimodal.scan_for_vulnerability", new_callable=AsyncMock
    ) as mock_scan, patch(
        "chat_agent.utils.multimodal.get_LLM_feedback_on_input", new_callable=AsyncMock
    ) as mock_llm_mod:
        res = await validate_multimodal_payload("Safe prompt", media)
        assert res is True
        mock_scan.assert_not_awaited()
        mock_llm_mod.assert_not_awaited()


@pytest.mark.asyncio
async def test_validate_multimodal_payload_runs_external_moderation_when_gemini_moderation_disabled():
    media = [(b"fake-image", "image/jpeg")]
    with patch.object(settings, "IS_GEMINI_MODERATION_ENOUGH", False), patch(
        "chat_agent.utils.multimodal.scan_for_vulnerability", new_callable=AsyncMock, return_value=True
    ) as mock_scan, patch(
        "chat_agent.utils.multimodal.get_LLM_feedback_on_input", new_callable=AsyncMock, return_value=True
    ) as mock_llm_mod:
        res = await validate_multimodal_payload("Safe prompt", media)
        assert res is True
        mock_scan.assert_awaited_once()
        mock_llm_mod.assert_awaited_once()


@pytest.mark.asyncio
async def test_openai_moderation_formats_data_url_from_bytes():
    mock_res = MagicMock(flagged=False, categories={})
    mock_response = MagicMock(results=[mock_res])
    mock_client = MagicMock()
    mock_client.moderations.create = AsyncMock(return_value=mock_response)

    with patch("openai.AsyncOpenAI", return_value=mock_client), patch.object(
        settings, "OPENAI_API_KEY", "sk-test-key"
    ):
        result = await get_LLM_feedback_on_input(
            media_type="image/png", media_data=b"test-bytes-content"
        )
        assert result is True
        mock_client.moderations.create.assert_awaited_once()
        call_input = mock_client.moderations.create.call_args[1]["input"]
        assert len(call_input) == 1
        assert call_input[0]["type"] == "image_url"
        assert call_input[0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_event_deduplication_and_eviction():
    event_id = "evt_test_unique_123"
    assert is_duplicate_event(event_id) is False
    assert is_duplicate_event(event_id) is True
    remove_dedup_event(event_id)
    assert is_duplicate_event(event_id) is False


@pytest.mark.asyncio
async def test_handle_slack_payload_session_keying():
    threaded_payload = {
        "event": {
            "type": "app_mention",
            "channel": "C123",
            "user": "U123",
            "ts": "100.1",
            "thread_ts": "100.0",
            "text": "threaded query",
        }
    }
    toplevel_payload = {
        "event": {
            "type": "app_mention",
            "channel": "C123",
            "user": "U123",
            "ts": "200.0",
            "text": "top level query",
        }
    }

    mock_run = AsyncMock(return_value="Reply")
    mock_post = AsyncMock()

    with patch("chat_agent.slack.slack_http.run_agent", mock_run), patch(
        "chat_agent.slack.slack_http.post_slack_message", mock_post
    ):
        await handle_slack_payload(threaded_payload)
        assert mock_run.call_args[1]["session_id"] == "slack:C123:100.0"

        await handle_slack_payload(toplevel_payload)
        assert mock_run.call_args[1]["session_id"] == "slack:C123:200.0"


@pytest.mark.asyncio
async def test_handle_slack_payload_error_evicts_dedup():
    payload = {
        "event_id": "EvtFail1",
        "event": {
            "type": "app_mention",
            "channel": "C123",
            "user": "U123",
            "text": "do work",
        },
    }
    with patch("chat_agent.slack.slack_http.run_agent", side_effect=RuntimeError("processing error")):
        with pytest.raises(RuntimeError, match="processing error"):
            await handle_slack_payload(payload)
        assert is_duplicate_event("EvtFail1") is False


@pytest.mark.asyncio
async def test_prior_turn_binary_pruning_in_history():
    from chat_agent.agents import gemini_model_runner as runner_mod

    session_id = "s_test_prune_1"
    runner_mod._HISTORY.pop(session_id, None)

    mock_part_bin = types.Part.from_bytes(data=b"old-png", mime_type="image/png")
    mock_part_txt = types.Part.from_text(text="previous question")
    mock_content = types.Content(role="user", parts=[mock_part_txt, mock_part_bin])
    runner_mod._HISTORY[session_id] = [mock_content]

    _prune_prior_binary_parts(session_id)

    parts = runner_mod._HISTORY[session_id][0].parts
    assert len(parts) == 2
    assert parts[0].text == "previous question"
    assert parts[1].text == "[Attachment: image/png - processed in prior turn]"
    assert parts[1].inline_data is None


@pytest.mark.asyncio
async def test_openai_moderation_audio_formats_and_skipping():
    mock_res = MagicMock(flagged=False, categories={})
    mock_response = MagicMock(results=[mock_res])
    mock_client = MagicMock()
    mock_client.moderations.create = AsyncMock(return_value=mock_response)

    with patch("openai.AsyncOpenAI", return_value=mock_client), patch.object(
        settings, "OPENAI_API_KEY", "sk-test-key"
    ):
        # MP3 format mapping
        res_mp3 = await get_LLM_feedback_on_input(media_type="audio/mp3", media_data=b"mp3data")
        assert res_mp3 is True
        call_input = mock_client.moderations.create.call_args[1]["input"]
        assert call_input[0]["type"] == "input_audio"
        assert call_input[0]["input_audio"]["format"] == "mp3"

        # WAV format mapping
        mock_client.moderations.create.reset_mock()
        res_wav = await get_LLM_feedback_on_input(media_type="audio/wav", media_data=b"wavdata")
        assert res_wav is True
        call_input = mock_client.moderations.create.call_args[1]["input"]
        assert call_input[0]["type"] == "input_audio"
        assert call_input[0]["input_audio"]["format"] == "wav"

        # Unsupported audio format skipped
        mock_client.moderations.create.reset_mock()
        res_m4a = await get_LLM_feedback_on_input(media_type="audio/m4a", media_data=b"m4adata")
        assert res_m4a is True
        mock_client.moderations.create.assert_not_called()


@pytest.mark.asyncio
async def test_openai_moderation_fail_closed_when_required():
    with patch.object(settings, "OPENAI_API_KEY", ""), patch.object(
        settings, "MODERATION_API_CHECK_REQ", True
    ), patch.dict("os.environ", {}, clear=True):
        res = await get_LLM_feedback_on_input(
            media_type="image/png", media_data=b"imagebytes"
        )
        assert res is False
