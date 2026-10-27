"""Final text contract: UTF-16 units, including separators, link and local prefix."""
# ECMAScript String.trim/trimStart, shared with the Admin preview contract.
TEXT_WHITESPACE = " \t\n\r\v\f\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


class MessageTooLongError(ValueError):
    pass


def final_notification_text(message, link, prefix=None):
    if not link:
        raise ValueError("canonical link is required")
    greeting = message.greeting
    if prefix is not None:
        prefix = prefix.strip(TEXT_WHITESPACE)
        if not prefix:
            raise ValueError("local prefix is required")
        while greeting.startswith(prefix):
            greeting = greeting[len(prefix):].lstrip(TEXT_WHITESPACE)
        greeting = prefix + "\n\n" + greeting
    sections = (value.replace("\u2063", "").strip(TEXT_WHITESPACE)
                for value in (greeting, message.introduction, message.note))
    body = "\n\n".join(value for value in sections if value)
    return body + "\n" + link if body else link


def utf16_units(text):
    return len(text.encode("utf-16-le", errors="surrogatepass")) // 2


def validate_final_text(text):
    if utf16_units(text) > 5000:
        raise MessageTooLongError("message_too_long")
    return text
