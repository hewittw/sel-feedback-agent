"""Thin wrapper around the Anthropic SDK. Every call is independent and stateless."""
import anthropic


class ClaudeError(Exception):
    """Raised for any API failure, with a message safe to show the user."""


class ClaudeClient:
    def __init__(self, api_key: str, model: str):
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def complete(self, system: str, user: str, max_tokens: int) -> str:
        try:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.AuthenticationError:
            raise ClaudeError("Authentication failed: check ANTHROPIC_API_KEY.") from None
        except anthropic.NotFoundError:
            raise ClaudeError(f"Model not found: check ANTHROPIC_MODEL ({self.model!r}).") from None
        except anthropic.APIConnectionError:
            raise ClaudeError("Could not reach the Claude API (network problem).") from None
        except anthropic.APIStatusError as e:
            raise ClaudeError(f"Claude API error {e.status_code}.") from None
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        if not text:
            raise ClaudeError(f"Claude returned no text (stop_reason={resp.stop_reason}).")
        return text
