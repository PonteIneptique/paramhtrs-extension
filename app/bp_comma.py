import re
import urllib.error
import urllib.parse
import urllib.request

from flask import Blueprint, request, jsonify, abort
from flask_login import login_required
from lxml import etree

bp_comma = Blueprint("bp_comma", __name__)

COMMA_API = "https://comma.inria.fr/api/document/"
SKIP_TAGS = {"note", "fw"}


def _local(tag):
    return tag.split("}")[-1] if "}" in tag else tag


def _collect(elem, lines, current):
    """Recursive DFS: split on <lb/>, skip <note>/<fw>, collect all other text."""
    tag = _local(elem.tag)
    if tag in SKIP_TAGS:
        if elem.tail:
            current.append(elem.tail)
        return
    if tag == "lb":
        line = re.sub(r"\s+", " ", "".join(current)).strip()
        if line:
            lines.append(line)
        current.clear()
        if elem.tail:
            current.append(elem.tail)
        return
    if elem.text:
        current.append(elem.text)
    for child in elem:
        _collect(child, lines, current)
    if elem.tail:
        current.append(elem.tail)


def parse_comma_tei(xml_bytes):
    root = etree.fromstring(xml_bytes)
    body = next((el for el in root.iter() if _local(el.tag) == "body"), root)
    lines, current = [], []
    _collect(body, lines, current)
    if current:
        line = re.sub(r"\s+", " ", "".join(current)).strip()
        if line:
            lines.append(line)
    return lines


@bp_comma.route("/api/comma/document")
@login_required
def comma_document():
    resource = urllib.parse.unquote(request.args.get("resource", "").strip())
    ref = urllib.parse.unquote(request.args.get("ref", "").strip())
    if not resource or not ref:
        abort(400)
    url = (
        f"{COMMA_API}"
        f"?resource={urllib.parse.quote(resource, safe='')}"
        f"&ref={urllib.parse.quote(ref, safe='')}"
    )
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            xml_bytes = resp.read()
    except urllib.error.HTTPError as e:
        return jsonify({"error": f"CoMMA returned {e.code}: {e.reason}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    lines = parse_comma_tei(xml_bytes)
    return jsonify({"label": ref, "lines": [{"text": t} for t in lines]})
