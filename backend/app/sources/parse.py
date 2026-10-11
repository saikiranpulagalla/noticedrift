"""Bounded, conservative HTML/PDF extraction. Parsing != authority or verified semantics."""
from __future__ import annotations
from hashlib import sha256
import re
from .models import ParsedSource, SourceSnapshot, SourceFailure, SourceErrorCode

MAX_TEXT_CHARS = 200_000
MAX_PDF_PAGES = 25


def _parsed(snapshot: SourceSnapshot, text: str, status: str, warnings: list[str], pages=()) -> ParsedSource:
    return ParsedSource(snapshot_sha256=snapshot.body_sha256,
                        normalized_text_sha256=sha256(text.encode('utf-8')).hexdigest(),
                        text=text, status=status, warning_codes=tuple(sorted(set(warnings))),
                        pages=tuple(pages))


def parse_snapshot(snapshot: SourceSnapshot) -> ParsedSource:
    try:
        if snapshot.content_type in ('text/html', 'text/plain'):
            return _parse_text(snapshot)
        if snapshot.content_type == 'application/pdf':
            return _parse_pdf(snapshot)
        raise SourceFailure(SourceErrorCode.UNSUPPORTED_MEDIA)
    except SourceFailure:
        raise
    except Exception:
        # Never trust invalid/failing parsers; no arbitrary exception details in evidence.
        return _parsed(snapshot, '', 'FAILED', ['PARSER_EXCEPTION'])


def _html_visibility_uncertain(node) -> bool:
    """Flag CSS/ARIA states unsupported by static-text extraction.

    This is intentionally a conservative *admission* gate, not a claim to
    reproduce a browser's CSS layout engine.
    """
    style = re.sub(r'\s+', '', str(node.get('style', '')).casefold())
    if node.has_attr('hidden') or str(node.get('aria-hidden', '')).casefold() == 'true':
        return True
    opacity = re.search(r'(?:^|;)opacity:([0-9.]+)(?:;|$)', style)
    if opacity:
        try:
            if float(opacity.group(1)) < 0.95:
                return True
        except ValueError:
            return True
    if re.search(r'(?:display:none|visibility:(?:hidden|collapse)|opacity:0(?:[;)]|$)|filter:.*?opacity\(0(?:[.)]|$)|color:transparent|font-size:0(?:px|pt|em|rem|;|$)|clip-path:|clip:rect\(|content-visibility:hidden)', style):
        return True
    if 'transform:' in style or 'position:fixed' in style or 'position:absolute' in style:
        # Unable to attest the on-screen location of extracted text.
        return True
    return False


def _css_visibility_rules(css: str):
    """Yield leaf rules with their enclosing at-rule context, not browser state.

    Unknown at-rules and nested selector blocks are also conditional: this
    static admission subset cannot establish their rendering conditions.
    """
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    stack = []
    for token in re.finditer(r'([^{}]*)([{}])', css):
        if token.group(2) == '{':
            selector = token.group(1).strip()
            conditional = bool(stack) or selector.startswith('@')
            stack.append((selector, token.end(), conditional))
        elif stack:
            selector, start, conditional = stack.pop()
            body = css[start:token.start(2)]
            if '{' not in body and '}' not in body:
                yield selector, body, conditional


def _closed_html_container(node, root) -> bool:
    if node.name == 'dialog' and not node.has_attr('open'):
        return True
    if node.name == 'details' and not node.has_attr('open'):
        summary = node.find('summary', recursive=False)
        return summary is None or not (root is summary or summary in root.parents)
    return False


def _parse_text(s: SourceSnapshot) -> ParsedSource:
    if s.content_type == 'text/plain':
        try:
            text = s.body.decode('utf-8-sig', errors='strict')
        except UnicodeDecodeError:
            return _parsed(s, '', 'UNSUPPORTED', ['TEXT_ENCODING_UNRESOLVED'])
        text = '\n'.join(line.strip() for line in text.splitlines() if line.strip())
        if len(text) > MAX_TEXT_CHARS:
            return _parsed(s, text[:MAX_TEXT_CHARS], 'PARTIAL', ['TEXT_TRUNCATED'])
        return _parsed(s, text, 'PARSED' if text else 'UNSUPPORTED', [] if text else ['NO_TEXT'])
    from bs4 import BeautifulSoup, Comment
    soup = BeautifulSoup(s.body, 'lxml')
    # These elements never serve as decisive evidence; remove executable and navigation noise.
    style_rules = [tag.get_text(' ', strip=True) for tag in soup.find_all('style')]
    # Unfetched stylesheets can affect any evidence element. Their URL or
    # placement outside <main> does not establish irrelevance. Never fetch CSS.
    external_styles = any('stylesheet' in tag.get('rel', []) and not tag.has_attr('disabled')
                          for tag in soup.find_all('link'))
    for css in style_rules:
        tokens = re.sub(r'/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', '', css, flags=re.S)
        external_styles |= bool(re.search(r'(?:^|;)\s*@import\b', tokens, re.I))
    for tag in soup(['script', 'style', 'template', 'noscript', 'svg', 'nav']):
        tag.decompose()
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()
    root = soup.find('main') or soup.find('article') or soup.body or soup
    warnings = []
    # The selected evidence root and all ancestors must be visible, too.
    for ancestor in [root, *root.parents]:
        if getattr(ancestor, 'attrs', None) is not None:
            if _html_visibility_uncertain(ancestor):
                return _parsed(s, '', 'UNSUPPORTED', ['HIDDEN_EVIDENCE_ROOT'])
            if _closed_html_container(ancestor, root):
                return _parsed(s, '', 'UNSUPPORTED', ['CLOSED_EVIDENCE_ROOT'])
    if external_styles:
        warnings.append('EXTERNAL_STYLESHEET_VISIBILITY_UNVERIFIED')
    # Native HTML controls have visibility semantics even without CSS.
    for tag in list(root.find_all(['dialog', 'details'])):
        if tag.parent is None or tag.has_attr('open'):
            continue
        if tag.name == 'dialog':
            tag.decompose()
        else:
            summary = tag.find('summary', recursive=False)
            for child in list(tag.contents):
                if child is not summary:
                    child.extract()
    # Comments and quoted third-party speech are never issuer-authored declarations.
    for tag in root.find_all(['blockquote', 'q', 'aside', 'footer']):
        if tag.name == 'footer' and re.search(
                r'(?im)^\s*(?:scope|applicability|applicable|applies|effective(?:ness)?|conditions?|(?:this|the)\s+(?:notice|recruitment|extension|cancellation))\b',
                tag.get_text('\n', strip=True)):
            # Still do not admit footer assertions. But dropping an apparent
            # governing qualifier must not turn a scoped body into ALL.
            warnings.append('HTML_FOOTER_QUALIFIER_UNVERIFIED')
        tag.decompose()
    for tag in root.find_all(True):
        hints = ' '.join(str(x) for x in [tag.get('id',''), *tag.get('class',[])]).casefold()
        if any(x in hints for x in ('comment','user-content','reader-review','discussion-replies')):
            tag.decompose()
    # A style block with hidden rules cannot be silently discarded: record
    # uncertain CSS and remove only selectors understood by our strict parser.
    hidden_root = False
    conditional_root = False
    for css in style_rules:
        visibility_rules = 0
        for selector, body, conditional in _css_visibility_rules(css):
            body = re.sub(r'\s+', '', body.casefold())
            if any(token in body for token in ('display:none', 'visibility:hidden', 'opacity:0', 'filter:opacity(0)', 'color:transparent', 'font-size:0', 'clip-path:', 'transform:')):
                visibility_rules += 1
                try:
                    if re.fullmatch(r'\s*[.#][a-zA-Z_][a-zA-Z0-9_-]*\s*', selector):
                        selector = selector.strip()
                        # Select from the complete document: root.select() cannot
                        # see a matching ancestor, and CSS applies to both.
                        hidden_nodes = list(soup.select(selector))
                        evidence_chain = [root, *root.parents]
                        root_matches = any(node is ancestor for node in hidden_nodes for ancestor in evidence_chain)
                        relevant_nodes = [node for node in hidden_nodes
                                          if any(node is child for child in root.descendants)]
                        if root_matches:
                            if conditional:
                                conditional_root = True
                            else:
                                hidden_root = True
                        if conditional and (root_matches or relevant_nodes):
                            warnings.append('CSS_RESPONSIVE_VISIBILITY_UNVERIFIED')
                        for hidden in relevant_nodes:
                            hidden.decompose()
                    else:
                        warnings.append('CSS_VISIBILITY_UNVERIFIED')
                except Exception:
                    warnings.append('CSS_VISIBILITY_UNVERIFIED')
        # A nested responsive visibility rule that cannot be mapped to a
        # supported selector must abstain; irrelevant selectors do not taint
        # an otherwise visible notice body.
        if re.search(r'@(media|supports)\b', css, re.I) and visibility_rules == 0 and re.search(
                r'opacity\s*:|visibility\s*:|display\s*:|filter\s*:|clip(?:-path)?\s*:|transform\s*:', css, re.I):
            warnings.append('CSS_VISIBILITY_UNVERIFIED')

    # Do not let stylesheet ordering obscure a definite exclusion, or turn
    # conditional root visibility into a claim of unconditional hiding.
    if hidden_root:
        return _parsed(s, '', 'UNSUPPORTED', warnings + ['HIDDEN_EVIDENCE_ROOT'])
    if conditional_root:
        return _parsed(s, '', 'UNSUPPORTED', warnings)

    # Naive flattened tables can swap column identities: preserve text but block definitive admission.
    if root.find('table') is not None:
        warnings.append('HTML_TABLE_STRUCTURE_UNVERIFIED')
    if root.find(['iframe', 'object', 'embed', 'canvas']) is not None:
        warnings.append('HTML_EMBEDDED_CONTENT_UNVERIFIED')
    # Hidden-looking textual content shouldn't become independently authoritative.
    for tag in root.find_all(attrs={'hidden': True}):
        tag.decompose()
    for tag in list(root.find_all(True)):
        if tag.parent is None:
            continue
        plain_style = re.sub(r'\s+', '', str(tag.get('style', '')).lower())
        if tag.has_attr('hidden') or 'display:none' in plain_style or 'visibility:hidden' in plain_style:
            # Fully understood static exclusion; other, unsupported visibility
            # controls remain a document-level uncertainty.
            tag.decompose()
        elif _html_visibility_uncertain(tag):
            warnings.append('HTML_PERCEPTIBILITY_UNVERIFIED')
            tag.decompose()
    text = '\n'.join(line.strip() for line in root.get_text('\n', strip=True).splitlines() if line.strip())
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
        warnings.append('TEXT_TRUNCATED')
    if len(text) < 20:
        return _parsed(s, text, 'UNSUPPORTED', ['NO_USEFUL_STATIC_TEXT'] + warnings)
    return _parsed(s, text, 'PARTIAL' if warnings else 'PARSED', warnings)


def _parse_pdf(s: SourceSnapshot) -> ParsedSource:
    import fitz
    try:
        doc = fitz.open(stream=s.body, filetype='pdf')
    except Exception:
        return _parsed(s, '', 'FAILED', ['INVALID_PDF'])
    with doc:
        if doc.is_encrypted:
            return _parsed(s, '', 'UNSUPPORTED', ['ENCRYPTED_PDF'])
        parts = []
        pages = []
        warnings = []
        offset = 0
        if doc.page_count > MAX_PDF_PAGES:
            warnings.append('PDF_PAGE_LIMIT')
        for i in range(min(doc.page_count, MAX_PDF_PAGES)):
            page = doc.load_page(i)
            extracted = page.get_text('text', sort=True).strip()
            # Text-only extraction can include invisible glyphs or text obscured
            # by later fills. Such PDFs are never eligible to govern automatically.
            try:
                sequence = page.get_bboxlog()
                for index, item in enumerate(sequence):
                    kind, bounds = item[0], fitz.Rect(item[1])
                    if kind == 'ignore-text':
                        warnings.append('PDF_NONVISIBLE_TEXT')
                    if kind in {'fill-text','stroke-text'}:
                        # A prior opaque fill/image can make dark ink invisible
                        # against a dark background. This extractor cannot verify
                        # background contrast, so it must not certify these glyphs.
                        for earlier in sequence[:index]:
                            if earlier[0] in {'fill-path','fill-image','fill-shade'}:
                                background = fitz.Rect(earlier[1])
                                if bounds.intersects(background) and (bounds & background).get_area() > bounds.get_area() * 0.20:
                                    warnings.append('PDF_BACKGROUND_PERCEPTIBILITY_UNVERIFIED')
                                    break
                        for later in sequence[index + 1:]:
                            if later[0] in {'fill-path','fill-image','fill-shade'}:
                                overlay = fitz.Rect(later[1])
                                if bounds.intersects(overlay) and (bounds & overlay).get_area() > bounds.get_area() * 0.20:
                                    warnings.append('PDF_TEXT_OCCLUSION_UNVERIFIED')
                                    break
                for item in page.get_texttrace():
                    if item.get('type') == 3 or item.get('opacity', 1) < 0.99:
                        warnings.append('PDF_NONVISIBLE_TEXT')
                    # Avoid governing assertions from nearly invisible/light or
                    # sub-legible glyphs. A complex background cannot be proven
                    # perceptible here: more elaborate artwork requires review.
                    if float(item.get('size', 0)) < 3.0:
                        warnings.append('PDF_TEXT_TOO_SMALL')
                    color = item.get('color')
                    if isinstance(color, (list, tuple)) and len(color) == 3:
                        luminance = sum(c * coeff for c, coeff in zip(color, (0.2126, 0.7152, 0.0722)))
                        if luminance > 0.88:
                            warnings.append('PDF_LOW_CONTRAST_UNVERIFIED')
            except (AttributeError, ValueError, RuntimeError):
                warnings.append('PDF_VISIBILITY_UNVERIFIED')
            # Pages with images or table structures may contain visually important missing context.
            if page.get_images(full=True):
                warnings.append('PDF_HAS_IMAGES')
            # Detect structured tables conservatively, without trusting flattened ordering.
            try:
                if page.find_tables().tables:
                    warnings.append('PDF_HAS_TABLES')
            except (AttributeError, ValueError, RuntimeError):
                warnings.append('PDF_LAYOUT_UNVERIFIED')
            if not extracted:
                warnings.append('PDF_PAGE_WITHOUT_TEXT')
            if offset + len(extracted) + 1 > MAX_TEXT_CHARS:
                warnings.append('TEXT_TRUNCATED')
                break
            if parts:
                parts.append('\n')
                offset += 1
            start = offset
            parts.append(extracted)
            offset += len(extracted)
            pages.append((i + 1, start, offset))
        text = ''.join(parts)
        if not text.strip():
            return _parsed(s, '', 'UNSUPPORTED', warnings + ['SCANNED_OR_EMPTY_PDF'])
        return _parsed(s, text, 'PARTIAL' if warnings else 'PARSED', warnings, pages)
