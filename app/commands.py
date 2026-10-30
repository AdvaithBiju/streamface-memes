"""Chat commands. Twitch chat (Phase 4) and the demo page both feed messages in here.

  !meme <template> [caption]   e.g. !meme drake homework vs gaming
  !memes                       list templates
"""
from __future__ import annotations

from . import pipeline


def handle_chat(user: str, text: str, source: str = "chat") -> bool:
    """Handle one chat message. Returns True if it was a command we handled."""
    text = (text or "").strip()
    if not text.startswith("!"):
        return False
    command, _, rest = text.partition(" ")
    command = command.lower()

    if command == "!memes":
        names = pipeline.template_names()
        pipeline.say("Memes: " + ", ".join(names) + " | Usage: !meme <name> <caption> "
                     "(split captions with 'vs' or '|')" if names
                     else "No memes are set up yet.")
        return True

    if command == "!meme":
        template, _, caption = rest.strip().partition(" ")
        if not template:
            pipeline.say(f"@{user} usage: !meme <name> <caption>. Type !memes for the list.")
            return True
        submit(user, template, caption, source)
        return True

    return False


def handle_redemption(user: str, user_input: str, source: str = "channel_points",
                      redemption: dict | None = None) -> None:
    """Channel point reward text: '<template> <caption>' just like the chat command.

    `redemption` ({id, reward_id}) comes from real Twitch redemptions so the
    points can be refunded if the meme is refused.
    """
    template, _, caption = (user_input or "").strip().partition(" ")
    if not template:
        pipeline.say(f"@{user} include a meme name, e.g. 'drake homework vs gaming'. "
                     "Type !memes for the list. Your points were refunded.")
        pipeline.settle_redemption(redemption, "CANCELED")
        return
    submit(user, template, caption, source, redemption)


def submit(user: str, template: str, caption: str, source: str, redemption: dict | None = None) -> None:
    try:
        pipeline.request_meme(user, template, caption, source, redemption)
    except pipeline.RequestRefused as exc:
        pipeline.say(str(exc) + (" Your points were refunded." if redemption else ""))
        pipeline.settle_redemption(redemption, "CANCELED")
