from .schema import NeronIdentity


class IdentityValidationError(RuntimeError):
    """Erreur de validation de l'identité Néron."""


class IdentityValidator:

    REQUIRED_FIELDS = [
        "name",
        "version",
        "role",
        "mission",
        "identity",
        "personality",
        "conversation",
        "context",
    ]

    @classmethod
    def validate(cls, identity: NeronIdentity):

        errors = []

        for field in cls.REQUIRED_FIELDS:
            value = getattr(identity, field, None)

            if not value or not value.strip():
                errors.append(
                    f"Champ obligatoire absent : {field}"
                )

        if errors:
            raise IdentityValidationError(
                "\n".join(errors)
            )

        return True
