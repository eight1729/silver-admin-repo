class DomainError(Exception):
    pass


class ExternalBusinessError(DomainError):
    pass


class ExternalMemberNotFoundError(ExternalBusinessError):
    pass


class ExternalJobNotFoundError(ExternalBusinessError):
    pass


class ExternalSystemUnavailableError(ExternalBusinessError):
    pass


class ExternalBusinessNotConfiguredError(ExternalBusinessError):
    pass


class LineAuthError(DomainError):
    pass


class LineIdTokenInvalidError(LineAuthError):
    pass


class QueueError(DomainError):
    pass


class SecretProviderError(DomainError):
    pass


class SecretNotFoundError(SecretProviderError):
    pass


class StaffAuthenticationError(DomainError):
    pass


class AuthenticatorNotConfiguredError(StaffAuthenticationError):
    pass


class StaffUnavailableError(StaffAuthenticationError):
    pass


class InactiveStaffError(StaffAuthenticationError):
    pass


class InvalidStaffConfigurationError(StaffAuthenticationError, ValueError):
    pass


class DemoModeDisabledError(StaffAuthenticationError):
    pass


class InvalidStaffTokenError(StaffAuthenticationError):
    pass


class UnknownStaffIdentityError(StaffAuthenticationError):
    pass


class StaffServiceScopeError(StaffAuthenticationError):
    pass
