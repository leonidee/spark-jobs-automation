class EnvironNotSet(Exception):
    def __init__(self, msg: str) -> None:
        """Can be raised if required environment variables not set while checking it with EnvironManager.

        ## Parameters
        `msg` : Error message
        """
        super().__init__(msg)


class DotEnvError(Exception):
    def __init__(self, msg: str) -> None:
        """Can be raised if EnvironManager enable to load environment variables.

        ## Parameters
        `msg` : Error message
        """
        super().__init__(msg)
