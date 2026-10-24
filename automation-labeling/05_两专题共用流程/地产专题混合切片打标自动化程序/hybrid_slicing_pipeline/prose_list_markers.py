"""Formatting-only list markers must not masquerade as factual measurements."""
import re


def without_list_markers(text):
    return re.sub(r'(?m)^[ \t]*(?:\d+[.)、]|[（(]\d+[）)])[ \t]+', '', text)
