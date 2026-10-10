"""Source ingestion gate. Importing this module performs no network activity."""
from .models import (SourceSnapshot, ParsedSource, EvidenceSpan, SourceFailure,
                     SourceErrorCode, AuthorityAttestation)
from .fetch import SafeSourceFetcher, PinnedHTTPTransport, safe_target, public_addresses
from .parse import parse_snapshot
from .evidence import (IssuerAuthorityRegistry, ground_exact_quote,
                       verify_span, admit_document)
from .store import SnapshotStore
