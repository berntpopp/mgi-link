"""D1 description leads (Tool-Schema Documentation Standard v1.1, rule 7).

Every tool description's first sentence must say what the tool returns.
"""

from __future__ import annotations

import re
from typing import Any

# ponytail: copied from genefoundry-router scripts/surface.py (lead_states_return,
# router v0.13.1); re-vendor byte-identically if this repo ever vendors surface.py.
_LEAD_VERBS = (  # noqa: SIM905 - kept identical to the router copy
    "get fetch retrieve list look lookup search find resolve report read predict annotate "
    "compute calculate count summarize summarise map translate convert describe show check "
    "validate classify score rank query browse discover explain compare diff normalize normalise "
    "expand evaluate assess enumerate identify locate export download match suggest recommend "
    "inspect generate render estimate"
).split()
_VERB_LEAD = re.compile(
    rf"^(?:use this (?:tool )?to )?(?:{'|'.join(_LEAD_VERBS)})(?:s|es|ies)?\b", re.IGNORECASE
)
_RETURNS = re.compile(
    r"(?<!not )(?<!n't )(?<!n’t )(?<!never )\breturn(?:s|ed|ing)?\b(?!\s*[~<\d])|→|->",  # noqa: RUF001
    re.IGNORECASE,
)
_FIELD_LIST = re.compile(r"\w+\W+\w+[^:]*:\s+[^.;:]+,")
_SENTENCE_END = re.compile(r"(?<!e\.g\.)(?<!i\.e\.)(?<=[.!?])\s+")


def _lead_states_return(description: str | None) -> bool:
    text = " ".join((description or "").split())
    lead = _SENTENCE_END.split(text, maxsplit=1)[0][:300]
    return bool(_VERB_LEAD.match(lead) or _RETURNS.search(lead) or _FIELD_LIST.search(lead))


async def test_every_tool_description_lead_states_what_it_returns(facade: Any) -> None:
    tools = await facade.list_tools()
    offenders = [t.name for t in tools if not _lead_states_return(t.description)]
    assert offenders == [], f"D1: first sentence must say what is returned: {offenders}"
