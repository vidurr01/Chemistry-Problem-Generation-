"""
Graph rules for Inorganic Chemistry (used by build_graph.py --subject inorganic).

Inorganic reaction TXs in concept_book_inorg.json read like
    from: "Na₂CrO₄ + H₂SO₄"            to: "Na₂Cr₂O₇ (sodium dichromate) + Na₂SO₄ + H₂O"
The graph's nodes are chemical SPECIES. An edge goes from the species that is
transformed to the product it becomes, chosen from BOTH sides together: the two must
share an element other than H and O, so a reagent written first is not mistaken for
the substrate. The first-written species wins when it qualifies. Examples:
    "CO + H₂O -> H₂ + CO₂"                      CO -> CO₂   (not CO -> H₂)
    "Al₂O₃ (thermite) + Fe₂O₃ -> Fe + Al₂O₃"    Fe₂O₃ -> Fe
Chains of edges are multi-step transformation sequences, e.g.
    FeCr₂O₄ → Na₂CrO₄ → Na₂Cr₂O₇ → K₂Cr₂O₇ → CrO₂Cl₂

Same method as the organic graph: rules map every raw from/to string onto a canonical
node id. Strings that are facts rather than species (shapes, trends, test colours,
"Hydrolysis of X vs Y", EAN calculations) map to None and stay out of the graph.
"""

import re

CHAPTER_KEY = "source_chapter"   # field on each concept-book TX that names its chapter

_SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "01234567890123456789+-")

# A formula token: element symbols, digits, (), [], hydrate dot, ½, optional charge.
_FORMULA = re.compile(r"^(?:[A-Z][a-z]?|\d+|[()\[\]]|·|½)+(?:\d*[+-])?$")

_ELEMENTS = set("""H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu
Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm
Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np
Pu Am Cm Bk Cf Es Fm Md No Lr""".split())

# Text that marks a fact/trend entry rather than a reaction.
_FACT_PREFIX = re.compile(
    r"^(trend|hydrolysis of|partial hydrolysis of|ammonolysis of|alcoholysis of|diagonal|"
    r"biological|anomalous|flame test|colour|color|rate:|no reaction|electrolysis|"
    r"solvay|interhalogen|thiosulphate|crown ether|cryptand|ean\b|smallest|largest)",
    re.IGNORECASE)
_FACT_ANYWHERE = re.compile(r"\s[<>]\s|\bvs\.?\s|\bEAN\b", re.IGNORECASE)

# Common names -> canonical formula node.
NAME_TO_FORMULA = {
    "bleaching powder": "Ca(OCl)2",
    "plaster of paris": "CaSO4·½H2O",
    "gypsum": "CaSO4·2H2O",
    "slaked lime": "Ca(OH)2",
    "quick lime": "CaO",
    "quicklime": "CaO",
    "limestone": "CaCO3",
    "washing soda": "Na2CO3·10H2O",
    "baking soda": "NaHCO3",
    "borax": "Na2[B4O5(OH)4]",
    "boric acid": "H3BO3",
    "orthoboric acid": "H3BO3",
    "chromite ore": "FeCr2O4",
    "malachite": "CuCO3·Cu(OH)2",
    "mohr's salt": "(NH4)2SO4·FeSO4·6H2O",
    "urea": "NH2CONH2",
    "silicone": "polysiloxane",
    "polysiloxane": "polysiloxane",
    "cement": "cement",
}

# Elements of the named (non-formula) nodes, for the shared-element test.
NAMED_NODE_ELEMENTS = {"polysiloxane": {"Si"}, "cement": {"Ca", "Si", "Al"}}

# Formula aliases that describe the same species.
FORMULA_ALIASES = {
    "B(OH)3": "H3BO3",
}


def _clean_formula(tok):
    tok = tok.strip().rstrip("↓↑,;:.")
    tok = re.sub(r"^\d+(?=[A-Z(\[])", "", tok)        # leading coefficient: 2KMnO4 -> KMnO4
    tok = re.sub(r"\((aq|s|l|g)\)$", "", tok)         # state label
    if tok.count("(") != tok.count(")") or tok.count("[") != tok.count("]"):
        return None
    if not tok or not re.search(r"[A-Z]", tok) or not _FORMULA.match(tok):
        return None
    # Every symbol must be a real element: rejects placeholders like M (metal), R (alkyl).
    if any(sym not in _ELEMENTS for sym in re.findall(r"[A-Z][a-z]?", tok)):
        return None
    if tok == "KK":   # MO-configuration shorthand, not a species
        return None
    return FORMULA_ALIASES.get(tok, tok)


def _species(part):
    """One '+'-separated term -> canonical species, or None."""
    part = part.strip()
    if not part:
        return None
    # 1) a named substance, e.g. "Bleaching powder (Ca(OCl)2 ...)" or "Gypsum (CaSO4·2H2O)"
    name = re.sub(r"\s*\(.*$", "", part).strip().lower()
    if name in NAME_TO_FORMULA:
        return NAME_TO_FORMULA[name]
    # 2) the first whitespace-free token is a formula, e.g. "Cu(NO3)2 (250°C)"
    tok = part.split()[0]
    formula = _clean_formula(tok)
    if formula:
        return formula
    # 3) a plain descriptive name followed by its formula, e.g. "Caro's acid (H2SO5)".
    #    The text before "(" must be words, not a broken formula like "M(OH)2".
    m = re.match(r"^([A-Za-z][A-Za-z' .-]{2,})\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)", part)
    if m and re.search(r"[a-z]{3}", m.group(1)):
        inner = m.group(2).split(",")[0].split()
        return _clean_formula(inner[0]) if inner else None
    return None


def side_species(text):
    """All species on one side of a TX, in the order written."""
    s = (text or "").translate(_SUB).strip()
    if not s or _FACT_PREFIX.match(s) or _FACT_ANYWHERE.search(s):
        return []
    if ":" in s:                                       # "Preparation ...: Be(OH)2 + ..." -> after colon
        s = s.split(":", 1)[1].strip()
    s = re.split(r"\s*->\s*|\s*→\s*", s)[0]
    out = []
    for part in re.split(r"\s+\+\s+", s):
        sp = _species(part)
        if sp and sp not in out:
            out.append(sp)
    return out


def _elements(species):
    """Elements used for the shared-element test: H and O are ignored unless the
    species is made only of them (H2, O2, H2O, H2O2)."""
    if species in NAMED_NODE_ELEMENTS:
        return NAMED_NODE_ELEMENTS[species]
    els = set(re.findall(r"[A-Z][a-z]?", species))
    heavy = els - {"H", "O"}
    return heavy or els


def principal_pair(tx):
    """(substrate, product) for one TX, or (None, None) if no pair shares an element."""
    left, right = side_species(tx.get("from")), side_species(tx.get("to"))
    best, best_key = (None, None), None
    for i, l in enumerate(left):
        for j, r in enumerate(right):
            shared = _elements(l) & _elements(r)
            if l == r or not shared:
                continue
            key = (i == 0, len(shared), -j, -i)   # first-written substrate, most shared, earliest product
            if best_key is None or key > best_key:
                best, best_key = (l, r), key
    return best


def normalize_node(raw, tx=None):
    """Map a raw from/to string to a species node, choosing substrate and product from
    both sides of the TX together (see principal_pair)."""
    if tx is None:
        found = side_species(raw)
        return found[0] if found else None
    sub, prod = principal_pair(tx)
    if raw is tx.get("from") or raw == tx.get("from"):
        return sub
    return prod


# ── Salt -> ion links ─────────────────────────────────────────────────────────
# A salt and the ion it releases in solution are different nodes (K2Cr2O7 vs Cr2O7 2-),
# so a chain that reaches the salt could not continue with the ion's reactions. These
# links join them. They are NOT concept-book entries: each is marked "synthetic".

# Cations with one fixed charge, so the salt's charge balance can be checked.
_FIXED_CATIONS = {"Li": 1, "Na": 1, "K": 1, "Rb": 1, "Cs": 1, "Ag": 1, "NH4": 1,
                  "Be": 2, "Mg": 2, "Ca": 2, "Sr": 2, "Ba": 2, "Zn": 2, "Al": 3}


def _ion_readings(ion):
    """Possible (formula, charge) readings of an ion id: "Cr2O72-" is Cr2O7 with 2- or
    Cr2O72 with 1-; the salt's charge balance decides which is meant."""
    m = re.match(r"^(.*?)(\d?)([+-])$", ion)
    if not m:
        return []
    body, digit, _sign = m.groups()
    readings = [(body + digit, 1)]
    if digit:
        readings.append((body, int(digit)))
    return readings


def _cation(prefix):
    """(symbol, total charge) of a cation prefix like "K2", "(NH4)2", "Ca", or None."""
    m = re.fullmatch(r"\(?([A-Z][a-z]?(?:H4)?)\)?(\d*)", prefix)
    if not m or m.group(1) not in _FIXED_CATIONS:
        return None
    return m.group(1), _FIXED_CATIONS[m.group(1)] * int(m.group(2) or 1)


_ALKALI = {"Li", "Na", "K", "Rb", "Cs", "NH4"}


def _soluble(cation, anion):
    """Standard solubility rules: only a salt that dissolves releases its ion."""
    if cation in _ALKALI or anion == "NO3":
        return True
    if anion in ("Cl", "Br", "I"):
        return cation != "Ag"                       # AgCl, AgBr, AgI are insoluble
    if anion == "SO4":
        return cation not in ("Ca", "Sr", "Ba")     # CaSO4 sparingly; SrSO4, BaSO4 insoluble
    return False                                    # sulfides, carbonates, oxalates, ... of others


def _salt_of(salt, ion):
    """True if `salt` is a fixed-charge cation plus exactly this ion, charges balanced,
    and the salt is soluble: K2Cr2O7 / Cr2O7 2-,  Ca(NO3)2 / NO3-,  K4[Fe(CN)6] / [Fe(CN)6] 4-.
    AgCl / Cl- is rejected: AgCl does not dissolve."""
    if "·" in salt or re.search(r"[+-]$", salt):
        return False
    for core, charge in _ion_readings(ion):
        if salt.endswith(core) and salt != core:                      # K2Cr2O7 = K2 + Cr2O7
            cat = _cation(salt[: -len(core)])
            if cat and cat[1] == charge:
                return _soluble(cat[0], core)
        m = re.fullmatch(r"(.+)\(" + re.escape(core) + r"\)(\d+)", salt)  # Ca(NO3)2
        if m:
            cat = _cation(m.group(1))
            if cat and cat[1] == charge * int(m.group(2)):
                return _soluble(cat[0], core)
    return False


def extra_edges(edges):
    """Salt -> ion "dissolves to" edges, added only where the ion has onward steps."""
    nodes = {e["from"] for e in edges} | {e["to"] for e in edges}
    out_from = {}
    for e in edges:
        out_from.setdefault(e["from"], []).append(e)
    chapter_of = {}
    for e in edges:
        chapter_of.setdefault(e["to"], e["chapter"])
        chapter_of.setdefault(e["from"], e["chapter"])
    links = []
    for ion in sorted(n for n in nodes if re.search(r"[+-]$", n) and out_from.get(n)):
        for salt in sorted(nodes):
            if not _salt_of(salt, ion):
                continue
            onward = out_from[ion]
            links.append({
                "id": f"{salt}_dissolves_to_{ion}",
                "from": salt,
                "to": ion,
                "reagents": ["H2O (dissolution)"],
                "conditions": f"{salt} in aqueous solution provides {ion}",
                "firing_condition": None,
                "chapter": chapter_of.get(salt) or onward[0]["chapter"],
                "archetype": sorted({a for e in onward for a in e.get("archetype", [])}),
                "chemoselectivity": {"requires_absent": [], "node_redirect": {}, "priority_ref": None},
                "tx_ids": [],
                "synthetic": True,
                "notes": (f"Not a concept-book entry: links the salt {salt} to the ion {ion} it "
                          f"releases in solution, so the ion's reactions can follow."),
            })
    return links
