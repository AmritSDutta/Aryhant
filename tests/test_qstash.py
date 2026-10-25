"""Hermetic unit tests for QStash signature verification and dependency handling."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import HTTPException, Request

from chat_agent.config.qstash_authentication import get_receiver, verify_qstash


def test_get_receiver_initialization():
    receiver1 = get_receiver()
    receiver2 = get_receiver()
    assert receiver1 is receiver2


@pytest.mark.asyncio
async def test_verify_qstash_missing_signature_header():
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {}
    mock_request.body = AsyncMock(return_value=b"{}")

    with pytest.raises(HTTPException) as exc_info:
        await verify_qstash(mock_request)

    assert exc_info.value.status_code == 401
    assert "Missing signature" in exc_info.value.detail


@pytest.mark.asyncio
async def test_verify_qstash_invalid_signature():
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"Upstash-Signature": "invalid_sig"}
    mock_request.body = AsyncMock(return_value=b'{"message": "hi"}')

    with patch("chat_agent.config.qstash_authentication.get_receiver") as mock_get_recv:
        mock_receiver = MagicMock()
        mock_receiver.verify.side_effect = Exception("Signature verification failed")
        mock_get_recv.return_value = mock_receiver

        with pytest.raises(HTTPException) as exc_info:
            await verify_qstash(mock_request)

        assert exc_info.value.status_code == 401
        assert "Invalid signature" in exc_info.value.detail


@pytest.mark.asyncio
async def test_verify_qstash_valid_signature():
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"Upstash-Signature": "valid_sig_123"}
    mock_request.body = AsyncMock(return_value=b'{"message": "hi"}')

    with patch("chat_agent.config.qstash_authentication.get_receiver") as mock_get_recv:
        mock_receiver = MagicMock()
        mock_receiver.verify.return_value = True
        mock_get_recv.return_value = mock_receiver

        # Should complete without raising exception
        await verify_qstash(mock_request)
        mock_receiver.verify.assert_called_once_with(
            body='{"message": "hi"}',
            signature="valid_sig_123",
        )
