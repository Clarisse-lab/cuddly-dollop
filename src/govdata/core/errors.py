class GovDataError(Exception):
    """Base exception for errors that callers may safely handle."""


class ConnectorNotFoundError(GovDataError):
    pass


class ConnectorConfigurationError(GovDataError):
    pass


class DatasetNotSupportedError(GovDataError):
    pass


class TransportError(GovDataError):
    pass


class InvalidResponseError(GovDataError):
    pass

