from typing import Protocol

from app.models import User


class NotificationAdapter(Protocol):
    def send(self, user: User, message: str) -> None: ...


class ConsoleNotificationAdapter:
    def send(self, user: User, message: str) -> None:
        print(f"[notify:console] to={user.email} message={message!r}")


class TwilioShapedSmsAdapter:
    """Logs in the shape a real Twilio call would take, without calling out.

    Swap this for a real client.messages.create(...) call once SMS credentials exist.
    """

    def send(self, user: User, message: str) -> None:
        print(
            f"[notify:sms] would call Twilio messages.create(to=+1, body={message!r}) "
            f"for {user.email}"
        )


_adapter: NotificationAdapter = ConsoleNotificationAdapter()


def get_notification_adapter() -> NotificationAdapter:
    return _adapter


def set_notification_adapter(adapter: NotificationAdapter) -> None:
    global _adapter
    _adapter = adapter


def notify_state_change(user: User, resident_label: str, ready_by_local: str) -> None:
    messages = {
        "Called": f"Your car has been called. Ready by {ready_by_local}.",
        "On the way": "Your car is on the way to the lobby.",
        "Delivered": "Your car has been delivered and is waiting at the lobby.",
    }
    message = messages.get(resident_label)
    if message:
        get_notification_adapter().send(user, message)
