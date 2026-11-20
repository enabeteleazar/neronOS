from .schema import NeronIdentity


class IdentityValidationError(RuntimeError):
    """Erreur de validation de l'identité Néron."""


class IdentityValidator:

    # NERON.md structure ("identity" + les champs Name/Version/Role/Mission
    # qu il porte) est la SOURCE CANONIQUE : sans lui, Neron n a pas
    # d identite. PERSONALITY.md/CONVERSATION.md/CONTEXT.md sont des
    # documents compagnons qui enrichissent le prompt quand ils existent ;
    # leur absence ne doit pas rendre l identite invalide (decision Phase 2C).
    REQUIRED_FIELDS = [
        "name",
        "version",
        "role",
        "mission",
        "identity",
    ]

    OPTIONAL_FIELDS = [
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
