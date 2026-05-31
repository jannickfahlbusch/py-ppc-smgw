"""Errors for the PPC-SMGW Client."""


class SessionCookieStillPresentError(Exception):
    """Exception raised when the session cookie is still present after deletion which prevents subsequent readings."""


class NotLoggedInError(Exception):
    """Exception raised when the user is not logged in."""


class LoginFailedError(Exception):
    """Exception raised when the login failed."""
