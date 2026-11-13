"""Filter explicit webpage decorations, leaving ordinary prose and fenced code intact."""
import re

_SECTION = re.compile(r'\[\[section:[^\]]*\]\]', re.IGNORECASE)
_PREFIXES = ('[[section:', '[[suggested_questions')
_SUGGESTIONS = re.compile(r'(?m)^[ \t]*\[\[(?:suggested_questions|section:suggested_questions)\]\]', re.IGNORECASE)
_FENCE = re.compile(r'^[ \t]{0,3}(`{3,}|~{3,})([^\r\n]*)\r?$')
_FENCED_SUGGESTIONS = re.compile(
    r'(?mi)^(?:[ \t]*\[\[(?!suggested_questions\b|section:suggested_questions\b)section:[^\]]*\]\])*[ \t]{0,3}(`{3,}|~{3,})[ \t]*suggested_questions(?=[ \t\r\n]|$)[^\r\n]*(?:\r?\n|$)'
)
_ADJOINED_CLOSE_SUGGESTION = re.compile(
    r'(?mi)(^[ \t]{0,3}`{3}[ \t]*)(?=(?:`{3,}|~{3,})[ \t]*suggested_questions\b|\[\[(?:suggested_questions|section:suggested_questions)\]\])'
)
_ADJOINED_CLOSE_SUGGESTION_AFTER_NL = re.compile(
    r'(?i)(\n[ \t]{0,3}`{3}[ \t]*)(?=(?:`{3,}|~{3,})[ \t]*suggested_questions\b|\[\[(?:suggested_questions|section:suggested_questions)\]\])'
)


def _fence_after(text, fence='', line=''):
    lines = (line + text).split('\n')
    for completed in lines[:-1]:
        cleaned = _SECTION.sub('', completed.rstrip('\r'))
        match = _FENCE.match(cleaned)
        if match:
            marker, info = match[1], match[2].strip()
            if not fence:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and not info:
                fence = ''
    tail = lines[-1]
    return fence, tail[:256]


def _find_top_level_suggestion(text, fence='', line=''):
    best = None
    for match in _SUGGESTIONS.finditer(text):
        current_fence, prefix = _fence_after(text[:match.start()], fence, line)
        if not current_fence and not prefix.strip():
            best = (match.start(), match.end(), '')
            break
    for match in _FENCED_SUGGESTIONS.finditer(text):
        current_fence, prefix = _fence_after(text[:match.start()], fence, line)
        if not current_fence and not _SECTION.sub('', prefix).strip():
            cand = (match.start(), match.end(), match[1])
            if best is None or cand[0] < best[0]:
                best = cand
            break
    return best


def _is_potential_suggestion_line(line_tail: str) -> bool:
    if not line_tail or '\n' in line_tail or len(line_tail) > 128:
        return False
    stripped_sec = re.sub(
        r'^(?:[ \t]*\[\[(?!suggested_questions\b|section:suggested_questions\b)section:[^\]]*\]\])+',
        '',
        line_tail,
        flags=re.IGNORECASE,
    )
    if stripped_sec.strip(' \t') == '':
        return len(stripped_sec) <= 3
    s = stripped_sec.lstrip(' \t')
    leading_ws = len(stripped_sec) - len(s)
    if s.startswith('['):
        low = s.lower()
        return any(
            target.startswith(low)
            for target in ('[[suggested_questions]]', '[[section:suggested_questions]]')
        )
    if leading_ws <= 3 and s[0] in ('`', '~'):
        m = re.match(r'^(`+|~+)([ \t]*)(.*)$', s)
        if not m:
            return False
        ticks, spaces, rest = m[1], m[2], m[3].lower()
        if len(ticks) < 3:
            return spaces == '' and rest == ''
        if rest == '' or 'suggested_questions'.startswith(rest):
            return True
        if re.match(r'^suggested_questions(?![a-z0-9_-])', rest):
            return True
    return False


def clean_web_text(text: str) -> str:
    if not text:
        return ''
    text = _ADJOINED_CLOSE_SUGGESTION.sub(r'\1\n', text)
    lines = text.splitlines(keepends=True)
    kept = []
    outer_fence = ''
    skip_suggestion_fence = ''
    for raw_line in lines:
        stripped_eol = raw_line.rstrip('\r\n')
        if skip_suggestion_fence:
            m = _FENCE.match(stripped_eol)
            if (
                m
                and m[1][0] == skip_suggestion_fence[0]
                and len(m[1]) >= len(skip_suggestion_fence)
                and not m[2].strip()
            ):
                skip_suggestion_fence = ''
            continue
        if not outer_fence and re.match(
            r'^[ \t]*\[\[(?:suggested_questions|section:suggested_questions)\]\]',
            stripped_eol,
            re.IGNORECASE,
        ):
            break
        cleaned_line = _SECTION.sub('', stripped_eol)
        m = _FENCE.match(cleaned_line)
        if not outer_fence:
            if m and re.match(r'^suggested_questions(?:\b|$)', m[2].strip(), re.IGNORECASE):
                skip_suggestion_fence = m[1]
                continue
            if m:
                outer_fence = m[1]
        elif (
            m
            and m[1][0] == outer_fence[0]
            and len(m[1]) >= len(outer_fence)
            and not m[2].strip()
        ):
            outer_fence = ''
        kept.append(raw_line)
    return _SECTION.sub('\n\n', ''.join(kept))


class WebTextFilter:
    def __init__(self):
        self.pending = ''
        self.suggestions = False
        self.skip_suggestion_fence = ''
        self.fence = ''
        self.line = ''

    def _emit(self, text):
        if not text:
            return ''
        self.fence, self.line = _fence_after(text, self.fence, self.line)
        return text

    def feed(self, text: str) -> str:
        if self.suggestions:
            return ''
        text = self.pending + text
        self.pending = ''
        if not self.fence or self.fence == '```':
            if (
                re.match(r'^[ \t]{0,3}`{3}[ \t]*$', self.line)
                and re.match(
                    r'^(?:(?:`{3,}|~{3,})[ \t]*suggested_questions(?=[ \t\r\n])|\[\[(?:suggested_questions|section:suggested_questions)\]\])',
                    text,
                    re.IGNORECASE,
                )
            ):
                text = '\n' + text
            elif (
                self.fence == '```'
                and re.match(r'^[ \t]{0,3}`{3}[ \t]*$', self.line)
                and '\n' not in text
                and _is_potential_suggestion_line(text)
            ):
                self.pending = text
                return ''
            if not self.line.strip():
                text = _ADJOINED_CLOSE_SUGGESTION.sub(r'\1\n', text)
            else:
                text = _ADJOINED_CLOSE_SUGGESTION_AFTER_NL.sub(r'\1\n', text)
        out_parts = []

        while text:
            if self.skip_suggestion_fence:
                close_re = re.compile(
                    r'(?m)^[ \t]{0,3}'
                    + re.escape(self.skip_suggestion_fence[0])
                    + '{'
                    + str(len(self.skip_suggestion_fence))
                    + r',}[ \t]*\r?\n'
                )
                close_match = close_re.search(text)
                if not close_match:
                    self.pending = text
                    return ''.join(out_parts)
                self.skip_suggestion_fence = ''
                self.fence = ''
                self.line = ''
                text = text[close_match.end():]
                continue

            hit = _find_top_level_suggestion(text, self.fence, self.line)
            if hit is not None:
                start, end, fence_marker = hit
                before = _SECTION.sub('\n\n', text[:start])
                if before:
                    out_parts.append(self._emit(before))
                if not fence_marker:
                    self.suggestions = True
                    return ''.join(out_parts)
                if not text[start:end].endswith('\n'):
                    self.pending = text[start:]
                    return ''.join(out_parts)
                self.skip_suggestion_fence = fence_marker
                self.fence = ''
                self.line = ''
                text = text[end:]
                continue
            break

        if not text:
            return ''.join(out_parts)

        # Hold back incomplete trailing top-level line that may become a suggestion block
        last_nl = text.rfind('\n')
        if last_nl >= 0:
            cand_fence, _ = _fence_after(text[: last_nl + 1], self.fence, self.line)
            tail_line = text[last_nl + 1 :]
            if not cand_fence and _is_potential_suggestion_line(tail_line):
                head = _SECTION.sub('\n\n', text[: last_nl + 1])
                self.pending = tail_line
                if head:
                    out_parts.append(self._emit(head))
                return ''.join(out_parts)
        elif not self.fence and _is_potential_suggestion_line(self.line + text):
            self.pending = text
            return ''.join(out_parts)

        text = _SECTION.sub('\n\n', text)
        lowered = text.lower()
        for prefix in _PREFIXES:
            start = lowered.rfind(prefix)
            if start >= 0 and ']]' not in text[start:] and len(text) - start < 512:
                self.pending = text[start:]
                out_parts.append(self._emit(text[:start]))
                return ''.join(out_parts)
        for length in range(min(max(map(len, _PREFIXES)) - 1, len(text)), 0, -1):
            if any(prefix.startswith(lowered[-length:]) for prefix in _PREFIXES):
                self.pending = text[-length:]
                out_parts.append(self._emit(text[:-length]))
                return ''.join(out_parts)
        out_parts.append(self._emit(text))
        return ''.join(out_parts)

    def finish(self) -> str:
        if self.suggestions or self.skip_suggestion_fence:
            self.pending = ''
            self.skip_suggestion_fence = ''
            return ''
        tail, self.pending = self.pending, ''
        if not tail:
            return ''
        if not self.fence and not self.line:
            tail = clean_web_text(tail)
        return self._emit(tail)
