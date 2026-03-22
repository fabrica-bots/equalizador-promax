class EqualizadorError(Exception):
    exit_code = 1


class ValidationError(EqualizadorError):
    exit_code = 1


class JiraIntegrationError(EqualizadorError):
    exit_code = 2


class ConflictPauseError(EqualizadorError):
    exit_code = 3


class InconsistentStateError(EqualizadorError):
    exit_code = 4


class GitCommandError(EqualizadorError):
    exit_code = 1

    def __init__(self, command: list[str], stderr: str, stdout: str = "") -> None:
        self.command = command
        self.stderr = stderr.strip()
        self.stdout = stdout.strip()
        message = f"Git command failed: {' '.join(command)}"
        if self.stderr:
            message = f"{message} ({self.stderr})"
        super().__init__(message)
