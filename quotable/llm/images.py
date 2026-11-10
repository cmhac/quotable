"""
How a page image is made for the stages that read cell text (spec 014).

``ImagePolicy`` says the resolution and detail value of the image sent with a page extraction, a
recheck and an audit request. ``TODAY`` is what quotable did before spec 014. ``policy_for`` picks
the policy from the model's provider, and ``check_page_sizes`` refuses a document whose pages
would be too large for the provider before any request is made.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ImagePolicy:
    """The resolution and detail of a page image, and the largest image the provider accepts."""

    dpi: int
    detail: str
    max_patches: int | None  # largest image in 32 px patches; None = no check
    max_side: int | None  # largest side in pixels; None = no check


TODAY = ImagePolicy(150, "high", None, None)
