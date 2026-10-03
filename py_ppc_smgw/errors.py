"""Errors for the PPC-SMGW Client."""


class PPCSMGWError(Exception):
    """Base exception for all py-ppc-smgw errors."""


class AuthError(PPCSMGWError):
    """Base exception for authentication and session errors."""


class SessionCookieStillPresentError(AuthError):
    """Exception raised when the session cookie is still present after deletion which prevents subsequent readings."""


class NotLoggedInError(AuthError):
    """Exception raised when the user is not logged in."""


class LoginFailedError(AuthError):
    """Exception raised when the login failed."""


class ResponseParseError(PPCSMGWError):
    """Exception raised when response data (HTML, XML, CMS) cannot be located or parsed."""
