"""Reads the Lua data files addons ship (QuestieDB's corrections, ForeverDB's addon data) as Python values.

Only literals: tables, strings, numbers, true/false/nil. A key written as an expression, `[questKeys.name]`, becomes its
last name part ("name"). A name used as a value stays a name ("zoneIDs.ELWYNN_FOREST"; `a + b` of two names is
"a+b"): nothing is looked up. Tables whose keys are 1..n in order come back as lists, others as dicts with str keys
(JSON keeps keys as strings anyway). A table that holds code (a function, a condition) is not read at all.
"""
import re

_TOKEN = re.compile(r"""
    (?P<space>\s+|--\[\[.*?\]\]|--[^\n]*)
  | (?P<string>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<long>\[(?P<eq>=*)\[.*?\](?P=eq)\])
  | (?P<number>-?0x[0-9a-fA-F]+|-?\d+\.?\d*(?:[eE][-+]?\d+)?|-?\.\d+)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)
  | (?P<punct>[{}\[\]=,;()+*/])
""", re.S | re.X)

_KEYWORDS = {"function", "end", "if", "then", "else", "elseif", "for", "while", "do", "repeat", "until", "local", "return", "and", "or",
             "not", "in", "break", "goto"}
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'", "\n": "\n", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}


def _unescape(body):
    out, i = [], 0
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        nxt = body[i + 1]
        if nxt.isdigit():                       # \ddd: a byte, used for UTF-8 sequences
            digits = re.match(r"\d{1,3}", body[i + 1:]).group(0)
            out.append(chr(int(digits)))
            i += 1 + len(digits)
            continue
        out.append(_ESCAPES.get(nxt, nxt))
        i += 2
    text = "".join(out)
    try:                                         # decimal escapes spell UTF-8 bytes one by one
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _tokens(text):
    pos = 0
    for m in _TOKEN.finditer(text):
        if m.start() != pos:
            raise ValueError(f"unexpected text at {pos}: {text[pos:pos + 40]!r}")
        pos = m.end()
        kind = "long" if m.group("long") else m.lastgroup
        if kind != "space":
            yield kind, m.group(kind)
    if pos != len(text):
        raise ValueError(f"unexpected text at {pos}: {text[pos:pos + 40]!r}")


class _Parser:
    def __init__(self, text):
        self.toks = list(_tokens(text))
        self.i = 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self, value=None):
        if self.i >= len(self.toks):
            raise ValueError("the text ends in the middle of a value")
        tok = self.toks[self.i]
        if value is not None and tok[1] != value:
            raise ValueError(f"expected {value!r}, got {tok[1]!r}")
        self.i += 1
        return tok

    def value(self):
        """A value, plus the small expressions data files use: `f("x")` (taken as its first argument) and `a + b`
        (summed when both are numbers, else kept as the text "a+b"). Any other arithmetic is code: refused."""
        left = self.atom()
        while self.peek()[1] in ("+", "*", "/"):
            op = self.take()[1]
            if op != "+":
                raise ValueError(f"arithmetic, not data ({op})")
            right = self.atom()
            if all(isinstance(side, (int, float)) and not isinstance(side, bool) for side in (left, right)):
                left = left + right
            else:
                left = f"{left}+{right}"
        return left

    def atom(self):
        kind, text = self.peek()
        if text == "(":
            self.take("(")
            inner = self.value()
            self.take(")")
            return inner
        if text == "{":
            return self.table()
        self.take()
        if kind == "string":
            return _unescape(text[1:-1])
        if kind == "long":                       # [[...]] / [==[...]==]: no escapes, a leading newline is dropped
            eq = len(re.match(r"\[(=*)\[", text).group(1))
            body = text[eq + 2:-(eq + 2)]
            return body[1:] if body.startswith("\n") else body
        if kind == "number":
            return int(text, 16) if text.lower().lstrip("-").startswith("0x") else (float(text) if re.search(r"[.eE]", text) else int(text))
        if kind == "name":
            if text in _KEYWORDS:                    # code where a value should be: never guessed at
                raise ValueError(f"code, not data ({text})")
            if self.peek()[1] == "(":                # a call such as l10n("text"): keep its first argument
                self.take("(")
                args = []
                while self.peek()[1] != ")":
                    args.append(self.value())
                    if self.peek()[1] == ",":
                        self.take()
                self.take(")")
                return args[0] if args else None
            return {"nil": None, "true": True, "false": False}.get(text, text)
        raise ValueError(f"unexpected {text!r}")

    def table(self):
        self.take("{")
        keyed, n = {}, 0
        while self.peek()[1] != "}":
            kind, text = self.peek()
            if text == "[":
                self.take("[")
                key_is_name = self.peek()[0] == "name"
                key = self.value()
                if key_is_name and isinstance(key, str) and "." in key:     # [questKeys.name] -> "name"; ["Mr. Smith"] stays
                    key = key.rsplit(".", 1)[1]
                self.take("]")
                self.take("=")
                keyed[key] = self.value()
            elif kind == "name" and self.i + 1 < len(self.toks) and self.toks[self.i + 1][1] == "=":
                self.take()
                self.take("=")
                keyed[text] = self.value()
            else:
                n += 1
                keyed[n] = self.value()
            if self.peek()[1] in (",", ";"):
                self.take()
            elif self.peek()[1] != "}":              # `5-1`, `1 2`: two values with nothing between them are not a list
                raise ValueError(f"expected , or }} after a field, got {self.peek()[1]!r}")
        self.take("}")
        if keyed and all(isinstance(k, int) for k in keyed) and sorted(keyed) == list(range(1, len(keyed) + 1)):
            return [keyed[k] for k in range(1, len(keyed) + 1)]
        return {str(k): v for k, v in keyed.items()}


def parse_value(text):
    parser = _Parser(text)
    value = parser.value()
    if parser.i != len(parser.toks):
        raise ValueError(f"unexpected {parser.peek()[1]!r} after the value")
    return value


def assignments(text):
    """Every top-level `ns.name = {...}` (or `name = {...}`) in an addon data file, as {name: value}."""
    out = {}
    for m in re.finditer(r"^(?:local\s+)?(?:\w+\.)?(\w+)\s*=\s*\{", text, re.M):
        start = m.end() - 1
        end = _match_brace(text, start)
        out[m.group(1)] = parse_value(text[start:end + 1])
    return out


def returned_table(text):
    """The table a `function X:Load() ... return { ... } end` module returns (QuestieDB corrections)."""
    m = re.search(r"\breturn\s*\{", text)
    start = m.end() - 1
    return parse_value(text[start:_match_brace(text, start) + 1])


def _match_brace(text, start):
    """Index of the } that closes the { at `start`, skipping strings, long strings and comments. Malformed input
    (an unterminated string or long string) raises ValueError, never IndexError."""
    depth, i, n = 0, start, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            j = i + 1
            while j < n and text[j] != ch:
                j += 2 if text[j] == "\\" else 1
            if j >= n:
                raise ValueError("unterminated string")
            i = j + 1
            continue
        if text.startswith("--", i):             # comment: --[[ ... ]] / --[==[ ... ]==] or to the end of the line
            m = re.match(r"--\[(=*)\[", text[i:i + 64])
            if m:
                end = text.find("]" + m.group(1) + "]", i + len(m.group(0)))
                if end < 0:
                    raise ValueError("unterminated comment")
                i = end + len(m.group(1)) + 2
            else:
                nl = text.find("\n", i)
                i = n if nl < 0 else nl
            continue
        if ch == "[":                            # long string: [[...]] or [==[...]==], braces inside don't count
            m = re.match(r"\[(=*)\[", text[i:i + 64])
            if m:
                close = "]" + m.group(1) + "]"
                end = text.find(close, i + len(m.group(0)))
                if end < 0:
                    raise ValueError("unterminated long string")
                i = end + len(close)
                continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("unbalanced braces")


def tables(text):
    """Every data table in an addon data file, whatever way it is written, as {name: value}:

    - `X.y = {...}` and `local y = {...}` (top-level assignments)
    - `X.y = [[return {...}]]` and `X["deDE"] = loadstring([[return {...}]])` (a table inside a long string)
    - `function M:Load() ... return {...}` (the table a function returns; name "M:Load")
    - `function M:Load() local a = {...} ... return a` (the tables a function keeps in locals; name "M:Load/a")
    A table that isn't a pure literal (code inside) is skipped and reported under "_skipped"; so is a function that
    returns two tables, or returns something and holds no table this reader found.
    """
    out, skipped = {}, []
    # long strings first, and blank them out so their contents aren't read as assignments
    def long_string(m):
        lhs, eq = m.group(1).strip(), m.group(2)
        start = m.end()
        close = "]" + eq + "]"
        end = text.find(close, start)
        if end < 0:
            skipped.append(f"{lhs}: unterminated long string")
            return lhs, start, len(text)
        body = text[start:end]
        r = re.search(r"\breturn\s*\{", body)
        if r:
            try:
                out[lhs] = parse_value(body[r.end() - 1:_match_brace(body, r.end() - 1) + 1])
            except Exception as error:          # one malformed table never stops the file (RecursionError included)
                skipped.append(f"{lhs}: {type(error).__name__}: {error}")
        return lhs, start, end + len(close)
    spans = []
    # at the start of a line only: an indented `[k.name] = [[text]]` is a field of a table, not a table of its own
    for m in re.finditer(r"^([\w.]+(?:\[[^\]\n]+\])?)\s*=\s*(?:loadstring\()?\[(=*)\[", text, re.M):
        lhs, start, end = long_string(m)
        spans.append((m.start(), end))
    blanked = text
    for start, end in reversed(spans):
        blanked = blanked[:start] + "\n" * blanked[start:end].count("\n") + blanked[end:]
    for m in re.finditer(r"^(?:local\s+)?([\w.]+(?:\[[^\]\n]+\])?)\s*=\s*\{", blanked, re.M):
        start = m.end() - 1
        try:
            out[m.group(1)] = parse_value(blanked[start:_match_brace(blanked, start) + 1])
        except Exception as error:
            skipped.append(f"{m.group(1)}: {type(error).__name__}: {error}")
    for m in re.finditer(r"^function\s+([\w.:]+)\s*\(", blanked, re.M):
        nxt = re.search(r"^function\s", blanked[m.end():], re.M)
        body_end = m.end() + nxt.start() if nxt else len(blanked)
        body = blanked[m.end():body_end]
        code = "\n".join(line.split("--", 1)[0] for line in body.split("\n"))      # same length per line is not needed: only counted
        found = 0
        # tables the function keeps in locals (`local fixesHorde = {...}` ... `return fixesHorde`)
        for local in re.finditer(r"^[ \t]+local\s+(\w+)\s*=\s*\{", body, re.M):
            start = m.end() + local.end() - 1
            try:
                out[f"{m.group(1)}/{local.group(1)}"] = parse_value(blanked[start:_match_brace(blanked, start) + 1])
                found += 1
            except Exception as error:
                skipped.append(f"{m.group(1)}/{local.group(1)}: {type(error).__name__}: {error}")
        returned = [r for r in re.finditer(r"\breturn\s*\{", body) if "--" not in body[body.rfind("\n", 0, r.start()) + 1:r.start()]]
        if len(returned) > 1:
            skipped.append(f"{m.group(1)}: returns {len(returned)} tables")
            continue
        if returned:
            start = m.end() + returned[0].end() - 1
            try:
                out[m.group(1)] = parse_value(blanked[start:_match_brace(blanked, start) + 1])
                found += 1
            except Exception as error:
                skipped.append(f"{m.group(1)}: {type(error).__name__}: {error}")
        elif not found and re.search(r"\breturn\s+[\w.]", code):
            skipped.append(f"{m.group(1)}: returns something, but no table was found in it")
    if skipped:
        out["_skipped"] = skipped
    return out
