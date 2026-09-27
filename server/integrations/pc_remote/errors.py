class PCRemoteError(RuntimeError):
    user_message = "L'agent PC distant est actuellement indisponible."


class PCRemoteUnavailable(PCRemoteError):
    pass


class PCRemoteApiError(PCRemoteError):
    pass


class PCRemoteAuthError(PCRemoteError):
    user_message = "Authentification refusée par l'agent PC distant."


class PCRemoteDeviceNotFound(PCRemoteError):
    user_message = "Je ne connais pas ce PC distant."


class PCRemoteAppNotFound(PCRemoteError):
    user_message = "Je ne trouve pas cette application sur ce PC distant."
