"""Smoke tests that the 3-panel editor template renders the annotation chips.

These guard the Vue markup in template/documents/editor.html — a Jinja render is
the only server-side check we get on it, so they assert the pieces that are easy
to break when the annotation row is edited.
"""

import pytest

from app import app as flask_app, db
from app.models import User, Project, Folder, Document, Part, Line


@pytest.fixture()
def app():
    flask_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        WTF_CSRF_ENABLED=False,
        SECRET_KEY="test-secret",
        LOGIN_DISABLED=False,
    )
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def editor_page(app):
    """Log a user in and return the rendered editor HTML for a one-line document."""
    user = User(username="scribe", is_approved=True)
    user.set_password("pw")
    db.session.add(user)
    db.session.flush()

    project = Project(name="proj", description="", creator_id=user.id)
    db.session.add(project)
    db.session.flush()
    folder = Folder(name="folder", project_id=project.id, creator_id=user.id)
    db.session.add(folder)
    db.session.flush()
    document = Document(label="d1", folder_id=folder.id, order=0)
    db.session.add(document)
    db.session.flush()
    part = Part(document_id=document.id, order=0)
    db.session.add(part)
    db.session.flush()
    db.session.add(Line(part_id=part.id, order=0, original_text="ꝑ tout"))
    db.session.commit()

    client = app.test_client()
    client.post("/login", data={"username": "scribe", "password": "pw"},
                follow_redirects=True)
    resp = client.get(f"/documents/{document.id}")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_draft_row_renders_before_the_pending_list(editor_page):
    """The draft annotation row must come before the pending v-for in the DOM,
    otherwise its Type menu is clipped at the bottom of the scrolling panel."""
    draft = editor_page.index('class="annot-row annot-pending"')
    listing = editor_page.index('v-for="annot in pendingAnnotationsSorted"')
    assert draft < listing


def test_cert_chip_present_in_both_rows(editor_page):
    """Pending and validated rows both carry the certainty chip."""
    assert editor_page.count('class="annot-chip annot-chip-cert cert-wrap"') == 2


def test_chip_order_is_type_certainty_tag_gap(editor_page):
    """Chips read outwards from what the annotation *is*: its type, then how sure
    the resolution is, then the entity tag, then the gap. Same order in the rows
    and in the focus-mode toolbar."""
    for chips in ("annot-chip-type", "annot-chip-cert", "annot-chip-tag", "annot-chip-gap"):
        assert editor_page.count(f'class="annot-chip {chips}') == 2

    # Match the full class attribute: the bare names also appear in the
    # stylesheet above the markup, in a different order.
    def order(names, prefix):
        return [n for _, n in sorted((editor_page.index(prefix + n), n) for n in names)]

    wanted = ["type", "cert", "tag", "gap"]
    assert order(wanted, 'class="annot-chip annot-chip-') == wanted
    assert order(wanted, 'class="fm-menu-btn fm-') == wanted


def test_qualifier_chips_are_gated(editor_page):
    """Tag, Gap and Certainty describe an annotation's output text, so they are
    hidden on the types that have none: deletion, ATR noise and insertion."""
    # In the rows they keep their slot (is-hidden), so the chip columns stay
    # aligned: Tag + Gap on both rows, and Certainty via isResolution.
    assert editor_page.count("'is-hidden': !hasQualifiers(annot)") == 4
    assert editor_page.count("'is-hidden': !isResolution(annot)") == 2
    assert 'v-if="hasQualifiers(annot)"' not in editor_page   # would reflow the row
    # Focus mode is a centred toolbar, not a column, so there it is a real v-if
    assert editor_page.count('v-if="hasQualifiers(focusCurrent)"') == 2
    assert 'v-if="isResolution(focusCurrent)"' in editor_page


def test_cert_menus_iterate_the_shared_groups(editor_page):
    """Every certainty menu renders from certGroups, so the labels, the icons and
    the abbreviation-only grouping cannot drift apart between menus."""
    assert editor_page.count('v-for="g in certGroups"') == 3   # row, focus, draft
    assert editor_page.count('v-for="c in g.states"') == 3
    assert "setCert(menuAnnot, c)" in editor_page
    assert "focusSetCert(c)" in editor_page
    assert "stageDraftCert(c)" in editor_page


def test_cert_group_headings_are_rendered(editor_page):
    """The grouping is what tells an annotator the graded states are for
    abbreviation resolutions only."""
    assert editor_page.count('class="menu-group"') == 2        # row + focus menus
    assert editor_page.count('class="menu-group is-sub"') == 1  # draft submenu


def test_menu_items_show_their_icon(editor_page):
    """Every menu that names a state shows that state's icon beside the label.
    Counted per vocabulary rather than in total, so adding a menu doesn't
    silently break the assertion."""
    # 3 certainty lists (row menu, focus mode, draft submenu), each binding the
    # icon twice: a v-if for the FA case and the :class that applies it
    assert editor_page.count("certIcons[c]") == 6
    # 3 type lists (row menu, focus mode, draft menu) driven off the shared map
    assert editor_page.count("annotTypeIcons[t]") == 3
    # and every icon sits in the fixed-width column
    assert 'class="menu-item-icon"' in editor_page


def test_ambiguous_glyph_is_defined_once_and_referenced(editor_page):
    """The ambiguous state has no Font Awesome icon; it lives in the sprite."""
    assert editor_page.count('<symbol id="icon-ambiguous"') == 1
    # 2 chips + 3 menus + the focus-mode button + the draft Type button
    assert editor_page.count('<use href="#icon-ambiguous"/>') == 7


def test_focus_mode_has_a_cert_button(editor_page):
    assert "fm-cert-wrap" in editor_page


# ── Type menus ────────────────────────────────────────────────────────────────

def test_type_menus_use_the_deployed_vocabulary(editor_page):
    """Every Type menu renders from ANNOT_TYPE_TITLES rather than its own
    strings, so they cannot drift from the Type chip on a committed row."""
    assert editor_page.count('v-for="t in annotTypeMenu"') == 3  # row, focus, draft
    assert "annotTypeTitles[t]" in editor_page
    assert "annotTypeIcons[t]" in editor_page
    # The old bespoke labels are gone
    assert "Ambiguous person name" not in editor_page
    assert "Markup (tag only, no change)" not in editor_page


def test_no_unclear_vocabulary_remains(editor_page):
    """'Unclear' names nothing in the UI vocabulary and must not resurface."""
    assert "unclear" not in editor_page.lower()


def test_type_menu_never_offers_insertion():
    """An insertion requires a null source (start == end), so it can only be
    created by insert mode — offering it would leave purpose:'insertion' on an
    annotation that still spans text."""
    import re
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "static" / "js" / "editor-utils.js"
    m = re.search(r"export const ANNOT_TYPE_MENU = \[(.*?)\];", src.read_text(), re.DOTALL)
    assert m, "ANNOT_TYPE_MENU not found in editor-utils.js"
    types = re.findall(r"'([^']+)'", m.group(1))
    assert types == ["normalizing", "deletion", "atr_noise", "non_resolv_abbr", "markup"]
    assert "insertion" not in types


# ── Guideline legend popover ──────────────────────────────────────────────────

def _help_anchors():
    """Every `anchor:` referenced by the help maps in editor-utils.js."""
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "static" / "js" / "editor-utils.js").read_text()
    return set(re.findall(r"anchor:\s*'([^']+)'", src))


def test_help_anchors_all_resolve_in_the_guidelines():
    """A popover that references a guideline section must point at a real id."""
    from pathlib import Path
    guidelines = (Path(__file__).resolve().parents[1]
                  / "template" / "guidelines.html").read_text()
    anchors = _help_anchors()
    assert anchors, "no help anchors found in editor-utils.js"
    missing = [a for a in anchors if f'id="{a}"' not in guidelines]
    assert not missing, f"guidelines.html has no heading for: {missing}"


def test_every_category_has_help_text():
    """Each vocabulary entry carries a blurb, so no category hovers up blank."""
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "static" / "js" / "editor-utils.js").read_text()

    def keys_of(const):
        m = re.search(rf"export const {const} = \{{(.*?)\n\}};", src, re.DOTALL)
        assert m, f"{const} not found"
        return set(re.findall(r"^\s{2}(\w+):", m.group(1), re.MULTILINE))

    assert keys_of("TYPE_HELP") == keys_of("ANNOT_TYPE_TITLES")
    assert keys_of("CERT_HELP") == keys_of("CERT_LABELS")
    assert keys_of("SEMTAG_HELP") == keys_of("SEMTAG_LABELS")


def test_popover_is_rendered_once_and_driven_by_hover(editor_page):
    assert editor_page.count('class="help-pop"') == 1
    assert "hideHelp" in editor_page
    # every vocabulary drives it
    for kind in ("'type'", "'cert'", "'semtag'", "'gap'"):
        assert f"showHelp({kind}," in editor_page


def test_draft_menu_qualifier_steps(editor_page):
    """Normalization opens certainty; the other two open their existing lists."""
    assert "stageDraftCert(c)" in editor_page          # Normalization -> certainty
    assert "markNonResolvAbbr(r)" in editor_page       # -> reason
    assert "markMarkup(tag)" in editor_page            # -> semtag
    assert "pickDraftType(t)" in editor_page
