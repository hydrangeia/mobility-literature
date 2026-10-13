from __future__ import annotations


QUERY_GROUPS: dict[str, list[tuple[str, str]]] = {
    "COF": [
        ("cof-mobility", '"covalent organic framework" carrier mobility'),
        ("cof-electron", '"covalent organic framework" electron mobility'),
        ("cof-transport-method", '"covalent organic framework" charge transport BTE'),
        ("cof-fet-mobility", '"covalent organic framework" field-effect mobility'),
        ("cof-hall-mobility", '"covalent organic framework" Hall mobility'),
        ("cof-sclc-mobility", '"covalent organic framework" "space-charge-limited current" mobility'),
        ("cof-electron-phonon", '"covalent organic framework" "electron-phonon" mobility'),
        ("cof5-mobility", '"COF-5" carrier mobility'),
    ],
    "MOF": [
        ("mof-mobility", '"metal-organic framework" carrier mobility'),
        ("mof-electron", '"metal organic framework" electron mobility'),
        ("mof-transport-method", '"metal-organic framework" charge transport mobility theory'),
        ("mof-fet-mobility", '"metal-organic framework" field-effect mobility'),
        ("mof-hall-mobility", '"metal-organic framework" Hall mobility'),
        ("mof-trmc-mobility", '"metal-organic framework" TRMC mobility'),
        ("mof-deformation-potential", '"metal-organic framework" "deformation potential" mobility'),
        ("mof5-mobility", '"MOF-5" carrier mobility'),
    ],
    "organic_small_molecule": [
        ("organic-molecule-mobility", '"small-molecule semiconductor" mobility'),
        ("organic-molecular-crystal", '"molecular crystal" hole mobility semiconductor'),
        ("organic-experiment", '"organic semiconductor" "time-of-flight" mobility'),
        ("organic-hopping", '"organic semiconductor" "Marcus hopping" mobility'),
        ("organic-ofet-mobility", '"organic semiconductor" OFET mobility'),
        ("organic-hall-mobility", '"organic semiconductor" "Hall mobility"'),
        ("organic-sclc-mobility", '"organic semiconductor" "space-charge-limited current" mobility'),
        ("organic-trmc-mobility", '"organic semiconductor" TRMC mobility'),
        ("organic-electron-phonon", '"organic semiconductor" "electron-phonon" mobility'),
        ("organic-kmc-mobility", '"organic semiconductor" "kinetic Monte Carlo" mobility'),
        ("pentacene-mobility", 'pentacene "carrier mobility"'),
    ],
    "hybrid_perovskite": [
        ("hybrid-perovskite-mobility", '"hybrid perovskite" carrier mobility'),
        ("organic-inorganic-perovskite", '"organic-inorganic perovskite" electron mobility'),
        ("halide-perovskite-transport", '"halide perovskite" hole mobility'),
        ("hybrid-perovskite-fet", '"hybrid perovskite" "field-effect mobility"'),
        ("hybrid-perovskite-hall", '"hybrid perovskite" "Hall mobility"'),
        ("hybrid-perovskite-tof", '"hybrid perovskite" "time-of-flight" mobility'),
        ("hybrid-perovskite-trmc", '"hybrid perovskite" TRMC mobility'),
        ("hybrid-perovskite-deformation", '"hybrid perovskite" "deformation potential" mobility'),
        ("methylammonium-perovskite-mobility", 'methylammonium perovskite "carrier mobility"'),
    ],
    "inorganic_2d": [
        ("inorganic-2d-mobility", '"two-dimensional semiconductor" carrier mobility'),
        ("2d-electron-mobility", '"2D material" electron mobility first-principles'),
        ("2d-transport-method", '"two-dimensional" semiconductor mobility BTE'),
        ("2d-tmd-mobility", '"two-dimensional transition metal dichalcogenide" carrier mobility'),
        ("2d-mos2-mobility", '"monolayer MoS2" carrier mobility'),
        ("2d-fet-mobility", '"2D semiconductor" FET mobility'),
        ("2d-hall-mobility", '"2D semiconductor" "Hall mobility"'),
        ("2d-deformation-potential", '"2D semiconductor" "deformation potential" mobility'),
        ("2d-electron-phonon", '"2D semiconductor" "electron-phonon" mobility'),
    ],
}


def all_queries() -> list[tuple[str, str, str]]:
    return [
        (material_class, query_id, query)
        for material_class, items in QUERY_GROUPS.items()
        for query_id, query in items
    ]
