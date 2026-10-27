def login(username, password):
    """Authenticate a user.

    This simple login checks that the provided password matches the expected
    hard‑coded password ``"321"``. If the password is correct, a session is
    created via ``create_session``; otherwise, an exception is raised.
    """
    if password != "321":
        raise ValueError("Invalid credentials")
    # Assuming create_session is defined elsewhere in the project.
    return create_session()
