"""Compatibility error type only; no device console or SSH is included."""
class ConsoleError(Exception):
    def __init__(self,message,status=400):
        super().__init__(message)
        self.status=status
