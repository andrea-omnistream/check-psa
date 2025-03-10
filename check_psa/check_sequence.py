"""Check two pogs for consistent sequence"""

from __future__ import annotations
import itertools as it
import logging
import typing as t

from check_psa.parse_psa import Pog, PsaParser

logger = logging.getLogger(__name__)


def check_sequence(
    subject_psa: PsaParser, reference_psa: PsaParser, product_master: t.Dict = {}
) -> t.List[t.Any]:
    "Check subject pog for consistent sequence versus reference"
    subject = subject_psa.decode_psa(product_master=product_master)
    reference = reference_psa.decode_psa(product_master=product_master)
    violations = []
    base_left_right = cdt_ordering(reference)
    check_left_right = cdt_ordering(subject)
    for base_left, base_rights in base_left_right.items():
        for base_right, base_locs in base_rights.items():
            for check_loc in check_left_right.get(base_right, {}).get(base_left, []):
                for base_loc in base_locs:
                    violation = {
                        "reference": {
                            "left": {"cdt": base_left, **base_loc["left"]},
                            "right": {"cdt": base_right, **base_loc["right"]},
                        },
                        "subject": {
                            "left": {"cdt": base_right, **check_loc["left"]},
                            "right": {"cdt": base_left, **check_loc["right"]},
                        },
                    }
                    violations.append(violation)
    return violations


def cdt_ordering(pog: Pog) -> t.Dict:
    "enumerate cdt pairs and their relationships to each other"
    left_right = {}

    for bay_no, bay in enumerate(pog["bays"], 1):
        for shelf_no, shelf in enumerate(bay["shelves"], 1):
            for (i, left_cdt), (j, right_cdt) in it.combinations(
                (
                    min(group)
                    for _, group in it.groupby(
                        enumerate((item["cdt0"] for item in shelf["items"]), 1),
                        key=lambda x: x[1],
                    )
                ),
                r=2,
            ):
                if left_cdt == right_cdt:
                    logger.warning(
                        f"left and right are the same cdt {left_cdt}, {bay_no=}, {shelf_no=}, {i=}, {j=}"
                    )
                    continue
                left_right.setdefault(left_cdt, {}).setdefault(right_cdt, []).append(
                    {
                        "left": {
                            "bay_no": bay_no,
                            "shelf_no": shelf_no,
                            "seq_no": i,
                        },
                        "right": {
                            "bay_no": bay_no,
                            "shelf_no": shelf_no,
                            "seq_no": j,
                        },
                    }
                )
            for cdt0, cdt_items in it.groupby(
                enumerate(shelf["items"], 1), key=lambda x: x[1]["cdt0"]
            ):
                for (i, left_cdt1), (j, right_cdt1) in it.combinations(
                    (
                        min(group)
                        for _, group in it.groupby(
                            ((item[0], item[1]["cdt1"]) for item in cdt_items),
                            key=lambda x: x[1],
                        )
                    ),
                    r=2,
                ):
                    left_cdt = f"{cdt0}/{left_cdt1}"
                    right_cdt = f"{cdt0}/{right_cdt1}"
                    if left_cdt == right_cdt:
                        logger.warning(
                            f"left and right are the same cdt {left_cdt}, {bay_no=}, {shelf_no=}, {i=}, {j=}"
                        )
                        continue
                    left_right.setdefault(left_cdt, {}).setdefault(
                        right_cdt, []
                    ).append(
                        {
                            "left": {
                                "bay_no": bay_no,
                                "shelf_no": shelf_no,
                                "seq_no": i,
                            },
                            "right": {
                                "bay_no": bay_no,
                                "shelf_no": shelf_no,
                                "seq_no": j,
                            },
                        }
                    )
            for cdt1, cdt1_items in it.groupby(
                enumerate(shelf["items"], 1),
                key=lambda x: f"{x[1]['cdt0']}/{x[1]['cdt1']}",
            ):
                for (i, left_cdt2), (j, right_cdt2) in it.combinations(
                    (
                        min(group)
                        for _, group in it.groupby(
                            ((item[0], item[1]["cdt2"]) for item in cdt1_items),
                            key=lambda x: x[1],
                        )
                    ),
                    r=2,
                ):
                    left_cdt = f"{cdt1}/{left_cdt2}"
                    right_cdt = f"{cdt1}/{right_cdt2}"
                    if left_cdt == right_cdt:
                        logger.warning(
                            f"left and right are the same cdt {left_cdt}, {bay_no=}, {shelf_no=}, {i=}, {j=}"
                        )
                        continue
                    left_right.setdefault(left_cdt, {}).setdefault(
                        right_cdt, []
                    ).append(
                        {
                            "left": {
                                "bay_no": bay_no,
                                "shelf_no": shelf_no,
                                "seq_no": i,
                            },
                            "right": {
                                "bay_no": bay_no,
                                "shelf_no": shelf_no,
                                "seq_no": j,
                            },
                        }
                    )

    return left_right
