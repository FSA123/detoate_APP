class ApiError(Exception):
    """
    Eroare destinată utilizatorului: app.py o transformă în
    {"error": message} cu statusul HTTP dat (400 implicit).
    """

    def __init__(self, message, status=400, extra=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.extra = extra or {}  # câmpuri în plus în răspuns, ex. erorile pe rânduri la import
