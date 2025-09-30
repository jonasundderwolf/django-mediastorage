import enum


class MediaStorageMode(enum.StrEnum):
    x_accel_redirect = "x-accel-redirect"
    http_forward_auth = "http-forward-auth"

    # todo: add a DEBUG mode for use with DEBUG=True which essentially disables a few
    #   checks that don't make sense for local dev environments. Build the response not
    #   based on the DEBUG setting but only on the MODE. It should still be possible to
    #   use other modes with DEBUG=True, but the responses should match the mode in this
    #   case.


class ProtectionClass(enum.Enum):
    """
    Protection class for data.

    The protection class is a rough estimation of how strong access to a given piece of
    data needs to be restricted.

    Attributes
    ----------

    PUBLIC :
        Data that can be released to the public without any issues.

        Examples: UI icons that are not static files, public profile pictures

    INTERNAL :
        Information considered to be internal, but without any additional restriction
        within the organization. Can be accessed by any employee or external workers.

    PRIVATE :
        Information of a personal nature intended for use only within the organization.

        This class is the minimum that applies for any personal information according to
        GDPR. When in doubt, anything that has a name on it belongs here.

        Examples: documents containing handwritten signatures, documents containing the
        names of people involved or other personal information, invoices, ...

    CONFIDENTIAL :
        Shared only with people who absolutely need to know.

        This is information that could harm the organization or people when in false
        hands.

        Examples: private phone numbers or addresses, financial information
    """

    PUBLIC = 0
    INTERNAL = 1
    PRIVATE = 2
    CONFIDENTIAL = 3

    def __gt__(self, other):
        return self.value > other.value
