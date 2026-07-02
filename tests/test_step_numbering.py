# tests/test_step_numbering.py
"""The guided rebuild agents must read 'Version 1'..'Version 4' contiguously so
the workshop UI never jumps a number (the floor confusion raised by Nicholas
Ahrendt). Each guided agent's ROUTE is a semantic slug (/hello, /tool, /skills,
/complete) that matches its version, so the SWML URL an attendee sees always
agrees with the version label -- no historical '/step11' hiding behind
'Version 4'.

Archived agents (step06/07/09) stay registered but are hidden from the guided
UI; their labels are marked 'Archived' (not 'Version N') so no two entries ever
share a version number. The outbound capstone (/outbound) is intentionally
label-less: it is not part of the Version sequence."""
import re
from main import STEPS

OUTBOUND_CAPSTONE_ROUTE = "/outbound"
GUIDED_ROUTES = ["/hello", "/tool", "/skills", "/complete"]


def test_guided_version_labels_are_contiguous_1_to_4():
    """The routes that carry a 'Version N' label read 1..4 in order."""
    nums = []
    for route, _agent_class, desc in STEPS:
        m = re.search(r"Version\s+(\d+)", desc)
        if m:
            nums.append(int(m.group(1)))
    assert nums == [1, 2, 3, 4], nums


def test_archived_agents_are_labelled_archived_not_versioned():
    labels = {route: desc for route, _c, desc in STEPS}
    for route in ("/step06", "/step07", "/step09"):
        desc = labels[route]
        assert desc.startswith("Archived"), f"{route} should be Archived: {desc!r}"
        assert not re.search(r"Version\s+\d+", desc), \
            f"archived {route} must not carry a Version label: {desc!r}"


def test_capstone_has_no_version_label():
    desc = {route: desc for route, _c, desc in STEPS}[OUTBOUND_CAPSTONE_ROUTE]
    assert not re.search(r"Version\s+\d+", desc), \
        f"capstone should not carry a Version label: {desc!r}"


def test_routes_are_semantic_slugs():
    routes = [entry[0] for entry in STEPS]
    assert routes == ["/hello", "/step06", "/step07", "/tool",
                      "/step09", "/skills", "/complete", "/outbound"]
