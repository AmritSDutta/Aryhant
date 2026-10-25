from __future__ import annotations

import argparse
import asyncio
import logging

from chat_agent.agents.runner import run_agent
from chat_agent.config import llm_ready, setup_logging, slack_ready
from chat_agent.slack.slack_app import start_slack

setup_logging()
logger = logging.getLogger("chat_agent.main")


async def run_channels(include_slack: bool = True) -> None:
    """Run configured messaging channels."""
    if not llm_ready():
        raise RuntimeError("Set USER_LLM_API_KEY in env before starting the agent.")
    tasks = []
    if include_slack:
        if slack_ready():
            tasks.append(asyncio.create_task(start_slack(), name="slack"))
        else:
            logger.warning("Slack not configured.")
    if not tasks:
        raise RuntimeError("No channel enabled. Configure Slack tokens.")
    await asyncio.gather(*tasks)


def main() -> None:
    """CLI entry point for running the chat agent and channels."""
    parser = argparse.ArgumentParser(description="ADK Slack chat agent")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve", "slack", "chat"])
    parser.add_argument("--message", default="", help="One-shot local chat message")
    args = parser.parse_args()

    if args.command == "chat":
        if not args.message:
            raise SystemExit("Pass --message for local chat.")
        reply = asyncio.run(run_agent("local-user", "local-session", args.message))
        print(reply)
        return
    if args.command == "slack":
        asyncio.run(run_channels(include_slack=True))
        return
    asyncio.run(run_channels(include_slack=True))


if __name__ == "__main__":
    main()

