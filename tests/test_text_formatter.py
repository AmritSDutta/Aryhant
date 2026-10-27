"""Unit tests for the semantic Markdown-to-human text interpreter and fallback cleanup."""
from __future__ import annotations

from chat_agent.utils.text_formatter import (
    fallback_cleanup_markdown,
    format_human_readable_text,
    interpret_markdown,
)


def test_sky_is_blue_user_example():
    """Verify translation of glued 'Why the sky looks blue' markdown response."""
    raw = (
        "Here is a simple way to understand why the sky looks blue:**1. Sunlight is made of many colors**"
        "Even though sunlight looks white, it is actually a mix of all the colors of the rainbow — "
        "red, orange, yellow, green, blue, indigo, and violet.**2. Earth has an atmosphere**"
        "The air around us is filled with tiny gas molecules, dust, and water droplets. When sunlight enters "
        "the atmosphere, it hits these tiny particles.**3. Blue light scatters the most**Different colors of "
        "light travel in different-sized waves. Blue light travels in shorter, smaller waves, so it gets "
        "scattered (bounced around) much more than red or yellow light. Because of this, blue light spreads "
        "across the sky and reaches your eyes from every di… **4. That is why the sky looks blue**When you "
        "look up during a clear day, your eyes catch all that scattered blue light, so the sky appears blue "
        "to you.**Bonus: Why is the sunset red?**At sunrise and sunset, sunlight has to travel through much "
        "more atmosphere to reach you. By the time it gets to your eyes, most of the blue light has been "
        "scattered away, leaving the reds and oranges behind.So the next time you see a blue sky, you are "
        "seeing sunlight playing hide-and-seek with air molecules! :mostly_sunny:Would you like me to explain "
        "anything else about weather, rainbows, or space?"
    )

    cleaned = format_human_readable_text(raw)

    # Assert no raw markdown bold syntax remains
    assert "**" not in cleaned

    # Assert numbered headings are cleanly un-glued on fresh lines
    assert "1. Sunlight is made of many colors\nEven though" in cleaned
    assert "2. Earth has an atmosphere\nThe air" in cleaned
    assert "3. Blue light scatters the most\nDifferent" in cleaned
    assert "4. That is why the sky looks blue\nWhen you" in cleaned
    assert "Bonus: Why is the sunset red?\nAt sunrise" in cleaned

    # Assert un-glued sentence boundary
    assert "behind.\n\nSo the next time" in cleaned

    # Assert emoji preserved and un-glued from closing question
    assert ":mostly_sunny:" in cleaned
    assert ":mostly_sunny:\n\nWould you like me to explain" in cleaned


def test_sun_is_white_user_example():
    """Verify translation of glued 'The Sun is actually white' markdown response."""
    raw = (
        "Here is the simple answer: **The Sun is actually white, but it looks yellow to us from Earth.**"
        "Here is why:**1. The Sun sends out all colors of light**The Sun shines with every color of the rainbow "
        "mixed together. When all those colors combine, they make white light.**2. Earth’s atmosphere acts like a "
        "filter**Before sunlight reaches your eyes, it passes through the air around Earth. Tiny molecules in "
        "the air scatter (bounce around) the blue and violet light more than the other colors.**3. Some blue light "
        "is removed**Because some of the blue light gets scattered away in different directions, the sunlight that "
        "reaches you directly has a little less blue in it. That makes the Sun look yellowish instead of pure "
        "white.**4. At sunrise and sunset, it looks even redder**Early in the morning and late in the evening, "
        "sunlight has to travel through much more air to reach you. Even more blue light gets scattered away, "
        "leaving mostly red and orange light — that is why the Sun looks red or orange near the horizon."
        "**Fun fact:** Astronauts in space see the Sun as pure white because there is no atmosphere to scatter "
        "the light!So the Sun is not really yellow — it just looks that way because of our atmosphere. "
        ":mostly_sunny:Would you like to know more about stars, rainbows, or how light travels?"
    )

    cleaned = format_human_readable_text(raw)

    assert "**" not in cleaned
    assert "The Sun is actually white, but it looks yellow to us from Earth.\n\nHere is why:" in cleaned
    assert "1. The Sun sends out all colors of light\nThe Sun shines" in cleaned
    assert "2. Earth’s atmosphere acts like a filter\nBefore sunlight" in cleaned
    assert "3. Some blue light is removed\nBecause some" in cleaned
    assert "4. At sunrise and sunset, it looks even redder\nEarly in" in cleaned
    assert "Fun fact:\nAstronauts in space" in cleaned
    assert "light!\n\nSo the Sun is not really" in cleaned
    assert ":mostly_sunny:\n\nWould you like to know more" in cleaned


def test_markdown_elements_interpretation():
    """Verify interpretation of headers, lists, code, and links."""
    text = (
        "# Introduction to Fractions\n\n"
        "Fractions represent parts of a whole.\n\n"
        "## Key Steps\n"
        "- First, find the common denominator.\n"
        "- Next, add the numerators.\n"
        "- Finally, simplify.\n\n"
        "Check this out: [ICSE Portal](https://cisce.org) and run `lcm(6, 8)`."
    )

    result = format_human_readable_text(text)
    assert "#" not in result
    assert "Introduction to Fractions" in result
    assert "Key Steps" in result
    assert "• First, find the common denominator." in result
    assert "• Next, add the numerators." in result
    assert "• Finally, simplify." in result
    assert "ICSE Portal (https://cisce.org)" in result
    assert "'lcm(6, 8)'" in result


def test_fallback_cleanup_on_error(monkeypatch):
    """Verify that if interpret_markdown raises an exception, fallback_cleanup_markdown takes over."""
    def fail_interpret(_: str) -> str:
        raise ValueError("Simulated parser failure")

    monkeypatch.setattr("chat_agent.utils.text_formatter.interpret_markdown", fail_interpret)

    raw = "Here is the title:**1. Step One**Details here.**Fun fact:** Something cool! :sparkles:Done"
    result = format_human_readable_text(raw)

    # Fallback cleanly un-glues and strips ** without crashing
    assert "**" not in result
    assert "1. Step One" in result
    assert "Fun fact:" in result
    assert ":sparkles:" in result


def test_empty_and_whitespace_input():
    """Verify handling of empty or blank inputs."""
    assert format_human_readable_text("") == ""
    assert format_human_readable_text("   \n\n  ") == ""
