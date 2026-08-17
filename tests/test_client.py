"""Tests for shared client helpers."""

import threading

import pytest

from py_ppc_smgw.client import _run_parser


@pytest.mark.asyncio
async def test_run_parser_uses_executor_thread() -> None:
    event_loop_thread = threading.get_ident()
    parser_threads: list[int] = []

    def parser(content: bytes) -> str:
        parser_threads.append(threading.get_ident())
        return content.decode()

    result = await _run_parser(parser, b"parsed")

    assert result == "parsed"
    assert parser_threads
    assert all(thread != event_loop_thread for thread in parser_threads)
