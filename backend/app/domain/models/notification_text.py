"""Final text contract: UTF-16 units, including separators, link and local prefix."""
class MessageTooLongError(ValueError):
    pass


def final_notification_text(message, link, prefix=None):
    if not link:
        raise ValueError("canonical link is required")
    greeting = message.greeting
    if prefix is not None:
        prefix = prefix.strip()
        if not prefix:
            raise ValueError("local prefix is required")
        while greeting.startswith(prefix):
            greeting = greeting[len(prefix):].lstrip()
        greeting = prefix + "\n\n" + greeting
    return "\n\n".join((greeting, message.introduction, message.note, link))


def utf16_units(text):
    return len(text.encode("utf-16-le", errors="surrogatepass")) // 2


def validate_final_text(text):
    if utf16_units(text) > 5000:
        raise MessageTooLongError("message_too_long")
    return text
