"""Email subsystem type aliases."""

type TemplateContext = dict[str, object]
type AttachmentMapping = dict[str, object]
type AttachmentTuple = tuple[object, ...]
type AttachmentInput = object
type EmailPayload = dict[str, object]
